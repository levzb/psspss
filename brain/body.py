"""The cat's body: where it is, which pose it holds, and how it gets between poses and places.

Every motion is a generator that yields (frame_ref, ms) and updates x / y as it goes:
x = left edge of the sprite cell, y = paw line, both in sprite px from the bottom-left
of the usable screen, kept inside [lo, hi] x [lo_y, hi_y].

With a `world` (a Terminal window, see world.py) the text is in the way: the cat walks around
it on the floor, or stands on top of a line (`on_shelf`) and then moves only along it.
"""
import math
from collections import deque

from .world import REACH

CELL = 32
DIRS = {(-1, 0): 'L', (1, 0): 'R', (0, -1): 'F', (0, 1): 'B',
        (-1, -1): 'dL', (1, -1): 'dR', (-1, 1): 'uL', (1, 1): 'uR'}


class Body:
    def __init__(self, cfg, rng):
        self.cfg, self.rng = cfg, rng
        self.adj = {}
        for a, b, ms in cfg['links']:
            self.adj.setdefault(a, []).append((b, ms))
            self.adj.setdefault(b, []).append((a, ms))
        self.x = self.y = 0.0
        self.lo, self.hi, self.lo_y, self.hi_y = -5, 400, 0, 220
        self.pose, self.doing = 'stand_R', ''
        self.world, self.on_shelf, self.airborne = None, False, False
        self.moves = 0                  # bumped by every jump: tells the app the cat changed lines itself

    # ---- where things are

    @property
    def center(self):
        return self.x + CELL / 2, self.y

    def clamp(self, x, y):
        return min(max(x, self.lo), self.hi), min(max(y, self.lo_y), self.hi_y)

    @property
    def paws(self):
        return self.x + CELL / 2, self.y

    def can_move(self, dx, dy=0):
        nx, ny = self.x + dx, self.y + dy
        if self.world is not None:
            w, px = self.world, nx + CELL / 2
            if self.on_shelf:
                return not dy and w.shelf_at(px, self.y) is not None
            return w.free(px, ny) or not w.free(*self.paws)          # stuck in text: any way out will do
        return not ((dx > 0 and nx > self.hi) or (dx < 0 and nx < self.lo)
                    or (dy > 0 and ny > self.hi_y) or (dy < 0 and ny < self.lo_y))

    def standing(self):
        return self.pose.startswith('stand_')

    def facing(self):
        """-1 if the current pose looks left, 1 if right, 0 if straight ahead / away."""
        side = self.pose.rsplit('_', 1)[-1]
        return -1 if side.endswith('L') else 1 if side.endswith('R') else 0

    # ---- pose graph

    def path(self, src, dst):
        prev, todo = {src: None}, deque([src])
        while todo:
            p = todo.popleft()
            for q, ms in self.adj.get(p, []):
                if q not in prev:
                    prev[q] = (p, ms)
                    todo.append(q)
        if dst not in prev:
            raise ValueError(f'no path {src} -> {dst}')
        steps = []
        while prev[dst]:
            p, ms = prev[dst]
            steps.append((dst, ms))
            dst = p
        return steps[::-1]

    def go(self, dst):
        for pose, ms in self.path(self.pose, dst):
            self.pose = pose
            yield self.cfg['poses'][pose], ms

    def stand_up(self):
        """Get on the feet by the shortest path, keeping the facing if there is one."""
        if not self.standing():
            near = min((p for p in self.cfg['poses'] if p.startswith('stand_')),
                       key=lambda p: len(self.path(self.pose, p)))
            yield from self.go(near)

    def hold_pose(self, ms=120):
        yield self.cfg['poses'][self.pose], ms

    # ---- clips

    def play(self, name, times=1):
        clip = self.cfg['clips'][name]
        for _ in range(times):
            for ref, ms, dx, dy in zip(clip['frames'], clip['ms'], clip['dx'], clip['dy']):
                if (dx or dy) and not self.can_move(dx, dy):
                    return
                self.x += dx
                self.y += dy
                yield ref, ms

    def step(self, o):
        """One step from anim.json (behaviour / on_click / on_drop / scroll edge)."""
        if 'go' in o:
            self.doing = f'{self.pose} -> {o["go"]}'
            yield from self.go(o['go'])
        elif 'pose' in o:
            self.pose = o['pose']
        elif 'play' in o:
            self.doing = f'{self.pose}: {o["play"]}'
            yield from self.play(o['play'], self.rng.randint(*o.get('times', [1, 1])))
            yield from self.hold_pose()              # settle back into the pose
        elif 'roam' in o:
            yield from self.roam(*o['roam'], o.get('run', 0))
        elif 'settle' in o:
            yield from self.settle()
        else:
            self.doing = f'{self.pose}: idle'
            yield from self.hold_pose(int(self.rng.uniform(*o['hold']) * 1000))

    def behave(self, n, allow=lambda o: True):
        """n weighted picks from the pose's behaviour table (the cat's small habits)."""
        for _ in range(n):
            opts = [o for o in self.cfg['behaviour'][self.pose] if allow(o) and o.get('go') != self.pose]
            clip_ok = [o for o in opts if 'play' not in o
                       or self.can_move(sum(self.cfg['clips'][o['play']]['dx']),
                                        sum(self.cfg['clips'][o['play']]['dy']))]
            if not clip_ok:
                return
            yield from self.step(self.rng.choices(clip_ok, weights=[o['w'] for o in clip_ok])[0])

    # ---- getting places

    def walk_to(self, tx, ty, kind='walk', max_cycles=None):
        """Walk (or run) to (tx, ty): one diagonal and one straight leg, turning in between.
        Stops at the end of a walk cycle, so it lands within half a cycle of the target."""
        if self.world is not None:
            yield from self.walk_in_world(tx + CELL / 2, ty, kind, max_cycles and max_cycles * 24)
            return
        tx, ty = self.clamp(tx, ty)
        vx, vy = tx - self.x, ty - self.y
        sx, sy = (vx > 0) - (vx < 0), (vy > 0) - (vy < 0)
        straight = (sx, 0) if abs(vx) > abs(vy) else (0, sy)
        legs = [((sx, sy), min(abs(vx), abs(vy))), (straight, abs(abs(vx) - abs(vy)))]
        if self.rng.random() < 0.5:
            legs.reverse()
        cycles_left = max_cycles
        for vec, length in legs:
            if vec == (0, 0):
                continue
            d = DIRS[vec]
            clip = self.cfg['clips'][f'{kind}_{d}']
            cycles = round(length / max(abs(sum(clip['dx'])), abs(sum(clip['dy']))))
            if cycles_left is not None:
                cycles = min(cycles, cycles_left)
                cycles_left -= cycles
            if cycles < 1:
                continue
            self.doing = f'{kind} {d}'
            yield from self.stand_up()
            yield from self.go(f'stand_{d}')
            yield from self.play(f'{kind}_{d}', cycles)
            yield from self.hold_pose()

    def roam(self, rmin, rmax, run_chance=0.0):
        """Walk to a random spot rmin..rmax px away (flattened vertically)."""
        if self.on_shelf:
            if self.rng.random() < 0.7:           # along the line it stands on
                l, _, r, _ = self.world.shelf_at(*self.paws)
                yield from self.along(self.rng.uniform(l + 3, r - 3))
                return
            yield from self.get_down()
        for _ in range(20):
            a, r = self.rng.uniform(0, 2 * math.pi), self.rng.uniform(rmin, rmax)
            tx, ty = self.x + r * math.cos(a), self.y + r * math.sin(a) * 0.6
            if self.lo <= tx <= self.hi and self.lo_y <= ty <= self.hi_y:
                break
        kind = 'run' if self.rng.random() < run_chance else 'walk'
        yield from self.walk_to(tx, ty, kind)

    def face(self, side):
        """Turn to look left (-1), right (1) or at you (0)."""
        yield from self.stand_up()
        yield from self.go({-1: 'stand_L', 1: 'stand_R', 0: 'stand_F'}[side])

    # ---- in a Terminal window

    def stride(self, kind, d, length):
        """Play the walk clip for about `length` px (not whole cycles), stopping at anything in the way.
        Returns how far it got."""
        clip, done = self.cfg['clips'][f'{kind}_{d}'], 0
        while True:
            for ref, ms, dx, dy in zip(clip['frames'], clip['ms'], clip['dx'], clip['dy']):
                step = max(abs(dx), abs(dy))
                if done + step / 2 > length or not self.can_move(dx, dy):   # no overshooting
                    return done
                self.x += dx
                self.y += dy
                done += step
                yield ref, ms

    def walk_in_world(self, px, y, kind='walk', budget=None):
        """Walk the paws to (px, y) around the text; along the line if both are on the same one."""
        w = self.world
        if self.on_shelf:
            here = w.shelf_at(*self.paws)
            if here is not None and here == w.shelf_at(px, y, tol=3):
                yield from self.along(px, kind)
                return
            yield from self.get_down()
        elif not w.free(*self.paws):
            yield from self.settle()
        goal = (px, y) if w.free(px, y) else w.nearest_free(px, y)
        for _ in range(12):                       # one leg at a time, planning again from where it got to
            legs = goal and w.route(self.paws, goal)
            while legs and legs[0][1] < 2 and len(legs) > 1:     # already there, near enough
                legs.pop(0)
            if not legs or (budget is not None and budget < 2):
                break
            vec, length = legs[0]
            if budget is not None:
                length = min(length, budget)
            d = DIRS[vec]
            self.doing = f'{kind} {d}'
            yield from self.stand_up()
            yield from self.go(f'stand_{d}')
            went = yield from self.stride(kind, d, length)
            yield from self.hold_pose()
            if budget is not None:
                budget -= went
            if not went:
                break

    def along(self, px, kind='walk'):
        """Walk along the line it stands on to px."""
        dist = px - self.paws[0]
        if abs(dist) < 2:
            return
        d = 'L' if dist < 0 else 'R'
        self.doing = f'along the line {d}'
        yield from self.stand_up()
        yield from self.go(f'stand_{d}')
        yield from self.stride(kind, d, abs(dist))
        yield from self.hold_pose()

    def hop(self, px, y, shelf=False):
        """Jump so the paws land at (px, y): on top of a line if `shelf`, else on the floor."""
        x0, y0, tx = self.x, self.y, px - CELL / 2
        side = -1 if tx < x0 - 1 else 1 if tx > x0 + 1 else (self.facing() or self.rng.choice((-1, 1)))
        d = 'L' if side < 0 else 'R'
        self.doing = 'jumps up' if y > y0 else 'jumps down'
        yield from self.face(side)
        clip = self.cfg['clips'][f'jump_{d}']
        weights = [abs(v) for v in clip['dx']]
        f = arc = 0.0
        self.airborne = True                      # cut short mid-air, the mind clears it and settles the cat
        for ref, ms, wx, dy in zip(clip['frames'], clip['ms'], weights, clip['dy']):
            f += wx / sum(weights)
            arc += dy
            self.x, self.y = x0 + (tx - x0) * f, y0 + (y - y0) * f + arc
            yield ref, ms
        self.x, self.y, self.on_shelf, self.airborne = tx, y, shelf, False
        self.pose = f'stand_{d}'
        self.moves += 1
        yield from self.hold_pose()

    def grounded(self):
        """On the floor or on a line, as it should be (always true outside a Terminal window)."""
        w = self.world
        return w is None or self.airborne or bool(w.shelf_at(*self.paws) if self.on_shelf else w.free(*self.paws))

    def climb_up(self):
        top = self.world.line_above(*self.paws)
        if top is not None:
            yield from self.hop(self.paws[0], top, shelf=True)

    def climb_down(self):
        top = self.world.line_below(*self.paws)
        if top is not None:
            yield from self.hop(self.paws[0], top, shelf=True)

    def jump_on_text(self):
        """Walk to a line of text that can be reached from the floor and jump on top of it."""
        w = self.world
        spots = w.shelf_spots()
        if not spots:
            return False
        weights = [1 / (1 + math.dist(near, self.paws) / 60) for _, near in spots]
        for _ in range(5):
            spot, near = self.rng.choices(spots, weights)[0]
            if math.dist(near, self.paws) < 3 or w.route(self.paws, near):
                yield from self.walk_in_world(*near)
                if math.dist(self.paws, near) < 6:
                    yield from self.hop(*spot, shelf=True)
                    return True
        return False

    def get_down(self):
        """Off the line it stands on, onto the nearest floor (walking to the line's end first if that is closer)."""
        w = self.world
        near = w.nearest_free(*self.paws)
        if near is None:
            return
        line = w.shelf_at(*self.paws)
        if line is not None and math.dist(near, self.paws) > REACH:
            ends = [(e, w.nearest_free(e, self.y)) for e in (line[0] + 3, line[2] - 3)]
            ends = [(e, n) for e, n in ends if n]
            if ends:
                e, near = min(ends, key=lambda en: math.dist(en[1], (en[0], self.y)))
                yield from self.along(e)
        yield from self.hop(*near)

    def settle(self):
        """Text appeared under the cat, or the line it stood on is gone: get to solid ground."""
        if self.grounded():
            return
        w = self.world
        near = w.nearest_free(*self.paws)
        if near is not None:
            yield from self.hop(*near)
