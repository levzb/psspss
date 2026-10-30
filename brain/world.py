"""The inside of a Terminal window as the cat's world.

Seen from above, like the rest of the screen: the empty part of the window is the floor, and
every line of text is a block the cat can't walk through. It can jump on top of a line, though,
walk along it like a shelf and climb from line to line.

Everything is in body px (sprite px from the bottom-left of the usable screen). A place is the
paw point: (cell left + CELL / 2, paw line). Pure and screen-free, so the tests can build one.
"""
import math
from collections import deque

STEP = 4            # path-finding grid
MX, MY = 6, 1       # how close the paws may come to text: sideways, up/down
HEADROOM = 21       # paws to the top of the head: on the floor the head stays inside the window
REACH = 26          # the longest jump between the floor and a shelf
CLIMB = 12          # the highest step from one line to the next


class World:
    def __init__(self, bounds, lines):
        """bounds: (left, bottom, right, top) of the text area; lines: (left, bottom, right, top[, text])."""
        self.bounds = bounds
        self.lines = sorted((tuple(ln[:4]) for ln in lines), key=lambda ln: -ln[3])   # top to bottom
        left, bottom, right, top = bounds
        self.cols = max(1, int((right - left) / STEP) + 1)
        self.rows = max(1, int((top - bottom) / STEP) + 1)
        self.grid = [[left + MX <= self.point(i, j)[0] <= right - MX and self.point(i, j)[1] <= top - HEADROOM
                      for i in range(self.cols)] for j in range(self.rows)]
        for l, b, r, t in self.lines:            # every grid point strictly inside a line's margin is text
            i0, i1 = math.floor((l - MX - left) / STEP) + 1, math.ceil((r + MX - left) / STEP) - 1
            j0, j1 = math.floor((b - MY - bottom) / STEP) + 1, math.ceil((t + MY - bottom) / STEP) - 1
            for j in range(max(j0, 0), min(j1, self.rows - 1) + 1):
                row = self.grid[j]
                for i in range(max(i0, 0), min(i1, self.cols - 1) + 1):
                    row[i] = False
        self._near = None

    def limits(self, cell):
        """lo, hi, lo_y, hi_y for the left edge and paw line of a `cell`-wide sprite."""
        left, bottom, right, top = self.bounds
        return left + MX - cell / 2, right - MX - cell / 2, bottom, top

    # ---- grid

    def point(self, i, j):
        return self.bounds[0] + i * STEP, self.bounds[1] + j * STEP

    def cell(self, px, y):
        return round((px - self.bounds[0]) / STEP), round((y - self.bounds[1]) / STEP)

    def open_cell(self, i, j):
        return 0 <= i < self.cols and 0 <= j < self.rows and self.grid[j][i]

    def free(self, px, y):
        """Floor the paws may stand on."""
        return self.open_cell(*self.cell(px, y))

    def neighbours(self, i, j):
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if (di or dj) and self.open_cell(i + di, j + dj) and \
                        (not (di and dj) or (self.open_cell(i + di, j) and self.open_cell(i, j + dj))):
                    yield i + di, j + dj

    # ---- shelves

    def shelf_at(self, px, y, tol=1.0):
        """The line whose top the paws stand on, or None."""
        return next((ln for ln in self.lines if abs(y - ln[3]) <= tol and ln[0] <= px <= ln[2]), None)

    def line_above(self, px, y):
        """Top of the next line up that has text over px, if it is a step away."""
        tops = [t for l, b, r, t in self.lines if l <= px <= r and y + 0.5 < t <= y + CLIMB]
        return min(tops) if tops else None

    def line_below(self, px, y):
        tops = [t for l, b, r, t in self.lines if l <= px <= r and y - CLIMB <= t < y - 0.5]
        return max(tops) if tops else None

    def shelf_spots(self, spacing=6):
        """[(spot on a line, the floor next to it)] for every place the cat can jump up from the floor."""
        out = []
        for l, b, r, t in self.lines:
            n = max(1, int((r - l - 6) / spacing))
            for k in range(n + 1):
                px = l + 3 + (r - l - 6) * k / n
                near = self.nearest_free(px, t, REACH)
                if near:
                    out.append(((px, t), near))
        return out

    # ---- getting around on the floor

    def nearest_free(self, px, y, within=math.inf):
        """A close floor point to (px, y), or None if there is none within `within` px."""
        if self._near is None:                  # flood out from all the floor at once, remembering the source
            self._near = [[(i, j) if self.grid[j][i] else None for i in range(self.cols)] for j in range(self.rows)]
            todo = deque((i, j) for j in range(self.rows) for i in range(self.cols) if self.grid[j][i])
            while todo:
                i, j = todo.popleft()
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        n = i + di, j + dj
                        if 0 <= n[0] < self.cols and 0 <= n[1] < self.rows and self._near[n[1]][n[0]] is None:
                            self._near[n[1]][n[0]] = self._near[j][i]
                            todo.append(n)
        i, j = self.cell(px, y)
        src = self._near[min(max(j, 0), self.rows - 1)][min(max(i, 0), self.cols - 1)]
        if src is None:
            return None
        q = self.point(*src)
        return q if math.dist(q, (px, y)) <= within else None

    def path(self, a, b):
        """Floor points from a to b on the grid (8-way, no corner cutting), or None."""
        start, goal = self.cell(*a), self.cell(*b)
        if not (self.open_cell(*start) and self.open_cell(*goal)):
            return None
        prev, todo = {start: None}, deque([start])
        while todo:
            c = todo.popleft()
            if c == goal:
                break
            for n in self.neighbours(*c):
                if n not in prev:
                    prev[n] = c
                    todo.append(n)
        if goal not in prev:
            return None
        out = []
        while goal is not None:
            out.append(self.point(*goal))
            goal = prev[goal]
        return out[::-1]

    def legs(self, a, b):
        """The walk from a to b as one diagonal and one straight leg [(dir, length)], if both stay on the floor."""
        vx, vy = b[0] - a[0], b[1] - a[1]
        sx, sy = (vx > 0) - (vx < 0), (vy > 0) - (vy < 0)
        diag, rest = min(abs(vx), abs(vy)), abs(abs(vx) - abs(vy))
        straight = (sx, 0) if abs(vx) > abs(vy) else (0, sy)
        for order in (((sx, sy), diag), (straight, rest)), ((straight, rest), ((sx, sy), diag)):
            p, ok = a, True
            for vec, length in order:
                for k in range(1, int(length / 2) + 2):
                    s = min(2 * k, length)
                    if not self.free(p[0] + vec[0] * s, p[1] + vec[1] * s):
                        ok = False
                        break
                if not ok:
                    break
                p = (p[0] + vec[0] * length, p[1] + vec[1] * length)
            if ok:
                return [(v, n) for v, n in order if n >= 1 and v != (0, 0)]
        return None

    def route(self, a, b):
        """[(dir, length)] legs to walk from floor point a to floor point b around the text, or None."""
        pts = self.path(a, b)
        if pts is None:
            return None
        out, here, k = [], a, 0
        while k < len(pts) - 1:
            for j in range(len(pts) - 1, k, -1):    # the farthest point still in a two-leg line of sight
                legs = self.legs(here, pts[j])
                if legs is not None:
                    break
            else:
                j, legs = k + 1, self.legs(here, pts[k + 1]) or []
            out += legs
            here, k = pts[j], j
        return [(v, n) for v, n in out if v != (0, 0) and n >= 1]
