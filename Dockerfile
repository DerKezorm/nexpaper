# nexpaper as a single container.
#
# Two stages: the interface is built first, then only the finished files go into the image. Node and
# node_modules stay out; at runtime FastAPI serves the built files itself.

# --- Stage 1: build the interface ------------------------------------------------------------------
#
# --platform=$BUILDPLATFORM: the image is built for amd64 and arm64. Without it this stage would run under
# emulation too, and "npm ci" under emulated ARM is very slow. Only /build/dist moves on from here.
FROM --platform=$BUILDPLATFORM node:22-alpine AS interface

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- Stage 2: runtime ------------------------------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXPAPER_DATA_DIR=/data \
    NEXPAPER_FRONTEND_DIST=/app/static

WORKDIR /app

# curl for the healthcheck, gosu to drop root at start. Tesseract reads the text of scans (through ocrmypdf), with the
# six languages the settings offer: all of them are in the image, nothing is loaded at run time. No Ghostscript:
# ocrmypdf draws the pages with PDFium and writes a plain searchable PDF (no PDF/A), which needs none.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gosu \
        tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-nld tesseract-ocr-pol \
        tesseract-ocr-tur \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=interface /build/dist ./static

# The user nexpaper runs as. The container starts as root and drops the rights in the entrypoint. The code and the
# interface stay root's: whoever got to run something as nexpaper could otherwise change what every browser loads.
RUN useradd --system --create-home --uid 1000 nexpaper \
    && mkdir -p /data \
    && chown -R nexpaper:nexpaper /data

COPY docker/entrypoint.sh /entrypoint.sh
# Strips Windows line endings: checked out on Windows the script would not start otherwise.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${NEXPAPER_PORT:-8000}/api/v1/health" || exit 1

# One worker: SQLite, and the sign-in brake and the second factor's waiting sign-ins live in this process.
ENTRYPOINT ["/entrypoint.sh"]
# No --forwarded-allow-ips "*": which proxies may speak for a sender is decided inside the app
# (NEXPAPER_TRUSTED_PROXIES), so that nobody can dodge the sign-in brake with a made-up X-Forwarded-For.
# No access log: nexpaper logs each request itself, with tokens in paths masked; uvicorn's lines would carry them.
# No "server: uvicorn" header: it tells a scanner what to try, and nobody else needs it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--workers", "1", "--no-proxy-headers", "--no-access-log", "--no-server-header"]
