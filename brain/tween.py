"""In-between frames for every change of pose (`psspss tween`).

The pack has no transition clips: going from one key pose to the next is a cut. For every link
of the pose graph this makes candidate in-betweens out of the two poses themselves, the way an
animator would: the head (top rows) of the next pose on the body of the last one, the rear first,
the front half or the back half first, or the pose sinking 1-4 px. Nothing is blended: each pixel
comes whole from one of the two frames.

Then it picks the chain of up to three candidates whose biggest step (pixels that change between
two frames in a row) is the smallest, with as few frames as that allows. The chosen frames are
kept as recipes (with a note of what they are made of) in brain/transitions.json; Body.go plays
them. Needs numpy (only here, not to run the cat).
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw

from .config import HERE, flip_name
from .sprites import CELL, ROOT, Sheet

OUT = os.path.join(HERE, 'transitions.json')
MAX_BETWEEN = 3           # in-between frames per link at most
SLACK = 15                # a chain with fewer frames wins if its biggest step is at most this much worse
WORTH = 0.85              # keep a chain only if its biggest step is under 85% of the plain cut
SPLITS = range(4, 29, 2)
EXTRA = 3                 # cost of every opaque pixel more (or less) than both poses have
BARE = 4                  # cost of every edge pixel that is not outline, more than both poses have


def candidates(a, b):
    """Recipes for in-betweens made of frames a and b."""
    out = []
    for base, other in ((a, b), (b, a)):
        for k in range(1, 5):
            out.append({'from': [base], 'ops': [['squash', ['bottom', -(k + 1)], k]],
                        'note': f'{base}, legs {k} px shorter'})
        for k in SPLITS:
            for box, what in (((0, 0, CELL, k), f'rows 0-{k}'), ((0, k, CELL, CELL), f'rows {k}-{CELL}'),
                              ((0, 0, k, CELL), f'columns 0-{k}'), ((k, 0, CELL, CELL), f'columns {k}-{CELL}')):
                out.append({'from': [base], 'ops': [['graft', other, *box], ['tidy', a, b]],
                            'note': f'{base} with {what} of {other}, loose bits dropped'})
    return out


def bare_edges(X):
    """Per frame: edge pixels (next to transparency) that are not the outline (darkest) color."""
    img = X.reshape(len(X), CELL, CELL)
    opaque = img != 0
    pad = np.pad(opaque, ((0, 0), (1, 1), (1, 1)))
    edge = opaque & ~(pad[:, :-2, 1:-1] & pad[:, 2:, 1:-1] & pad[:, 1:-1, :-2] & pad[:, 1:-1, 2:])
    rgb = img >> 8
    lum = ((rgb >> 16) & 255) * 3 + ((rgb >> 8) & 255) * 6 + (rgb & 255)
    dark = np.where(opaque, lum, 1 << 30).reshape(len(X), -1).min(axis=1)[:, None, None]
    return (edge & (lum > dark)).reshape(len(X), -1).sum(axis=1)


def walk_frames(cfg, pose):
    """Hand-drawn walk frames of a standing pose's direction (a cat turns with a step)."""
    clip = cfg['clips'].get('walk_' + pose.split('_', 1)[1]) if pose.startswith('stand_') else None
    return list(dict.fromkeys(clip['frames'])) if clip else []


def pixels(sheet, refs):
    """(N, 1024) array of RGBA packed into one int; fully transparent pixels are 0."""
    out = np.zeros((len(refs), CELL * CELL), dtype=np.uint32)
    for i, ref in enumerate(refs):
        a = np.asarray(sheet.frame(ref), dtype=np.uint32).reshape(-1, 4)
        out[i] = np.where(a[:, 3] > 0, (a[:, 0] << 24) | (a[:, 1] << 16) | (a[:, 2] << 8) | a[:, 3], 0)
    return out


def steps(X):
    """N x N: how many pixels change between every two frames."""
    return np.stack([(X != X[i]).sum(axis=1) for i in range(len(X))]).astype(np.int32)


def chain(D, a, b):
    """Best in-betweens from frame a to frame b: ([frame indexes], biggest step)."""
    big = np.iinfo(np.int64).max // 2
    D = D.astype(np.int64)
    cost = D[a].copy()                       # biggest step so far, ending on each frame (1 in-between)
    cost[[a, b]] = big
    parents, options = [], [(int(D[a, b]), [])]
    for h in range(1, MAX_BETWEEN + 1):
        if h > 1:                            # one more in-between: best way into v from any u
            via = np.maximum(cost[:, None], D)
            parent = via.argmin(axis=0)
            cost = via[parent, np.arange(len(D))]
            cost[[a, b]] = big
            parents.append(parent)
        end = np.maximum(cost, D[:, b])
        v = int(end.argmin())
        path = [v]
        for parent in reversed(parents):
            v = int(parent[v])
            path.append(v)
        options.append((int(end.min()), path[::-1]))
    top = min(c for c, _ in options)
    c, path = min(((c, p) for c, p in options if c <= top + SLACK), key=lambda cp: len(cp[1]))
    return path, c


def build(cfg):
    """({link: [refs]}, {recipe name: recipe}, report rows (a, b, plain cut, biggest step, refs))."""
    poses, sheet = cfg['poses'], Sheet(cfg['sheet'], cfg['generated'])
    cuts = {tuple(link.split('>')) for link in cfg['tween']['cut']}
    cuts |= {(b, a) for a, b in cuts}
    out, recipes, report = {}, {}, []
    for a, b, _ in cfg['links']:
        A, B = poses[a], poses[b]
        if (flip_name(a), flip_name(b)) in cuts or (a, b) in cuts:
            sheet.generated, sheet.cache = cfg['generated'], {}
            report.append((a, b, int(steps(pixels(sheet, [A, B]))[0, 1]), None, []))
            continue
        cands = candidates(A, B)
        sheet.generated = dict(cfg['generated'], **{f'_c{i}': r for i, r in enumerate(cands)})
        sheet.cache = {}
        drawn = walk_frames(cfg, a) + walk_frames(cfg, b)
        refs, seen = [A, B], set()
        X = pixels(sheet, [A, B])
        seen = {X[0].tobytes(), X[1].tobytes()}
        for ref in drawn + [f'@_c{i}:0' for i in range(len(cands))]:   # drop repeats
            x = pixels(sheet, [ref])[0]
            if x.tobytes() not in seen:
                seen.add(x.tobytes())
                refs.append(ref)
                X = np.vstack([X, x])
        D = steps(X)
        area = (X != 0).sum(axis=1)
        extra = np.maximum(0, area - area[:2].max()) + np.maximum(0, area[:2].min() - area)
        bare = bare_edges(X)
        bare = np.maximum(0, bare - bare[:2].max())
        penalty = EXTRA * extra + BARE * bare                  # a second tail, a cut-off body: like a bigger step
        path, top = chain(D + penalty[None, :], 0, 1)
        direct = int(D[0, 1])
        top = int(max([D[0, path[0]]] + [D[p, q] for p, q in zip(path, path[1:])] + [D[path[-1], 1]])) \
            if path else direct
        frames = []
        if path and top < direct * WORTH:
            for i in path:
                if refs[i].startswith('@_c'):
                    name = f'tw{len(recipes)}'
                    recipes[name] = cands[int(refs[i][3:-2])]
                    frames.append(f'@{name}:0')
                else:
                    frames.append(refs[i])
            out[f'{a}>{b}'], out[f'{b}>{a}'] = frames, frames[::-1]
        else:
            top = direct
        report.append((a, b, direct, top, frames))
    sheet.generated = cfg['generated']
    return out, recipes, report


def write(cfg, path=OUT):
    out, recipes, report = build(cfg)
    for r in recipes.values():
        r['tween'] = True                     # pictured in transitions.png, not in before_after.png
    with open(path, 'w') as f:
        json.dump({'note': 'made by `psspss tween` (brain/tween.py): in-between frames for every pose link',
                   'transitions': out, 'generated': recipes}, f, indent=1)
    return report


def preview(cfg, report, out_dir=os.path.join(ROOT, 'assets', 'generated'), zoom=4):
    """Before/after: for every link, the plain cut, then the cut with its in-betweens (one row each);
    and an animated GIF of all of them."""
    sheet = Sheet(cfg['sheet'], cfg['generated'])
    poses, cell = cfg['poses'], CELL * zoom
    rows = [(a, b, direct, direct if top is None else top, [poses[a]] + frames + [poses[b]])
            for a, b, direct, top, frames in report if not a.endswith('R') and not b.endswith('R')]
    width = 200 + cell * (MAX_BETWEEN + 2) + 40 + cell * 2
    img = Image.new('RGBA', (width, cell * len(rows)), (236, 228, 205, 255))
    draw = ImageDraw.Draw(img)
    big = lambda ref: sheet.frame(ref).resize((cell, cell), Image.NEAREST)
    for y, (a, b, direct, top, seq) in enumerate(rows):
        draw.text((8, y * cell + cell // 2 - 14), f'{a} > {b}', fill=(40, 40, 40, 255))
        draw.text((8, y * cell + cell // 2 + 2), f'jump {direct} -> {top}', fill=(120, 60, 60, 255))
        img.alpha_composite(big(seq[0]), (200, y * cell))       # before: the cut
        img.alpha_composite(big(seq[-1]), (200 + cell, y * cell))
        for i, ref in enumerate(seq):                            # after
            img.alpha_composite(big(ref), (200 + cell * 2 + 40 + i * cell, y * cell))
    draw.line([(200 + cell * 2 + 20, 0), (200 + cell * 2 + 20, img.size[1])], fill=(200, 80, 80, 255), width=2)
    sheet_path = os.path.join(out_dir, 'transitions.png')
    img.save(sheet_path)

    # animated: every link in a grid, there and back, each at its own pace
    cols, small = 5, CELL * 3
    grid_rows = -(-len(rows) // cols)
    loops = []
    for a, b, _, _, seq in rows:
        tl = [(seq[0], 700)] + [(r, 90) for r in seq[1:-1]] + [(seq[-1], 700)] \
            + [(r, 90) for r in seq[-2:0:-1]]
        loops.append(tl)
    tick, frames = 30, []
    for t in range(0, 3600, tick):
        f = Image.new('RGBA', (cols * small, grid_rows * (small + 14)), (236, 228, 205, 255))
        d = ImageDraw.Draw(f)
        for k, tl in enumerate(loops):
            total, at = sum(ms for _, ms in tl), t % sum(ms for _, ms in tl)
            for ref, ms in tl:
                if at < ms:
                    break
                at -= ms
            x, y = (k % cols) * small, (k // cols) * (small + 14)
            f.alpha_composite(sheet.frame(ref).resize((small, small), Image.NEAREST), (x, y))
            d.text((x + 4, y + small), f'{rows[k][0]} > {rows[k][1]}'[:16], fill=(60, 60, 60, 255))
        frames.append(f.convert('RGB').quantize(colors=64))
    gif_path = os.path.join(out_dir, 'transitions.gif')
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=tick, loop=0)
    return sheet_path, gif_path
