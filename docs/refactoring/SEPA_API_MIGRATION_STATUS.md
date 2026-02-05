# SEPA API Migration Status

**Status:** Complete (Backward Compatibility Maintained)
**Last Updated:** 2026-02-05

## Overview

The SEPA-related functions have been migrated from the Member DocType to the dedicated API module while maintaining backward compatibility through re-exports.

## Architecture

### Canonical Location
```
verenigingen/api/member/sepa_api.py
```

### Backward Compatibility Shim
```
verenigingen/verenigingen/doctype/member/member_compat.py
```

## Functions Migrated

| Function | Original Location | Current Location | Re-exported |
|----------|------------------|------------------|-------------|
| `create_and_link_mandate_enhanced` | `member.py` / `member_utils.py` | `sepa_api.py` | ✅ Yes |
| `deactivate_old_sepa_mandates` | `member.py` | `sepa_api.py` | ✅ Yes |
| `derive_bic_from_iban` | `member.py` | `sepa_api.py` | ✅ Yes |
| `get_active_sepa_mandate` | `member.py` | `sepa_api.py` | ✅ Yes |
| `refresh_sepa_mandates` | `member.py` | `sepa_api.py` | ✅ Yes |
| `validate_mandate_creation` | `member.py` | `sepa_api.py` | ✅ Yes |

## Usage Patterns

### New Code (Recommended)
```python
from verenigingen.api.member.sepa_api import (
    create_and_link_mandate_enhanced,
    get_active_sepa_mandate,
)
```

### Legacy Code (Still Works)
```python
from verenigingen.verenigingen.doctype.member.member_compat import (
    create_and_link_mandate_enhanced,
    get_active_sepa_mandate,
)
```

## Duplicate Removal

### Issue Identified
The function `create_and_link_mandate_enhanced` was found in two locations:
1. `api/member/sepa_api.py` (canonical)
2. `verenigingen/doctype/member/member_utils.py` (duplicate)

### Resolution
Removed the duplicate from `member_utils.py` (~75 lines).

The canonical version in `sepa_api.py` is re-exported via `member_compat.py` for backward compatibility.

## Security Decorators

All SEPA API functions use appropriate security decorators:

| Function | Decorator | Operation Type |
|----------|-----------|----------------|
| `create_and_link_mandate_enhanced` | `@critical_api` | `FINANCIAL` |
| `validate_mandate_creation` | `@critical_api` | `FINANCIAL` |
| `get_active_sepa_mandate` | `@high_security_api` | `MEMBER_DATA` |
| `refresh_sepa_mandates` | `@critical_api` | `FINANCIAL` |
| `deactivate_old_sepa_mandates` | `@critical_api` | `FINANCIAL` |
| `derive_bic_from_iban` | `@standard_api` | `UTILITY` |

## Deprecation Timeline

### Current State (2026-02-05)
- Functions accessible via both paths
- Re-exports in `member_compat.py` working correctly
- No deprecation warnings (too disruptive for now)

### Phase 1 (Future)
- Add deprecation warnings to `member_compat.py` imports
- Update internal code to use `sepa_api.py` directly
- Document migration in release notes

### Phase 2 (Future)
- Remove re-exports from `member_compat.py`
- Update documentation to only reference `sepa_api.py`

## Related Functions in member_utils.py

The following SEPA-related functions remain in `member_utils.py` as they are utility functions called from the API layer:

| Function | Purpose | Keep/Move |
|----------|---------|-----------|
| `generate_mandate_reference` | Generate mandate reference | Keep |
| `validate_mandate_reference` | Check if reference available | Keep |
| `check_and_handle_sepa_mandate` | Check/handle existing mandate | Keep |
| `need_new_mandate` | Check if new mandate needed | Keep |
| `create_and_link_mandate` | Create and link mandate | Keep |

These are lower-level utilities that support the main API functions.

## Testing

SEPA API functions are tested via:
- Unit tests in `tests/test_sepa_api.py`
- Integration tests in `tests/test_member_sepa_integration.py`
- Cypress E2E tests for form interactions

## Notes

1. The backward compatibility shim (`member_compat.py`) should be maintained indefinitely as external integrations may depend on the old import paths.

2. The duplicate in `member_utils.py` was likely created during an incomplete refactoring and has now been cleaned up.

3. All SEPA operations go through proper security checks - no `ignore_permissions=True` in the API layer.

---

*Document maintained as part of SEPA API consolidation efforts*
