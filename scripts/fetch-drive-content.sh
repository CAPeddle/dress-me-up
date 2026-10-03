#!/usr/bin/env bash
#
# Pull the "Dress Me Up" scans out of Google Drive into content/.
#
#   ./scripts/fetch-drive-content.sh --setup     # one-time: install rclone, authorise
#   ./scripts/fetch-drive-content.sh             # pull everything
#   ./scripts/fetch-drive-content.sh --set Fantasy
#
# Why not the Claude Drive connector: it returns files as base64 into the model's
# context. The smallest scan here is ~600 KB and the largest 10.6 MB; that is the
# wrong mechanism for moving binaries onto disk. rclone talks to the same Drive
# account and writes straight to the filesystem.
#
# No sudo: rclone installs as a static binary into ~/.local/bin.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$REPO_ROOT/content/source"
REMOTE="${RCLONE_REMOTE:-gdrive}"
DRIVE_FOLDER="Dress me up"
BIN_DIR="$HOME/.local/bin"

# Folder ids, captured 2026-08-25. Only needed if the folder gets renamed and
# the path lookup stops working.
#   Dress me up   1dv7oJL8JNB71Fw8Odd4aDgJ2WxlfKtsc
#   Fantasy       1yLX5hR8_LplJr3vObzE0xHKkvzHxa1qQ   (9 PDFs)
#   Fantasy w Boy 1DR1-gPCemb_zTvAWT-8rsEyCeLTLib6N   (8 PDFs)
#   Knight        1aTsLLUnSH5Nrq2hdXgZ2KxQj9iE_pvjc   (1 PDF)

SETUP=false
SET_NAME=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --setup) SETUP=true; shift ;;
    --set) SET_NAME="${2:?--set needs a folder name}"; shift 2 ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

# Refuse to run elevated. Under sudo, HOME is root's, so the binary installs to
# /root/.local/bin and the OAuth token lands in root's config — both invisible to
# the user who actually runs the pull. Nothing here needs root.
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  cat >&2 <<'EOM'
error: do not run this with sudo.

rclone installs into your own ~/.local/bin and authorises against YOUR Drive
account. Run as root and both end up under /root, where your user cannot see
them. Re-run without sudo:

    ./scripts/fetch-drive-content.sh --setup

If a previous sudo run already created them, clean up with:

    sudo rm -rf /root/.local/bin/rclone /root/.config/rclone
EOM
  exit 2
fi

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32mok\033[0m   %s\n' "$1"; }
die()  { printf '\n\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

export PATH="$BIN_DIR:$PATH"

# --- install rclone, no sudo ------------------------------------------------
if ! command -v rclone >/dev/null 2>&1; then
  $SETUP || die "rclone not installed. Run: $0 --setup"

  step "Installing rclone into $BIN_DIR"
  mkdir -p "$BIN_DIR"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  arch="$(uname -m)"; case "$arch" in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; esac

  # Pinned, and checked against the sums published beside it. The binary lands on
  # PATH and is then run by this script, so a redirected download or a trusted-root
  # proxy would be executing as this user; TLS alone decides nothing about what
  # arrived. Bump the version deliberately rather than tracking rclone-current.
  RCLONE_VERSION="v1.71.0"
  base="https://downloads.rclone.org/${RCLONE_VERSION}"
  zip="rclone-${RCLONE_VERSION}-linux-${arch}.zip"
  curl -fL --progress-bar -o "$tmp/$zip" "$base/$zip" || die "download failed"
  curl -fsSL -o "$tmp/SHA256SUMS" "$base/SHA256SUMS" || die "could not fetch SHA256SUMS"
  # Only this archive's line, so an unrelated entry cannot satisfy the check.
  grep -F " $zip" "$tmp/SHA256SUMS" > "$tmp/want" || die "no checksum published for $zip"
  ( cd "$tmp" && sha256sum -c --status want ) \
    || die "rclone checksum mismatch — refusing to install $zip"

  unzip -qj "$tmp/$zip" '*/rclone' -d "$BIN_DIR"
  chmod +x "$BIN_DIR/rclone"
  ok "$(rclone version | head -1)"
fi

# --- authorise --------------------------------------------------------------
if ! rclone listremotes 2>/dev/null | grep -qx "${REMOTE}:"; then
  cat <<EOM

No rclone remote named '${REMOTE}' yet. This is a one-time interactive step:
Google's OAuth needs a browser, so it cannot be scripted.

  rclone config

  n) New remote
  name> ${REMOTE}
  Storage> drive
  client_id / client_secret> (leave blank, press enter)
  scope> 2          <-- read-only. This tool never writes to your Drive.
  service_account_file> (blank)
  Edit advanced config> n
  Use web browser to automatically authenticate> y
  Configure this as a Shared Drive> n

OVER SSH WITH NO BROWSER ON THIS MACHINE
----------------------------------------
rclone's callback listens on localhost:53682. Forward that port and your local
browser can reach it — nothing needs installing on the local side.

  1. Reconnect, forwarding the port:

         ssh -L 53682:localhost:53682 $USER@$(hostname)

  2. Run 'rclone config' as above, answering **y** to the browser question.
     It will fail to launch a browser and print a URL instead:

         http://127.0.0.1:53682/auth?state=...

  3. Paste that URL into the browser on your LOCAL machine. Approve access.
     The tunnel carries the callback back here and rclone completes.

If you cannot forward ports, answer **n** at the browser question instead.
rclone prints an 'rclone authorize "drive" ...' command to run on any machine
that has both a browser and rclone; it returns a token blob you paste back here.

Then re-run this script.
EOM
  exit 1
fi
ok "rclone remote '${REMOTE}' configured"

# --- pull -------------------------------------------------------------------
SOURCE="${REMOTE}:${DRIVE_FOLDER}"
[[ -n "$SET_NAME" ]] && SOURCE="${SOURCE}/${SET_NAME}"

step "Pulling '${SOURCE}' -> content/source/"
mkdir -p "$DEST"
rclone copy "$SOURCE" "${DEST}${SET_NAME:+/$SET_NAME}" \
  --progress --drive-acknowledge-abuse=false \
  --include "*.pdf" --include "*.jpg" --include "*.jpeg" --include "*.png" \
  || die "copy failed — check the folder name matches Drive exactly (note the trailing space in 'Dress me up ')"

step "What landed"
find "$DEST" -type f \( -name '*.pdf' -o -name '*.jpg' -o -name '*.jpeg' -o -name '*.png' \) \
  | sed "s|$DEST/||" | awk -F/ '{print $1}' | sort | uniq -c | sort -rn
echo
printf 'total: %s files, %s\n' \
  "$(find "$DEST" -type f | wc -l)" "$(du -sh "$DEST" | cut -f1)"

cat <<'EOM'

Next — decide which source to feed the pipeline (they are scans of the same pages):

    tools/.venv/bin/python tools/assess_source_quality.py \
        content/source/Fantasy/*.pdf content/source/Fantasy/*.jpg

Then extract from whichever wins on the `items` / `q50` columns.
EOM
