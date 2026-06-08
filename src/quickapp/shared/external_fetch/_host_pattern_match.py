import ipaddress


def match_host(host: str, patterns: list[str]) -> bool:
    """Return True if ``host`` matches any of the allowlist patterns.

    Pattern grammar (case-insensitive):

    * ``example.com`` — exact host match only.
    * ``*.example.com`` — any subdomain of ``example.com`` with at least one
      label (e.g. ``a.example.com``, ``a.b.example.com``). Does not match
      ``example.com`` itself.

    IP-literal hosts (``1.2.3.4``, ``[::1]``) never match: the SSRF guard is
    responsible for IP-level filtering, and an allowlist for IP literals would
    invite confusion between domain policy and SSRF policy.
    """
    if not host or not patterns:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    h = host.lower()
    for pattern in patterns:
        p = pattern.lower()
        if p.startswith("*."):
            suffix = p[1:]
            if h.endswith(suffix) and len(h) > len(suffix):
                return True
        elif p == h:
            return True
    return False
