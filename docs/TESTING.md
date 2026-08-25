# Testing — Dress-me-up

*Recovered from a Claude Code feedback memory captured on the original
Windows machine.*

## Rule

Test on a **physical Galaxy Tab S6 Lite over `adb`**, never the emulator.

**Why:** the Android emulator did not work reliably on the original Windows
machine, across previous attempts. A `Medium_Tablet` AVD and tablet system
images existed on disk but were never actually used for this project — the
project owner tests on hardware.

## How to apply

1. Build a debug APK: `./gradlew assembleDebug`.
2. Connect the tablet with USB debugging enabled, then `adb install -r
   app/build/outputs/apk/debug/app-debug.apk` (path will vary once the
   project is scaffolded).
3. There is no local UI feedback loop without the tablet connected — batch
   UI work between device sessions rather than expecting per-change
   on-screen verification.

## New on Ubuntu (not a concern on the original Windows setup)

`scripts/setup-ubuntu.sh` installs this rule for you; the rest of this section is
what it does and why, for when it needs adjusting.

`adb devices` may show the tablet as `unauthorized`, or not list it at all,
until a udev rule exists for the vendor ID. If so:

```bash
# /etc/udev/rules.d/51-android.udev.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="04e8", MODE="0666", GROUP="plugdev"
# 04e8 is Samsung's USB vendor ID — the Tab S6 Lite is a Samsung device
```

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Reconnect the tablet and accept the USB-debugging RSA key prompt on the
tablet screen when it appears.
