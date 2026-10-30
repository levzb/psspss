"""Long-term memory: the spots where the cat likes to sleep (persisted in brain/memory.json)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MEMORY = os.path.join(HERE, 'memory.json')


class Memory:
    def __init__(self, path=MEMORY, radius=30, keep=8):
        self.path, self.radius, self.keep = path, radius, keep
        self.spots = []                     # [x, y, times slept there]
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    self.spots = json.load(f).get('sleep_spots', [])
            except (OSError, ValueError):
                self.spots = []

    def slept_at(self, x, y):
        """Remember a nap at (x, y): strengthen a nearby spot or start a new one."""
        for s in self.spots:
            if abs(s[0] - x) + abs(s[1] - y) < self.radius:
                s[0], s[1] = (s[0] * s[2] + x) / (s[2] + 1), (s[1] * s[2] + y) / (s[2] + 1)
                s[2] += 1
                break
        else:
            self.spots.append([x, y, 1])
        self.spots.sort(key=lambda s: -s[2])
        del self.spots[self.keep:]
        self.save()

    def favourite(self, rng):
        """A known spot, picked in proportion to how often it was used; None if none yet."""
        if not self.spots:
            return None
        s = rng.choices(self.spots, weights=[s[2] for s in self.spots])[0]
        return s[0], s[1]

    def save(self):
        if not self.path:
            return
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'sleep_spots': [[round(x, 1), round(y, 1), n] for x, y, n in self.spots]}, f)
        os.replace(tmp, self.path)
