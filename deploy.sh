#!/usr/bin/env bash
# Release PyGUI: bump the version, test, build, upload to PyPI (or TestPyPI), tag and push.
#
#   ./deploy.sh             asks for everything it needs
#   ./deploy.sh --dry-run   does every step except the upload and the push
#
# Optional environment variables (skip the matching question):
#   PYPI_TOKEN      API token for the chosen index (otherwise asked, hidden; or taken from ~/.pypirc)
#   PYTHON          interpreter used to build (default: python3)
#
# Nothing is published until you confirm the summary. If the upload fails, the version
# bump commit and tag are removed again, so the repository is left as it was.
set -euo pipefail

PACKAGE="pygui-desktop"
IMPORT_NAME="pygui"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

cd "$ROOT"
export PYTHONWARNINGS="ignore"          # urllib3 warns about LibreSSL on macOS's Python; harmless
export PIP_DISABLE_PIP_VERSION_CHECK=1
VERSIONED_FILES=(pyproject.toml "$IMPORT_NAME/__init__.py" specs/specification.md specs/matrix.md)

# ------------------------------------------------------------------ output helpers
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; OFF=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""
fi
step() { printf '\n%s==> %s%s\n' "$BLUE$BOLD" "$1" "$OFF"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$OFF" "$1"; }
die()  { printf '%s✗ %s%s\n' "$RED" "$1" "$OFF" >&2; exit 1; }

ask() {  # ask "Question" "default" -> echoes the answer
  local answer
  read -r -p "$1 ${DIM}[$2]${OFF} " answer </dev/tty || true
  printf '%s' "${answer:-$2}"
}

confirm() {  # confirm "Question" "y|n" -> exit status
  local answer
  answer="$(ask "$1 (y/n)" "$2")"
  [[ "$answer" =~ ^[YyOo] ]]
}

# ------------------------------------------------------------------ 1. preconditions
step "Checking the repository"
command -v git >/dev/null || die "git is not installed"
command -v "$PYTHON" >/dev/null || die "$PYTHON is not installed (set PYTHON=/path/to/python3)"
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 9))' || die "$PYTHON is older than 3.9"
git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository: $ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  git status --short
  die "the working tree has uncommitted changes: commit or stash them first"
fi
ok "working tree clean"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "main" ]]; then
  confirm "You are on '$BRANCH', not 'main'. Release from '$BRANCH' anyway?" "n" || die "cancelled"
fi

REMOTE="$(git remote | head -n1)"
[[ -n "$REMOTE" ]] || die "no git remote configured (git remote add origin <url>)"
git fetch --quiet "$REMOTE" "$BRANCH" || die "could not fetch $REMOTE/$BRANCH"
BEHIND="$(git rev-list --count "HEAD..$REMOTE/$BRANCH" 2>/dev/null || echo 0)"
[[ "$BEHIND" == "0" ]] || die "$BRANCH is $BEHIND commit(s) behind $REMOTE/$BRANCH: pull first"
ok "up to date with $REMOTE/$BRANCH"
START_SHA="$(git rev-parse HEAD)"

CURRENT="$("$PYTHON" - <<'EOF'
import re, pathlib
m = re.search(r'^version\s*=\s*"([^"]+)"', pathlib.Path("pyproject.toml").read_text(), re.M)
print(m.group(1) if m else "")
EOF
)"
[[ -n "$CURRENT" ]] || die "could not read the version from pyproject.toml"
ok "current version: $CURRENT"

# ------------------------------------------------------------------ 2. questions
step "Release settings"

bump() {  # bump <version> <patch|minor|major>
  "$PYTHON" - "$1" "$2" <<'EOF'
import sys
v, part = sys.argv[1], sys.argv[2]
major, minor, patch = (int(x) for x in (v.split(".") + ["0", "0"])[:3])
print({"patch": f"{major}.{minor}.{patch + 1}", "minor": f"{major}.{minor + 1}.0",
       "major": f"{major + 1}.0.0"}[part])
EOF
}

echo "Which version do you want to release?"
echo "  1) $(bump "$CURRENT" patch)  patch: bug fixes"
echo "  2) $(bump "$CURRENT" minor)  minor: new features, compatible"
echo "  3) $(bump "$CURRENT" major)  major: breaking changes"
echo "  4) $CURRENT  keep the current version (first upload, or a failed one)"
echo "  5) other"
case "$(ask "Choice" "1")" in
  1) VERSION="$(bump "$CURRENT" patch)" ;;
  2) VERSION="$(bump "$CURRENT" minor)" ;;
  3) VERSION="$(bump "$CURRENT" major)" ;;
  4) VERSION="$CURRENT" ;;
  5) VERSION="$(ask "Version (e.g. 1.2.3 or 1.2.3rc1)" "")" ;;
  *) die "unknown choice" ;;
esac
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([a-z]+[0-9]+)?$ ]] || die "'$VERSION' is not a version like 1.2.3"
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
  die "tag v$VERSION already exists"
fi

echo
echo "Where do you want to publish?"
echo "  1) TestPyPI  https://test.pypi.org  (rehearsal, separate account)"
echo "  2) PyPI      https://pypi.org       (real release, permanent)"
case "$(ask "Choice" "1")" in
  1) INDEX="testpypi"; UPLOAD_URL="https://test.pypi.org/legacy/"; INDEX_URL="https://test.pypi.org"
     TOKEN_PAGE="https://test.pypi.org/manage/account/token/" ;;
  2) INDEX="pypi"; UPLOAD_URL="https://upload.pypi.org/legacy/"; INDEX_URL="https://pypi.org"
     TOKEN_PAGE="https://pypi.org/manage/account/token/" ;;
  *) die "unknown choice" ;;
esac

# a version can never be uploaded twice, even after deleting it
STATUS="$(curl -s -o /dev/null -w '%{http_code}' "$INDEX_URL/pypi/$PACKAGE/$VERSION/json" || echo 000)"
[[ "$STATUS" != "200" ]] || die "$PACKAGE $VERSION is already on $INDEX: choose another version"

echo
RUN_GUI=0
if [[ "$(uname)" == "Darwin" ]] && confirm "Also run the native window tests (windows open on screen for ~40 s)?" "n"; then
  RUN_GUI=1
fi

PUSH=1
confirm "Commit the version, tag v$VERSION and push to $REMOTE after the upload?" "y" || PUSH=0

TOKEN="${PYPI_TOKEN:-}"
if [[ -z "$TOKEN" && $DRY_RUN -eq 0 ]]; then
  if [[ -f "$HOME/.pypirc" ]] && grep -q "^\[$INDEX\]" "$HOME/.pypirc"; then
    ok "using the [$INDEX] credentials from ~/.pypirc"
  else
    echo
    echo "An API token for $INDEX is needed (it starts with 'pypi-'). Create one at:"
    echo "  $TOKEN_PAGE"
    echo "For a first upload the scope must be 'Entire account'. It is used for this upload only, never saved."
    read -r -s -p "Token (hidden): " TOKEN </dev/tty
    echo
    [[ "$TOKEN" == pypi-* ]] || die "that does not look like a PyPI token (it should start with 'pypi-')"
  fi
fi

# ------------------------------------------------------------------ 3. summary
step "Summary"
printf '  package   %s\n' "$PACKAGE"
printf '  version   %s -> %s\n' "$CURRENT" "$VERSION"
printf '  index     %s (%s)\n' "$INDEX" "$INDEX_URL/project/$PACKAGE/"
printf '  git       %s\n' "$([[ $PUSH -eq 1 ]] && echo "commit + tag v$VERSION, push to $REMOTE/$BRANCH" || echo "no commit, no push")"
printf '  tests     headless%s\n' "$([[ $RUN_GUI -eq 1 ]] && echo " + native windows" || true)"
[[ $DRY_RUN -eq 1 ]] && printf '  %sdry run: nothing will be uploaded or pushed%s\n' "$YELLOW" "$OFF"
[[ "$INDEX" == "pypi" && $DRY_RUN -eq 0 ]] && warn "a PyPI release is permanent: $VERSION can never be uploaded again"
confirm "Go?" "n" || die "cancelled"

# ------------------------------------------------------------------ 4. work
WORK="$(mktemp -d)"
COMMITTED=0
cleanup() { rm -rf "$WORK"; }
rollback() {
  if [[ $COMMITTED -eq 1 ]]; then
    git tag -d "v$VERSION" >/dev/null 2>&1 || true
    git reset --hard --quiet "$START_SHA"
    warn "the version commit and tag were removed; the repository is back at $(git rev-parse --short HEAD)"
  else
    git checkout --quiet -- "${VERSIONED_FILES[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'rollback; die "interrupted"' INT TERM

step "Setting version $VERSION"
"$PYTHON" - "$VERSION" <<'EOF'
import re, sys, pathlib
version = sys.argv[1]
for path, pattern, repl, required in (
    ("pyproject.toml", r'^version\s*=\s*"[^"]+"', f'version = "{version}"', True),
    ("pygui/__init__.py", r'^__version__\s*=\s*"[^"]+"', f'__version__ = "{version}"', True),
    ("specs/specification.md", r'^Version of record: `[^`]+`', f'Version of record: `{version}`', False),
):
    p = pathlib.Path(path)
    text, n = re.subn(pattern, repl, p.read_text(), count=1, flags=re.M)
    if n != 1 and required:
        sys.exit(f"could not set the version in {path}")
    p.write_text(text)
EOF
ok "pyproject.toml, $IMPORT_NAME/__init__.py, specs/specification.md"

step "Running the tests"
# the suite prints expected tracebacks (error-handling tests): keep them in a log unless it fails
GUI_FLAG=""
[[ $RUN_GUI -eq 1 ]] && GUI_FLAG=1
if ! PYGUI_GUI_TESTS="$GUI_FLAG" "$PYTHON" -m unittest discover -s tests >"$WORK/tests.log" 2>&1; then
  tail -n 60 "$WORK/tests.log"
  rollback
  die "tests failed (full log above)"
fi
ok "$(grep -E '^Ran [0-9]+ tests' "$WORK/tests.log") · $(tail -n 1 "$WORK/tests.log")"
"$PYTHON" tests/matrix.py || { rollback; die "the requirement matrix has gaps"; }
if [[ -n "$(git status --porcelain specs/matrix.md)" ]]; then
  warn "specs/matrix.md changed while rebuilding it: it will be part of the release commit"
fi
ok "tests passed"

step "Building"
"$PYTHON" -m venv "$WORK/venv"
"$WORK/venv/bin/python" -m pip install --quiet --upgrade pip build twine || { rollback; die "could not install build and twine"; }
rm -rf dist build ./*.egg-info
"$WORK/venv/bin/python" -m build --outdir dist . >"$WORK/build.log" 2>&1 || { cat "$WORK/build.log"; rollback; die "build failed"; }
"$WORK/venv/bin/twine" check --strict dist/* || { rollback; die "twine check failed"; }
ok "$(ls dist | tr '\n' ' ')"

step "Checking the wheel in a clean environment"
"$PYTHON" -m venv "$WORK/check"
"$WORK/check/bin/python" -m pip install --quiet dist/*.whl || { rollback; die "the wheel does not install"; }
(cd "$WORK" && "$WORK/check/bin/python" - "$VERSION" <<'EOF'
import os, sys
import pygui
from pygui import App, ui
from pygui.app import Renderer, Session
assert pygui.__version__ == sys.argv[1], pygui.__version__
assert os.path.isfile(os.path.join(os.path.dirname(pygui.__file__), "static", "client.js"))
app = App("check")
app.page("/")(lambda: ui.h1("ok"))
s = Session(app, "c", "/", "dark")
assert Renderer(s).build()[0]
s.close()
EOF
) || { rollback; die "the built wheel does not work"; }
ok "installs, imports and renders"

if [[ $PUSH -eq 1 && "$VERSION" != "$CURRENT" ]]; then
  git add "${VERSIONED_FILES[@]}"
  git commit --quiet -m "Release $VERSION"
  COMMITTED=1
fi
if [[ $PUSH -eq 1 ]]; then
  git tag -a "v$VERSION" -m "$PACKAGE $VERSION"
  COMMITTED=1
fi

if [[ $DRY_RUN -eq 1 ]]; then
  step "Dry run finished"
  rollback
  ok "everything up to the upload worked; dist/ holds the files that would have been uploaded"
  exit 0
fi

step "Uploading to $INDEX"
if [[ -n "$TOKEN" ]]; then
  TWINE_USERNAME="__token__" TWINE_PASSWORD="$TOKEN" \
    "$WORK/venv/bin/twine" upload --non-interactive --repository-url "$UPLOAD_URL" dist/* \
    || { rollback; die "upload failed"; }
else
  "$WORK/venv/bin/twine" upload --non-interactive --repository "$INDEX" dist/* || { rollback; die "upload failed"; }
fi
unset TOKEN
ok "uploaded: $INDEX_URL/project/$PACKAGE/$VERSION/"
trap 'die "interrupted (the package is already published; push by hand if needed)"' INT TERM  # never roll back now

if [[ $PUSH -eq 1 ]]; then
  step "Pushing to $REMOTE"
  if git push --quiet "$REMOTE" "$BRANCH" && git push --quiet "$REMOTE" "v$VERSION"; then
    ok "pushed $BRANCH and tag v$VERSION"
  else
    warn "the package is published but the push failed; push by hand:"
    echo "    git push $REMOTE $BRANCH && git push $REMOTE v$VERSION"
  fi
fi

step "Verifying the install from $INDEX"
"$PYTHON" -m venv "$WORK/verify"
INDEX_ARGS="--index-url=https://pypi.org/simple/"
[[ "$INDEX" == "testpypi" ]] && INDEX_ARGS="--index-url=https://test.pypi.org/simple/"
for attempt in 1 2 3 4 5 6; do
  if "$WORK/verify/bin/python" -m pip install --quiet --no-cache-dir "$INDEX_ARGS" "$PACKAGE==$VERSION" 2>/dev/null; then
    (cd "$WORK" && "$WORK/verify/bin/python" -c "import pygui; print('installed', pygui.__version__)")
    ok "pip install $PACKAGE==$VERSION works"
    break
  fi
  [[ $attempt -eq 6 ]] && { warn "not installable yet; the index can take a few minutes to update"; break; }
  printf '%s  waiting for the index to update (%s/6)…%s\n' "$DIM" "$attempt" "$OFF"
  sleep 20
done

step "Done"
echo "  $INDEX_URL/project/$PACKAGE/$VERSION/"
if [[ "$INDEX" == "testpypi" ]]; then
  echo "  try it:  pip install --index-url https://test.pypi.org/simple/ $PACKAGE==$VERSION"
else
  echo "  install: pip install $PACKAGE"
fi
