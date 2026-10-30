"""Tests: `psspss test`."""
import math
import random
import unittest

from .body import CELL, Body
from .check import junctions, problems
from .config import flip_name, load_config
from .memory import Memory
from .sim import SCREEN, TERMINAL, DayUser, Sim, StillUser
from .sprites import Sheet, frame_diff, skins
from .world import World


class Base(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()


class Config(Base):
    def test_anim_json_has_no_problems(self):
        self.assertEqual(problems(self.cfg), [])

    def test_every_pose_reaches_every_pose(self):
        body = Body(self.cfg, random.Random(0))
        for a in self.cfg['poses']:
            for b in self.cfg['poses']:
                body.path(a, b)                     # raises if unreachable

    def test_clips_join_their_poses(self):
        # links between key poses may jump (no in-between frames in the pack); clips may not
        bad = [(n, label) for n, label in junctions(self.cfg) if label.startswith('clip') and n > 70]
        self.assertEqual(bad, [])


class Generated(Base):
    def test_generated_frames_stay_in_palette_on_every_skin(self):
        cats, accessories = skins()
        self.assertTrue(cats and accessories)
        for path in [c + (f'+{a}' if a else '') for c in cats for a in [None] + accessories]:
            sheet = Sheet(path, self.cfg['generated'])
            pal = sheet.palette()
            for name, recipe in self.cfg['generated'].items():
                if recipe.get('tween') and '+' in path:    # in-betweens: the cats are enough (and quicker)
                    continue
                for i in range(len(recipe['from'])):
                    for ref in (f'@{name}:{i}', f'@{name}:{i}~'):
                        px = list(sheet.frame(ref).get_flattened_data())
                        with self.subTest(skin=path, ref=ref):
                            self.assertTrue({p[3] for p in px} <= {0, 255}, 'partial alpha')
                            self.assertTrue({p for p in px if p[3]} <= pal, 'color not in the sheet')
                            self.assertTrue(any(p[3] for p in px), 'empty frame')

    def test_every_pose_change_is_smooth_or_a_cut_on_purpose(self):
        cuts = {tuple(c.split('>')) for c in self.cfg['tween']['cut']}
        for n, label in junctions(self.cfg):
            if label.startswith('link') and 'on purpose' not in label:
                self.assertLessEqual(n, 100, label)
        for a, b, _ in self.cfg['links']:
            with self.subTest(link=f'{a}>{b}'):
                frames = self.cfg['transitions'].get(f'{a}>{b}')
                if frames is None and not ({(a, b), (b, a), (flip_name(a), flip_name(b)), (flip_name(b), flip_name(a))} & cuts):
                    sheet = Sheet(self.cfg['sheet'], self.cfg['generated'])
                    self.assertLess(frame_diff(sheet.frame(self.cfg['poses'][a]), sheet.frame(self.cfg['poses'][b])), 30)
                elif frames is not None:
                    self.assertEqual(frames[::-1], self.cfg['transitions'][f'{b}>{a}'])

    def test_stalk_is_lower_than_standing(self):
        sheet = Sheet(self.cfg['sheet'], self.cfg['generated'])
        top = lambda ref: sheet.frame(ref).getchannel('A').getbbox()[1]
        self.assertGreater(top(self.cfg['poses']['stalk_L']), top(self.cfg['poses']['stand_L']) + 2)


def start(sim, activity, **needs):
    sim.mind.needs.update(needs)
    sim.frames = sim.mind.switch(activity)


class Behaviour(Base):
    def test_hunt_ends_with_a_pounce_on_the_pointer(self):
        for seed, cursor in [(1, (300.0, 120.0)), (2, (60.0, 40.0)), (3, (420.0, 200.0))]:
            with self.subTest(seed=seed, cursor=cursor):
                sim = Sim(self.cfg, StillUser(cursor), seed=seed)
                sim.run(3)
                start(sim, 'hunt', energy=0.9, boredom=0.9)
                done = sim.run(120, until=lambda s: s.mind.activity != 'hunt')
                self.assertTrue(done, 'hunt never finished')
                refs = [r for *_, r in sim.trail]
                self.assertTrue(any(r.startswith('@creep') for r in refs), 'did not creep')
                self.assertTrue(any(r.startswith('@stalkhi') for r in refs), 'did not wiggle before the pounce')
                paws = sim.body.x + (8 if sim.body.facing() < 0 else CELL - 8)
                self.assertLess(abs(paws - cursor[0]), 14, 'landed too far from the pointer')
                self.assertLess(abs(sim.body.y - cursor[1]), 8)

    def test_hunt_is_abandoned_when_the_prey_moves(self):
        user = StillUser((300.0, 120.0))
        sim = Sim(self.cfg, user, seed=4)
        sim.run(3)
        start(sim, 'hunt', energy=0.9, boredom=0.9)
        sim.run(2)
        user.cursor = (100.0, 250.0)
        sim.run(30, until=lambda s: s.mind.activity != 'hunt')
        self.assertFalse(any(r.startswith('@stalkhi') for *_, r in sim.trail), 'pounced at an empty spot')

    def test_falls_asleep_when_you_leave_and_greets_you_back(self):
        user = StillUser((250.0, 150.0), idle=0)
        sim = Sim(self.cfg, user, seed=5)
        sim.mind.needs['energy'] = 0.9
        sim.run(200)                                   # idle passes away_after (120 s)
        self.assertEqual(sim.mind.activity, 'sleep')
        self.assertTrue(sim.body.pose.startswith(('sleep_', 'back_', 'curl_', 'stretch_')))
        user.idle0, user.cursor = -sim.t, (100.0, 60.0)  # you are back: idle restarts from 0
        sim.run(60, until=lambda s: s.mind.activity == 'greet')
        self.assertEqual(sim.mind.activity, 'greet')
        sim.run(60, until=lambda s: s.mind.activity != 'greet')
        self.assertLess(math.dist(sim.body.center, (100.0, 60.0)), 40, 'did not come to the pointer')

    def test_chases_a_pointer_darting_past(self):
        class Darting(StillUser):
            def at(self, t):
                return 0.0, (150 + 60 * math.cos(t * 3), 120 + 40 * math.sin(t * 3))
        sim = Sim(self.cfg, Darting(), seed=6)
        sim.run(2)
        sim.body.x, sim.body.y = 120.0, 110.0
        sim.mind.needs.update(energy=0.9, boredom=0.9)
        sim.frames = sim.mind.switch('rest')
        self.assertTrue(sim.run(10, until=lambda s: s.mind.activity == 'chase'))

    def test_sleeps_at_a_favourite_spot(self):
        mem = Memory(path=None)
        for _ in range(5):
            mem.slept_at(200.0, 100.0)
        sim = Sim(self.cfg, StillUser((10.0, 10.0)), seed=7, memory=mem)
        sim.mind.m = dict(sim.mind.m, favourite_spot=1.0)
        sim.run(2)
        sim.body.x, sim.body.y = 260.0, 160.0
        start(sim, 'sleep', energy=0.2)
        sim.run(60, until=lambda s: s.body.pose.startswith('sleep_'))
        self.assertLess(math.dist((sim.body.x, sim.body.y), (200.0, 100.0)), 25)

    def test_visits_your_window(self):
        sim = Sim(self.cfg, StillUser((10.0, 10.0)), seed=8)
        sim.run(2)
        start(sim, 'visit', affection=0.9)
        sim.run(90, until=lambda s: s.body.pose == 'sit_F')
        left, bottom, right, top = sim.user.window
        self.assertEqual(sim.body.pose, 'sit_F')
        self.assertLess(abs(sim.body.y - top), 6, 'should sit on the top edge of the window')
        self.assertLess(sim.mind.needs['affection'], 0.9)

    def test_sleepier_at_night(self):
        def asleep(hour):
            sim = Sim(self.cfg, DayUser(random.Random(9)), seed=9, hour=hour)
            sim.run(3 * 3600)
            return sim.time_in['sleep'] / sum(sim.time_in.values())
        self.assertGreater(asleep(0.0), asleep(11.0))

    def test_a_working_day(self):
        sim = Sim(self.cfg, DayUser(random.Random(10)), seed=10, hour=9)
        sim.run(8 * 3600)
        lo, hi, lo_y, hi_y = SCREEN
        for t, x, y, _ in sim.trail[200:]:
            self.assertTrue(lo - 0.01 <= x <= hi + 0.01 and lo_y - 0.01 <= y <= hi_y + 0.01, (t, x, y))
        done = {a for _, a in sim.log}
        self.assertTrue({'sleep', 'rest', 'wander', 'hunt', 'chase', 'greet', 'visit'} <= done, done)
        share = sim.time_in['sleep'] / sum(sim.time_in.values())
        self.assertTrue(0.2 < share < 0.6, share)


class InTerminal(Base):
    def test_only_the_part_inside_its_window_and_not_covered_shows(self):
        from .app import hidden_rects
        cat = (100, 100, 96, 96)
        term = (7, 1, (0, 0, 500, 500))
        self.assertEqual(hidden_rects(cat, [term], 7), [])                       # all of it inside, in front
        browser = (9, 2, (150, 0, 900, 900))
        self.assertEqual(hidden_rects(cat, [browser, term], 7), [(50, 0, 46, 96)])  # its right half is under it
        self.assertEqual(hidden_rects(cat, [term, browser], 7), [])              # the browser is behind
        self.assertEqual(hidden_rects((450, 100, 96, 96), [term], 7), [(50, 0, 46, 96)])   # sticks out of the window
        self.assertEqual(hidden_rects(cat, [browser], 7), [(0, 0, 96, 96)])     # its window is not on screen


    def test_floor_and_shelves(self):
        w = World((0, 0, 200, 100), [(0, 60, 100, 65), (0, 55, 150, 60)])
        self.assertFalse(w.free(50, 62))                 # in the text
        self.assertTrue(w.free(180, 58))                 # right of it
        self.assertTrue(w.free(50, 20))                  # below it
        self.assertEqual(w.shelf_at(120, 60), (0, 55, 150, 60))
        self.assertEqual(w.line_above(50, 60), 65)
        self.assertIsNone(w.line_above(120, 60))         # nothing over the end of the longer line
        self.assertTrue(w.shelf_spots())

    def test_routes_go_around_the_text(self):
        w = TERMINAL
        for a, b in [((540, 300), (20, 10)), ((300, 10), (520, 280)), ((60, 40), (500, 150))]:
            legs = w.route(a, b)
            self.assertIsNotNone(legs, (a, b))
            p = a
            for (vx, vy), n in legs:
                for k in range(int(n) + 1):
                    self.assertTrue(w.free(p[0] + vx * k, p[1] + vy * k), (a, b, p))
                p = (p[0] + vx * n, p[1] + vy * n)
            self.assertLess(math.dist(p, b), 3)

    def assert_on_solid_ground(self, sim):
        b = sim.body
        self.assertTrue(b.grounded() or b.x < 0, (b.paws, b.on_shelf, b.doing))

    def test_climbs_the_text(self):
        for seed in (11, 12, 13):
            with self.subTest(seed=seed):
                sim = Sim(self.cfg, StillUser((10.0, 10.0)), seed=seed, world=TERMINAL)
                sim.run(3)
                sim.body.x, sim.body.y = 470.0, 40.0
                start(sim, 'climb', energy=0.9, boredom=0.9)
                tops = set()

                def watch(s):
                    self.assert_on_solid_ground(s)
                    if s.body.on_shelf:
                        tops.add(s.body.y)
                    return s.mind.activity != 'climb'
                self.assertTrue(sim.run(300, until=watch), 'climb never finished')
                self.assertTrue(tops, 'never got onto the text')
                self.assertGreater(len(tops), 1, 'never went from line to line')

    def test_a_working_day_in_a_terminal(self):
        sim = Sim(self.cfg, DayUser(random.Random(14)), seed=14, hour=9, world=TERMINAL)
        sim.run(3)
        sim.body.x, sim.body.y = 470.0, 40.0
        sim.run(2 * 3600, until=lambda s: self.assert_on_solid_ground(s))
        done = {a for _, a in sim.log}
        self.assertIn('climb', done)
        self.assertNotIn('visit', done)


if __name__ == '__main__':
    unittest.main()
