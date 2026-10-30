"""The macOS side: a transparent click-through window for the sprite, the menu-bar item,
mouse (click / drag), scroll riding, and reading the senses (pointer, idle time, active window).

Standing on a Terminal window, the cat moves in: the window becomes its world (world.py), rebuilt
4 times a second from the text on screen (terminal.py). Dragging it out is the way to leave."""
import io
import os
import random
import signal
import time

import objc
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered, NSColor,
    NSCompositingOperationCopy, NSCompositingOperationSourceOver, NSEvent, NSEventMaskScrollWheel,
    NSFloatingWindowLevel, NSGraphicsContext, NSImage, NSImageInterpolationNone, NSMenu, NSMenuItem, NSPanel,
    NSRectFillUsingOperation, NSScreen, NSSound, NSStatusBar, NSVariableStatusItemLength, NSView, NSWorkspace,
    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle, NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSData, NSMakeRect, NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer, NSZeroRect
from Quartz import (
    CGEventSourceSecondsSinceLastEventType, CGWindowListCopyWindowInfo, kCGAnyInputEventType,
    kCGEventSourceStateCombinedSessionState, kCGNullWindowID, kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionOnScreenOnly,
)

from . import terminal
from .body import CELL, Body
from .memory import Memory
from .mind import LABELS, Mind
from .senses import Tracker
from .sprites import Sheet, skin_name, skins
from .world import World

FEET = 25          # first transparent row under the paws of standing poses
HEAD = 4           # first opaque row of the tallest standing poses
PAD = 5            # transparent margin inside the cell: lets the cat reach the real screen edge
ASK = ['hunt', 'chase', 'climb', 'zoomies', 'visit', 'sleep', 'greet']


def timer(seconds, target, selector, repeats):
    t = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(seconds, target, selector, None, repeats)
    NSRunLoop.currentRunLoop().addTimer_forMode_(t, NSRunLoopCommonModes)
    return t


def screen_top():
    return NSScreen.screens()[0].frame().size.height


def app_windows():
    """On-screen normal windows, front to back: (window id, owner pid, (left, bottom, right, top)) in pt."""
    top = screen_top()
    for w in CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID):
        if w['kCGWindowLayer'] == 0:
            b = w['kCGWindowBounds']
            left, bottom = b['X'], top - b['Y'] - b['Height']
            yield w['kCGWindowNumber'], w['kCGWindowOwnerPID'], (left, bottom, left + b['Width'], bottom + b['Height'])


def window_at(x, y):
    """(window id, owner pid, box) of the topmost normal window under the point, or None."""
    for wid, pid, (l, b, r, t) in app_windows():
        if l <= x < r and b <= y < t:
            return wid, pid, (l, b, r, t)
    return None


def active_window():
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = app.processIdentifier() if app else None
    if pid in (None, os.getpid()):
        return None
    return next((box for _, p, box in app_windows() if p == pid), None)


class CatView(NSView):
    sprite = None
    ctl = None

    def drawRect_(self, rect):
        NSColor.clearColor().set()
        NSRectFillUsingOperation(rect, NSCompositingOperationCopy)
        if self.sprite is not None:
            NSGraphicsContext.currentContext().setImageInterpolation_(NSImageInterpolationNone)
            self.sprite.drawInRect_fromRect_operation_fraction_(
                self.bounds(), NSZeroRect, NSCompositingOperationSourceOver, 1.0)

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        self.ctl.mouse_down()

    def mouseDragged_(self, event):
        self.ctl.mouse_dragged()

    def mouseUp_(self, event):
        self.ctl.mouse_up()


class Controller(NSObject):
    @objc.python_method
    def setup(self, cfg):
        self.cfg, self.scale = cfg, cfg['scale']
        self.scroll_cfg = cfg['scroll']
        self.cats, self.accessories = skins()
        self.cat, self.accessory = cfg['sheet'], None
        self.set_skin(cfg['sheet'])
        rng = random.Random()
        self.body = Body(cfg, rng)
        self.body.x = -CELL
        self.tracker = Tracker()
        self.mind = Mind(cfg, self.body, Memory(), self.tracker.s, rng)
        self.frames = self.mind.run()
        self.doing = self.timer = self.grab = self.scroll = None
        self.dragging, self.passthrough = False, True
        self.window, self.window_at_t, self.last_poll = None, 0.0, time.monotonic()
        self.home, self.world_t, self.lines = None, 0.0, None   # the Terminal window it lives in
        self.not_terminal = set()   # windows already asked: no text area there
        self.anchor = None          # (char index, body.moves, its top) of the line it stands on
        self.sound = NSSound.soundNamed_(cfg['sound']) if cfg.get('sound') else None
        self.sound_on = self.sound is not None

        size = CELL * self.scale
        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, size, size), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(False)
        win.setHidesOnDeactivate_(False)
        win.setIgnoresMouseEvents_(True)
        win.setLevel_(NSFloatingWindowLevel)
        win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorIgnoresCycle)
        self.view = CatView.alloc().initWithFrame_(NSMakeRect(0, 0, size, size))
        self.view.ctl = self
        win.setContentView_(self.view)
        win.orderFrontRegardless()
        self.win = win
        self.build_menu()
        self.sense()
        self.step_(None)
        timer(1 / 30, self, 'poll:', True)
        self.monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSEventMaskScrollWheel, self.scrolled)

    # ---------------------------------------------------------------- menu

    @objc.python_method
    def item(self, menu, title, action=None, target=None, key=''):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if target is not None:
            it.setTarget_(target)
        menu.addItem_(it)
        return it

    @objc.python_method
    def build_menu(self):
        menu = NSMenu.alloc().init()
        self.menu_status = self.item(menu, '')
        self.menu_needs = self.item(menu, '')
        menu.addItem_(NSMenuItem.separatorItem())
        ask = NSMenu.alloc().init()
        for name in ASK:
            it = self.item(ask, f'{LABELS[name]} (через 2 с)', 'ask:', self)
            it.setRepresentedObject_(name)
        self.item(menu, 'Попросить').setSubmenu_(ask)
        self.skin_items = {}
        for title, kind, paths in (('Кот', 'cat', self.cats), ('Аксессуар', 'accessory', [None] + self.accessories)):
            sub = NSMenu.alloc().init()
            for path in paths:
                it = self.item(sub, skin_name(path) if path else 'без аксессуара', 'chooseSkin:', self)
                it.setRepresentedObject_([kind, path or ''])
                it.setState_(path == getattr(self, kind))
                self.skin_items.setdefault(kind, []).append(it)
            self.item(menu, title).setSubmenu_(sub)
        if self.sound is not None:
            self.item(menu, 'Звук', 'toggleSound:', self).setState_(self.sound_on)
        menu.addItem_(NSMenuItem.separatorItem())
        self.item(menu, 'Выйти', 'terminate:', NSApplication.sharedApplication(), 'q')
        self.status = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.status.button().setTitle_('🐱')
        self.status.setMenu_(menu)

    def chooseSkin_(self, item):
        kind, path = item.representedObject()
        setattr(self, kind, path or None)
        self.set_skin('+'.join(p for p in (self.cat, self.accessory) if p))
        for it in self.skin_items[kind]:
            it.setState_(it is item)
        self.show(self.ref)

    def toggleSound_(self, item):
        self.sound_on = not self.sound_on
        item.setState_(self.sound_on)

    def ask_(self, item):
        self.asked = item.representedObject()
        timer(2.0, self, 'startAsked:', False)      # time to put the pointer where you want it

    def startAsked_(self, _timer):
        if not self.dragging:
            self.interrupt(self.mind.switch(self.asked))

    # ---------------------------------------------------------------- drawing

    @objc.python_method
    def set_skin(self, path):
        self.sheet = Sheet(path, self.cfg.get('generated'))
        self.images = {}

    @objc.python_method
    def image(self, ref):
        if ref not in self.images:
            buf = io.BytesIO()
            self.sheet.frame(ref).save(buf, 'PNG')
            data = buf.getvalue()
            self.images[ref] = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(data, len(data)))
        return self.images[ref]

    @objc.python_method
    def show(self, ref):
        self.ref = ref
        self.view.sprite = self.image(ref)
        self.view.setNeedsDisplay_(True)

    @objc.python_method
    def screen(self):
        return NSScreen.screens()[0].visibleFrame()

    @objc.python_method
    def to_body(self, x, y):
        vf = self.screen()
        return (x - vf.origin.x) / self.scale, (y - vf.origin.y) / self.scale

    @objc.python_method
    def place(self):
        vf, b, s = self.screen(), self.body, self.scale
        self.win.setFrameOrigin_((round(vf.origin.x + b.x * s), round(vf.origin.y + (b.y - (CELL - FEET)) * s)))

    @objc.python_method
    def set_bounds(self):
        vf, b = self.screen(), self.body
        if b.world is not None:
            b.lo, b.hi, b.lo_y, b.hi_y = b.world.limits(CELL)
            return
        b.lo, b.hi = -PAD, int(vf.size.width / self.scale) - CELL + PAD
        b.lo_y, b.hi_y = 0, int(vf.size.height / self.scale) - (FEET - HEAD)

    @objc.python_method
    def paws_pt(self):
        vf, b, s = self.screen(), self.body, self.scale
        return vf.origin.x + (b.x + CELL / 2) * s, vf.origin.y + b.y * s

    @objc.python_method
    def box_to_body(self, box):
        return self.to_body(box[0], box[1]) + self.to_body(box[2], box[3])

    def step_(self, _timer):
        self.set_bounds()
        ref, ms = next(self.frames)
        if self.body.doing != self.doing:
            self.doing = self.body.doing
            print(f'{time.strftime("%H:%M:%S")} [{self.mind.activity}] {self.doing}', flush=True)
        self.show(ref)
        self.place()
        self.timer = timer(ms / 1000, self, 'step:', False)

    @objc.python_method
    def interrupt(self, frames):
        if self.timer is not None:
            self.timer.invalidate()
        self.frames = frames
        self.step_(None)

    # ---------------------------------------------------------------- senses

    @objc.python_method
    def sense(self):
        now = time.monotonic()
        if now - self.window_at_t > 1:                # window lookups are not free: once a second
            self.window_at_t = now
            box = active_window()
            if box:
                box = self.to_body(box[0], box[1]) + self.to_body(box[2], box[3])
            self.window = box
        loc = NSEvent.mouseLocation()
        lt = time.localtime()
        idle = CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateCombinedSessionState, kCGAnyInputEventType)
        self.tracker.feed(now, lt.tm_hour + lt.tm_min / 60, idle, self.to_body(loc.x, loc.y), self.window)

    def poll_(self, _timer):
        """30 Hz: senses, needs, preemption, and whether the pointer is over the cat."""
        now = time.monotonic()
        self.mind.update(now - self.last_poll)
        self.last_poll = now
        self.sense()
        if self.scroll is not None:
            if self.scroll['anchor'] is not None:
                self.follow_text()
            # Terminal animates its scrolling, so keep following the text a little longer
            if now - self.scroll['last'] > (0.3 if self.scroll['anchor'] is None else 0.7):
                self.scroll_ended()
        if not self.dragging and self.scroll is None and now - self.world_t > 0.25:
            self.world_t = now
            self.refresh_world()
        if not self.dragging and self.scroll is None:
            self.set_bounds()
            name = self.mind.preempt()
            if name:
                self.interrupt(self.mind.switch(name))
        self.menu_status.setTitle_(f'Кот: {LABELS.get(self.mind.activity, self.mind.activity)} — {self.body.doing}')
        self.menu_needs.setTitle_(self.mind.status().split(' · ', 1)[1])
        if self.dragging:
            return
        loc, fr, s = NSEvent.mouseLocation(), self.win.frame(), self.scale
        px, py = int((loc.x - fr.origin.x) // s), CELL - 1 - int((loc.y - fr.origin.y) // s)
        alpha = self.sheet.frame(self.ref).getchannel('A')
        hit = any(alpha.getpixel((x, y)) for x in range(px - 1, px + 2) for y in range(py - 1, py + 2)
                  if 0 <= x < CELL and 0 <= y < CELL)
        if hit == self.passthrough:
            self.passthrough = not hit
            self.win.setIgnoresMouseEvents_(self.passthrough)

    # ---------------------------------------------------------------- living in a Terminal window

    @objc.python_method
    def refresh_world(self, settle=True):
        """Rebuild the world from the Terminal window the cat lives in, or move into the one under its paws."""
        b = self.body
        if self.home is None:
            px, py = self.paws_pt()
            hit = terminal.trusted() and window_at(px, py + 4 * self.scale)   # its legs are on the window
            if not hit or hit[0] in self.not_terminal:
                return
            area = terminal.text_area(hit[1], hit[2])
            if area is None:
                self.not_terminal.add(hit[0])
                return
            self.home = {'wid': hit[0], 'area': area, 'view': None}
            print(f'{time.strftime("%H:%M:%S")} moved into a Terminal window', flush=True)
        home = self.home
        view = terminal.viewport(home['area'])
        if view is None or not any(wid == home['wid'] for wid, _, _ in app_windows()):
            self.leave_world()
            return
        if home['view'] is not None and view != home['view']:      # the window moved: so does the cat
            b.x += (view[0] - home['view'][0]) / self.scale
            b.y += (view[3] - home['view'][3]) / self.scale
            self.anchor = None
        home['view'] = view
        lines = [self.box_to_body(ln[:4]) for ln in terminal.visible_lines(home['area'])]
        if (view, lines) != self.lines:
            self.lines = (view, lines)
            b.world = World(self.box_to_body(view), lines)
        self.follow_line()
        self.set_bounds()
        if not b.airborne:
            self.place()
        if settle and not b.grounded() and not self.mind.reacting:
            self.interrupt(self.mind.react([{'settle': True}], 'pushed by the text'))

    @objc.python_method
    def follow_line(self):
        """Keep the cat on its line when new output pushes the text up."""
        b, area = self.body, self.home['area']
        if not b.on_shelf or b.airborne:
            self.anchor = None
            return
        if self.anchor is None or self.anchor[1] != b.moves:      # it jumped: hold on to the new line
            px, py = self.paws_pt()
            i = terminal.index_at(area, px, py - 3)
            box = i is not None and terminal.char_box(area, i)
            self.anchor = (i, b.moves, box[3]) if box else None
            return
        i, moves, top = self.anchor
        box = terminal.char_box(area, i)
        if box and abs(box[3] - top) > 0.5:
            b.y += (box[3] - top) / self.scale
            self.anchor = (i, moves, box[3])

    @objc.python_method
    def leave_world(self):
        if self.home is not None:
            print(f'{time.strftime("%H:%M:%S")} left the Terminal window', flush=True)
        self.home = self.anchor = self.lines = None
        self.body.world, self.body.on_shelf, self.body.airborne = None, False, False
        self.set_bounds()

    # ---------------------------------------------------------------- mouse

    @objc.python_method
    def mouse_down(self):
        loc, fr = NSEvent.mouseLocation(), self.win.frame()
        self.grab = (loc.x - fr.origin.x, loc.y - fr.origin.y, loc.x, loc.y)

    @objc.python_method
    def mouse_dragged(self):
        if self.grab is None:
            return
        loc = NSEvent.mouseLocation()
        gx, gy, x0, y0 = self.grab
        if not self.dragging:
            if abs(loc.x - x0) + abs(loc.y - y0) < 4:
                return
            self.dragging = True
            if self.timer is not None:
                self.timer.invalidate()
            self.leave_world()
            self.show(self.cfg['held'])
        self.win.setFrameOrigin_((loc.x - gx, loc.y - gy))

    @objc.python_method
    def mouse_up(self):
        if self.grab is None:
            return
        self.grab = None
        if self.dragging:
            self.dragging = False
            fr = self.win.frame()
            x, y = self.to_body(fr.origin.x, fr.origin.y)
            b = self.body
            b.x, b.y = x, y + CELL - FEET
            self.refresh_world(settle=False)          # dropped on a Terminal window: lives there now
            frames = self.mind.dropped(b.x, b.y)
            line = b.world and b.world.shelf_at(*b.paws, tol=4)
            if line:                                  # put down on a line of text: stays on it
                b.y, b.on_shelf = line[3], True
            self.interrupt(frames)
        elif not self.mind.reacting:
            if self.sound_on:
                self.sound.stop()
                self.sound.play()
            self.interrupt(self.mind.clicked())

    # ---------------------------------------------------------------- scrolling

    @objc.python_method
    def scrolled(self, event):
        """Global scroll-wheel monitor: ride along with the content of the window under the cat.
        In a Terminal window the cat holds on to the character under its paws and moves exactly as
        far as that character really moved (nothing, if the text is already at its top or bottom).
        Elsewhere it trusts the wheel."""
        if self.dragging:
            return
        dy = event.scrollingDeltaY()
        if not event.hasPreciseScrollingDeltas():
            dy *= self.scroll_cfg['line_pt']
        if not dy:
            return
        vf, b, s = self.screen(), self.body, self.scale
        if self.scroll is None:
            paws = (vf.origin.x + (b.x + CELL / 2) * s, vf.origin.y + (b.y + 3) * s)
            under_cat, mouse = window_at(*paws), NSEvent.mouseLocation()
            under_mouse = window_at(mouse.x, mouse.y)
            ride = under_cat is not None and under_mouse is not None and under_cat[0] == under_mouse[0]
            self.scroll = {'ride': ride, 'dist': 0.0, 'cling': False, 'bounds': under_cat and under_cat[2],
                           'area': None, 'anchor': None}
            if ride and terminal.trusted():
                home = self.home
                area = home['area'] if home and home['wid'] == under_cat[0] else \
                    terminal.text_area(under_cat[1], under_cat[2])
                anchor = area and terminal.anchor(area, *paws)
                if anchor:
                    self.scroll.update(area=area, anchor=anchor[0], line_y=anchor[1])
        sc = self.scroll
        sc['last'] = time.monotonic()
        if not sc['ride']:
            return
        if sc['anchor'] is None:
            sc['dist'] += abs(dy)
            self.ride(-dy)                     # content moves down the screen when deltaY > 0
        else:
            self.follow_text()

    @objc.python_method
    def follow_text(self):
        sc = self.scroll
        box = terminal.char_box(sc['area'], sc['anchor'])
        if not box:
            return
        dy, sc['line_y'] = box[1] - sc['line_y'], box[1]
        if dy:
            sc['dist'] += abs(dy)
            self.ride(dy)

    @objc.python_method
    def ride(self, dy):
        """Move the cat dy points with the content; hang on at the window's edge."""
        vf, b, s, sc = self.screen(), self.body, self.scale, self.scroll
        _, bottom, _, top = sc['bounds']
        lo = max(b.lo_y, (bottom - vf.origin.y) / s)
        hi = min(b.hi_y, (top - self.scroll_cfg['top_inset'] - vf.origin.y) / s - (FEET - HEAD))
        y = b.y + dy / s
        if not lo <= y <= hi:
            y = min(max(y, lo), hi)
            if not sc['cling']:
                sc['cling'] = True
                if self.timer is not None:
                    self.timer.invalidate()
                self.show(self.cfg['held'])
        b.y = y
        self.place()

    @objc.python_method
    def scroll_ended(self):
        sc, self.scroll = self.scroll, None
        self.anchor = None                            # the cat moved with the text: take a new hold
        if sc['cling']:
            self.interrupt(self.mind.react(self.scroll_cfg['edge'], 'scrolled to the edge'))
        elif sc['ride'] and sc['dist'] > self.scroll_cfg['wake_after'] and not self.mind.reacting:
            self.interrupt(self.mind.clicked('shaken by scrolling'))


def run_app(cfg):
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    ctl = Controller.alloc().init()
    ctl.setup(cfg)
    signal.signal(signal.SIGINT, lambda *_: app.terminate_(None))
    signal.signal(signal.SIGTERM, lambda *_: app.terminate_(None))
    app.run()
