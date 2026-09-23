"""
webapp.py — Web front end for convert.py.

Serves a single upload page and a JSON conversion endpoint. The app always
serves from ``/`` inside its container; when a reverse proxy mounts it at a
sub-path (e.g. ``/transcripts/``), the proxy strips that prefix and sends it in
the ``X-Forwarded-Prefix`` header so generated URLs include it.

Configuration (environment variables):
    MAX_UPLOAD_MB       Largest accepted PDF, in megabytes (default: 50)
    TRUSTED_PROXY_HOPS  Number of proxies whose X-Forwarded-* headers are
                        trusted (default: 1; set 0 when not behind a proxy)
"""

import io
import logging
import os

from flask import Flask, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from convert import pdf_to_text

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))

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

log = logging.getLogger("transcript-converter")


def _flag(name, default):
    """Read a boolean form field ("1"/"true"/"on" are true)."""
    value = request.form.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "on", "yes")


def _error(message, status):
    return jsonify({"error": message}), status


@app.get("/")
def index():
    return render_template("index.html", max_upload_mb=MAX_UPLOAD_MB)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/convert")
def convert():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return _error("No file was uploaded.", 400)
    if not upload.filename.lower().endswith(".pdf"):
        return _error("Only PDF files can be converted.", 400)

    data = upload.read()
    if not data.startswith(b"%PDF"):
        return _error("This file does not appear to be a valid PDF.", 400)

    try:
        text, notes = pdf_to_text(
            io.BytesIO(data),
            strip_timestamps=_flag("strip_timestamps", False),
            reflow=_flag("reflow", True),
            remove_front_matter=_flag("remove_front_matter", True),
        )
    except Exception:
        log.exception("Conversion failed for %s", upload.filename)
        return _error("The PDF could not be read. It may be damaged, "
                      "password-protected, or a scanned image with no text.", 422)

    if not text.strip():
        notes.append("No text was found. If this is a scanned document, "
                     "it needs OCR before it can be converted.")

    return jsonify({"text": text, "notes": notes})


@app.errorhandler(413)
def too_large(_):
    return _error(f"File is larger than the {MAX_UPLOAD_MB} MB limit.", 413)


if __name__ == "__main__":
    app.run(debug=True, port=8000)
