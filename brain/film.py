"""A ~18 s promo of the cat, drawn in the terminal for VHS to record (`vhs film.tape`).

The desktop cat is a macOS window that a terminal recorder can't see, so here the cat draws
itself into the terminal: two sprite pixels per character cell ('▀', truecolor fg + bg), one
pixel per column. Each cut is a few seconds of the real body (Body, World, the anim.json clips),
scripted so it lands on its moment: walking in, climbing lines of text, the pounce, a nap.
"""
import random
import re
import shutil
import sys
import time

from .body import CELL, Body
from .sprites import Sheet, skins
from .world import World

FEET, HEAD = 25, 4               # as in app.py: first empty row under the paws, first row of the head
BG = (30, 30, 46)
TEXT, DIM, PROMPT, ACCENT = (205, 214, 244), (147, 153, 178), (166, 227, 161), (245, 194, 231)
BAR = (49, 50, 68)
POINTER = ['X.....', 'XX....', 'XWX...', 'XWWX..', 'XWWWX.', 'XWWWWX', 'XWWXXX', 'XXWX..', 'X.XWX.', '..XX..']
FPS = 25
REF_ROW = re.compile(r'(\d+):')
GIT_LOG = ['a41f2c9 cat climbs the lines of your terminal',
           '7be03d1 hunt: stalk, wiggle, pounce',
           'c19e8aa needs: energy, boredom, affection',
           'f02b6d4 naps at a favourite spot']


class Screen:
    """Character cells: the terminal text above, a caption bar on the last row.
    The text area doubles as a pixel canvas W x H (H = 2 x its rows), pixel (0, 0) top-left."""

    def __init__(self):
        self.cols, self.rows = shutil.get_terminal_size()
        self.area = self.rows - 1
        self.W, self.H = self.cols, 2 * self.area
        self.prev = {}
        self.out = sys.stdout

    def draw(self, lines, pixels, labels, caption):
        """lines [[(text, color), ...]] from the top; pixels {(px, py): rgb}; labels [(row, col, text, color)]."""
        cells = {}
        for r, line in enumerate(lines[:self.area]):
            c = 0
            for text, color in line:
                for ch in text:
                    if c < self.cols:
                        cells[r, c] = (ch, color, BG)
                    c += 1
        for r, c, text, color in labels:
            for i, ch in enumerate(text):
                if 0 <= r < self.area and 0 <= c + i < self.cols:
                    cells[r, c + i] = (ch, color, BG)
        for px, py in pixels:
            y0 = py - py % 2
            cells[py // 2, px] = ('▀', pixels.get((px, y0)) or BG, pixels.get((px, y0 + 1)) or BG)
        for c, ch in enumerate(caption[:self.cols].ljust(self.cols)):
            cells[self.rows - 1, c] = (ch, ACCENT, BAR)
        blank = (' ', TEXT, BG)
        buf = []
        for key in set(self.prev) | set(cells):
            cell = cells.get(key, blank)
            if self.prev.get(key, blank) != cell:
                (r, c), (ch, fg, bg) = key, cell
                buf.append(f'\x1b[{r + 1};{c + 1}H\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m'
                           f'\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m{ch}')
        self.prev = {k: v for k, v in cells.items() if v != blank}
        self.out.write(''.join(buf))
        self.out.flush()

    def start(self):
        self.out.write(f'\x1b[?1049h\x1b[?25l\x1b[48;2;{BG[0]};{BG[1]};{BG[2]}m\x1b[2J')
        self.out.flush()

    def stop(self):
        self.out.write('\x1b[0m\x1b[?25h\x1b[?1049l')
        self.out.flush()


class Promo:
    def __init__(self, cfg):
        self.cfg, self.scr = cfg, Screen()
        self.cats = skins()[0]                 # the plain cats only
        self.sheets = {path: Sheet(path, cfg.get('generated')) for path in self.cats}
        self.actors = []                       # {'skin', 'body', 'frames', 'next', 'ref'}
        self.lines, self.labels, self.cursor, self.caption = [], [], None, ''
        self.t = 0.0

    # ---- a cut: who is on screen, what text is around, what they do

    def world(self, lines):
        """The text as the cat's world: every non-blank line is a block, its top a shelf."""
        scr, boxes = self.scr, []
        for k, line in enumerate(lines):
            text = ''.join(t for t, _ in line)
            start, end = len(text) - len(text.lstrip()), len(text.rstrip())
            if end > start:
                boxes.append((start, scr.H - 2 * (k + 1), end, scr.H - 2 * k))
        return World((0, 0, scr.W, scr.H), boxes)

    def actor(self, cat, x, y, pose, script, world=None):
        body = Body(self.cfg, random.Random(len(self.actors) + 3))
        body.x, body.y, body.pose, body.world = x, y, pose, world
        body.lo, body.hi, body.lo_y, body.hi_y = -CELL, self.scr.W, 0, self.scr.H
        self.actors.append({'skin': self.cats[cat], 'body': body, 'frames': script(body), 'next': self.t, 'ref': None})
        return body

    def cut(self, caption, lines=(), cursor=None):
        self.actors, self.labels, self.cursor = [], [], cursor
        self.caption = f'  pspsps   ·   {caption}'
        self.lines = [list(ln) for ln in lines]

    def run(self, seconds, move=None):
        end = self.t + seconds
        while self.t < end - 1e-9:
            tick = time.monotonic()
            self.t += 1 / FPS
            if move:
                self.cursor = move(self.t)
            for a in self.actors:
                while self.t >= a['next']:
                    a['ref'], ms = next(a['frames'])
                    a['next'] += ms / 1000
            self.draw()
            time.sleep(max(0.0, 1 / FPS - (time.monotonic() - tick)))

    # ---- drawing

    def draw(self):
        pixels, labels, scr = {}, list(self.labels), self.scr
        for a in self.actors:
            b, f = a['body'], self.sheets[a['skin']].frame(a['ref'])
            x0, top = round(b.x), scr.H - FEET - round(b.y)
            for sy in range(CELL):
                for sx in range(CELL):
                    p = f.getpixel((sx, sy))
                    if p[3] and 0 <= x0 + sx < scr.W and 0 <= top + sy < scr.H:
                        pixels[x0 + sx, top + sy] = p[:3]
            m = REF_ROW.match(a['ref'])
            row = int(m.group(1)) if m else -1
            bubble = 'meow!' if 28 <= row <= 31 else 'z z z' if 12 <= row <= 19 else None
            if bubble:
                labels.append(((top + HEAD) // 2 - 2, x0 + 20, bubble, ACCENT))
        if self.cursor:
            cx, cy = round(self.cursor[0]), scr.H - 1 - round(self.cursor[1])
            for j, row in enumerate(POINTER):
                for i, ch in enumerate(row):
                    if ch != '.' and 0 <= cx + i < scr.W and 0 <= cy + j < scr.H:
                        pixels[cx + i, cy + j] = (255, 255, 255) if ch == 'W' else (17, 17, 27)
        scr.draw(self.lines, pixels, labels, self.caption)

    # ---- the promo

    def play(self):
        scr = self.scr
        W, H, mid = scr.W, scr.H, scr.W / 2 - CELL / 2
        prompt = [('~/pspsps', PROMPT), (' $ ', TEXT)]

        self.run(0.5)                                          # VHS starts showing a moment after Enter

        # 1. walks in
        self.cut('a pixel cat that lives in your terminal', [prompt + [('ls', TEXT)],
                                                               [('README.md  assets  brain  pet.py', DIM)], prompt])
        self.actor(0, mid - 66, 8, 'stand_R', lambda b: self.walk_in(b, mid))
        self.run(3.0)

        # 2. climbs the text
        pad = (H - 28) // 2 - len(GIT_LOG) - 1                 # the last line's top ends up 28 px up
        lines = [[]] * pad + [prompt + [('git log --oneline', TEXT)]] + [[(c, DIM)] for c in GIT_LOG]
        self.cut('text is furniture: it climbs the lines', lines)
        world = self.world(self.lines)
        last = world.lines[-1]
        self.actor(1, last[2] + 4 - CELL / 2, 6, 'stand_L', lambda b: self.climb(b, world), world)
        self.run(3.4)

        # 3. hunts the pointer
        self.cut('it hunts your cursor', [prompt])
        x0 = W * 0.3
        leap = abs(sum(self.cfg['clips']['pounce_R']['dx']))
        self.cursor = (x0 + 6 + leap + CELL - 8, 10)
        self.actor(2, x0, 8, 'stand_R', self.hunt)
        self.run(3.0)

        # 4. washes, 5. meows when clicked, 6. naps
        self.cut('washes up', [prompt])
        self.actor(0, mid, 10, 'sit_F', lambda b: self.loop(b, 'wash_sit'))
        self.run(1.9)
        self.cut('meows when you click it', [prompt])
        body = self.actor(1, mid, 10, 'stand_F', self.meow)
        tx, ty = body.x + CELL / 2 + 1, body.y + 12
        t0 = self.t
        self.run(1.9, move=lambda t: (tx + 40 * max(0, 1 - (t - t0) / 0.6), ty - 18 * max(0, 1 - (t - t0) / 0.6)))
        self.cut('naps when you are away', [prompt])
        self.actor(2, mid, 10, 'sleep_R', lambda b: self.loop(b, 'breathe_R'))
        self.run(1.9)

        # 7. all three
        self.cut('three cats · needs, habits, a brain of its own')
        gap = 46
        for i in range(3):
            self.actor(i, mid + (i - 1) * gap, 12, 'sit_F', self.idle)
        title = 'p s p s p s'
        tag = 'a pixel cat that lives on your screen'
        head = (H - FEET - 12 + HEAD) // 2                     # text row of the cats' heads
        self.labels = [(max(0, head - 6), (W - len(title)) // 2, title, ACCENT),
                       (max(1, head - 4), (W - len(tag)) // 2, tag, DIM)]
        self.run(3.6)

    # ---- what they do in each cut

    def walk_in(self, b, x):
        while b.x < x:
            yield from b.play('walk_R')
        yield from b.go('stand_F')
        yield from b.go('sit_F')
        yield from self.loop(b, 'blink_sit')

    def climb(self, b, world):
        yield from b.hold_pose(300)
        l, _, r, top = world.lines[-1]
        yield from b.hop(r - 6, top, shelf=True)               # floor -> the last line
        yield from b.along(r - 22)
        for _ in range(2):                                     # and up, line by line
            yield from b.climb_up()
        yield from b.go('sit_F')
        yield from self.loop(b, 'blink_sit')

    def hunt(self, b):
        yield from b.go('stalk_R')
        yield from b.play('creep_R')
        yield from b.play('pounce_R')
        yield from b.go('stand_R')
        yield from self.loop(b, 'paw_R')

    def meow(self, b):
        yield from b.hold_pose(650)
        yield from self.loop(b, 'meow_stand')

    def idle(self, b):
        yield from b.hold_pose(random.Random(b.x).randint(100, 700))
        while True:
            yield from b.behave(1, allow=lambda o: 'go' not in o and 'scratch' not in o.get('play', ''))

    @staticmethod
    def loop(b, clip):
        while True:
            yield from b.play(clip)


def play_film(cfg):
    promo = Promo(cfg)
    promo.scr.start()
    try:
        promo.play()
    finally:
        promo.scr.stop()
