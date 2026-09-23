# Transcript Converter

Converts oral history transcript PDFs to clean plain text. Handles multi-column layouts and tables common in oral history transcripts.

Available two ways: a **web app** for staff (upload one or many PDFs, download `.txt` files or a `.zip`), and the original **command-line script**.

## Web app

`webapp.py` (Flask) serves a single page plus a JSON API. The conversion logic lives entirely in `convert.py`.

| Route | Purpose |
|---|---|
| `GET /` | Upload page |
| `POST /api/convert` | Multipart form: `file` (PDF), optional `strip_timestamps`, `reflow`, `remove_front_matter` (`1`/`0`). Returns `{"text": "...", "notes": [...]}` or `{"error": "..."}` |
| `GET /healthz` | Health check |

The browser sends each file as its own request (two at a time), so every file gets its own status and one bad PDF doesn't hold up the others. The `.zip` of all results is assembled in the browser, which keeps the server stateless: nothing is written to disk.

### Run in Docker

```bash
docker build -t transcript-converter .
docker run --rm -p 8000:8000 transcript-converter
# open http://localhost:8000
```

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_MB` | `50` | Largest accepted PDF |
| `WEB_WORKERS` | `2` | Gunicorn worker processes (conversion is CPU-bound) |
| `WEB_TIMEOUT` | `300` | Seconds before a stuck conversion's worker is recycled |
| `TRUSTED_PROXY_HOPS` | `1` | Proxies whose `X-Forwarded-*` headers are trusted; `0` if exposed directly |

### Hosting at a sub-path

The app always serves from `/` inside the container. To mount it at e.g. `/transcripts/`, the reverse proxy should strip that prefix and send `X-Forwarded-Prefix: /transcripts`; every URL on the page is then generated with the prefix.

### Run locally without Docker

```bash
pip install -r requirements.txt
python webapp.py    # http://localhost:8000, with auto-reload
```

## Command line

### Setup

```bash
pip install -r requirements.txt
```

### Usage

```bash
python convert.py [input] [--output-dir OUTPUT_DIR]
```

`input` can be either a single PDF file or a folder containing PDFs.

**Convert a single PDF:**
```bash
python convert.py document.pdf
```

**Convert all PDFs in the current directory:**
```bash
python convert.py
```

**Convert all PDFs in a specific folder:**
```bash
python convert.py /path/to/pdfs
```

**Write output files to a different folder:**
```bash
python convert.py /path/to/pdfs --output-dir /path/to/output
python convert.py document.pdf --output-dir /path/to/output
```

**Keep the opening metadata block and Abstract:**
```bash
python convert.py document.pdf --keep-front-matter
```

### Output

Each PDF produces a `.txt` file with the same base name (e.g. `alston-legacy.pdf` → `alston-legacy.txt`). By default the `.txt` file is written alongside the PDF. Use `--output-dir` to collect all output in one place.


### How It Works

- **Tables** are extracted and rendered as `cell | cell` rows before the surrounding text.
- **Multi-column text** is detected by finding horizontal gaps between words. Columns are read left-to-right, each top-to-bottom, so the output reads naturally even when the source PDF uses a two-column layout.
- **Single-column pages** are passed through as-is.
- **Front matter** — the opening metadata block (title, `Interviewee:`, `Date of Interview:`, accession ID, etc.) and any Abstract — is removed by default, so output begins at the first spoken turn. The block is only dropped when a transcript-start marker (`Begin Interview`, `Begin Recording`, `Transcript Tape 1, Side A`, …) follows a genuine metadata block, so transcripts that open directly on dialogue are left untouched. Pass `--keep-front-matter` to retain it.
