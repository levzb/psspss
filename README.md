# pspsps

[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)
![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)
![Python 3.14](https://img.shields.io/badge/python-3.14-3776AB.svg)

A pixel cat that lives in your macOS Terminal window. Started and driven from the command line.

![pspsps](assets/video/pspsps-promo.gif)

## Features

- **Needs.** Energy, boredom and wish for attention change over time. The cat picks what to do from what it needs most.
- **Activities.** Walks, rests, washes, sleeps at favourite spots, has evening zoomies.
- **Cursor play.** Chases a fast pointer; stalks a still one, wiggles and pounces.
- **You.** Falls asleep when you are away, greets you when you are back.
- **Mouse.** Click it and it purrs; drag it into another Terminal window. Clicks pass through everywhere else.
- **Terminal.app.** Empty space is the floor and every line of text is a shelf. The cat walks around the text, jumps onto lines and climbs them. It rides along when you scroll or new output pushes the text up. Only the part inside its window shows: a window in front covers it.
- **Still, not frozen.** Blinks while it sits (eyes-shut frames for the side poses are generated).
- **Generated frames.** Stalk, creep, pounce and blink frames are built in code from the sheet's pixels and palette.
- **Transitions.** Sitting, lying down, crouching into a stalk and rolling over in sleep play in-between frames made from the two poses (the rear sits first, the front lies down first). Turns stay quick cuts. No blending, no new colors.

## Requirements

- macOS (tested on 15), Python 3.14
- Accessibility permission for the terminal you start it from (for the Terminal.app features)

## Install

```sh
git clone https://github.com/levzb/psspss && cd psspss
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./psspss install
```

## Use

| command | |
|---|---|
| `psspss` | let the cat in (if it is in: what it is up to) |
| `psspss stop` | let it out |
| `psspss status` | what it is doing and how it feels |
| `psspss here` | call it into the window you are typing in |
| `psspss cat [grey\|ginger\|white]` | list the cats / switch |
| `psspss hunt` · `chase` · `climb` · `zoomies` · `sleep` · `greet` | ask it to (2 s to place the pointer) |
| `psspss sound [on\|off]` | purr on click |
| `psspss log` | follow what it does |

Dev: `psspss run` (foreground), `test`, `check` (validate `brain/anim.json`), `gen` (generated frames and a
before/after sheet in `assets/generated/`), `tween` (rebuild `brain/transitions.json`), `sim 8` (simulate an
8-hour day), `film` (the promo; `vhs film.tape` records it).

Log, settings and the control socket live in `~/.psspss/`.

## Layout

```
psspss            the command
brain/
  anim.json       frames, poses, clips, generated-frame recipes, habits, needs
  config.py       loads anim.json, mirrors left-facing poses and clips
  sprites.py      sheets, layers, generated frames
  transitions.json  in-between frames for every pose link (made by tween.py)
  tween.py        builds the in-betweens
  body.py         pose graph, walking, jumping, shelves
  mind.py         needs, choosing and running activities
  world.py        a Terminal window as a world: floor, text, shelves, paths
  terminal.py     Terminal.app text and positions via the Accessibility API
  senses.py       pointer speed and stillness
  memory.py       favourite sleep spots
  app.py          macOS window, mouse, scrolling
  control.py      how psspss talks to the running cat
  sim.py          headless simulator
  film.py         the promo, drawn with half-block characters
  check.py        config validation
  tests.py        tests
assets/
  sprites/        32x32 sheets, 352x1696 px: base/ cats, valentine/ and winter/ accessories
  aseprite/       editable sources of the sheets
  reference/      animation list, frame indexes, palette
  generated/      frames made in code, their provenance, a before/after sheet
  video/          the promo
```

## License

Code: [Unlicense](LICENSE). The cat sprites in `assets/` are by Last tick and are not covered by the Unlicense.
