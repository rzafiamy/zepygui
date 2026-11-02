# Contributing to ZePyGUI

Thanks for helping! ZePyGUI stays small on purpose, so a few rules keep it that way.

## Ground rules

- **Standard library only.** The package must never import a third-party module
  (`tests/test_platform.py` checks it). Tools under `tools/` may use Node and Playwright.
- **Python 3.9+.** No syntax or library calls newer than 3.9 in `zepygui/`.
- **Every behaviour is a requirement.** New behaviour gets a line in
  [`specs/specification.md`](specs/specification.md) and a test whose docstring says
  `covers: REQ-…` (or a row in [`specs/manual.md`](specs/manual.md) when it cannot be automated).
- **Measure performance claims** with `bench/bench.py`, before and after.

## Development setup

```bash
git clone https://github.com/rzafiamy/zepygui.git
```

```bash
cd zepygui && python3 -m pip install -e .
```

Run the checks before opening a pull request:

```bash
python3 -m unittest discover -s tests
```

```bash
python3 tests/matrix.py --check
```

```bash
python3 bench/bench.py
```

If you changed anything visible, regenerate the screenshots (needs Node and `playwright`):

```bash
node tools/screenshots.mjs
```

## Pull requests

- One topic per pull request, with a short description of what and why.
- Add an entry under *Unreleased* in [`CHANGELOG.md`](CHANGELOG.md).
- Keep the style of the surrounding code: small functions, docstrings that say what a caller gets,
  comments that explain *why*.
- Third-party artwork (icons, fonts) must be credited in [`CREDITS.md`](CREDITS.md) with its
  licence text in `licences/`.

## Reporting bugs

Open an issue with the ZePyGUI version, your OS and Python version, the run mode
(`native`, `window`, `browser`, `server`), and the smallest script that shows the problem.
