#!/usr/bin/env python3
"""Desktop cat. Everything that makes it tick lives in brain/.

    .venv/bin/python pet.py          run the cat (menu-bar 🐱: what it is doing and feeling, ask, skin, sound, quit)
    .venv/bin/python pet.py check    validate brain/anim.json and print pose-junction pixel diffs
    .venv/bin/python pet.py gen      write generated frames + before/after sheet to assets/generated/
    .venv/bin/python pet.py sim [hours] [seed]   simulate a working day, print where the time went
    .venv/bin/python pet.py test     run the tests
    .venv/bin/python pet.py film     play the ~19 s promo in this terminal (vhs film.tape records it)
"""
import fcntl
import os
import sys

from brain.config import load_config

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    cmd, args = (sys.argv[1:2] or ['run'])[0], sys.argv[2:]
    if cmd == 'check':
        from brain.check import check
        sys.exit(0 if check(load_config()) else 1)
    if cmd == 'gen':
        from brain.sprites import write_generated
        index, path = write_generated(load_config())
        print(f'{len(index)} frames, provenance in assets/generated/index.json, before/after: {path}')
        return
    if cmd == 'sim':
        from brain.sim import report
        report(hours=float(args[0]) if args else 8.0, seed=int(args[1]) if len(args) > 1 else 1)
        return
    if cmd == 'test':
        import unittest
        result = unittest.main(module='brain.tests', argv=['pet.py test'], exit=False, verbosity=2).result
        sys.exit(not result.wasSuccessful())
    if cmd == 'film':
        from brain.film import play_film
        play_film(load_config())
        return
    if cmd != 'run':
        sys.exit(__doc__)
    lock = open(os.path.join(HERE, '.pet.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit('cat is already running (menu bar 🐱 -> Выйти)')
    from brain.app import run_app
    run_app(load_config())


if __name__ == '__main__':
    main()
