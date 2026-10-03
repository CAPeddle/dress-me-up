# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Relationships

Scans decompose into Pages, each of which has a Page Type. Only Item Sheets yield
Items. Every extracted Item carries exactly one Sidecar, and the Sidecars that pass
QA become entries in the Catalog. The Catalog and the Characters definition meet at
Category: an Item names the Category it belongs to, a Snap Point names the Category
it accepts, and placement is the act of matching them.

## The scan pipeline

### Page Type
What a scanned page is *for*, which decides whether anything on it is worth
extracting. The distinction exists because a sticker book is not a uniform sheet of
merchandise: it interleaves the dolls, the things you dress them in, and artwork that
merely shows the result. Only one of the three yields catalog content.

### Base Body
A page whose subject is a paper doll in underwear, drawn full length against a
decorative background. It is the figure other things are placed *onto*, never a
source of Items. Its second use is as the reference image a human reads Snap Points
off.
*Also heard as:* mannequin — the family's word for it; the same thing.

### Item Sheet
A page of loose cut-outs — garments, headwear, weapons, Companions — intended to be
separated and applied to a Base Body. The only Page Type the extractor opens.

### Illustration Plate
A page showing fully-dressed characters posed together, as inspiration rather than
material. Visually it resembles an Item Sheet, and mistaking one for the other is the
expensive direction of error: it feeds uncuttable artwork into the Catalog.

### Floating Region
A region of ink that does not reach the edge of the scanned area. The distinction
matters because page decoration bleeds off the paper while genuine cut-outs sit in
white space, so floating-ness is a proxy for cuttability. It is only a proxy: items
printed in contact with each other merge into one region, and how much white space a
printer leaves is a per-book decision.

### Sidecar
The record of everything known about one extracted Item, stored beside its image.
*Avoid:* manifest entry

A Sidecar accumulates rather than being rewritten: extraction establishes it,
classification adds the Item's Category and Group, quality assessment adds a score
and a verdict, and the Catalog build only reads. Because no stage overwrites an
earlier stage's fields, a partially processed set is still valid, any single stage can
be re-run alone, and a rejected Item can always account for its own rejection.

### Group
The theme an Item belongs to, inherited from the book it was scanned out of rather
than from anything visible in the Item itself. Scanner output is named by timestamp,
so the containing folder is normally the only surviving evidence of theme.

## The catalog contract

### Catalog
The generated inventory of accepted Items that the app reads, together with their
downsampled images. It is the sole interface between the offline pipeline and the
app: nothing else crosses, and everything in it is reproducible from the scans.

### Category
The kind of slot an Item occupies — headwear, footwear, a weapon, and so on. Category
is the matching key between the two halves of the system: an Item declares the
Category it is, a Snap Point declares the Category it accepts, and an Item can only
lock onto a Snap Point that names its own Category.

### Companion
A creature Item — a bird, a squirrel, a teddy, a jellyfish — placed on a character
rather than worn by it. Distinct from a mount, which is ridden: the books scanned so
far contain only Companions, and `mount` is held for a rideable a Dragon book may yet
supply.

### Correction
A human verdict about one Item that supersedes what the classifier guessed: the
Category it actually belongs to, or a rejection saying the cut-out is unusable or is
not dress-up material at all. Corrections are the Catalog's only source of Category —
the classifier's output is a suggestion that orders the review and nothing more. A
Correction names its Item by the same geometry a re-extraction uses to recognise it,
not by the Item's positional id, so re-cutting a page cannot silently reattach a
label to the wrong cut-out.

### Snap Point
A position on a Base Body where an Item of a stated Category belongs, expressed
relative to the image rather than in pixels so it holds at any display size. A Snap
Point marks where the centre of a placed Item sits, not its corner.

Snap Points are authored by eye against a real Base Body; nothing derives them. A
Category with no Snap Point on a given character is not an error — Items of that
Category are simply placed freely instead of locking.

## The web version

### Hand
The set of Items the child has picked up but not yet placed, shown as a strip on
screen. It stands in for the paper habit of stacking a few stickers on her fingers
while paging through the mannequins. Items enter it by a tap on the supply and leave
it one at a time by a tap on a Base Body, and it survives paging between bodies.

### Page Triage
The stage that decides, per scanned page, its rotation and its Page Type before
anything is extracted, and records those verdicts in a manifest a human confirms.
Accepted Item Sheet verdicts are trusted; every other verdict is confirmed by eye,
because the classifier's rejections are the unreliable direction.

### Plain Build
The web version of the game as static files and client-side state, with no
recording code, no collector endpoint, and no rig fingerprint in it. It is the
form that could later be bundled offline with no permissions, and the boundary
check must pass against it.

### Playtest Build
A Plain Build with the recording layer added and served by the collector for one
observed session. The only form in which anything about the child's play is
recorded, and it is governed by the playtest rig's boundary document. Never the
form she plays unsupervised.

## Flagged ambiguities

- "Item" refers to a single cut-out throughout — a garment, a helm, a mount. It is
  never used for a whole Item Sheet, and never for a Base Body.
