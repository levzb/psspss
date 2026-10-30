"""Validate anim.json and report how well poses join up (pixel diffs at every junction)."""
import re

from .body import DIRS, Body
from .sprites import Sheet, frame_diff

JUMP = 100         # junction diff (px of 1024) above which a cut is visibly jerky


def problems(cfg):
    """Everything wrong with the config, as a list of messages (empty = fine)."""
    out = []
    poses, clips = cfg['poses'], cfg['clips']
    sheet = Sheet(cfg['sheet'], cfg.get('generated'))
    refs = list(poses.values()) + [r for c in clips.values() for r in c['frames']] + [cfg['held']]
    for ref in refs:
        try:
            if not sheet.frame(ref).getchannel('A').getbbox():
                out.append(f'frame {ref} is empty')
        except (KeyError, ValueError, IndexError) as e:
            out.append(f'frame {ref}: {e!r}')
    for a, b, _ in cfg['links']:
        out += [f'link uses unknown pose {p}' for p in (a, b) if p not in poses]
    body = Body(cfg, None)

    def steps_ok(pose, steps):
        for s in steps:
            if 'play' in s and s['play'] not in clips:
                out.append(f'{pose}: unknown clip {s["play"]}')
            if 'pose' in s:
                if s['pose'] not in poses:
                    out.append(f'{pose}: unknown pose {s["pose"]}')
                pose = s['pose']
            if 'go' in s:
                try:
                    body.path(pose, s['go'])
                    pose = s['go']
                except ValueError:
                    out.append(f'{pose}: cannot reach {s["go"]}')

    for pose, opts in cfg['behaviour'].items():
        if pose not in poses:
            out.append(f'behaviour for unknown pose {pose}')
        steps_ok(pose, opts)
    for pose, seqs in cfg['on_click'].items():
        for seq in seqs:
            steps_ok(pose if pose in poses else 'stand_F', seq)
    steps_ok('stand_F', cfg['on_drop'])
    steps_ok('stand_F', cfg['scroll']['edge'])
    out += [f'pose {p} has no behaviour' for p in poses if p not in cfg['behaviour']]
    # what the mind relies on
    for d in DIRS.values():
        out += [f'missing {n}' for n in (f'walk_{d}', f'run_{d}', f'paw_{d}') if n not in clips]
        out += [f'missing pose stand_{d}' for _ in [0] if f'stand_{d}' not in poses]
    for s in 'LR':
        out += [f'missing {n}' for n in (f'creep_{s}', f'pounce_{s}', f'jump_{s}', f'yawn_lie_{s}', f'breathe_{s}')
                if n not in clips]
        out += [f'missing pose {n}' for n in (f'stalk_{s}', f'loaf_{s}', f'sleep_{s}') if n not in poses]
    first = next(iter(poses))
    out += [f'pose {p} cannot be reached from {first}' for p in poses if not reachable(body, first, p)]
    return out


def reachable(body, a, b):
    try:
        body.path(a, b)
        return True
    except ValueError:
        return False


def junctions(cfg):
    """[(diff, label)] for every link and every clip's way in and out of its pose."""
    sheet = Sheet(cfg['sheet'], cfg.get('generated'))
    poses, clips = cfg['poses'], cfg['clips']

    def d(a, b):
        return frame_diff(sheet.frame(a), sheet.frame(b))

    def clip_junction(pose, name):
        c = clips[name]
        entry = c['frames'][-1] if c.get('cycle') else c['frames'][0]
        return max(d(poses[pose], entry), d(c['frames'][-1], poses[pose]))

    rows = []
    right = re.compile(r'_[a-z]?R$')
    for a, b, _ in cfg['links']:
        if not (right.search(a) or right.search(b)):
            rows.append((d(poses[a], poses[b]), f'link  {a} <-> {b}'))
    for pose, opts in cfg['behaviour'].items():
        if not right.search(pose):
            for o in opts:
                if 'play' in o:
                    rows.append((clip_junction(pose, o['play']), f'clip  {pose} -> {o["play"]}'))
    for dname in ('L', 'dL', 'uL', 'F', 'B'):
        for kind in ('walk', 'run'):
            rows.append((clip_junction(f'stand_{dname}', f'{kind}_{dname}'), f'clip  stand_{dname} -> {kind}_{dname}'))
    rows.append((clip_junction('stalk_L', 'creep_L'), 'clip  stalk_L -> creep_L'))
    rows.append((clip_junction('stalk_L', 'pounce_L'), 'clip  stalk_L -> pounce_L'))
    return sorted(set(rows), reverse=True)


def check(cfg):
    errs = problems(cfg)
    for e in errs:
        print('ERROR', e)
    if errs:
        return False
    print(f'pose junctions (px differing out of 1024; >{JUMP} = visible jump)')
    for n, label in junctions(cfg):
        print(f'  {n:4d} {"JUMP " if n > JUMP else "     "}{label}')
    return True
