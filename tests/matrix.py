"""Build specs/matrix.md from the tests themselves, and fail if any requirement is uncovered.

    python3 tests/matrix.py           # rebuild the matrix; exit 1 on any coverage problem
    python3 tests/matrix.py --check   # also exit 1 if the committed matrix is out of date

Coverage is claimed where the test lives:
  * a ``covers: REQ-…`` line in a test method's docstring (tests/test_*.py);
  * a row of specs/manual.md: ``| MT-nnn | procedure | REQ-…, REQ-… |``.
Tests in test_native.py open a real window and are labelled ``auto (gui)``.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "specs" / "specification.md"
MANUAL = ROOT / "specs" / "manual.md"
MATRIX = ROOT / "specs" / "matrix.md"
TESTS = ROOT / "tests"
GUI_FILES = {"test_native.py"}

REQ_LINE = re.compile(r"^- \*\*(REQ-[A-Z]+-\d{3})\*\* (.*?)(?: \*\*\[(T|M)\]\*\*)?\s*$")
REQ_ID = re.compile(r"REQ-[A-Z]+-\d{3}")
MANUAL_ROW = re.compile(r"^\| (MT-\d+) \| (.+) \| ((?:REQ-[A-Z]+-\d{3}(?:, )?)+) \|\s*$")


def load_requirements():
    reqs = {}
    for line in SPEC.read_text("utf-8").splitlines():
        m = REQ_LINE.match(line)
        if m:
            rid, text, marker = m.groups()
            if rid in reqs:
                raise SystemExit(f"duplicate requirement id {rid}")
            reqs[rid] = {"text": text, "marker": marker, "withdrawn": "WITHDRAWN" in text}
    return reqs


def load_automated():
    found = []
    for path in sorted(TESTS.glob("test_*.py")):
        kind = "auto (gui)" if path.name in GUI_FILES else "auto"
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                doc = ast.get_docstring(node) or ""
                for line in doc.splitlines():
                    if line.strip().startswith("covers:"):
                        for rid in REQ_ID.findall(line):
                            found.append((rid, kind, node.name[5:].replace("_", " "), f"tests/{path.name}"))
    return found


def load_manual():
    found = []
    for line in MANUAL.read_text("utf-8").splitlines():
        m = MANUAL_ROW.match(line)
        if m:
            mid, procedure, ids = m.groups()
            for rid in REQ_ID.findall(ids):
                found.append((rid, "manual", f"{mid} {procedure}", "specs/manual.md"))
    return found


def cell(text):
    return text.replace("|", "\\|").replace("\n", " ")


def build():
    reqs = load_requirements()
    coverage = {rid: [] for rid in reqs}
    problems = []
    for rid, kind, title, source in load_automated() + load_manual():
        if rid not in coverage:
            problems.append(f"{source}: '{title[:60]}' covers unknown requirement {rid}")
            continue
        coverage[rid].append((kind, title, source))

    rows, counts = [], {"auto": 0, "gui": 0, "manual": 0, "uncovered": 0}
    for rid, req in reqs.items():
        entries = coverage[rid]
        kinds = sorted({k for k, _, _ in entries})
        automated = any(k.startswith("auto") for k in kinds)
        if req["withdrawn"]:
            verified = "withdrawn"
        elif not entries:
            verified = "**uncovered**"
            counts["uncovered"] += 1
            problems.append(f"{rid} has no test")
        else:
            verified = ", ".join(kinds)
            if automated:
                counts["auto"] += 1
                counts["gui"] += all(k == "auto (gui)" for k in kinds if k.startswith("auto"))
            else:
                counts["manual"] += 1
        if not req["withdrawn"] and entries:
            if req["marker"] == "T" and not automated:
                problems.append(f"{rid} is marked [T] but no automated test covers it")
            if req["marker"] == "M" and "manual" not in kinds:
                problems.append(f"{rid} is marked [M] but no row of manual.md covers it")
            if req["marker"] is None:
                problems.append(f"{rid} has no [T]/[M] marker")
        tests = "<br>".join(f"`{cell(title)}` ({source})" for _, title, source in entries) or "—"
        rows.append(f"| **{rid}** {cell(req['text'])} | {verified} | {tests} |")

    total = len(reqs)
    header = f"""# Traceability matrix

**Generated — do not edit.** `python3 tests/matrix.py` rebuilds it from the tests
themselves: the `covers:` line of each test in `tests/test_*.py`, and the rows of
[`manual.md`](manual.md). Requirements are defined in [`specification.md`](specification.md).

`auto` tests run headless with `python3 -m unittest discover -s tests`.
`auto (gui)` tests open a real native window and run on macOS with
`ZEPYGUI_GUI_TESTS=1`.

Requirements: **{total}** · covered by an automated test: **{counts['auto']}**
(of which GUI only: **{counts['gui']}**) · manual only: **{counts['manual']}**
· uncovered: **{counts['uncovered']}**

| Requirement | Verified by | Tests |
|---|---|---|
"""
    return header + "\n".join(rows) + "\n", problems, counts, total


def main(argv):
    content, problems, counts, total = build()
    if "--check" in argv:
        current = MATRIX.read_text("utf-8") if MATRIX.exists() else ""
        if current != content:
            problems.append("specs/matrix.md is out of date: run python3 tests/matrix.py")
    else:
        MATRIX.write_text(content, "utf-8")
    print(f"{total} requirements · {counts['auto']} automated ({counts['gui']} GUI only) · "
          f"{counts['manual']} manual · {counts['uncovered']} uncovered")
    for p in problems:
        print(f"  ✗ {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
