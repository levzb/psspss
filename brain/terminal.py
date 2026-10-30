"""Reading Terminal.app through the Accessibility API: where its text sits on screen.

Needs the Accessibility permission. A process started from Terminal inherits Terminal's,
so check AXIsProcessTrusted(). All points here are AppKit screen points (origin bottom-left);
AX itself works top-left, hence the flips.
"""
import ApplicationServices as AS
from AppKit import NSScreen


def _top():
    return NSScreen.screens()[0].frame().size.height


def ax(el, name):
    err, v = AS.AXUIElementCopyAttributeValue(el, name, None)
    return v if err == 0 else None


def trusted():
    return bool(AS.AXIsProcessTrusted())


def _find(el, role, depth=4):
    if ax(el, 'AXRole') == role:
        return el
    if depth:
        for ch in ax(el, 'AXChildren') or []:
            hit = _find(ch, role, depth - 1)
            if hit is not None:
                return hit
    return None


def frame(el):
    """(left, bottom, right, top) of an element on screen, or None."""
    pos, size = ax(el, 'AXPosition'), ax(el, 'AXSize')
    if pos is None or size is None:
        return None
    ok, pos = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
    ok2, size = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
    if not (ok and ok2):
        return None
    top = _top()
    return pos.x, top - pos.y - size.height, pos.x + size.width, top - pos.y


def text_area(pid, box):
    """The AXTextArea of app `pid`'s window whose frame is `box` (left, bottom, right, top), or None."""
    app = AS.AXUIElementCreateApplication(pid)
    for win in ax(app, 'AXWindows') or []:
        f = frame(win)
        if f and all(abs(a - b) < 2 for a, b in zip(f, box)):
            return _find(win, 'AXTextArea')
    return None


def viewport(area):
    """The visible part of the text area (the area itself is as tall as the whole scrollback)."""
    return frame(ax(area, 'AXParent'))


def index_at(area, x, y):
    """Index of the character at the screen point, or None."""
    point = AS.AXValueCreate(AS.kAXValueCGPointType, (x, _top() - y))
    err, v = AS.AXUIElementCopyParameterizedAttributeValue(area, 'AXRangeForPosition', point, None)
    if err != 0 or v is None:
        return None
    ok, (loc, _) = AS.AXValueGetValue(v, AS.kAXValueCFRangeType, None)
    return loc if ok else None


def anchor(area, x, y):
    """(index, bottom) of a character to follow while the text scrolls: the one at the point,
    else the first visible one (every character moves the same). None if there is no text."""
    for i in (index_at(area, x, y), visible_range(area)[0]):
        box = i is not None and char_box(area, i)
        if box:
            return i, box[1]
    return None


def visible_range(area):
    err, v = AS.AXUIElementCopyAttributeValue(area, 'AXVisibleCharacterRange', None)
    if err != 0 or v is None:
        return None, 0
    ok, r = AS.AXValueGetValue(v, AS.kAXValueCFRangeType, None)
    return r if ok else (None, 0)


def char_box(area, index, length=1):
    """(left, bottom, right, top) of the characters [index, index+length) on screen, or None."""
    r = AS.AXValueCreate(AS.kAXValueCFRangeType, (index, length))
    err, v = AS.AXUIElementCopyParameterizedAttributeValue(area, 'AXBoundsForRange', r, None)
    if err != 0 or v is None:
        return None
    ok, rect = AS.AXValueGetValue(v, AS.kAXValueCGRectType, None)
    if not ok:
        return None
    top = _top()
    return rect.origin.x, top - rect.origin.y - rect.size.height, rect.origin.x + rect.size.width, top - rect.origin.y


def visible_lines(area):
    """[(left, bottom, right, top, text)] for every visible line that has text, in screen points."""
    loc, length = visible_range(area)
    if loc is None:
        return []
    r = AS.AXValueCreate(AS.kAXValueCFRangeType, (loc, length))
    err, text = AS.AXUIElementCopyParameterizedAttributeValue(area, 'AXStringForRange', r, None)
    if err != 0 or text is None:
        return []
    out, pos = [], loc
    for line in text.split('\n'):
        start, end = len(line) - len(line.lstrip()), len(line.rstrip())
        if end > start:
            box = char_box(area, pos + start, end - start)
            if box:
                out.append((*box, line[start:end]))
        pos += len(line) + 1
    return out
