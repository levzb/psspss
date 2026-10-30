"""Run the cat without a screen: a made-up user, simulated time. Used by the tests and `pet.py sim`."""
import collections
import random

from .body import CELL, Body
from .memory import Memory
from .mind import LABELS, Mind
from .senses import Tracker
from .world import World

# a Terminal window full of text: 40 lines of ragged length over an empty bottom part
TERMINAL = World((0, 0, 558, 324), [(0, 320 - 4.7 * (k + 1), 40 + (k * 97) % 400, 320 - 4.7 * k) for k in range(40)])

SCREEN = (-5, 523, 0, 300)          # lo, hi, lo_y, hi_y in sprite px (about 1680 x 1000 pt at scale 3)
WINDOW = (40, 20, 480, 260)         # the active window, body coords


class StillUser:
    """Pointer parked at `cursor`; you last touched anything `idle` seconds before t=0."""

    def __init__(self, cursor=None, idle=0.0, window=WINDOW):
        self.cursor, self.idle0, self.window = cursor, idle, window

    def at(self, t):
        return self.idle0 + t, self.cursor


class DayUser:
    """Works at the computer: types (keeps idle low), moves the pointer every now and then,
    sometimes flicks it fast, and takes a break every 40-70 minutes."""

    def __init__(self, rng, window=WINDOW):
        self.rng, self.window = rng, window
        self.cursor = (260.0, 140.0)
        self.move = None                       # (t0, t1, from, to)
        self.next_move = 5.0
        self.last_input = 0.0
        self.break_at = rng.uniform(2400, 4200)
        self.break_end = None

    def at(self, t):
        rng = self.rng
        if self.break_end is None and t >= self.break_at:
            self.break_end = t + rng.uniform(300, 1200)
        if self.break_end is not None:
            if t < self.break_end:
                return t - self.last_input, self.cursor
            self.break_end, self.break_at = None, t + rng.uniform(2400, 4200)
        if self.move and t >= self.move[1]:
            self.cursor, self.move = self.move[3], None
        if self.move is None and t >= self.next_move:
            to = (rng.uniform(SCREEN[0] + 20, SCREEN[1]), rng.uniform(SCREEN[2] + 10, SCREEN[3]))
            dur = rng.uniform(0.3, 1.2)
            self.move = (t, t + dur, self.cursor, to)
            self.next_move = t + dur + rng.expovariate(1 / 25)
        if self.move:
            t0, t1, a, b = self.move
            k = (t - t0) / (t1 - t0)
            self.cursor = (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
            self.last_input = t
        elif rng.random() < 0.3:                 # typing
            self.last_input = t
        return t - self.last_input, self.cursor


class Sim:
    def __init__(self, cfg, user, seed=1, hour=10.0, memory=None, screen=SCREEN, world=None):
        self.rng = random.Random(seed)
        self.body = Body(cfg, self.rng)
        self.body.lo, self.body.hi, self.body.lo_y, self.body.hi_y = screen
        if world is not None:                 # live inside it, as the app does in a Terminal window
            self.body.world = world
            self.body.lo, self.body.hi, self.body.lo_y, self.body.hi_y = world.limits(CELL)
        self.body.x = -32
        self.tracker = Tracker()
        self.memory = memory or Memory(path=None)
        self.mind = Mind(cfg, self.body, self.memory, self.tracker.s, self.rng)
        self.user, self.hour0, self.t = user, hour, 0.0
        self.frames = self.mind.run()
        self.log = []                         # (t, activity) whenever the activity changes
        self.time_in = collections.Counter()
        self.trail = []                       # (t, x, y, frame ref)
        self.sense()

    def sense(self):
        idle, cursor = self.user.at(self.t)
        self.tracker.feed(self.t, (self.hour0 + self.t / 3600) % 24, idle, cursor, self.user.window)

    def preempt(self):
        name = self.mind.preempt()
        if name:
            self.frames = self.mind.switch(name)
        return name

    def run(self, seconds, until=None):
        """Advance `seconds` of simulated time (or until until(sim) is true). Long frames are
        cut into 0.25 s slices so preemption can interrupt them, as the app's 30 Hz poll does."""
        end = self.t + seconds
        while self.t < end:
            ref, ms = next(self.frames)
            self.trail.append((self.t, self.body.x, self.body.y, ref))
            left = ms / 1000
            while left > 0:
                dt = min(0.25, left)
                left -= dt
                self.t += dt
                self.mind.update(dt)
                self.time_in[self.mind.activity] += dt
                self.sense()
                if self.preempt():
                    break
            if not self.log or self.log[-1][1] != self.mind.activity:
                self.log.append((self.t, self.mind.activity))
            if until and until(self):
                return True
        return False


def report(hours=8.0, seed=1, hour=9.0):
    """Simulate a working day and print where the time went."""
    from .config import load_config
    rng = random.Random(seed)
    sim = Sim(load_config(), DayUser(rng), seed=seed, hour=hour)
    sim.run(hours * 3600)
    total = sum(sim.time_in.values())
    print(f'{hours:g} simulated hours from {hour:g}:00, seed {seed}')
    for name, sec in sim.time_in.most_common():
        starts = sum(1 for _, a in sim.log if a == name)
        print(f'  {LABELS.get(name, name):22s} {100 * sec / total:5.1f}%   {starts:4d} times')
    xs = [x for _, x, _, _ in sim.trail[50:]]
    ys = [y for _, _, y, _ in sim.trail]
    print(f'  x {min(xs):.0f}..{max(xs):.0f}, y {min(ys):.0f}..{max(ys):.0f} (screen {SCREEN})')
    print(f'  favourite sleep spots: {[[round(v) for v in s] for s in sim.memory.spots]}')
    print('  needs at the end:', {k: round(v, 2) for k, v in sim.mind.needs.items()})
    pounces = sum(1 for _, _, _, r in sim.trail if r.startswith('@stalkhi'))
    print(f'  pounces: {pounces // 2}; first hour of activities:')
    print('   ', ' → '.join(f'{LABELS.get(a, a)}' for t, a in sim.log if t < 3600)[:600])
    return sim

