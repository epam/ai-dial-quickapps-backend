FROM python:3.13-alpine AS builder

RUN apk update && apk upgrade --no-cache libcrypto3 libssl3 zlib musl musl-utils
RUN apk add --no-cache gcc alpine-sdk linux-headers musl-dev git
RUN pip install poetry==2.3.2

WORKDIR /app

COPY pyproject.toml poetry.lock poetry.toml README.md ./
RUN poetry install --no-interaction --no-ansi --no-cache --no-root \
  --no-directory --only main

COPY  ./src/quickapp /app/quickapp
COPY  ./config/predefined /app/predefined
RUN poetry install --no-interaction --no-ansi --no-cache --only main

FROM python:3.13-alpine AS runtime

RUN apk update && apk upgrade --no-cache libcrypto3 libssl3 libexpat zlib musl musl-utils

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYDANTIC_V2=True

# Copy the sources and virtual env. No poetry.
RUN adduser -u 1001 --disabled-password --gecos "" appuser
COPY --chown=appuser --from=builder /app .

RUN echo '#!/bin/sh' > /docker_entrypoint.sh && \
    echo 'set -e' >> /docker_entrypoint.sh && \
    echo '. ./.venv/bin/activate' >> /docker_entrypoint.sh && \
    echo 'exec "$@"' >> /docker_entrypoint.sh && \
    chmod +x /docker_entrypoint.sh

EXPOSE 5000

USER appuser
ENTRYPOINT ["/docker_entrypoint.sh"]

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:5000/health || exit 1

CMD ["uvicorn", "quickapp.app:app", "--host", "0.0.0.0", "--port", "5000", "--lifespan", "on"]
