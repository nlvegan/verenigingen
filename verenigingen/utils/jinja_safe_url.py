"""Jinja filter ``safe_url`` for URLs a non-staff user can set (#2884).

``|e`` stops an attribute breakout but not a ``javascript:``/``data:``/``vbscript:`` scheme, so a
user-writable URL printed into ``href``/``src`` needs ``{{ value|safe_url|e }}``. Registered through
the ``jinja.filters`` hook (every public function defined in this module becomes a filter).
"""

from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https", "mailto")


def safe_url(value):
    """Return ``value`` when it is a relative URL or http/https/mailto, else ``""``.

    An allowlist, not a ``javascript:`` blocklist. Control characters and backslashes are refused
    outright: browsers delete tabs/newlines inside a scheme (``java\\tscript:``) and read ``/\\host``
    as protocol-relative. A leading ``//`` is a foreign host. Frappe File URLs are ``/files/...`` or
    ``/private/files/...`` and pass unchanged.
    """
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url or any(ch == "\\" or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url) or url.startswith("//"):
        return ""
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return ""
    return url if not scheme or scheme in ALLOWED_SCHEMES else ""
