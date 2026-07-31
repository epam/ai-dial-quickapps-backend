FROM python:3.13-alpine AS test-builder

RUN apk update && apk upgrade --no-cache libcrypto3 libssl3 musl musl-utils
RUN apk add --no-cache gcc alpine-sdk linux-headers musl-dev git
RUN pip install --no-cache-dir poetry==2.3.2

WORKDIR /app

COPY pyproject.toml poetry.lock poetry.toml README.md ./
RUN poetry install --no-interaction --no-ansi --no-cache --no-root \
  --no-directory --only main --with test

# Copy app code (as in main)
COPY ./src/quickapp /app/quickapp
COPY ./config/predefined /app/predefined
RUN poetry install --no-interaction --no-ansi --no-cache --only main --with test

RUN . ./.venv/bin/activate && \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

# Copy tests
COPY ./integration_tests ./integration_tests


# Stage 2: Test runtime (reuse app runtime base for infra)
FROM python:3.13-alpine AS test-runtime
RUN apk update && apk upgrade --no-cache libcrypto3 libssl3 libexpat musl musl-utils

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN adduser -u 1001 --disabled-password --gecos "" appuser
COPY --chown=appuser --from=test-builder /app .

# pip vendors vulnerable msgpack/setuptools; not needed at runtime
RUN rm -rf \
      /usr/local/lib/python*/site-packages/pip \
      /usr/local/lib/python*/site-packages/pip-*.dist-info \
      /usr/local/lib/python*/ensurepip \
      /usr/local/bin/pip \
      /usr/local/bin/pip3 \
      /usr/local/bin/pip3.* \
      .venv/lib/python*/site-packages/pip \
      .venv/lib/python*/site-packages/pip-*.dist-info \
      .venv/bin/pip \
      .venv/bin/pip3 \
      .venv/bin/pip3.*

COPY --chown=appuser << 'EOF' /docker_test_entrypoint.sh && chmod +x /docker_test_entrypoint.sh
#!/bin/sh
set -e
. ./.venv/bin/activate
exec pytest "$@"
EOF

USER appuser
ENTRYPOINT ["/docker_test_entrypoint.sh"]

HEALTHCHECK --interval=30s CMD pytest --version || exit 1
