# Working content

Not tracked by git — see `.gitignore`.

- `source/` — mirror of the `Dress me up` folder in Google Drive, pulled by
  `scripts/fetch-drive-content.sh`. Subfolders `Fantasy` (9 PDFs), `Fantasy w
  Boy` (8), `Knight` (1), each also holding raw JPG captures of the same pages.
  Drive is the backup; this is a working copy.
- `pdfs/` — whichever scans were selected to feed the pipeline.
- `sidecars/` — one PNG cutout plus one `.sidecar.json` per extracted item,
  written by `tools/extract_pdf.py` and annotated in place by
  `tools/classify_and_qa.py`.

Only `tools/build_catalog.py` output reaches the app, under
`app/src/main/assets/`. Everything here is regenerable from the PDFs.
