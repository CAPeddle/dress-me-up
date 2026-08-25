# Working content

Not tracked by git — see `.gitignore`.

- `pdfs/` — scanned sticker-book PDFs. The source material. Back these up
  somewhere other than a single machine.
- `sidecars/` — one PNG cutout plus one `.sidecar.json` per extracted item,
  written by `tools/extract_pdf.py` and annotated in place by
  `tools/classify_and_qa.py`.

Only `tools/build_catalog.py` output reaches the app, under
`app/src/main/assets/`. Everything here is regenerable from the PDFs.
