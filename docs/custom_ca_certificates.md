# Custom CA Certificates

This document describes how to configure Quick Apps to trust a private or corporate Root CA
when running behind a TLS-intercepting proxy.

## Overview

When Quick Apps is deployed behind a corporate HTTPS proxy that terminates TLS and re-signs
traffic with an internal Root CA, outbound connections fail with:

```
ConnectError: SSL: CERTIFICATE_VERIFY_FAILED
```

The container ships with a standard Alpine CA bundle that does not include private CAs.
The `USE_SYSTEM_CA_CERTS` mechanism solves this by merging a custom CA certificate into
the bundle at container startup, before the application process starts.

## Usage

1. Obtain the corporate Root CA certificate in PEM format (`.crt` extension).
2. Mount it into the container under `/certificates/`.
3. Set `USE_SYSTEM_CA_CERTS=1`.

**Docker Compose example:**

```yaml
services:
  quickapps:
    environment:
      USE_SYSTEM_CA_CERTS: "1"
    volumes:
      - /path/to/corporate-ca.crt:/certificates/corporate-ca.crt:ro
```

Multiple certificates are supported — every `*.crt` file found under `/certificates/` is
merged into the bundle.

## How It Works

The `docker_cacert_entrypoint.sh` script is sourced by the container entrypoint before the
Python process starts. When `USE_SYSTEM_CA_CERTS=1`:

1. A temporary file is created containing the Alpine system CA bundle
   (`/etc/ssl/certs/ca-certificates.crt`).
2. All `*.crt` files from `/certificates/` are appended to it.
3. `SSL_CERT_FILE` is exported pointing to the merged bundle.

`httpx` (the HTTP client used throughout the app) reads `SSL_CERT_FILE` automatically, so
no application code changes are required.

When `USE_SYSTEM_CA_CERTS` is not set the script is a no-op and existing behaviour is unchanged.
