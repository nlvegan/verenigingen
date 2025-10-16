# Custom CSRF Protection - Archival Notes

**Date Archived:** 2025-10-16
**Reason:** Redundant with Frappe Framework's native CSRF protection

## Why This Was Built

The custom CSRF protection module (`csrf_protection.py`) was built to provide:
- HMAC-based token generation with timestamps
- 1-hour token expiry
- Stateless validation without session storage
- Custom token format: `user:timestamp:signature`

## Why It's Not Needed

### Frappe Has Native CSRF Protection

Frappe Framework (`/apps/frappe/frappe/auth.py:83-98`) provides built-in CSRF protection that:
- Automatically validates all POST/PUT/DELETE/PATCH requests
- Stores tokens in `frappe.session.data.csrf_token`
- Accepts tokens from `X-Frappe-CSRF-Token` header or `csrf_token` form field
- Auto-injects tokens into web pages
- No decorator required - it's middleware-level

### Our Custom Code Was Disabled By Default

Looking at `csrf_protection.py:132-152`, the validation logic had:

```python
if frappe.conf.get("disable_custom_csrf_protection", True):  # Default to disabled
    # Falls back to Frappe's native validation
    return True
```

**The custom CSRF was disabled by default** and just deferred to Frappe's implementation.

### HMAC Tokens Are Overkill for CSRF

HMAC-based tokens are useful for:
- Stateless API authentication (JWT)
- Distributed systems needing to validate tokens without shared state
- Long-lived tokens with embedded metadata

**For CSRF protection**, random session-based tokens are:
- Simpler (less attack surface)
- Standard practice (used by Django, Rails, Frappe)
- Adequate for the threat model (browser-based CSRF attacks)
- Easier to invalidate (just clear the session)

### API Requests Don't Need CSRF Protection

CSRF protection is only needed for browser-based requests that:
- Automatically send cookies
- Can be tricked by malicious sites

API requests using `Authorization` headers:
- Don't automatically send credentials
- Can't be exploited via CSRF
- Should NOT have CSRF validation applied

Frappe correctly skips CSRF validation for API-authenticated requests.

## Where It Was Used

The custom CSRF code was referenced in:
- `verenigingen/utils/security/api_security_framework.py` (3 usages)
- Various test files
- Security documentation

**All actual validation calls** ultimately deferred to Frappe's native implementation.

## Migration Path

Instead of custom CSRF validation, use:

```python
# OLD (custom CSRF):
from verenigingen.utils.security.csrf_protection import CSRFProtection
csrf = CSRFProtection()
csrf.validate_request()

# NEW (direct Frappe native):
# Nothing needed! Frappe's auth.py validates automatically
# If you need explicit validation:
if frappe.request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
    # Frappe already validated CSRF in HTTPRequest.__init__
    # Just proceed with your logic
    pass
```

For generating tokens for frontend:
```python
# OLD:
token = csrf_protection.generate_token()

# NEW:
token = frappe.sessions.get_csrf_token()
```

## Security Implications

**No security degradation** - we're using Frappe's battle-tested native implementation instead of custom code.

Benefits:
- ✅ Less code to maintain
- ✅ Consistent with framework conventions
- ✅ Automatically gets framework security updates
- ✅ No risk of implementation bugs in custom code

## References

- Frappe native CSRF: `/apps/frappe/frappe/auth.py:83-98`
- Frappe session management: `/apps/frappe/frappe/sessions.py`
- Discussion: See conversation logs from 2025-10-16
