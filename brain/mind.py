"""The cat's mind: needs that drift with time, and activities picked to satisfy the strongest one.

Needs, each 0..1, change per minute depending on the current activity (anim.json "mind"):
  energy     drops while awake, faster when running; refills while asleep
  boredom    grows while nothing happens; play (chasing, hunting, zoomies) burns it off
  affection  wish for your attention; grows while you ignore the cat, a click or a greeting fills it

Every time an activity ends, each candidate gets a score from the needs, the time of day and
what the senses report, and one is drawn at random in proportion to score^2. Some events cut
in right away (`preempt`): you leave (it goes to sleep), you come back (it greets you), the
pointer darts past (chase) or stops near it (hunt).

Inside a Terminal window (body.world) there is one more thing to do: climb the lines of text.
"""
import math

from .body import CELL

LABELS = {'sleep': 'спит', 'rest': 'отдыхает', 'wander': 'гуляет', 'chase': 'гоняется за курсором',
          'hunt': 'охотится на курсор', 'greet': 'встречает вас', 'visit': 'пришёл к вашему окну',
          'zoomies': 'носится', 'react': 'реагирует', 'arrive': 'пришёл', 'climb': 'лазит по тексту'}
SLEEP_POSES = ('sleep_', 'back_', 'curl_', 'stretch_')
BREATHE = {'sleep': 'breathe', 'back': 'breathe_back', 'curl': 'breathe_curl', 'stretch': 'breathe_stretch'}
REST_POSES = ('sit_', 'loaf_', 'lieside_', 'crouch_')


def in_hours(hour, span):
    a, b = span
    return a <= hour < b if a < b else hour >= a or hour < b


class Mind:
    def __init__(self, cfg, body, memory, senses, rng):
        self.cfg, self.m = cfg, cfg['mind']
        self.body, self.memory, self.senses, self.rng = body, memory, senses, rng
        self.needs = dict(self.m['start'])
        self.activity = 'arrive'
        self.started = {}            # activity -> time it last started (for cooldowns)
        self.reacting = False
        self.was_away = False

    # ---------------------------------------------------------------- needs

    @property
    def night(self):
        return in_hours(self.senses.hour, self.m['night'])

    def update(self, dt):
        """Let dt seconds of the current activity act on the needs."""
        for need, table in self.m['per_minute'].items():
            rate = table.get(self.activity, table['default'])
            if need == 'energy' and self.night:
                rate = rate * self.m['night_sleepiness'] if rate < 0 else rate / self.m['night_sleepiness']
            self.needs[need] = min(1.0, max(0.0, self.needs[need] + rate * dt / 60))

    def adjust(self, changes):
        for need, d in changes.items():
            self.needs[need] = min(1.0, max(0.0, self.needs[need] + d))

    def status(self):
        n = self.needs
        return (f'{LABELS.get(self.activity, self.activity)} · энергия {n["energy"]:.0%} · '
                f'скука {n["boredom"]:.0%} · хочет внимания {n["affection"]:.0%}')

    # ---------------------------------------------------------------- what the senses say

    def cooled(self, name):
        return self.senses.t - self.started.get(name, -1e9) > self.m[name]['cooldown']

    def cursor_dist(self):
        c = self.senses.cursor
        return math.dist(c, self.body.center) if c else math.inf

    def cursor_on_screen(self):
        c, b = self.senses.cursor, self.body
        return c is not None and b.lo <= c[0] - CELL / 2 <= b.hi and b.lo_y <= c[1] <= b.hi_y

    def chase_ok(self):
        c, n = self.m['chase'], self.needs
        return (self.cursor_on_screen() and self.senses.speed > c['speed'] and self.cursor_dist() < c['radius']
                and n['boredom'] > c['boredom'] and n['energy'] > c['energy'] and self.cooled('chase'))

    def hunt_ok(self):
        h, n, s = self.m['hunt'], self.needs, self.senses
        return (self.cursor_on_screen() and h['still'][0] < s.still < h['still'][1]
                and 25 < self.cursor_dist() < h['radius']
                and n['boredom'] > h['boredom'] and n['energy'] > h['energy'] and self.cooled('hunt'))

    def away(self):
        return self.senses.idle > self.m['away_after']

    # ---------------------------------------------------------------- choosing

    def scores(self):
        n, s = self.needs, self.senses
        e, b, a = n['energy'], n['boredom'], n['affection']
        sleep = 3 * (1 - e) ** 2 + (0.8 if self.night else 0) + (3 if self.away() else 0)
        if e > 0.7 and not self.night and not self.away():
            sleep *= 0.2
        z, world = self.m['zoomies'], self.body.world
        return {
            'sleep': sleep,
            'rest': 0.7 + 0.8 * (1 - e),
            'wander': 0.3 + 0.8 * b + 0.4 * e if e > 0.2 else 0.05,
            'visit': (2 * a if a > self.m['visit']['affection'] and s.window and self.cooled('visit')
                      and world is None else 0),       # in a Terminal window it is at your window already
            'climb': (0.3 + 0.6 * b if world is not None and e > self.m['climb']['energy']
                      and self.cooled('climb') else 0),
            'zoomies': 1.5 if (in_hours(s.hour, self.m['evening']) and e > z['energy'] and self.cooled('zoomies')
                               and self.rng.random() < z['chance']) else 0,
            'hunt': 2 * b if self.hunt_ok() else 0,
        }

    def choose(self):
        sc = {k: v * v for k, v in self.scores().items() if v > 0}
        return self.rng.choices(list(sc), weights=list(sc.values()))[0]

    def preempt(self):
        """An activity that should start right now, interrupting the current one, or None."""
        if self.reacting or self.activity == 'arrive':     # let it walk onto the screen first
            return None
        away = self.away()
        if away:
            self.was_away = True
        elif self.was_away and self.senses.idle < 2:
            self.was_away = False
            return 'greet'
        if away and self.activity not in ('sleep', 'greet'):
            return 'sleep'
        if self.activity in ('rest', 'wander', 'visit'):
            if self.chase_ok():
                return 'chase'
            if self.hunt_ok():
                return 'hunt'
        return None

    # ---------------------------------------------------------------- the main loop

    def run(self):
        intro, b = self.cfg['intro'], self.body
        b.pose, b.doing = intro['pose'], 'arrives'
        yield from b.play(intro['play'], self.rng.randint(*intro['times']))
        yield from self.loop()

    def loop(self):
        while True:
            yield from self.do(self.choose())

    def do(self, name):
        self.activity = name
        self.started[name] = self.senses.t
        n = yield from counted(getattr(self, f'act_{name}')())
        if not n:                                  # nothing to show: don't spin without yielding
            yield from self.body.hold_pose(300)

    def switch(self, name):
        """Drop what we are doing and start `name` (used for preemption)."""
        self.activity = name                       # at once, so preemption doesn't fire again
        self.body.airborne = False
        yield from self.body.settle()
        yield from self.body.hold_pose()
        yield from self.do(name)
        yield from self.loop()

    def react(self, steps, label, changes=None):
        """A reflex (click, drop, scroll): play anim.json steps, then carry on as usual."""
        self.reacting, self.activity, self.body.doing = True, 'react', label
        self.body.airborne = False
        if changes:
            self.adjust(changes)
        if not steps or 'pose' not in steps[0]:
            yield from self.body.hold_pose()       # stop mid-stride first
        for s in steps:
            yield from self.body.step(s)
        self.reacting = False
        yield from self.loop()

    def clicked(self, label='clicked'):
        seqs = self.cfg['on_click'].get(self.body.pose) or self.cfg['on_click']['default']
        return self.react(self.rng.choice(seqs), label, self.m['click'])

    def dropped(self, x, y):
        self.body.x, self.body.y = self.body.clamp(round(x), round(y))
        return self.react(self.cfg['on_drop'] + [{'settle': True}], 'dropped', self.m['drop'])

    # ---------------------------------------------------------------- activities

    def side_of(self, x):
        """-1 if x is left of the cat, 1 if right."""
        return -1 if x < self.body.center[0] else 1

    def act_rest(self):
        b, rng = self.body, self.rng
        if not b.pose.startswith(REST_POSES):
            side = 'L' if b.facing() < 0 else 'R'
            spot = rng.choices(['sit_F', f'loaf_{side}', f'sit_{side}', f'lieside_{side}'], [5, 3, 1, 1])[0]
            yield from b.go(spot)
        yield from b.behave(rng.randint(2, 6), allow=lambda o: o.get('go', 'sit_').startswith(REST_POSES))

    def act_wander(self):
        b, rng = self.body, self.rng
        for _ in range(rng.randint(1, 3)):
            yield from b.roam(40, 200, run_chance=0.1 + 0.2 * self.needs['energy'])
            yield from b.behave(1, allow=lambda o: 'go' not in o)

    def act_sleep(self):
        b, rng = self.body, self.rng
        spot = self.memory.favourite(rng) if rng.random() < self.m['favourite_spot'] else None
        if spot and math.dist(spot, (b.x, b.y)) < 250:
            b.doing = 'going to a favourite spot'
            yield from b.walk_to(*spot)
        side = rng.choice('LR')
        b.doing = 'going to sleep'
        yield from b.go(f'loaf_{side}')
        yield from b.play(f'yawn_lie_{side}')
        yield from b.go(f'sleep_{side}')
        self.memory.slept_at(b.x, b.y)
        target = 1.0 if self.night else rng.uniform(0.85, 1.0)
        b.doing = 'asleep'
        while self.needs['energy'] < target or self.away():   # alone, a cat just sleeps on
            kind = b.pose.split('_')[0]
            if rng.random() < 0.03:                 # turn over in its sleep
                yield from b.go(rng.choice([f'{p}{side}' for p in SLEEP_POSES if not b.pose.startswith(p)]))
                continue
            yield from b.play(f'{BREATHE[kind]}_{side}')
        b.doing = 'waking up'
        yield from b.go(f'loaf_{side}')
        yield from b.play(f'yawn_lie_{side}')

    def act_climb(self):
        """Up onto the text, along the lines and from line to line; sometimes it stays up there."""
        b, rng = self.body, self.rng
        if b.world is None:
            return
        if not b.on_shelf:
            b.doing = 'looking for a way up'
            if not (yield from b.jump_on_text()):
                return
        for _ in range(rng.randint(3, 8)):
            r = rng.random()
            if r < 0.4:
                yield from b.climb_up()
            elif r < 0.55:
                yield from b.climb_down()
            elif r < 0.85:
                yield from b.roam(0, 0)
            else:
                yield from b.behave(1, allow=lambda o: 'go' not in o)
        if rng.random() < 0.4:                     # sits up there for a while
            yield from b.go(rng.choice(['sit_F', 'loaf_L', 'loaf_R']))
            yield from b.behave(rng.randint(2, 5), allow=lambda o: o.get('go', 'sit_').startswith(REST_POSES))
        elif rng.random() < 0.7:
            yield from b.get_down()

    def act_zoomies(self):
        b, rng = self.body, self.rng
        for _ in range(rng.randint(4, 7)):
            tx = b.lo + 10 if b.x > (b.lo + b.hi) / 2 else b.hi - 10
            yield from b.walk_to(tx, rng.uniform(b.lo_y, b.lo_y + (b.hi_y - b.lo_y) * 0.5), 'run')
        side = 'L' if b.facing() < 0 else 'R'
        yield from b.go(f'loaf_{side}')
        yield from b.hold_pose(int(rng.uniform(3, 6) * 1000))

    def act_greet(self):
        b, s = self.body, self.senses
        if b.pose.startswith(SLEEP_POSES):
            side = b.pose[-1]
            yield from b.go(f'loaf_{side}')
            yield from b.play(f'yawn_lie_{side}')
        if s.cursor:
            cx, cy = s.cursor
            off = 22 * self.side_of(cx)             # stop beside the pointer, not on it
            yield from b.walk_to(cx - CELL / 2 - off, cy - 12)
        yield from b.face(0)
        yield from b.play('meow_stand')
        yield from b.go('sit_F')
        yield from b.behave(2, allow=lambda o: 'go' not in o)

    def act_visit(self):
        b, s = self.body, self.senses
        if not s.window:
            return
        left, bottom, right, top = s.window
        x = max(left, right - 30) - CELL / 2
        y = top if top <= b.hi_y else bottom + 2  # on the window's top edge, else inside its bottom
        b.doing = 'walking to your window'
        yield from b.walk_to(x, y)
        yield from b.go('sit_F')
        self.adjust({'affection': self.m['visit']['arrived']})
        yield from b.behave(self.rng.randint(4, 8), allow=lambda o: 'go' not in o)

    def act_chase(self):
        b, s, c = self.body, self.senses, self.m['chase']
        t0 = s.t
        while s.t - t0 < c['max_s'] and s.cursor and self.needs['energy'] > 0.1:
            cx, cy = s.cursor
            if math.dist((cx, cy), b.center) < 16:          # caught up: bat at it
                yield from b.face(self.side_of(cx) if abs(cx - b.center[0]) > 3 else 0)
                side = {-1: 'L', 1: 'R', 0: 'F'}[b.facing()]
                yield from b.play(f'paw_{side}')
                if s.still > 1:
                    break
                continue
            n = yield from counted(b.walk_to(cx - CELL / 2, cy, 'run', max_cycles=1))
            if not n:                                       # closer than one stride
                yield from b.hold_pose(150)
            if s.still > 2.5:                               # it stopped moving: lost interest
                break
        yield from b.stand_up()

    def act_hunt(self):
        """Sneak up on a resting pointer and pounce on it."""
        b, s, rng = self.body, self.senses, self.rng
        if not s.cursor:
            return
        cx, cy = target = s.cursor
        side = self.side_of(cx)                    # -1: prey is on the left
        d = 'L' if side < 0 else 'R'
        leap = abs(sum(self.cfg['clips'][f'pounce_{d}']['dx']))
        front = 8 if side < 0 else CELL - 8         # where the front paws are inside the cell
        land_x = cx - front
        start_x = land_x - side * leap
        b.doing = 'sneaking closer'
        yield from b.walk_to(start_x - side * 30, cy)
        if self.prey_moved(target):
            return
        yield from b.face(side)
        yield from b.go(f'stalk_{d}')
        b.doing = 'stalking'
        while (b.x - start_x) * side < -3:
            if self.prey_moved(target):
                yield from b.stand_up()
                return
            n = yield from counted(b.play(f'creep_{d}'))
            if not n:
                break
        if self.prey_moved(target):
            yield from b.stand_up()
            return
        b.doing = 'pounce!'
        yield from b.play(f'pounce_{d}')
        yield from b.hold_pose(200)
        yield from b.go(f'stand_{d}')
        yield from b.play(f'paw_{d}', rng.randint(1, 2))
        self.adjust({'boredom': -0.4})

    def prey_moved(self, target):
        return self.senses.cursor is None or math.dist(self.senses.cursor, target) > 12


def counted(gen):
    """yield from gen, returning how many frames it yielded."""
    n = 0
    for item in gen:
        n += 1
        yield item
    return n
