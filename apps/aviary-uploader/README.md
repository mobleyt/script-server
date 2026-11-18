# Aviary Uploader

Batch-create resources in an [Aviary](https://www.aviaryplatform.com) collection from a metadata spreadsheet. Each row becomes one resource. Any media URLs in the row are attached as media files, and Aviary downloads them itself, so no media passes through this server.

In the deployed stack it's served at `/aviary/`, behind a username and password (see the top-level README).

## Using it

1. **Choose a collection.** The list is loaded live from Aviary.
2. **Add a spreadsheet** (.csv or .xlsx; only the first sheet is read). Every row is checked, and problems are listed before anything is sent to Aviary.
3. **Upload.** Rows are sent one at a time, and each one shows its result and a link to the new resource. **Stop** halts after the current row.
4. **Download results (.csv)** lists the outcome, resource ID and URL for every row.

### Spreadsheet format

The first row holds the headers. The page links to a starter file (`template.csv`).

| Column | Notes |
|---|---|
| `Title` | Required |
| `Access` | `public`, `private`, `restricted` or `internal`. If blank, `AVIARY_DEFAULT_ACCESS` is used |
| `Custom Unique Identifier` | Optional. If a resource with this identifier already exists, the row is **skipped**, so a partly finished file can be re-run safely. It must be unique within the file |
| `Featured` | Optional: `yes`/`no` |
| `Media URL`, `Media URL 2`, … | Any header starting with "Media URL". Each value must be an http(s) link Aviary can download (public, or a Dropbox/Box-style share link) |
| anything else | An Aviary metadata field, named as it appears in Aviary (e.g. `Description`, `Rights Statement`). `Field (Vocabulary)` also sets the vocabulary term, e.g. `Agent (Creator)` or `Date (Created)` |

**Several values in one cell:** separate them with `|` (set by `MULTI_VALUE_DELIMITER`). For example, `Smith, Jane | Doe, John` in an `Agent (Creator)` column creates two Agent values, and both get the vocabulary *Creator*. Spaces around the delimiter and empty pieces are ignored. This works for media URL cells too. A field may also be repeated across columns, so for values that need different vocabularies, use `Agent (Creator)` and `Agent (Contributor)` columns. There is no way to escape the delimiter, so if your values contain `|`, choose a different delimiter in `.env`.

Blank cells and blank rows are ignored.

### Results

| Status | Meaning |
|---|---|
| Created | The resource was created and every media link was accepted. Aviary then downloads and transcodes the media in the background |
| Created · N media failed | The resource exists, but Aviary rejected some media links. Add them in Aviary by hand, or delete the resource and re-run the row |
| Skipped | A resource with that Custom Unique Identifier already exists |
| Failed | Nothing was created for that row. **Retry** sends only the failed rows again |

## Routes

| Route | Purpose |
|---|---|
| `GET /` | The upload page |
| `GET /template.csv` | Example spreadsheet |
| `GET /api/collections` | `{"collections": [{id, title}]}` |
| `POST /api/parse` | Multipart field `file`. Returns `{"rows": [...]}` with per-row `errors` and creates nothing |
| `POST /api/resources` | JSON `{collection_id, row}`, one parsed row. Returns `{status, resource_id, url, media: [{url, id \| error}]}` |
| `GET /healthz` | Health check (does not call Aviary) |

## Configuration

| Variable | Default | |
|---|---|---|
| `AVIARY_API_KEY` | — | **Required.** API key of the Aviary user the app acts as ([creating an API key](https://coda.aviaryplatform.com/edit-user-profile-83#_luHGN)). Resources it creates are attributed to that user |
| `AVIARY_ORG_ID` | — | **Required.** Numeric organization ID (see below) |
| `AVIARY_BASE_URL` | `https://www.aviaryplatform.com` | API host |
| `AVIARY_DEFAULT_ACCESS` | `private` | Access for rows with a blank Access cell |
| `MULTI_VALUE_DELIMITER` | `\|` | Separates several values in one cell |
| `MAX_UPLOAD_MB` | `10` | Largest spreadsheet accepted |
| `MAX_ROWS` | `500` | Most rows accepted per file |
| `WEB_WORKERS` / `WEB_THREADS` / `WEB_TIMEOUT` | `2` / `4` / `300` | Gunicorn |
| `TRUSTED_PROXY_HOPS` | `1` | |

To find the organization ID, call the sign-in endpoint with the key. The response lists the user's organizations with their IDs:

```bash
curl -s -X POST -H "Authorization: $AVIARY_API_KEY" https://www.aviaryplatform.com/api/v1/auth/sign_in
```

Unlike the other apps, this container needs outbound internet access to reach Aviary, so in `compose.yaml` it is also attached to the `egress` network.

```bash
# Run just this app locally
pip install -r requirements.txt
AVIARY_API_KEY=... AVIARY_ORG_ID=... TRUSTED_PROXY_HOPS=0 python webapp.py   # http://localhost:8000

# Check how a spreadsheet will be read, without touching Aviary
python sheet.py my-metadata.csv
```
