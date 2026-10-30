"""Sprite sheet access and frame generation.

A sheet path may stack layers with '+': 'base/cat-1.png+winter/santa-hat-1.png' draws the
accessory sheet over the cat (the valentine and winter sheets hold only accessories).

Frame refs:  'row:col' on the sheet, '@name:i' = frame i of generated recipe `name`
(see "generated" in anim.json), trailing '~' = mirrored.

Generated frames are made only by moving and repainting existing pixels with colors
sampled from the same sheet: no blending, alpha stays 0/255, palette stays the sheet's.
They are rebuilt on the fly for whatever skin is loaded; `pet.py gen` writes the
base-skin results to assets/generated/ with their provenance.
"""
import json
import os
import re

from PIL import Image, ImageDraw, ImageOps

CELL = 32
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = re.compile(r'(?:(\d+):(\d+)|@(\w+)(?::(\d+))?)(~?)')


def frame_diff(a, b):
    """Pixels that differ where at least one of the two frames is opaque."""
    return sum(1 for p, q in zip(a.get_flattened_data(), b.get_flattened_data())
               if (p[3] or q[3]) and p != q)


def find(img, color):
    """(x, y) of the first pixel of `color`, scanning rows top to bottom; None if absent."""
    for y in range(CELL):
        for x in range(CELL):
            if img.getpixel((x, y)) == color:
                return x, y
    return None


def islands(img):
    """Groups of opaque pixels touching each other (8 ways), biggest first."""
    left = {(x, y) for y in range(CELL) for x in range(CELL) if img.getpixel((x, y))[3]}
    out = []
    while left:
        todo = [left.pop()]
        group = set(todo)
        while todo:
            x, y = todo.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    p = (x + dx, y + dy)
                    if p in left:
                        left.remove(p)
                        group.add(p)
                        todo.append(p)
        out.append(group)
    return sorted(out, key=len, reverse=True)


def resolve(img, v):
    """A coordinate: a number, ['top', d] (first opaque row + d) or ['bottom', d] (last opaque row + 1 + d)."""
    if isinstance(v, list):
        box = img.getchannel('A').getbbox()
        return (box[1] if v[0] == 'top' else box[3]) + v[1]
    return v


def apply_op(img, op, sample):
    """One pixel edit. sample(ref, x, y) reads a color from the current sheet (for paint / find)."""
    kind, args = op[0], op[1:]
    out = img.copy()
    if kind == 'squash':                      # delete rows [row, row+k), everything above drops by k
        row, k = resolve(img, args[0]), args[1]
        out = Image.new('RGBA', img.size)
        out.paste(img.crop((0, row + k, CELL, CELL)), (0, row + k))
        out.paste(img.crop((0, 0, CELL, row)), (0, k))
    elif kind == 'shift':                     # move the whole frame by (dx, dy)
        dx, dy = args
        out = Image.new('RGBA', img.size)
        out.paste(img, (dx, dy))
    elif kind == 'move':                      # cut the box [x0, x1) x [y0, y1) and put it down at (+dx, +dy)
        x0, y0, x1, y1 = (resolve(img, v) for v in args[:4])
        dx, dy = args[4:]
        part = img.crop((x0, y0, x1, y1))
        ImageDraw.Draw(out).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(0, 0, 0, 0))
        out.alpha_composite(part, (x0 + dx, y0 + dy))   # alpha is 0/255, so this is a plain overwrite
    elif kind == 'erase':                     # clear the box [x0, x1) x [y0, y1)
        x0, y0, x1, y1 = (resolve(img, v) for v in args)
        ImageDraw.Draw(out).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(0, 0, 0, 0))
    elif kind == 'graft':                     # copy the box [x0, x1) x [y0, y1) of frame `ref` as it is
        ref, x0, y0, x1, y1 = args
        for y in range(y0, y1):
            for x in range(x0, x1):
                out.putpixel((x, y), sample(ref, x, y))
    elif kind == 'tidy':                      # drop loose bits, unless they were loose in a source too (whiskers)
        kept = []
        for ref in args:
            src = [[sample(ref, x, y) for x in range(CELL)] for y in range(CELL)]
            kept.append(src)
        for group in islands(img)[1:]:
            ok = False
            for src in kept:
                ring = {(x + dx, y + dy) for x, y in group for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - group
                if all(src[y][x] == img.getpixel((x, y)) for x, y in group) and \
                        all(not (0 <= x < CELL and 0 <= y < CELL) or not src[y][x][3] for x, y in ring):
                    ok = True
            if not ok:
                for p in group:
                    out.putpixel(p, (0, 0, 0, 0))
    elif kind == 'paint':                     # draw rows of chars; char -> color of pixel [ref, x, y]
        x, y, rows, keys = args
        if isinstance(x, dict) and 'at' in x:  # {'at': [x, y], 'same': [[ref, x, y], ...]}: only if those match
            if len({sample(*where) for where in x.get('same', [])}) > 1:
                return out                    # e.g. glasses over the eyes on this skin: leave it be
            x, y = x['at']
        elif isinstance(x, dict):             # {'find': [ref, x, y], 'dx', 'dy'}: next to a pixel of that color
            spot = find(img, sample(*x['find']))
            if spot is None:                  # e.g. a hat covers the ear on this skin: leave it be
                return out
            x, y = spot[0] + x.get('dx', 0), spot[1] + x.get('dy', 0)
        else:
            y = resolve(img, y)
        colors = {ch: sample(*where) for ch, where in keys.items()}
        for j, line in enumerate(rows):
            for i, ch in enumerate(line):
                if ch == '-':
                    out.putpixel((x + i, y + j), (0, 0, 0, 0))
                elif ch != '.':
                    out.putpixel((x + i, y + j), colors[ch])
    else:
        raise ValueError(f'unknown op {kind}')
    return out


class Sheet:
    def __init__(self, path, generated=None):
        self.path = path
        layers = [Image.open(os.path.join(ROOT, p)).convert('RGBA') for p in path.split('+')]
        self.img = layers[0]
        for layer in layers[1:]:                  # alpha is 0/255, so this is a plain overwrite
            self.img = Image.alpha_composite(self.img, layer)
        self.generated = generated or {}
        self.cache = {}

    def source_of(self, ref):
        """(source ref, recipe) of a generated ref."""
        m = REF.fullmatch(ref)
        name, idx = m.group(3), int(m.group(4) or 0)
        recipe = self.generated[name]
        return recipe['from'][idx], recipe

    def frame(self, ref):
        if ref not in self.cache:
            m = REF.fullmatch(ref)
            if not m:
                raise ValueError(f'bad frame ref {ref!r}')
            if m.group(3):
                src_ref, recipe = self.source_of(ref.rstrip('~'))
                f = self.frame(src_ref)
                for op in recipe['ops']:
                    f = apply_op(f, op, lambda r, x, y: self.frame(r).getpixel((x, y)))
            else:
                r, c = int(m.group(1)), int(m.group(2))
                f = self.img.crop((c * CELL, r * CELL, (c + 1) * CELL, (r + 1) * CELL))
            self.cache[ref] = ImageOps.mirror(f) if m.group(5) else f
        return self.cache[ref]

    def palette(self):
        return {p for p in self.img.get_flattened_data() if p[3]}


def skins():
    """(cats, accessories): sheet paths relative to ROOT. Base sheets are whole cats, the rest are layers."""
    found = sorted(os.path.relpath(os.path.join(d, f), ROOT)
                   for d, _, fs in os.walk(os.path.join(ROOT, 'assets', 'sprites')) for f in fs if f.endswith('.png'))
    cats = [p for p in found if os.sep + 'base' + os.sep in p]
    return cats, [p for p in found if p not in cats]


def skin_name(path):
    return ' + '.join(os.path.splitext(os.path.basename(p))[0] for p in path.split('+'))


def write_generated(cfg, out_dir=os.path.join(ROOT, 'assets', 'generated'), zoom=8):
    """Render every generated frame for the base skin + provenance + a before/after sheet."""
    sheet = Sheet(cfg['sheet'], cfg['generated'])
    pal = sheet.palette()
    os.makedirs(out_dir, exist_ok=True)
    index, pairs = {}, []
    for name, recipe in cfg['generated'].items():
        for i, src_ref in enumerate(recipe['from']):
            ref = f'@{name}:{i}'
            f = sheet.frame(ref)
            if recipe.get('tween'):           # in-betweens: their before/after is transitions.png
                f.save(os.path.join(out_dir, f'{name}.png'))
                index[f'{name}.png'] = {'ref': ref, 'from': src_ref, 'sheet': cfg['sheet'], 'ops': recipe['ops'],
                                        'note': recipe.get('note', '')}
                continue
            colors = {p for p in f.get_flattened_data() if p[3]}
            alphas = {p[3] for p in f.get_flattened_data()}
            if not colors <= pal or not alphas <= {0, 255} or (0, 0, 0, 0) in colors:
                raise ValueError(f'{ref}: color outside the sheet palette or partial alpha')
            fn = f'{name}_{i}.png'
            f.save(os.path.join(out_dir, fn))
            index[fn] = {'ref': ref, 'from': src_ref, 'sheet': cfg['sheet'], 'ops': recipe['ops'],
                         'note': recipe.get('note', '')}
            pairs.append((src_ref, ref, sheet.frame(src_ref), f))
    with open(os.path.join(out_dir, 'index.json'), 'w') as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)

    # before/after: one row per generated frame, source left, result right, on a light floor
    cell = CELL * zoom
    out = Image.new('RGBA', (cell * 2 + 8, cell * len(pairs)), (236, 228, 205, 255))
    for row, (_, _, before, after) in enumerate(pairs):
        for col, im in enumerate((before, after)):
            out.alpha_composite(im.resize((cell, cell), Image.NEAREST), (col * (cell + 8), row * cell))
    ImageDraw.Draw(out).line([(cell + 3, 0), (cell + 3, out.size[1])], fill=(200, 80, 80, 255), width=2)
    path = os.path.join(out_dir, 'before_after.png')
    out.save(path)
    return index, path
