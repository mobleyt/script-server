"""
webapp.py — Web front end for reformat_transcripts.py.

Serves a single upload page and an endpoint that returns the reformatted .docx.
The app always serves from ``/`` inside its container; when a reverse proxy
mounts it at a sub-path (e.g. ``/rev/``), the proxy strips that prefix and sends
it in the ``X-Forwarded-Prefix`` header so generated URLs include it.

Configuration (environment variables):
    MAX_UPLOAD_MB       Largest accepted .docx, in megabytes (default: 50)
    TRUSTED_PROXY_HOPS  Number of proxies whose X-Forwarded-* headers are
                        trusted (default: 1; set 0 when not behind a proxy)
"""

import logging
import os

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from reformat_transcripts import reformat_docx_bytes

DOCX_MIMETYPE = ("application/vnd.openxmlformats-officedocument."
                 "wordprocessingml.document")

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

log = logging.getLogger("rev-converter")


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
    if not upload.filename.lower().endswith(".docx"):
        return _error("Only Word .docx files can be reformatted.", 400)

    try:
        new_docx, changes = reformat_docx_bytes(upload.read())
    except ValueError as e:
        return _error(f"This file could not be reformatted: {e}.", 422)
    except Exception:
        log.exception("Reformat failed for %s", upload.filename)
        return _error("This file could not be read. Check that it opens "
                      "correctly in Word, then try again.", 422)

    # The count travels in a header so the body can be the .docx itself.
    return Response(new_docx, mimetype=DOCX_MIMETYPE,
                    headers={"X-Reformatted-Count": str(changes)})


@app.errorhandler(413)
def too_large(_):
    return _error(f"File is larger than the {MAX_UPLOAD_MB} MB limit.", 413)


if __name__ == "__main__":
    app.run(debug=True, port=8000)
