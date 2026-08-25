#!/usr/bin/env bash
#
# One-shot environment setup for dress-me-up on Ubuntu.
#
#   ./scripts/setup-ubuntu.sh              # everything
#   ./scripts/setup-ubuntu.sh --check      # report state, change nothing
#   ./scripts/setup-ubuntu.sh --skip-udev  # e.g. on a machine with no tablet
#
# Safe to re-run: every step checks before it acts. Only the JDK install and the
# udev rule need sudo, and both announce themselves before asking.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}"

# Pinned deliberately. build-tools 34.0.0 matches compileSdk 34; the original
# project fell back to 36.1.0 because 34.0.0 was corrupted in its Windows SDK
# install. We try 34.0.0 first here — that corruption was probably local.
BUILD_TOOLS_PRIMARY="34.0.0"
BUILD_TOOLS_FALLBACK="36.1.0"
PLATFORM="android-34"
JDK_PACKAGE="openjdk-21-jdk"
PYTHON_VERSION="3.12"

# Override if Google moves the archive; check https://developer.android.com/studio#command-line-tools-only
CMDLINE_TOOLS_URL="${CMDLINE_TOOLS_URL:-https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip}"

SAMSUNG_VENDOR_ID="04e8"
UDEV_RULE="/etc/udev/rules.d/51-android.rules"

CHECK_ONLY=false
SKIP_UDEV=false
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=true ;;
    --skip-udev) SKIP_UDEV=true ;;
    -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32mok\033[0m   %s\n' "$1"; }
warn() { printf '    \033[33mwarn\033[0m %s\n' "$1"; }
todo() { printf '    \033[33mtodo\033[0m %s\n' "$1"; }
die()  { printf '\n\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

# --- 1. JDK ----------------------------------------------------------------
step "JDK 21"
if need_cmd javac && javac -version 2>&1 | grep -q ' 21\.'; then
  ok "$(javac -version 2>&1)"
elif $CHECK_ONLY; then
  todo "not installed — would run: sudo apt install -y $JDK_PACKAGE"
else
  echo "    installing $JDK_PACKAGE (needs sudo)"
  sudo apt-get update -qq
  sudo apt-get install -y "$JDK_PACKAGE"
  ok "$(javac -version 2>&1)"
fi

# --- 2. Android SDK --------------------------------------------------------
step "Android SDK at $SDK_ROOT"
SDKMANAGER="$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"

if [[ -x "$SDKMANAGER" ]]; then
  ok "cmdline-tools present"
elif $CHECK_ONLY; then
  todo "cmdline-tools missing — would download and unpack to $SDK_ROOT"
else
  need_cmd curl  || die "curl not found: sudo apt install curl"
  need_cmd unzip || die "unzip not found: sudo apt install unzip"

  echo "    downloading cmdline-tools"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fL --progress-bar -o "$tmp/tools.zip" "$CMDLINE_TOOLS_URL" \
    || die "download failed — check CMDLINE_TOOLS_URL is still current"
  unzip -q "$tmp/tools.zip" -d "$tmp"
  # The zip unpacks to cmdline-tools/; sdkmanager insists on being at
  # cmdline-tools/latest/ or it cannot resolve its own package path.
  mkdir -p "$SDK_ROOT/cmdline-tools"
  rm -rf "$SDK_ROOT/cmdline-tools/latest"
  mv "$tmp/cmdline-tools" "$SDK_ROOT/cmdline-tools/latest"
  ok "cmdline-tools installed"
fi

if ! $CHECK_ONLY && [[ -x "$SDKMANAGER" ]]; then
  echo "    accepting licences"
  yes | "$SDKMANAGER" --sdk_root="$SDK_ROOT" --licenses >/dev/null 2>&1 || true

  echo "    installing platform-tools and $PLATFORM"
  "$SDKMANAGER" --sdk_root="$SDK_ROOT" "platform-tools" "platforms;$PLATFORM" >/dev/null

  if "$SDKMANAGER" --sdk_root="$SDK_ROOT" "build-tools;$BUILD_TOOLS_PRIMARY" >/dev/null 2>&1; then
    INSTALLED_BUILD_TOOLS="$BUILD_TOOLS_PRIMARY"
  else
    warn "build-tools $BUILD_TOOLS_PRIMARY failed — falling back to $BUILD_TOOLS_FALLBACK"
    "$SDKMANAGER" --sdk_root="$SDK_ROOT" "build-tools;$BUILD_TOOLS_FALLBACK" >/dev/null
    INSTALLED_BUILD_TOOLS="$BUILD_TOOLS_FALLBACK"
  fi
  ok "build-tools $INSTALLED_BUILD_TOOLS"

  if [[ "$INSTALLED_BUILD_TOOLS" != "$(grep -oP 'buildToolsVersion = "\K[^"]+' "$REPO_ROOT/app/build.gradle.kts" || true)" ]]; then
    warn "app/build.gradle.kts pins a different buildToolsVersion — reconcile before building"
  fi
fi

# --- 3. local.properties ---------------------------------------------------
step "local.properties"
LOCAL_PROPS="$REPO_ROOT/local.properties"
if [[ -f "$LOCAL_PROPS" ]] && grep -q '^sdk.dir=' "$LOCAL_PROPS"; then
  ok "$(grep '^sdk.dir=' "$LOCAL_PROPS")"
elif $CHECK_ONLY; then
  todo "would write sdk.dir=$SDK_ROOT"
else
  echo "sdk.dir=$SDK_ROOT" > "$LOCAL_PROPS"
  ok "wrote sdk.dir=$SDK_ROOT (gitignored)"
fi

# --- 4. udev rule for the tablet -------------------------------------------
step "adb access to the Galaxy Tab (udev)"
if $SKIP_UDEV; then
  ok "skipped"
elif [[ -f "$UDEV_RULE" ]]; then
  ok "$UDEV_RULE exists"
elif $CHECK_ONLY; then
  todo "would write $UDEV_RULE for Samsung vendor $SAMSUNG_VENDOR_ID"
else
  echo "    writing $UDEV_RULE (needs sudo)"
  echo "SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$SAMSUNG_VENDOR_ID\", MODE=\"0666\", GROUP=\"plugdev\"" \
    | sudo tee "$UDEV_RULE" >/dev/null
  sudo udevadm control --reload-rules
  sudo udevadm trigger
  ok "rule installed — reconnect the tablet and accept the RSA prompt on screen"
fi

# --- 5. Python pipeline ----------------------------------------------------
step "Python pipeline"
if ! need_cmd uv; then
  if $CHECK_ONLY; then
    todo "uv not found — would need: curl -LsSf https://astral.sh/uv/install.sh | sh"
  else
    die "uv not found. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
  fi
elif $CHECK_ONLY; then
  [[ -d "$REPO_ROOT/tools/.venv" ]] && ok "tools/.venv exists" || todo "would create tools/.venv"
else
  uv venv "$REPO_ROOT/tools/.venv" --python "$PYTHON_VERSION" >/dev/null
  uv pip install --python "$REPO_ROOT/tools/.venv/bin/python" -q -e "$REPO_ROOT/tools[dev]"
  ok "tools/.venv ready"
fi

# --- 6. Verify -------------------------------------------------------------
step "Verify"
$CHECK_ONLY && { echo; echo "check only — nothing was changed."; exit 0; }

export ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="$SDK_ROOT/platform-tools:$PATH"

need_cmd adb && ok "$(adb version | head -1)" || warn "adb not on PATH"

if (cd "$REPO_ROOT/tools" && .venv/bin/python -m pytest -q >/dev/null 2>&1); then
  ok "pipeline tests pass"
else
  warn "pipeline tests failed — run: cd tools && .venv/bin/python -m pytest"
fi

echo "    building the app (first run downloads Gradle, this takes a while)"
if (cd "$REPO_ROOT" && ./gradlew --quiet :app:testDebugUnitTest 2>&1 | tail -20); then
  ok "app unit tests pass"
else
  warn "app build/test failed — this code has never been compiled, so expect real errors here"
fi

cat <<'EOM'

Done. Add these to your shell profile so adb and the SDK stay on PATH:

    export ANDROID_SDK_ROOT="$HOME/Android/Sdk"
    export PATH="$ANDROID_SDK_ROOT/platform-tools:$PATH"

Next: plug in the tablet, run `adb devices`, and accept the prompt on screen.
EOM
