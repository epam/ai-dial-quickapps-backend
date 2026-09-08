#!/usr/bin/env bash
# Regenerates the local dev CA and the Keycloak leaf certificate under ./certs/.
# After regenerating, re-trust the CA in your login keychain:
#   sudo security add-trusted-cert -d -r trustRoot \
#     -k /Library/Keychains/System.keychain docker_compose_files/keycloak/certs/ca.crt
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p certs && cd certs

# `docker compose up` may have pre-created directories at these bind-mount paths.
for stale in ca.crt ca.key keycloak.crt keycloak.key; do
  [ -d "$stale" ] && rm -rf "$stale"
done

if [ -f ca.crt ] && [ "${FORCE:-}" != "1" ]; then
  echo "certs/ already present — nothing to do."
  echo "Run with FORCE=1 to regenerate; you will then have to trust the new CA again."
  exit 0
fi

openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
  -keyout ca.key -out ca.crt \
  -subj "/CN=DIAL Local Dev CA/O=DIAL local development" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

openssl req -newkey rsa:2048 -nodes -keyout keycloak.key -out keycloak.csr \
  -subj "/CN=keycloak.localtest.me"

cat > san.cnf <<'EXT'
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:keycloak.localtest.me,DNS:keycloak,DNS:localhost,IP:127.0.0.1
EXT

openssl x509 -req -in keycloak.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out keycloak.crt -days 3650 -sha256 -extfile san.cnf

rm -f keycloak.csr ca.srl san.cnf
chmod 644 ca.crt keycloak.crt keycloak.key

# `x509 -ext` is OpenSSL-only; macOS ships LibreSSL, so dump full text instead.
openssl x509 -in keycloak.crt -noout -subject -issuer -dates
openssl x509 -in keycloak.crt -noout -text | grep -A1 "Subject Alternative Name"
