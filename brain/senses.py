"""What the cat knows about you. Coordinates are in body space (sprite px, see body.py).
The app feeds raw readings; the simulator and the tests feed made-up ones."""
import math
from dataclasses import dataclass


@dataclass
class Senses:
    t: float = 0.0               # seconds, monotonic
    hour: float = 12.0           # local time of day, 0..24
    idle: float = 0.0            # seconds since you last touched the mouse or keyboard
    cursor: tuple = None         # (x, y) of the mouse pointer
    speed: float = 0.0           # pointer speed, px/s, smoothed
    still: float = 0.0           # seconds since the pointer last moved
    window: tuple = None         # active window: (left, bottom, right, top)


class Tracker:
    """Turns raw readings into Senses: pointer speed and how long it has been still."""

    def __init__(self):
        self.s = Senses()
        self.moved_at = 0.0

    def feed(self, t, hour, idle, cursor, window):
        s, dt = self.s, max(t - self.s.t, 1e-3)
        if cursor is not None and s.cursor is not None:
            dist = math.dist(cursor, s.cursor)
            s.speed = 0.6 * s.speed + 0.4 * dist / dt
            if dist > 0.5:
                self.moved_at = t
        s.t, s.hour, s.idle, s.cursor, s.window = t, hour, idle, cursor, window
        s.still = t - self.moved_at
        return s
