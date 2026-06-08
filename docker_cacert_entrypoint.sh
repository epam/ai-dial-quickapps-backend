#!/bin/sh
# Sourced from docker_entrypoint.sh to configure CA certificates.
# Set USE_SYSTEM_CA_CERTS=1 and mount custom .crt files under /certificates/
# to merge them with the system CA bundle and export SSL_CERT_FILE.
if [ "${USE_SYSTEM_CA_CERTS}" = "1" ]; then
    _MERGED_CA_BUNDLE=$(mktemp)
    cat /etc/ssl/certs/ca-certificates.crt > "${_MERGED_CA_BUNDLE}"
    for _cert_file in /certificates/*.crt; do
        [ -f "${_cert_file}" ] && cat "${_cert_file}" >> "${_MERGED_CA_BUNDLE}"
    done
    export SSL_CERT_FILE="${_MERGED_CA_BUNDLE}"
    unset _MERGED_CA_BUNDLE _cert_file
fi
