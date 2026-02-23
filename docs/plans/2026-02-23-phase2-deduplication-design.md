# Phase 2: Deduplication Design

**Date:** 2026-02-23
**Source:** Codebase-wide DRY/SOLID/KISS audit (`docs/audits/codebase-dry-solid-kiss-audit-2026-02-23.md`)
**Estimated Impact:** ~2,500 LOC removed across 7 items (item #6 skipped — already well-designed)

---

## Item 1: Consolidate 4 SEPA Operation Managers → 1 (-800 LOC)

### Current State

4 files in `vereinigingen_payments/utils/` implementing the same 4-step SEPA batch creation workflow:

| File | LOC | Class | Key Difference |
|------|-----|-------|----------------|
| `sepa_operations_simple.py` | 240 | `SimpleSEPAManager` | One-at-a-time item creation |
| `frappe_native_sepa_operations.py` | 597 | `FrappeNativeSEPAManager` | Frappe ORM, has `@frappe.whitelist()` endpoints |
| `frappe_native_sepa_operations_optimized.py` | 531 | `FrappeNativeSEPAManagerOptimized` | Batch queries, reduced DB round-trips |
| `sepa_operations_bulk_true.py` | 517 | `TrueBulkSEPAManager` | Single bulk insert, progress callbacks |

All four share identical logic for: mandate validation, creditor grouping, batch document creation, error handling.

### Design

**Strategy pattern** — one `SEPABatchCreator` class with a pluggable `ItemProcessor` strategy.

```python
# vereinigingen_payments/utils/sepa_batch_creator.py (~300 LOC)

class SEPABatchCreator:
    """Unified SEPA batch creation with pluggable item processing."""

    def __init__(self, processor: "ItemProcessor" = None):
        self.processor = processor or SimpleItemProcessor()

    def create_direct_debit_batch(self, collection_date, members=None, ...):
        # 1. Validate mandates (shared)
        # 2. Group by creditor (shared)
        # 3. Create batch document (shared)
        # 4. Process items (delegated to strategy)
        self.processor.process_items(batch_doc, items, ...)
        return batch_doc

class ItemProcessor(ABC):
    """Strategy interface for item processing."""
    @abstractmethod
    def process_items(self, batch_doc, items, ...): ...

class SimpleItemProcessor(ItemProcessor):      # ~30 LOC
class OptimizedItemProcessor(ItemProcessor):    # ~80 LOC
class BulkItemProcessor(ItemProcessor):         # ~80 LOC
```

**`frappe_native_sepa_operations.py`** retains its `@frappe.whitelist()` endpoints but delegates to `SEPABatchCreator`. This avoids breaking the API surface.

### Verification
- `py_compile` all modified/new files
- Existing SEPA tests must pass
- `grep -r` for imports of deleted classes → update callers

---

## Item 2: `@portal_page` Decorator for Templates (-600 LOC)

### Current State

20+ template `get_context()` functions repeat this boilerplate (~25-30 LOC each):

```python
def get_context(context):
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login"), frappe.AuthenticationError)

    member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("No member found"), frappe.PermissionError)

    member_doc = frappe.get_doc("Member", member)
    context.member = member_doc
    context.title = "Page Title"
    context.no_cache = 1
    # ... then unique logic
```

### Design

```python
# vereinigingen/utils/portal_decorators.py (~60 LOC)

def portal_page(title=None, no_cache=True):
    """Decorator for template get_context that handles login + member lookup."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(context):
            if frappe.session.user == "Guest":
                frappe.throw(_("Please login to access this page"), frappe.AuthenticationError)

            member_name = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
            if not member_name:
                frappe.throw(_("No member record found for your account"), frappe.PermissionError)

            context.member = frappe.get_doc("Member", member_name)
            if title:
                context.title = title
            context.no_cache = no_cache

            return func(context)
        return wrapper
    return decorator
```

**Usage:**
```python
@portal_page(title="My Memberships")
def get_context(context):
    # context.member already available
    context.memberships = frappe.get_all(...)
```

### Verification
- Templates still render correctly (manual spot-check 3-4 pages)
- Guest users still get redirected/error
- `py_compile` decorator module + all modified templates

---

## Item 3: Permission Checker Base Class (-400 LOC)

### Current State

`permissions.py` (1,826 LOC) has:
- 8x duplicated role-checking blocks (`frappe.get_roles(user)`, iterate, check)
- 5x chapter board member verification (query `tabChapter Board Member`)
- Multiple permission methods following the same pattern: check admin → check specific role → check chapter membership

### Design

```python
# Extract to top of permissions.py (~80 LOC)

class PermissionCheckerBase:
    """Base class for permission checks with cached role lookups."""

    def __init__(self, user=None):
        self.user = user or frappe.session.user
        self._roles = None
        self._chapter_board_cache = {}

    @property
    def roles(self):
        if self._roles is None:
            self._roles = set(frappe.get_roles(self.user))
        return self._roles

    def has_any_role(self, *roles):
        return bool(self.roles & set(roles))

    def is_chapter_board_member(self, chapter_name=None):
        """Check if user is a board member, optionally for a specific chapter."""
        if chapter_name in self._chapter_board_cache:
            return self._chapter_board_cache[chapter_name]

        filters = {"user": self.user, "status": "Active"}
        if chapter_name:
            filters["parent"] = chapter_name

        result = bool(frappe.db.exists("Chapter Board Member", filters))
        self._chapter_board_cache[chapter_name] = result
        return result
```

Existing permission functions refactored to use this base class, replacing inline role lookups.

### Verification
- All permission checks still return same results
- `py_compile`
- Run permission-related tests if available

---

## Item 4: Event Subscriber Base (-200 LOC)

### Current State

3 subscriber files (`chapter_subscribers.py`, `member_subscribers.py`, `team_subscribers.py`) share:
- 7x document existence checks with identical try/except
- 3x email notification context building
- 32x identical `frappe.log_error()` patterns

### Design

```python
# vereinigingen/events/subscribers/base_subscriber.py (~60 LOC)

class BaseSubscriber:
    """Shared utilities for event subscribers."""

    @staticmethod
    def get_doc_safe(doctype, name, log_prefix="Subscriber"):
        """Get document with existence check and error logging."""
        if not frappe.db.exists(doctype, name):
            frappe.log_error(
                f"{log_prefix}: {doctype} {name} not found",
                f"{log_prefix} Error"
            )
            return None
        return frappe.get_doc(doctype, name)

    @staticmethod
    def send_notification(recipients, subject, template, context, log_prefix="Subscriber"):
        """Send email notification with standard error handling."""
        try:
            frappe.sendmail(
                recipients=recipients,
                subject=subject,
                template=template,
                args=context
            )
        except Exception:
            frappe.log_error(
                f"{log_prefix}: Failed to send notification",
                f"{log_prefix} Error"
            )
```

### Verification
- Event handlers still fire correctly
- `py_compile` all modified files

---

## Item 5: IBAN/Email Validation Consolidation (-200 LOC)

### Current State

- `utils/validation/iban_validator.py` — **canonical** IBAN with full MOD-97 check
- `utils/validation/api_validators.py` — **incomplete** IBAN (regex only, no MOD-97)
- `utils/csv/csv_data_validator.py` — correctly delegates to `iban_validator.py`
- Email validation scattered across `api_validators.py`, `application_validators.py`, and inline in templates

### Design

1. **IBAN:** Make `api_validators.py` delegate to `iban_validator.validate_iban()` instead of its own incomplete regex. Remove the duplicate implementation.

2. **Email:** `api_validators.py` should delegate to Frappe's `validate_email_address()` (which `application_validators.py` already uses) instead of its own regex.

### Verification
- IBAN validation still works end-to-end
- Invalid IBANs (bad checksum) are correctly rejected
- `py_compile` modified files

---

## Item 6: State Machine — SKIP

The SEPA batch state machine (`services/payment/sepa_batch_state_machine.py`, 464 LOC) is already well-designed with table-driven transitions. No consolidation needed.

---

## Items 7-8: e_boekhouden Party/Invoice Consolidation (-300 LOC)

### Current State

**Party creation (7 functions):**
- Functions 1-2 (`_get_or_create_customer`, `_get_or_create_supplier`) use different resolver logic (eBoekhouden-specific lookup)
- Functions 3-7 (company-specific party creators) share identical try/except/return boilerplate

**Invoice creation (2 functions):**
- `_create_sales_invoice()` and `_create_purchase_invoice()` are 95% identical (215 LOC each). Only differ in: party field name (`customer` vs `supplier`), item account field, debit/credit direction.

### Design

**Party creation:** Extract `_get_or_create_company_party(party_type, company_name, ...)` to handle functions 3-7. Functions 1-2 remain as-is (different resolver).

**Invoice creation:** Extract `_create_invoice_base(invoice_type, party_field, party_name, ...)` called by both sales and purchase creators.

```python
def _create_invoice_base(invoice_type, party_field, party_name, items, ...):
    """Shared invoice creation logic for sales and purchase invoices."""
    doc = frappe.new_doc(invoice_type)
    doc.set(party_field, party_name)
    doc.posting_date = posting_date
    # ... 95% shared setup logic ...
    for item in items:
        doc.append("items", {
            "item_code": item["item_code"],
            "qty": item["qty"],
            "rate": item["rate"],
        })
    doc.insert()
    return doc
```

### Verification
- `py_compile` modified file
- e_boekhouden import tests still pass (if available)
- `grep -r` for callers of modified functions → verify they still work

---

## Execution Order

1. **SEPA Operations** (item 1) — largest impact, self-contained
2. **Template Decorator** (item 2) — high impact, many files but simple changes
3. **Permission Checker** (item 3) — single file, moderate impact
4. **Event Subscribers** (item 4) — small impact, simple extraction
5. **IBAN/Email Validation** (item 5) — small impact, delegation only
6. **e_boekhouden Party/Invoice** (items 7-8) — deferred domain, do last

---

## Risk Analysis

| Item | Risk | Mitigation |
|------|------|------------|
| SEPA consolidation | LOW | Strategy pattern preserves all 3 processing modes; existing tests verify |
| Template decorator | LOW | Pure extraction; templates still call `get_context()` normally |
| Permission base | LOW | Same logic, just deduplicated; permission tests verify |
| Event subscribers | LOW | Helper methods only; event flow unchanged |
| Validation | LOW | Delegation to existing canonical implementations |
| e_boekhouden | LOW | Pure extraction; callers unchanged; deferred bugs stay deferred |
