FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    WEB_WORKERS=2 \
    WEB_TIMEOUT=300

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY convert.py webapp.py ./
COPY templates ./templates
COPY static ./static

# Make app files readable by the runtime user regardless of how they were
# saved on the build host.
RUN chmod -R a+rX /app \
 && useradd --system --no-create-home appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"

# PDF parsing is CPU-bound, so scale with processes (WEB_WORKERS), not threads.
# WEB_TIMEOUT allows long transcripts to finish before a worker is recycled.
CMD exec gunicorn webapp:app \
    --bind 0.0.0.0:${PORT} \
    --workers ${WEB_WORKERS} \
    --timeout ${WEB_TIMEOUT} \
    --access-logfile -
