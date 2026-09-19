# Working content

Not tracked by git — see `.gitignore`.

- `source/` — mirror of the `Dress me up` folder in Google Drive, pulled by
  `scripts/fetch-drive-content.sh`. Subfolders `Fantasy` (9 PDFs), `Fantasy w
  Boy` (8), `Knight` (1), each also holding raw JPG captures of the same pages.
  Drive is the backup; this is a working copy.
- `pdfs/` — a scratch drop for PDFs that are not part of a `source/` set: the
  synthetic `fantasy-smoke.pdf` from `tools/make_smoke_pdf.py`, or a one-off
  hand-named scan. The pipeline normally runs straight off `source/<Set>/*.pdf`,
  because the classifier takes an item's group from the containing folder first
  and the timestamp filenames carry nothing; a PDF here only classifies if its
  own name says which theme it is.
- `triage/` — per-PDF page manifests (`<stem>.json`: rotation and page-type
  verdict per page), hand-written overrides (`<stem>.overrides.json`) and one
  contact sheet per verdict (`<stem>.<verdict>.png`), written by
  `tools/triage_pages.py`. `tools/extract_pdf.py --triage` reads the manifests.
- `sidecars/` — one PNG cutout plus one `.sidecar.json` per extracted item,
  written by `tools/extract_pdf.py` and annotated in place by
  `tools/classify_and_qa.py`.

Only `tools/build_catalog.py` output reaches the app, under
`app/src/main/assets/`. Everything here is regenerable from the PDFs.
