# syntax=docker/dockerfile:1

# ---- builder: resolve and install dependencies into a venv -----------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY reweave/ reweave/

# Editable install: the `reweave` console script and dependencies land in
# /opt/venv, while the import resolves to /app/reweave. server.py derives
# REPO_ROOT from the package location, so dashboard/ and demo/ must be
# siblings of the package — keeping the source at /app preserves that layout.
RUN pip install -e .

# ---- runtime ---------------------------------------------------------------
FROM python:3.12-slim

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    REWEAVE_DB=/data/reweave.db

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Repo layout the server expects: dashboard/ and demo/ next to reweave/.
COPY pyproject.toml README.md LICENSE ./
COPY reweave/ reweave/
COPY demo/ demo/
COPY dashboard/ dashboard/
COPY skills/ skills/
COPY harness/ harness/

RUN groupadd -r reweave \
    && useradd -r -g reweave -d /app -s /usr/sbin/nologin reweave \
    && mkdir -p /data \
    && chown reweave:reweave /data

USER reweave

VOLUME ["/data"]
EXPOSE 8321

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8321/api/health', timeout=4).status == 200 else 1)"]

CMD ["reweave", "serve", "--host", "0.0.0.0"]
