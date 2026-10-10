#!/usr/bin/env bash
# Builds the release for an aarch64 ROCKNIX handheld: dist/autogamer/ and a tarball of it. Needs an arm64 Linux host
# with podman and git. Autogamer itself is Python and shell; the one thing built is llamatalk (llama-server,
# tts-server and models.sh), fetched at its pinned commit and built by its own build/build.sh.
# Env: JOBS (default 3), LLAMATALK_SRC=<a clean llamatalk checkout at LLAMATALK_COMMIT> builds from it (and its build
# cache) instead of a fetch.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
W="$ROOT/build/work"; OUT="$ROOT/dist/autogamer"
LLAMATALK=https://github.com/mercurious/llamatalk    LLAMATALK_COMMIT=091fd0054909ac0e9a67473b7642f89f725ce854

fetch() {   # fetch <url> <commit> <dir>: that one commit, nothing else
  [ "$(git -C "$3" rev-parse HEAD 2>/dev/null)" = "$2" ] && return 0
  mkdir -p "$3"; git -C "$3" init -q
  git -C "$3" fetch -q --depth 1 "$1" "$2"
  git -C "$3" checkout -q --detach FETCH_HEAD
}

"$ROOT/test/check_no_roms.sh"
mkdir -p "$W"
LT=${LLAMATALK_SRC:-$W/llamatalk}
if [ -n "${LLAMATALK_SRC:-}" ]; then
  [ "$(git -C "$LT" rev-parse HEAD)" = $LLAMATALK_COMMIT ] && [ -z "$(git -C "$LT" status --porcelain)" ] \
    || { echo "LLAMATALK_SRC must be a clean checkout of llamatalk $LLAMATALK_COMMIT" >&2; exit 1; }
else fetch $LLAMATALK $LLAMATALK_COMMIT "$LT"; fi
JOBS=${JOBS:-3} "$LT/build/build.sh"

rm -rf "$OUT"; mkdir -p "$OUT"
cp -r "$LT/dist/llamatalk" "$ROOT/app" "$ROOT/ports" "$ROOT/test" "$ROOT/tools" "$OUT/"
cp "$ROOT"/install.sh "$ROOT"/README.md "$ROOT"/LICENSE "$ROOT"/THIRD_PARTY.md "$OUT/"
find "$OUT" -name __pycache__ -prune -exec rm -rf {} +
chmod +x "$OUT"/install.sh "$OUT"/app/*.sh "$OUT"/test/*.sh
tar -C "$ROOT/dist" -czf "$ROOT/dist/autogamer-aarch64.tar.gz" autogamer
ls -la "$OUT" "$OUT/app"; du -sh "$ROOT/dist/autogamer-aarch64.tar.gz"
