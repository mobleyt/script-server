# Oral History Transcript Reformatter

This script reformats oral history interview transcripts by swapping the order of speaker names and timestamps.

## What It Does

**Before:**
```
Brandon Fish (00:00:02):
This is what Brandon said...

(00:00:35):
Brandon continues speaking...

Millicent Brown (00:01:00):
Now Millicent speaks...
```

**After:**
```
00:00:02 BRANDON FISH
This is what Brandon said...

00:00:35 BRANDON FISH
Brandon continues speaking...

00:01:00 MILLICENT BROWN
Now Millicent speaks...
```

The script:
- Removes parentheses around timestamps
- Swaps the order so timestamp comes first
- **Converts all speaker names to UPPERCASE**
- **Removes the trailing colon**
- Preserves hyperlinks on timestamps
- **Automatically adds speaker names to continuation timestamps** (timestamps without names)
- **Supports both timestamp formats**: `HH:MM:SS` (e.g., 00:01:30) and `MM:SS` (e.g., 01:30)
- Maintains all other formatting

## Web app

`webapp.py` (Flask) serves an upload page at `/rev/` in the deployed stack (see the top-level README). Staff drop in one or more `.docx` files, click **Reformat**, and download each result as `<name>_reformatted.docx` or all of them together as a `.zip`. Every file shows how many speaker entries were changed, and a file with no matching lines is flagged instead of failing silently.

| Route | Purpose |
|---|---|
| `GET /` | Upload page |
| `POST /api/convert` | Multipart form field `file` (.docx). Returns the reformatted .docx, with the number of changes in the `X-Reformatted-Count` header, or `{"error": "..."}` |
| `GET /healthz` | Health check |

Documents are processed entirely in memory, and nothing is written to disk.

Environment variables: `MAX_UPLOAD_MB` (default `50`), `WEB_WORKERS` (`2`), `WEB_TIMEOUT` (`300`), `TRUSTED_PROXY_HOPS` (`1`).

```bash
# Run just this app locally
pip install -r requirements.txt
python webapp.py            # http://localhost:8000

# Or in Docker
docker build -t rev-converter .
docker run --rm -p 8000:8000 rev-converter
```

## Command line

### Requirements

- Python 3.x (tested with Python 3.6+)
- No additional packages needed for the command-line script, which uses only the Python standard library (the web app adds Flask and Gunicorn)

### Usage

#### Process a Single File

```bash
python reformat_transcripts.py input_file.docx output_file.docx
```

Example:
```bash
python reformat_transcripts.py "Brandon_Fish_Interview.docx" "Brandon_Fish_Interview_Reformatted.docx"
```

#### Process Multiple Files in a Directory

```bash
python reformat_transcripts.py input_directory/ output_directory/
```

Example:
```bash
python reformat_transcripts.py ./raw_transcripts/ ./reformatted_transcripts/
```

This will process all `.docx` files in the input directory and save reformatted versions with the same filenames to the output directory.

## How It Works

1. **Opens** the Word document (a zip archive) in memory and reads its internal XML
2. **Identifies** speaker name and timestamp patterns in the document
3. **Tracks speakers** to handle continuation timestamps (timestamps without names)
4. **Reformats** each occurrence by:
   - Extracting the speaker name and timestamp
   - For continuation timestamps, using the last speaker's name
   - Rebuilding the paragraph with timestamp first, then speaker name
   - Preserving the hyperlink on the timestamp
5. **Repacks** the Word document with the changes, keeping every other part as it was
6. **Saves** the reformatted document to the specified output location

## Command-line output

The script reports:
- Which file is being processed
- How many speaker entries were found and reformatted
- Where the output file was saved
- Summary statistics when processing multiple files

Example output:
```
Processing: /path/to/Brandon_Fish_Interview.docx
  Unpacking document...
  Finding and reformatting speaker/timestamp patterns...
  Successfully reformatted 79 speaker entries
  Packing document...
  Saved to: /path/to/output.docx
```

## Notes

- The script preserves all hyperlinks on timestamps
- All other document formatting remains unchanged
- The script only modifies paragraphs that match the speaker/timestamp pattern
- Documents are processed in memory, with no temporary files
- **Both timestamp formats are supported**: Files with `HH:MM:SS` (00:01:30) or `MM:SS` (01:30) timestamps will both work correctly

## Troubleshooting

If you encounter errors:

1. **"Error unpacking"** - Make sure the input file is a valid .docx file (not .doc or other format)
2. **"No .docx files found"** - Check that your input directory contains .docx files
3. **Permission errors** - Ensure you have write permissions to the output location
4. **"Error processing document"** - The document may have an unusual structure; check if it opens correctly in Word

## Example Files

- `example_reformatted_transcript.docx` - Sample with full `HH:MM:SS` timestamps (Brandon Fish interview)
- `example_reformatted_transcript_short_timestamps.docx` - Sample with short `MM:SS` timestamps (Melissa Moore interview)
