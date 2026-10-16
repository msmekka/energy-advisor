#!/usr/bin/env bash
# Bring a checkout up to date from origin. The rig is a pull-only consumer of
# this repo: it never commits, never pushes, never merges.
#
#   ./sync.sh              # fast-forward the current branch, report what moved
#   ./sync.sh --check      # report only, change nothing
#
# Why git rather than rsync or scp: every campaign row carries the commit SHA,
# so "which code produced this row?" stays answerable months later. rsync is
# faster and makes that question unanswerable, which is the one question a
# calibration rig must always be able to answer.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# The only paths a measurement depends on. A change anywhere else -- rules/,
# preso/, docs -- cannot invalidate a campaign, so it is reported separately
# from the ones that can.
MEASUREMENT_PATHS=(etdc benchmarks)

CHECK_ONLY=0

log() { echo "[sync] $*"; }
die() { echo "[sync] error: $*" >&2; exit 1; }

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    *) echo "usage: $0 [--check]" >&2; exit 1 ;;
  esac
done

cd "$REPO_ROOT"

# A root pull leaves root-owned files in a checkout the campaign user has to
# read and write -- the same mistake the measurements/ vs runs/ ownership split
# exists to avoid. sudo is for pin_baseline.sh and nothing else.
if [[ $EUID -eq 0 ]]; then
  die "do not run as root -- the checkout belongs to the campaign user"
fi

git rev-parse --git-dir >/dev/null 2>&1 || die "$REPO_ROOT is not a git checkout"

branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" != "HEAD" ]] || die "detached HEAD -- check out a branch before syncing"

# Tracked edits mean the SHA recorded on every row would be a lie about the
# code that produced it. Refuse rather than stash: a stash on a measurement rig
# is a local change you will forget you made.
if ! git diff --quiet || ! git diff --cached --quiet; then
  git status --short
  die "working tree has tracked modifications -- the rig must match a commit exactly"
fi

# Untracked files do not block a fast-forward, but the campaign runner refuses
# to start on a dirty tree, so surface them now rather than at campaign start.
untracked="$(git ls-files --others --exclude-standard)"
if [[ -n "$untracked" ]]; then
  log "warning: untracked files present (the runner will refuse to start on these):"
  while IFS= read -r f; do log "    $f"; done <<< "$untracked"
fi

git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1 \
  || die "branch '$branch' has no upstream -- git branch --set-upstream-to=origin/$branch"

log "fetching origin"
git fetch --quiet origin

local_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse '@{u}')"

if [[ "$local_sha" == "$remote_sha" ]]; then
  log "already up to date: $branch at $(git rev-parse --short HEAD)"
  log "HEAD = $local_sha"
  exit 0
fi

# Divergence is something to look at, never to resolve automatically -- the rig
# should have no commits of its own, so this means something unexpected
# happened here.
if ! git merge-base --is-ancestor "$local_sha" "$remote_sha"; then
  die "local '$branch' has diverged from its upstream; inspect with 'git log --oneline @{u}..HEAD'"
fi

log "$branch: $(git rev-parse --short "$local_sha") -> $(git rev-parse --short "$remote_sha")"

# Whether this sync invalidates comparability with rows already collected is
# the thing you actually want to know, so say it plainly either way.
changed="$(git diff --name-only "$local_sha" "$remote_sha" -- "${MEASUREMENT_PATHS[@]}")"
if [[ -n "$changed" ]]; then
  log "measurement code changed:"
  while IFS= read -r f; do log "    $f"; done <<< "$changed"
  log "rows collected before this sync are NOT comparable with rows collected after it"
else
  log "nothing changed under ${MEASUREMENT_PATHS[*]} -- existing rows stay comparable"
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  log "--check: stopping without pulling"
  exit 0
fi

git merge --ff-only --quiet "$remote_sha"
log "now at $(git rev-parse --short HEAD) on $branch"
log "HEAD = $(git rev-parse HEAD)"
