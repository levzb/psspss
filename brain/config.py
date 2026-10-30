"""Load anim.json: expand frame ranges and per-frame values, add the mirrored _R twins."""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, 'anim.json')
TRANSITIONS = os.path.join(HERE, 'transitions.json')     # made by `pet.py tween`
RANGE = re.compile(r'(\d+:|@\w+:)(\d+)-(\d+)(~?)')


def flip_name(name):
    m = re.fullmatch(r'(.*_[a-z]?)L', name)
    return m.group(1) + 'R' if m else name


def flip_ref(ref):
    return ref[:-1] if ref.endswith('~') else ref + '~'


def flip_steps(steps):
    return [{k: flip_name(v) if k in ('play', 'go', 'pose') else v for k, v in s.items()} for s in steps]


def expand_ref(ref):
    """'7:0-3' -> ['7:0', ..., '7:3']; '@creep_L:0-5~' likewise; single refs pass through."""
    m = RANGE.fullmatch(ref)
    if not m:
        return [ref]
    head, a, b, mir = m.groups()
    return [f'{head}{c}{mir}' for c in range(int(a), int(b) + 1)]


def per_frame(clip, key, n, default=0):
    v = clip.get(key, default)
    v = v if isinstance(v, list) else [v] * n
    if len(v) != n:
        raise ValueError(f'{key}: {len(v)} values for {n} frames')
    return v


def load_config(path=CONFIG, transitions=TRANSITIONS):
    with open(path) as f:
        cfg = json.load(f)
    cfg['transitions'] = {}
    if transitions and os.path.exists(transitions):
        with open(transitions) as f:
            tw = json.load(f)
        cfg['transitions'] = tw['transitions']
        cfg['generated'].update(tw['generated'])
    for recipe in cfg.get('generated', {}).values():
        recipe['from'] = [r for ref in recipe['from'] for r in expand_ref(ref)]
    for name, clip in cfg['clips'].items():
        frames = [r for ref in clip['frames'] for r in expand_ref(ref)]
        try:
            seqs = [per_frame(clip, k, len(frames)) for k in ('ms', 'dx', 'dy')]
        except ValueError as e:
            raise ValueError(f'clip {name}: {e}') from None
        if clip.get('pingpong'):
            frames, seqs = frames + frames[-2::-1], [s + s[-2::-1] for s in seqs]
        clip['frames'] = frames
        clip['ms'], clip['dx'], clip['dy'] = seqs
    expand_mirrors(cfg)
    return cfg


def expand_mirrors(cfg):
    poses, clips = cfg['poses'], cfg['clips']
    for name, ref in list(poses.items()):
        poses.setdefault(flip_name(name), flip_ref(ref))
    for name, clip in list(clips.items()):
        if flip_name(name) not in clips:
            clips[flip_name(name)] = dict(clip, frames=[flip_ref(f) for f in clip['frames']],
                                          dx=[-d for d in clip['dx']])
    seen = {(a, b) for a, b, _ in cfg['links']}
    for a, b, ms in list(cfg['links']):
        fa, fb = flip_name(a), flip_name(b)
        if (fa, fb) not in seen:
            cfg['links'].append([fa, fb, ms])
            seen.add((fa, fb))
    blinks = cfg.get('blink', {}).get('frames', {})
    for name, ref in list(blinks.items()):
        blinks.setdefault(flip_name(name), flip_ref(ref))
    for name, opts in list(cfg['behaviour'].items()):
        cfg['behaviour'].setdefault(flip_name(name), flip_steps(opts))
    for name, seqs in list(cfg['on_click'].items()):
        cfg['on_click'].setdefault(flip_name(name), [flip_steps(s) for s in seqs])
