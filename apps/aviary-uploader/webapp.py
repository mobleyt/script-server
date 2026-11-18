"""
webapp.py — Batch-create Aviary resources from a metadata spreadsheet.

Staff pick a collection, upload a .csv/.xlsx, review the parsed rows, then the
page sends the rows one at a time to ``/api/resources``, which creates each
resource and attaches its media links. One request per row keeps requests
short and the app stateless.

The app always serves from ``/`` inside its container; when a reverse proxy
mounts it at a sub-path (e.g. ``/aviary/``), the proxy strips that prefix and
sends it in the ``X-Forwarded-Prefix`` header so generated URLs include it.

Configuration (environment variables):
    AVIARY_API_KEY          Aviary user API key (required)
    AVIARY_ORG_ID           Aviary organization ID (required)
    AVIARY_BASE_URL         API host (default: https://www.aviaryplatform.com)
    AVIARY_DEFAULT_ACCESS   Access for rows with a blank Access cell
                            (default: private)
    MULTI_VALUE_DELIMITER   Separates several values in one cell (default: |)
    MAX_UPLOAD_MB           Largest accepted spreadsheet, in megabytes (default: 10)
    MAX_ROWS                Most rows accepted in one spreadsheet (default: 500)
    TRUSTED_PROXY_HOPS      Number of proxies whose X-Forwarded-* headers are
                            trusted (default: 1; set 0 when not behind a proxy)
"""

import logging
import os

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from aviary import AviaryClient, AviaryError
from sheet import SheetError, media_title, parse_sheet, template_csv, validate_row

AVIARY_API_KEY = os.environ.get("AVIARY_API_KEY", "").strip()
AVIARY_ORG_ID = os.environ.get("AVIARY_ORG_ID", "").strip()
AVIARY_BASE_URL = os.environ.get("AVIARY_BASE_URL", "https://www.aviaryplatform.com").strip()
DEFAULT_ACCESS = os.environ.get("AVIARY_DEFAULT_ACCESS", "private").strip().lower()
DELIMITER = os.environ.get("MULTI_VALUE_DELIMITER", "|")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "10"))
MAX_ROWS = int(os.environ.get("MAX_ROWS", "500"))
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))

CONFIGURED = bool(AVIARY_API_KEY and AVIARY_ORG_ID)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
if TRUSTED_PROXY_HOPS:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUSTED_PROXY_HOPS,
        x_proto=TRUSTED_PROXY_HOPS,
        x_host=TRUSTED_PROXY_HOPS,
        x_prefix=TRUSTED_PROXY_HOPS,
    )

log = logging.getLogger("aviary-uploader")


def _error(message, status):
    return jsonify({"error": message}), status


def _client():
    return AviaryClient(AVIARY_BASE_URL, AVIARY_API_KEY, AVIARY_ORG_ID)


def _not_configured():
    return _error("The Aviary API key or organization ID isn't set on the "
                  "server. Ask the administrator to add them to .env.", 503)


@app.get("/")
def index():
    return render_template("index.html", configured=CONFIGURED,
                           max_upload_mb=MAX_UPLOAD_MB, max_rows=MAX_ROWS,
                           delimiter=DELIMITER, default_access=DEFAULT_ACCESS)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/template.csv")
def template():
    return Response(template_csv(DELIMITER), mimetype="text/csv",
                    headers={"Content-Disposition":
                             'attachment; filename="aviary-upload-template.csv"'})


@app.get("/api/collections")
def collections():
    if not CONFIGURED:
        return _not_configured()
    try:
        return jsonify({"collections": _client().list_collections()})
    except AviaryError as e:
        log.warning("Listing collections failed: %s (%s)", e.message, e.status)
        return _error(f"Couldn't load collections: {e.message}.", 502)


@app.post("/api/parse")
def parse():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return _error("No file was uploaded.", 400)
    try:
        rows = parse_sheet(upload.filename, upload.read(), delimiter=DELIMITER,
                           default_access=DEFAULT_ACCESS, max_rows=MAX_ROWS)
    except SheetError as e:
        return _error(f"{e}.", 422)
    except Exception:
        log.exception("Parsing failed for %s", upload.filename)
        return _error("This file could not be read. Check that it opens "
                      "correctly in Excel, then try again.", 422)
    return jsonify({"rows": rows})


def _clean_row(raw):
    """Rebuild a row from untrusted JSON, keeping only the expected shape."""
    if not isinstance(raw, dict):
        return None
    text = lambda v: v.strip() if isinstance(v, str) else ""
    row = {
        "row": raw.get("row"),
        "title": text(raw.get("title")),
        "access": text(raw.get("access")),
        "cuid": text(raw.get("cuid")),
        "featured": raw.get("featured") is True,
        "metadata": [],
        "media": [text(u) for u in raw.get("media") or [] if text(u)],
    }
    for entry in raw.get("metadata") or []:
        if isinstance(entry, dict) and text(entry.get("field")) and text(entry.get("value")):
            row["metadata"].append({"field": text(entry["field"]),
                                    "value": text(entry["value"]),
                                    "vocabulary": text(entry.get("vocabulary"))})
    return row


@app.post("/api/resources")
def create_resource():
    if not CONFIGURED:
        return _not_configured()
    body = request.get_json(silent=True) or {}
    try:
        collection_id = int(body.get("collection_id"))
    except (TypeError, ValueError):
        return _error("Choose a collection first.", 400)
    row = _clean_row(body.get("row"))
    if row is None:
        return _error("The row data is missing.", 400)
    errors = validate_row(row, DEFAULT_ACCESS)
    if errors:
        return _error("; ".join(errors) + ".", 422)

    client = _client()
    result = {"status": "created", "resource_id": None, "url": None, "media": []}
    try:
        if row["cuid"]:
            existing = client.find_resource_by_cuid(row["cuid"])
            if existing:
                result.update(status="skipped", resource_id=existing.get("id"),
                              url=existing.get("direct_url") or existing.get("persistent_url"),
                              message="A resource with this Custom Unique Identifier "
                                      "already exists")
                return jsonify(result)
        resource = client.create_resource(collection_id, row)
    except AviaryError as e:
        log.warning("Row %s: creating resource failed: %s (%s)", row["row"], e.message, e.status)
        return _error(f"{e.message}.", 502)

    result["resource_id"] = resource.get("id")
    result["url"] = resource.get("direct_url") or resource.get("persistent_url")
    for url in row["media"]:
        try:
            media = client.add_media_link(resource["id"], url, media_title(url))
            result["media"].append({"url": url, "id": media.get("id")})
        except AviaryError as e:
            log.warning("Row %s: media %s failed: %s (%s)", row["row"], url, e.message, e.status)
            result["media"].append({"url": url, "error": e.message})
            result["status"] = "partial"
    return jsonify(result)


@app.errorhandler(413)
def too_large(_):
    return _error(f"File is larger than the {MAX_UPLOAD_MB} MB limit.", 413)


if __name__ == "__main__":
    app.run(debug=True, port=8000)
