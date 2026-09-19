# What is in this directory

`catalog.json`, `items/`, `bodies.json` and `bodies/` are **generated** by the
pipeline (`tools/build_catalog.py`) and are not tracked, so a fresh clone has
none of them until the pipeline has run. Every content build rewrites them at
that build's shared scale.

`characters.json` and `characters/` are hand-authored and tracked. They are what
the rest of this file is about.

# Authoring `characters.json`

The catalog is generated. **This file is not** — snap points have to be placed by
eye against a real base body, and that is the one manual step between a compiling
app and a playable one.

The values checked in now are a **placeholder**: a symmetric guess against a body
image that does not exist yet. They are enough to exercise drag, snap, and remove
mechanics; they are not enough to look right.

## Coordinate system

- `x` and `y` are normalized **0..1** against the base image, not pixels. `0,0`
  is the top-left of the image; `1,1` the bottom-right.
- A snap point marks the **centre** of the item that lands on it, not its corner.
- Items draw at `ITEM_WIDTH_FRACTION` (0.28) of the canvas width — see
  `ui/CharacterCanvas.kt`. Account for that when judging where a centre should sit.

## Doing it properly

1. Pick a base body from the extracted content and save it as
   `app/src/main/assets/characters/<id>.png`. It must be a full body, facing
   forward, with limbs clear of the torso so overlays do not fight the outline.
2. Open it in any editor that reports cursor position, and note the pixel
   coordinate where each item's centre belongs.
3. Divide by the image width/height to normalize. A point at (612, 240) on a
   1224x2000 image is `x: 0.500, y: 0.120`.
4. One point per category the character supports. A category with no point is not
   an error — items of that category free-place instead of snapping.
5. Rebuild and check on the device. `SnapCalculator` is unit-tested, so if an item
   lands wrong the arithmetic is fine and the coordinate is wrong.

## Categories

`hat`, `hair`, `top`, `bottom`, `dress`, `shoes`, `weapon`, `shield`,
`accessory`, `wings`, `mount` — defined in `tools/dressup_pipeline/models.py`.
An item only snaps to a point declaring its own category.

Two points may share a coordinate (`dress` and `top` overlap on the torso); the
category filter keeps them from competing.
