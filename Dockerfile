FROM python:3.12-slim

ARG TARGETARCH=amd64
ARG GITLEAKS_VERSION=8.30.1
ARG SEMGREP_VERSION=1.182.1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        tar && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Install Gitleaks 8.30.1 with SHA256 checksum verification
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64) GL_ARCH="x64" ;; \
        arm64) GL_ARCH="arm64" ;; \
        *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    TARBALL="gitleaks_${GITLEAKS_VERSION}_linux_${GL_ARCH}.tar.gz"; \
    BASE_URL="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}"; \
    curl -fsSL -o "/tmp/${TARBALL}" "${BASE_URL}/${TARBALL}"; \
    curl -fsSL -o "/tmp/gitleaks_checksums.txt" "${BASE_URL}/gitleaks_${GITLEAKS_VERSION}_checksums.txt"; \
    cd /tmp && grep "  ${TARBALL}\$" gitleaks_checksums.txt | sha256sum -c -; \
    tar -xzf "/tmp/${TARBALL}" -C /usr/local/bin gitleaks; \
    chmod 0755 /usr/local/bin/gitleaks; \
    rm -f "/tmp/${TARBALL}" /tmp/gitleaks_checksums.txt; \
    /usr/local/bin/gitleaks version

# Install Semgrep in an isolated virtualenv and symlink into PATH
RUN uv venv /opt/semgrep && \
    uv pip install --no-cache --python /opt/semgrep/bin/python "semgrep==${SEMGREP_VERSION}" && \
    ln -s /opt/semgrep/bin/semgrep /usr/local/bin/semgrep && \
    /usr/local/bin/semgrep --version

# Create non-root user 'app' (fixed UID 10001), writable /hf_cache, and global git safe.directory
RUN groupadd -g 10001 app && \
    useradd -u 10001 -g 10001 -m -d /home/app -s /bin/bash app && \
    mkdir -p /hf_cache /repos /app && \
    chown -R app:app /hf_cache /home/app /app && \
    git config --system --add safe.directory '*'

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache && \
    ! ls -d /app/.venv/lib/python*/site-packages/nvidia* >/dev/null 2>&1

COPY app ./app
COPY migrations ./migrations
COPY rules ./rules
COPY hooks ./hooks
COPY scripts ./scripts

RUN chown -R app:app /app /hf_cache /home/app

ENV HOME=/home/app \
    TMPDIR=/tmp \
    HF_HOME=/hf_cache \
    KODGARD_HOME=/app \
    PATH="/app/.venv/bin:/usr/local/bin:${PATH}"

USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
