# Corrections — the labels the catalogue actually trusts

One file per source PDF, `<pdf-stem>.corrections.json`, holding a person's verdict
on each cutout extracted from that PDF. `dressup_pipeline/corrections.py` reads
and writes them, and the catalogue build is to accept no category that is not in
here.

The pipeline's classifier still writes `category` and `group` onto every sidecar,
but on this corpus that is a *suggestion* and not much better than a guess — it
reasons from where an item sits on the page, and these books lay items out to fill
paper. A file in this directory is the part a human confirmed.

## Why these files are tracked in git

Because the judgement in them is not repeatable. Labelling the corpus is roughly
half an hour of looking at cutouts and deciding, and there is no way to derive it
again from the scans. The scans themselves are regenerable and live under
`content/`, which `.gitignore` ignores but for its README — so a tracked file
cannot sit beside the corpus, and these live here instead.
`../base_bodies.json` is the same idea: hand-authored JSON, tracked, under
`tools/`.

The records carry geometry and a verdict — no image data, no absolute paths,
nothing identifying this machine. Keep it that way.

## What a record says

```json
{
  "corrections": [
    {
      "source_pdf": "20260509081050",
      "page": 0,
      "bbox": { "x": 1371, "y": 79, "w": 374, "h": 165 },
      "page_width": 2480,
      "page_height": 3507,
      "dpi": 300,
      "category": "bottom",
      "rejection": null
    }
  ]
}
```

Either `category` names the slot it was filed under or `rejection` says why it is
not an item (`bad_crop`, `multi_item`, `not_an_item`) — exactly one of the two. A
cutout holding two items that works as one item is *filed*, with a category, like
anything else; `multi_item` is for the ones that need cutting apart later.

An item is identified by the PDF stem plus its geometry, never by its `item_id`
(KTD2): ids are positional, so a re-extraction that loses one cutout renumbers
every id after it. The five geometry fields are not unique on their own —
`20260509081050` and `20260509081623` are two scans of one physical page and share
byte-identical boxes — which is why the stem is part of the identity and why each
record repeats it even though the filename already says it.

The trade is that a cutout which moves by a pixel is a different item. Its old
correction is kept and reported as unmatched rather than dropped, so the work is
never lost quietly; re-label the item it became.

Records are written sorted by that identity, so a labelling pass shows up in a
diff as the verdicts that changed rather than as the whole file.
