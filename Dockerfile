# syntax=docker/dockerfile:1
# MoSPI survey data validation workspace (PLFS) — one image for the review
# server and, optionally, the batch pipeline.  Survey data is never baked in:
# stored runs are mounted at /data (see docker-compose.yml and docs/deployment/DOCKER.md).

FROM python:3.11.9-slim-bookworm AS runtime

# Git commit of the source the image was built from (plan W0.5); reported by /healthz.
ARG MOSPI_CODE_VERSION=unknown
LABEL org.opencontainers.image.revision=$MOSPI_CODE_VERSION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
# Optional build secret "extra_ca": the CA of a TLS-inspecting proxy/antivirus on
# the build machine.  It is used for this pip step only and is never written to
# an image layer.  Without it, the standard certificate store is used.
RUN --mount=type=secret,id=extra_ca     if [ -s /run/secrets/extra_ca ]; then         cat "$(python -c 'import certifi; print(certifi.where())' 2>/dev/null || echo /etc/ssl/certs/ca-certificates.crt)" /run/secrets/extra_ca > /tmp/build-ca.pem         && export PIP_CERT=/tmp/build-ca.pem;     fi     && pip install --no-cache-dir -r requirements.txt     && rm -f /tmp/build-ca.pem

# Application packages only (raw data, runs, notebooks and media are excluded by .dockerignore).
COPY mospi/ mospi/
COPY scripts/ scripts/

# Unprivileged runtime user; /data is supplied by bind mounts.
RUN groupadd --gid 10001 mospi && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin mospi \
    && mkdir -p /data && chown mospi:mospi /data
USER 10001:10001

ENV HOME=/tmp \
    MOSPI_CONTAINER=1 \
    MOSPI_HOST=0.0.0.0 \
    MOSPI_PORT=8000 \
    MOSPI_FUSION_ROOT=/data/fusion/runs \
    MOSPI_PROJECT_ROOT=/data     MOSPI_CODE_VERSION=$MOSPI_CODE_VERSION

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=8).status == 200 else 1)"

CMD ["python", "-m", "mospi.app.serve"]


# Test image: the same code plus pytest (docker compose --profile test run --rm tests).
FROM runtime AS test
USER root
COPY requirements-dev.txt pyproject.toml conftest.py ./
COPY tests/ tests/
RUN --mount=type=secret,id=extra_ca     if [ -s /run/secrets/extra_ca ]; then         cat "$(python -c 'import certifi; print(certifi.where())' 2>/dev/null || echo /etc/ssl/certs/ca-certificates.crt)" /run/secrets/extra_ca > /tmp/build-ca.pem         && export PIP_CERT=/tmp/build-ca.pem;     fi     && pip install --no-cache-dir -r requirements-dev.txt     && rm -f /tmp/build-ca.pem
USER 10001:10001
ENV HOME=/tmp
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
