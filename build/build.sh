#!/usr/bin/env bash
# Builds the release for an aarch64 ROCKNIX handheld: dist/autogamer/ and a tarball of it. Needs an arm64 Linux host
# with podman and git. Autogamer itself is Python and shell; the one thing built is llamatalk (llama-server,
# tts-server and models.sh), fetched at its pinned commit and built by its own build/build.sh.
# The one game it brings, NES Pickleball (the author's homebrew cartridge, MIT), comes as the add-on tarball of its
# pinned release (the ROM, its sidecar, its mailbox contract): fetched from GitHub (gh, signed in as the repo's owner
# while the repo is private), or PICKLEBALL_SRC=<a tarball or an unpacked add-on directory> built by the cartridge's
# own tools/addon.sh; the ROM must have the pinned SHA-256.
# Env: JOBS (default 3), LLAMATALK_SRC=<a clean llamatalk checkout at LLAMATALK_COMMIT> builds from it (and its build
# cache) instead of a fetch, ENGINE (podman, default, or docker; passed to llamatalk's build), PICKLEBALL_SRC.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
W="$ROOT/build/work"; OUT="$ROOT/dist/autogamer"; VER=$(cat "$ROOT/VERSION")
LLAMATALK=https://github.com/mercurious/llamatalk    LLAMATALK_COMMIT=d422c0b36c2ec7cd9359c9250a0bd8cb88f71111
PICKLEBALL_REPO=mercurious/nes-pickleball PICKLEBALL_VERSION=0.0.2
PICKLEBALL_ROM_SHA256=01b464bf5b8de17de03379657aa5bd1dcb3c69ab5ce980bd33374dfbccf8a674   # pickleball.nes, the v0.0.1 cartridge

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

# the pickleball add-on: pickleball/ (pickleball.nes, VERSION, sidecar/, docs) from the pinned release
PB="$W/pickleball"; rm -rf "$PB"; mkdir -p "$PB"
if [ -d "${PICKLEBALL_SRC:-}" ]; then cp -r "${PICKLEBALL_SRC%/}/." "$PB/"
else
  TGZ=${PICKLEBALL_SRC:-}
  if [ -z "$TGZ" ]; then
    TGZ="$W/pickleball-addon-$PICKLEBALL_VERSION.tar.gz"
    [ -f "$TGZ" ] || gh release download "v$PICKLEBALL_VERSION" -R $PICKLEBALL_REPO -p "pickleball-addon-*.tar.gz" -O "$TGZ"
  fi
  tar -xzf "$TGZ" -C "$PB" --strip-components=1
fi
[ "$(sha256sum "$PB/pickleball.nes" | cut -d' ' -f1)" = "$PICKLEBALL_ROM_SHA256" ] || { echo "pickleball.nes is not the pinned cartridge" >&2; exit 1; }
[ "$(cat "$PB/VERSION")" = "$PICKLEBALL_VERSION" ] || { echo "the add-on is $(cat "$PB/VERSION"), not $PICKLEBALL_VERSION" >&2; exit 1; }
for f in sidecar/pickleball_coop.py sidecar/voices.py sidecar/cache.py sidecar/ra.py sidecar/pad.py MAILBOX.md; do
  [ -f "$PB/$f" ] || { echo "the add-on lacks $f" >&2; exit 1; }
done

rm -rf "$OUT"; mkdir -p "$OUT"
cp -r "$LT/dist/llamatalk" "$ROOT/app" "$ROOT/ports" "$ROOT/test" "$ROOT/tools" "$PB" "$OUT/"
cp "$ROOT"/install.sh "$ROOT"/README.md "$ROOT"/LICENSE "$ROOT"/THIRD_PARTY.md "$ROOT"/VERSION "$OUT/"
{ echo "autogamer $VER $(git -C "$ROOT" rev-parse HEAD)"; cat "$LT/dist/llamatalk/BUILD.txt"
  echo "nes-pickleball $PICKLEBALL_VERSION add-on, pickleball.nes sha256 $PICKLEBALL_ROM_SHA256"; } > "$OUT/BUILD.txt"
find "$OUT" -name __pycache__ -prune -exec rm -rf {} +
chmod +x "$OUT"/install.sh "$OUT"/app/*.sh "$OUT"/test/*.sh "$OUT"/pickleball/sidecar/*.py
"$ROOT/test/check_no_roms.sh" "$OUT"
tar -C "$ROOT/dist" -czf "$ROOT/dist/autogamer-aarch64.tar.gz" autogamer
ls -la "$OUT" "$OUT/app"; du -sh "$ROOT/dist/autogamer-aarch64.tar.gz"
