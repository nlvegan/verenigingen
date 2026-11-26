"""Constant-time string comparison that fails closed on non-ASCII input (#1164)."""

import hmac


def safe_compare_digest(a, b) -> bool:
    """``hmac.compare_digest`` for caller-supplied strings.

    ``hmac.compare_digest`` raises ``TypeError`` when either ``str`` holds a
    non-ASCII character, so a guest-supplied header such as ``héllo`` produced a
    different answer (raw exception text, a 500) from an ordinary wrong token. Both
    sides are encoded to UTF-8 first (``surrogatepass``, so a lone surrogate does not
    raise), so a non-ASCII value is simply "not equal".
    A ``None`` on either side is also "not equal".
    """
    if a is None or b is None:
        return False
    if isinstance(a, str):
        a = a.encode("utf-8", errors="surrogatepass")
    if isinstance(b, str):
        b = b.encode("utf-8", errors="surrogatepass")
    return hmac.compare_digest(a, b)
