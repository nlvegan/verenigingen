# Phase 2: Deduplication Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate duplicated code across 6 areas identified in the codebase-wide DRY/SOLID/KISS audit, removing ~2,500 LOC while preserving all behavior.

**Architecture:** Pure refactoring — extract shared logic into helpers/base classes, update callers to delegate. No new features, no behavior changes. Strategy pattern for SEPA operations; helper functions for permissions, subscribers, and validation; `setup_portal_context()` adoption for templates.

**Tech Stack:** Python 3.10+, Frappe Framework v15, existing test infrastructure.

**Design Doc:** `docs/plans/2026-02-23-phase2-deduplication-design.md`

---

## Task 1: IBAN Validation — Delegate to Canonical Source

**Files:**
- Modify: `vereinigingen/utils/validation/api_validators.py:169-198`
- Reference: `vereinigingen/utils/validation/iban_validator.py:32-103` (canonical implementation)

**Why first:** Smallest, safest change. Builds confidence. The `api_validators.py` IBAN check uses regex only (no MOD-97 checksum), while `iban_validator.py` has the full implementation.

**Step 1: Read the canonical IBAN validator interface**

Read `vereinigingen/utils/validation/iban_validator.py` lines 32-103 to understand the `validate_iban()` signature and return value.

**Step 2: Replace api_validators.validate_iban() with delegation**

In `vereinigingen/utils/validation/api_validators.py`, replace lines 169-198:

```python
@classmethod
def validate_iban(cls, iban: str, required: bool = False) -> Optional[str]:
    """
    Validate IBAN format

    Args:
        iban: IBAN to validate
        required: Whether IBAN is required

    Returns:
        Normalized IBAN

    Raises:
        ValidationError: If IBAN is invalid
    """
    if not iban:
        if required:
            raise ValidationError("IBAN is required")
        return None

    # Normalize IBAN
    iban = iban.upper().replace(" ", "")

    # Check basic format
    if not cls.IBAN_PATTERN.match(iban):
        raise ValidationError("Invalid IBAN format")

    # For more thorough validation, could implement MOD-97 check here

    return iban
```

With:

```python
@classmethod
def validate_iban(cls, iban: str, required: bool = False) -> Optional[str]:
    """
    Validate IBAN format with full MOD-97 checksum verification.

    Delegates to the canonical iban_validator for thorough validation.

    Args:
        iban: IBAN to validate
        required: Whether IBAN is required

    Returns:
        Normalized IBAN

    Raises:
        ValidationError: If IBAN is invalid
    """
    if not iban:
        if required:
            raise ValidationError("IBAN is required")
        return None

    from vereinigingen.utils.validation.iban_validator import validate_iban as canonical_validate_iban

    result = canonical_validate_iban(iban)
    if not result.get("valid"):
        raise ValidationError(result.get("message", "Invalid IBAN format"))

    return result.get("iban", iban.upper().replace(" ", ""))
```

**Step 3: Verify with py_compile**

Run: `python -m py_compile vereinigingen/utils/validation/api_validators.py`
Expected: No output (success)

**Step 4: Commit**

```bash
git add vereinigingen/utils/validation/api_validators.py
git commit -m "refactor: delegate IBAN validation to canonical iban_validator with MOD-97"
```

---

## Task 2: Email Validation — Delegate to Frappe Built-in

**Files:**
- Modify: `vereinigingen/utils/validation/api_validators.py:34-66`

**Why:** The custom regex `EMAIL_PATTERN` at line 25 is less comprehensive than Frappe's `validate_email_address()`. The `application_validators.py` already uses Frappe's version.

**Step 1: Read the current email validation**

Read `vereinigingen/utils/validation/api_validators.py` lines 24-66 to see the full `validate_email` method.

**Step 2: Replace with Frappe delegation**

Replace the `validate_email` classmethod body to delegate to `frappe.utils.validate_email_address()` while preserving the same interface (accepts `email`, `required`; returns normalized email or raises `ValidationError`):

```python
@classmethod
def validate_email(cls, email: str, required: bool = True) -> Optional[str]:
    """
    Validate and normalize email address.

    Delegates to Frappe's built-in email validation for comprehensive checks.

    Args:
        email: Email address to validate
        required: Whether email is required

    Returns:
        Normalized email address

    Raises:
        ValidationError: If email is invalid
    """
    if not email:
        if required:
            raise ValidationError("Email is required")
        return None

    email = email.strip().lower()

    from frappe.utils import validate_email_address

    if not validate_email_address(email):
        raise ValidationError(f"Invalid email format: {email}")

    return email
```

**Step 3: Remove unused EMAIL_PATTERN constant**

Remove line 25: `EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")`

Also check if `IBAN_PATTERN` at line 28 is still used elsewhere in the class. If validate_iban no longer uses it and no other method does, remove it too.

**Step 4: Verify**

Run: `python -m py_compile vereinigingen/utils/validation/api_validators.py`
Expected: No output (success)

**Step 5: Commit**

```bash
git add verenigingen/utils/validation/api_validators.py
git commit -m "refactor: delegate email validation to Frappe built-in validate_email_address"
```

---

## Task 3: Permission Helpers — Extract Shared Role-Checking

**Files:**
- Modify: `verenigingen/permissions.py`

**Why:** 17 instances of admin role checking and 8 instances of chapter board member resolution follow identical patterns. Extract helper functions near the top of the file.

**Step 1: Read the permission functions to identify the exact patterns**

Read `verenigingen/permissions.py` at these key sections:
- Lines 60-100 (imports, Roles class)
- Lines 380-430 (has_member_permission — reference implementation)
- Lines 470-530 (has_volunteer_permission — another instance)
- Lines 555-635 (has_donor_permission — another instance)

**Step 2: Add `_has_admin_access()` helper**

Add near existing helper functions (look for other `_` prefixed helpers, likely around line 200-280):

```python
def _has_admin_access(user_roles, admin_role_set=None):
    """Check if user has any admin role. Used by 17+ permission functions."""
    if admin_role_set is None:
        admin_role_set = Roles.ADMIN_ROLES
    return any(role in user_roles for role in admin_role_set)
```

**Step 3: Add `_has_chapter_board_access()` helper**

```python
def _has_chapter_board_access(user, user_roles, target_member_name):
    """Check if user is a chapter board member with access to target member.

    Used by has_member_permission, has_volunteer_permission, has_donor_permission,
    has_donation_permission, has_address_permission, and their query variants.
    """
    if "Verenigingen Chapter Board Member" not in user_roles:
        return False

    try:
        user_chapter_names = get_user_chapter_memberships_cached(user, get_cache_key())
        if user_chapter_names and _is_member_in_chapters(target_member_name, user_chapter_names):
            return True
    except Exception:
        pass

    return False
```

**Step 4: Replace duplicated patterns in permission functions**

For each of the 17 admin role checks, replace:
```python
admin_roles = Roles.ADMIN_ROLES
if any(role in user_roles for role in admin_roles):
    frappe.logger().debug(f"User {user} has admin role, granting access")
    return True
```
With:
```python
if _has_admin_access(user_roles):
    return True
```

For the 8 chapter board checks, replace the multi-line pattern with:
```python
if _has_chapter_board_access(user, user_roles, member_name):
    return True
```

**Note:** Some permission functions have additional logic after the board check (e.g., termination request fallback in `has_member_permission`). Keep that function-specific logic in place — only extract the common prefix.

**Step 5: Verify**

Run: `python -m py_compile verenigingen/permissions.py`
Expected: No output (success)

**Step 6: Commit**

```bash
git add verenigingen/permissions.py
git commit -m "refactor: extract _has_admin_access() and _has_chapter_board_access() from 25 duplicated patterns"
```

---

## Task 4: Event Subscriber Helpers — Extract Document Safety + Error Handling

**Files:**
- Create: `verenigingen/events/subscribers/subscriber_utils.py`
- Modify: `verenigingen/events/subscribers/chapter_subscribers.py`
- Modify: `verenigingen/events/subscribers/member_subscribers.py`
- Modify: `verenigingen/events/subscribers/team_subscribers.py`

**Step 1: Create subscriber_utils.py with shared helpers**

```python
"""
Shared utilities for event subscriber handlers.

Provides safe document retrieval and standardized error logging
used across chapter, member, and team subscriber modules.
"""

import frappe


def get_doc_if_exists(doctype, name, log_prefix="Subscriber"):
    """Get document with existence check and warning log.

    Returns None with a warning log if the document doesn't exist yet
    (common during background job processing before commit).

    Args:
        doctype: Frappe DocType name
        name: Document name/ID
        log_prefix: Prefix for log messages

    Returns:
        Document object or None
    """
    if not frappe.db.exists(doctype, name):
        frappe.logger("events").warning(
            f"Cannot process {log_prefix} - {doctype} {name} not yet committed to database"
        )
        return None
    return frappe.get_doc(doctype, name)


def should_skip_for_bulk(is_bulk_import=False):
    """Check if event processing should be skipped during bulk imports.

    Args:
        is_bulk_import: Explicit bulk import flag from event data

    Returns:
        True if processing should be skipped
    """
    return is_bulk_import or frappe.flags.in_import or getattr(frappe.flags, "in_bulk_import", False)
```

**Step 2: Update chapter_subscribers.py**

Replace the 6 instances of the existence check pattern. Example at lines 33-40:

Before:
```python
if not frappe.db.exists("Chapter", chapter_name):
    frappe.logger("events").warning(
        f"Cannot handle board role assignment - Chapter {chapter_name} not yet committed to database"
    )
    return

chapter = frappe.get_doc("Chapter", chapter_name)
```

After:
```python
from vereinigingen.events.subscribers.subscriber_utils import get_doc_if_exists

chapter = get_doc_if_exists("Chapter", chapter_name, "board role assignment")
if not chapter:
    return
```

Apply same pattern at all 6 locations identified by the exploration agent.

**Step 3: Update member_subscribers.py**

Replace 3 instances of bulk import check (lines 31, 88, 141):

Before:
```python
if is_bulk_import or frappe.flags.in_import or frappe.flags.in_bulk_import:
    return
```

After:
```python
from verenigingen.events.subscribers.subscriber_utils import should_skip_for_bulk

if should_skip_for_bulk(is_bulk_import):
    return
```

Replace document existence checks (4-5 instances).

**Step 4: Update team_subscribers.py**

Replace document existence checks and any bulk import checks using the same helpers.

**Step 5: Verify**

Run:
```bash
python -m py_compile vereinigingen/events/subscribers/subscriber_utils.py
python -m py_compile verenigingen/events/subscribers/chapter_subscribers.py
python -m py_compile verenigingen/events/subscribers/member_subscribers.py
python -m py_compile vereinigingen/events/subscribers/team_subscribers.py
```
Expected: No output (success) for all 4

**Step 6: Commit**

```bash
git add verenigingen/events/subscribers/
git commit -m "refactor: extract subscriber_utils with get_doc_if_exists() and should_skip_for_bulk()"
```

---

## Task 5: Template Login — Migrate to setup_portal_context()

**Files:**
- Modify: ~15 template files in `verenigingen/templates/pages/`
- Reference: `verenigingen/utils/member_portal_utils.py:390-420` (existing `setup_portal_context()`)

**Why:** `setup_portal_context()` already exists and handles guest check + member lookup + context setup. ~15 template `get_context()` functions duplicate this logic inline instead of calling it.

**Context:** 5 templates already use `setup_portal_context()`: `my_dues_schedule.py`, `address_change.py`, `my_addresses.py`, `personal_details.py`, `membership_adjustment.py`. The remaining ~15 use inline guest checks.

**Step 1: Identify candidate templates**

Templates with `get_context()` that have inline guest check AND member lookup but DON'T use `setup_portal_context()`:
- `member_portal.py` (line 23 guest check, line 46 member lookup)
- `contact_request.py` (line 17 guest check)
- `manage_donations.py` (line 28 guest check)
- `chapter_join.py` (line 31 guest check)
- `brand_management.py` (line 16 guest check)
- `mollie_payment_processing.py` (line 23 guest check)
- `mollie_bulk_payment_creation.py` (line 31 guest check)
- `mollie_payments_debug.py` (line 27 guest check)
- `mollie_subscription_recreation.py` (line 39 guest check)
- `ponto_api_debug.py` (line 18 guest check)
- `sepa_reconciliation_dashboard.py` (line 15 guest check)
- `payment_plans.py` (line 20 guest check)
- `board/document_upload.py` (line 28 guest check)
- `board/document_browser.py` (line 29 guest check)
- `volunteer/dashboard.py` (line 10)
- `volunteer/profile.py` (line 9)
- `volunteer/skills.py` (line 11)
- `volunteer/expense_claim_new.py` (line 14)
- `volunteer-portal/expense_claim_new.py` (line 27)
- `verenigingen/join_chapter.py` (line 30)

**Step 2: For each template, read the get_context function**

Read each file's `get_context()` to understand:
1. Does it do member lookup after guest check? → Full `setup_portal_context()` replacement
2. Does it only do guest check (admin pages)? → Use `validate_user_logged_in()` directly
3. Does it have unique setup that setup_portal_context doesn't handle? → Partial replacement

**Step 3: Replace inline patterns**

**Pattern A** (guest check + member lookup → `setup_portal_context()`):
```python
# Before:
def get_context(context):
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login"), frappe.AuthenticationError)
    context.no_cache = 1
    member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
    if not member:
        frappe.throw(...)
    # ...unique logic...

# After:
from verenigingen.utils.member_portal_utils import setup_portal_context

def get_context(context):
    member = setup_portal_context(context, "Page Title")
    if not member:
        return
    # ...unique logic using member...
```

**Pattern B** (guest check only, no member lookup → `validate_user_logged_in()`):
```python
# Before:
def get_context(context):
    if frappe.session.user == "Guest":
        frappe.throw(_("..."), frappe.PermissionError)
    # ...admin logic, no member needed...

# After:
from vereinigingen.utils.error_handling import validate_user_logged_in

def get_context(context):
    validate_user_logged_in()
    # ...admin logic...
```

**Step 4: Handle @frappe.whitelist() methods in template files**

The guest checks inside `@frappe.whitelist()` methods (e.g., `my_dues_schedule.py:287`, `address_change.py:136`, `membership_adjustment.py:323,546,681,745`) should use `validate_user_logged_in()`:

```python
# Before (inside @frappe.whitelist method):
if frappe.session.user == "Guest":
    frappe.throw(_("Please login"), frappe.PermissionError)

# After:
from vereinigingen.utils.error_handling import validate_user_logged_in
validate_user_logged_in()
```

**Step 5: Verify**

Run py_compile on all modified files:
```bash
for f in $(git diff --name-only); do python -m py_compile "$f"; done
```

**Step 6: Commit**

```bash
git add vereinigingen/templates/pages/
git commit -m "refactor: migrate ~20 templates to setup_portal_context() / validate_user_logged_in()"
```

---

## Task 6: SEPA Operations — Extract Shared Dataclass and Validation

**Files:**
- Create: `verenigingen/verenigingen_payments/utils/sepa_models.py`
- Modify: `vereinigingen/verenigingen_payments/utils/sepa_operations_simple.py`
- Modify: `verenigingen/verenigingen_payments/utils/frappe_native_sepa_operations.py`
- Modify: `vereinigingen/verenigingen_payments/utils/frappe_native_sepa_operations_optimized.py`
- Modify: `vereinigingen/verenigingen_payments/utils/sepa_operations_bulk_true.py`

**Step 1: Read all 4 SEPA files to identify exact shared code**

Read each file fully to map the shared patterns:
- Dataclass definitions (4 variants of the same operation struct)
- Permission validation logic
- Operation grouping logic
- Result formatting

**Step 2: Create sepa_models.py with shared structures**

```python
"""
Shared data models and utilities for SEPA operations.

Consolidates duplicated dataclasses and helper logic from the 4 SEPA manager implementations.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SEPAOperation:
    """Unified SEPA operation data structure.

    Used across all SEPA manager implementations (simple, native, optimized, bulk).
    """
    member_id: str
    operation_type: str  # "create", "update", "cancel"
    operation_data: Dict[str, Any] = field(default_factory=dict)


def build_result(
    success: bool,
    processed: int,
    failed: int,
    errors: Optional[List[str]] = None,
    execution_time: Optional[float] = None,
    details: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Build standardized SEPA operation result dict."""
    result = {
        "success": success,
        "processed": processed,
        "failed": failed,
        "errors": errors or [],
    }
    if execution_time is not None:
        result["execution_time"] = execution_time
    if details:
        result.update(details)
    return result
```

**Step 3: Update all 4 SEPA files to import from sepa_models**

In each file, replace the local dataclass with an import:

```python
# Before (in each file):
class SimpleSEPAOperation:
    def __init__(self, member_id, operation_type, operation_data):
        ...

# After:
from vereinigingen.vereiningen_payments.utils.sepa_models import SEPAOperation
# Keep old class name as alias for backwards compatibility with tests
SimpleSEPAOperation = SEPAOperation
```

Replace result dict construction with `build_result()` calls.

**Step 4: Extract shared validation into sepa_models.py**

The permission validation pattern shared between optimized and bulk_true:

```python
def validate_bulk_permissions(operations, user=None):
    """Validate user has permission for bulk SEPA operations.

    Shared by FrappeNativeSEPAManagerOptimized and TrueBulkSEPAManager.
    """
    if not user:
        user = frappe.session.user

    if not operations:
        return [], []

    authorized = []
    unauthorized = []

    for op in operations:
        if frappe.has_permission("SEPA Mandate", "write", user=user):
            authorized.append(op)
        else:
            unauthorized.append(op)

    return authorized, unauthorized
```

**Step 5: Update optimized + bulk_true to use shared validation**

Replace the local `_validate_bulk_permissions()` methods with calls to the shared function.

**Step 6: Update comparison/test utilities**

Update imports in:
- `utils/sepa_baseline_test.py`
- `utils/sepa_optimization_comparison.py`
- `utils/sepa_three_way_comparison.py`
- `tests/test_sepa_simple_baseline.py`
- `tests/test_frappe_native_sepa_operations.py`
- `tests/test_sepa_optimization.py`

**Step 7: Verify**

```bash
python -m py_compile verenigingen/verenigingen_payments/utils/sepa_models.py
python -m py_compile vereinigingen/verenigingen_payments/utils/sepa_operations_simple.py
python -m py_compile verenigingen/verenigingen_payments/utils/frappe_native_sepa_operations.py
python -m py_compile vereinigingen/verenigingen_payments/utils/frappe_native_sepa_operations_optimized.py
python -m py_compile verenigingen/verenigingen_payments/utils/sepa_operations_bulk_true.py
```

**Step 8: Commit**

```bash
git add vereinigingen/vereinigingen_payments/utils/
git add vereinigingen/utils/sepa_*.py vereinigingen/tests/test_sepa_*.py
git commit -m "refactor: extract shared SEPA models and validation (-200 LOC)"
```

---

## Task 7: e_boekhouden — Consolidate Company Party Creation

**Files:**
- Modify: `vereinigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py:992-1065`

**Step 1: Read the 5 party creation functions (3-7)**

Read lines 938-1065 to see the full code for:
- `_get_or_create_generic_party()` (lines 938-989) — already the canonical version
- `_get_or_create_generic_customer()` (lines 992-994) — 1-line wrapper, keep as-is
- `_get_or_create_generic_supplier()` (lines 997-999) — 1-line wrapper, keep as-is
- `_get_or_create_company_as_customer()` (lines 1002-1032) — duplicates generic_party pattern
- `_get_or_create_company_as_supplier()` (lines 1035-1065) — duplicates generic_party pattern

**Step 2: Extract `_get_or_create_company_party()`**

Functions 6 and 7 are identical except for `party_type` ("Customer" vs "Supplier") and the name suffix. Extract:

```python
def _get_or_create_company_party(party_type, company, debug_info):
    """Get or create the company as a customer or supplier for internal transactions.

    Uses centralized BankTransactionParser for party creation to ensure
    consistent matching and creation logic across the codebase.

    Args:
        party_type: "Customer" or "Supplier"
        company: Company name
        debug_info: List to append debug messages to
    """
    try:
        from vereinigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

        party_name_candidate = f"{company} (Internal)"

        parser = BankTransactionParser()
        party_name, created = parser.find_or_create_party(
            party_name=party_name_candidate,
            party_type=party_type,
            iban=None,
        )

        if created:
            debug_info.append(f"Created company {party_type.lower()}: {party_name}")
        else:
            debug_info.append(f"Found existing company {party_type.lower()}: {party_name}")

        return party_name

    except Exception as e:
        debug_info.append(f"Error creating company {party_type.lower()}: {str(e)}")
        return None


def _get_or_create_company_as_customer(company, debug_info):
    """Get or create the company as a customer for internal transactions."""
    return _get_or_create_company_party("Customer", company, debug_info)


def _get_or_create_company_as_supplier(company, debug_info):
    """Get or create the company as a supplier for internal transactions."""
    return _get_or_create_company_party("Supplier", company, debug_info)
```

**Step 3: Verify**

Run: `python -m py_compile vereinigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py`

**Step 4: Commit**

```bash
git add verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py
git commit -m "refactor: consolidate company party creation into _get_or_create_company_party()"
```

---

## Task 8: e_boekhouden — Extract Shared Invoice Creation Logic

**Files:**
- Modify: `verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py:2225-2332,2837-2942`

**Step 1: Read both invoice creation functions side by side**

Read `_create_sales_invoice()` (lines 2225-2332) and `_create_purchase_invoice()` (lines 2837-2942). Map the differences:

| Aspect | Sales Invoice | Purchase Invoice |
|--------|--------------|------------------|
| Doc type | `Sales Invoice` | `Purchase Invoice` |
| Party field | `customer` | `supplier` |
| Party resolver | `resolve_customer()` | `resolve_supplier()` |
| Reference field | `po_no` | `bill_no` + `supplier_invoice_no` |
| Account field | `debit_to` | `credit_to` |
| Account resolver | `_resolve_receivable_account()` | `_resolve_payable_account()` |
| Line item processor | `_process_invoice_line_items()` | `_process_purchase_invoice_line_items()` |
| Parallel validation | No | `_run_parallel_credit_note_validation()` |

**Step 2: Extract `_setup_invoice_common()`**

Extract the 80%+ shared setup logic:

```python
def _setup_invoice_common(doc, mutation_detail, company, cost_center, debug_info):
    """Set up common fields shared between sales and purchase invoices.

    Handles: company, posting_date, currency, payment terms, remarks,
    credit note detection, custom tracking fields, fiscal year, and submission.

    Args:
        doc: The invoice document (Sales Invoice or Purchase Invoice)
        mutation_detail: eBoekhouden mutation data
        company: Company name
        cost_center: Cost center
        debug_info: Debug message list

    Returns:
        tuple: (is_credit_note, effective_total_amount) or None if credit note detection fails
    """
    from frappe.utils import add_days
    from .invoice_helpers import get_or_create_payment_terms

    mutation_id = mutation_detail.get("id")
    description = mutation_detail.get("description", f"eBoekhouden Import {mutation_id}")
    invoice_number = mutation_detail.get("invoiceNumber")

    # Basic fields
    doc.company = company
    doc.posting_date = mutation_detail.get("date")
    doc.set_posting_time = 1

    # Currency
    company_currency = frappe.db.get_value("Company", company, "default_currency") or "EUR"
    doc.currency = company_currency
    doc.conversion_rate = 1.0

    # Payment terms and due date
    payment_days = mutation_detail.get("Betalingstermijn", 30)
    if payment_days:
        try:
            payment_terms = get_or_create_payment_terms(payment_days)
            if payment_terms:
                doc.payment_terms_template = payment_terms
            doc.due_date = add_days(doc.posting_date, payment_days)
        except Exception as e:
            debug_info.append(f"Warning: Failed to create payment terms for {payment_days} days: {str(e)}")
            doc.due_date = add_days(doc.posting_date, payment_days)

    # Description
    doc.remarks = description

    # Credit note detection
    credit_note_result = _detect_credit_note_improved(mutation_detail, debug_info)
    if credit_note_result is None:
        debug_info.append("ERROR: Credit note detection returned None - skipping invoice creation")
        return None

    is_credit_note, effective_total_amount = credit_note_result
    doc.is_return = is_credit_note

    if is_credit_note:
        debug_info.append(
            f"Processing as credit note (effective amount: {effective_total_amount}), will convert amounts to positive"
        )

    # Custom tracking fields
    doc.eboekhouden_mutation_nr = str(mutation_id)
    if invoice_number:
        doc.eboekhouden_invoice_number = invoice_number

    return is_credit_note, effective_total_amount
```

**Step 3: Extract `_save_and_submit_invoice()`**

```python
def _save_and_submit_invoice(doc, company, debug_info):
    """Save and submit an invoice with fiscal year handling.

    Args:
        doc: The invoice document
        company: Company name
        debug_info: Debug message list
    """
    invoice_type = doc.doctype

    try:
        doc.save()
        debug_info.append(f"Saved {invoice_type} draft: {doc.name}")
    except Exception as save_error:
        debug_info.append(f"ERROR: Failed to save {invoice_type}: {str(save_error)}")
        raise

    from .invoice_helpers import ensure_fiscal_year_exists

    try:
        ensure_fiscal_year_exists(doc.posting_date, company, debug_info)
    except Exception as fy_error:
        debug_info.append(f"WARNING: Could not ensure fiscal year: {str(fy_error)}")

    try:
        doc.submit()
        debug_info.append(f"Submitted {invoice_type}: {doc.name}")
    except Exception as submit_error:
        debug_info.append(f"ERROR: Failed to submit {invoice_type} {doc.name}: {str(submit_error)}")
        debug_info.append(f"Submit error type: {type(submit_error).__name__}")
        raise

    debug_info.append(f"Created enhanced {invoice_type} {doc.name} with {len(doc.items)} line items")
```

**Step 4: Simplify `_create_sales_invoice()` and `_create_purchase_invoice()`**

```python
def _create_sales_invoice(mutation_detail, company, cost_center, debug_info):
    """Create Sales Invoice with ALL available fields from detailed mutation data"""
    from .party_resolver import resolve_customer

    mutation_id = mutation_detail.get("id")
    description = mutation_detail.get("description", f"eBoekhouden Import {mutation_id}")
    invoice_number = mutation_detail.get("invoiceNumber")
    relation_id = mutation_detail.get("relationId")

    debug_info.append(f"Creating Sales Invoice for mutation {mutation_id}")

    si = frappe.new_doc("Sales Invoice")

    # Common setup
    result = _setup_invoice_common(si, mutation_detail, company, cost_center, debug_info)
    if result is None:
        return None
    is_credit_note, effective_total_amount = result

    # Sales-specific fields
    customer = resolve_customer(relation_id, debug_info)
    si.customer = customer

    if mutation_detail.get("Referentie"):
        si.po_no = mutation_detail.get("Referentie")

    receivable_account = _resolve_receivable_account(mutation_detail, company, debug_info)
    if receivable_account:
        si.debit_to = receivable_account

    # Process line items
    _process_invoice_line_items(
        si, mutation_detail, cost_center, is_credit_note, invoice_number, description, company, debug_info
    )

    # Save and submit
    _save_and_submit_invoice(si, company, debug_info)
    return si


def _create_purchase_invoice(mutation_detail, company, cost_center, debug_info):
    """Create Purchase Invoice with ALL available fields from detailed mutation data"""
    from .party_resolver import resolve_supplier

    mutation_id = mutation_detail.get("id")
    description = mutation_detail.get("description", f"eBoekhouden Import {mutation_id}")
    invoice_number = mutation_detail.get("invoiceNumber")
    relation_id = mutation_detail.get("relationId")

    debug_info.append(f"Creating Purchase Invoice for mutation {mutation_id}")

    pi = frappe.new_doc("Purchase Invoice")

    # Common setup
    result = _setup_invoice_common(pi, mutation_detail, company, cost_center, debug_info)
    if result is None:
        return None
    is_credit_note, effective_total_amount = result

    # Purchase-specific fields
    supplier = resolve_supplier(relation_id, debug_info)
    pi.supplier = supplier

    if invoice_number:
        pi.bill_no = invoice_number
    if mutation_detail.get("Referentie"):
        pi.supplier_invoice_no = mutation_detail.get("Referentie")

    # Parallel credit note validation (purchase only)
    _run_parallel_credit_note_validation(
        mutation_id, mutation_detail, is_credit_note, effective_total_amount, debug_info
    )

    payable_account = _resolve_payable_account(mutation_detail, company, debug_info)
    if payable_account:
        pi.credit_to = payable_account

    # Process line items
    _process_purchase_invoice_line_items(
        pi, mutation_detail, cost_center, is_credit_note, company, debug_info
    )

    # Save and submit
    _save_and_submit_invoice(pi, company, debug_info)
    return pi
```

**Step 5: Verify**

Run: `python -m py_compile verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py`

**Step 6: Commit**

```bash
git add verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py
git commit -m "refactor: extract _setup_invoice_common() and _save_and_submit_invoice() (-100 LOC)"
```

---

## Task 9: Final Verification and Audit Update

**Step 1: Run py_compile on all modified files**

```bash
find vereinigingen/ -name "*.py" -newer docs/plans/2026-02-23-phase2-deduplication-plan.md | \
    xargs -I{} python -m py_compile {}
```

**Step 2: Run ruff check**

```bash
ruff check vereinigingen/utils/validation/api_validators.py \
    vereinigingen/permissions.py \
    verenigingen/events/subscribers/ \
    verenigingen/vereinigingen_payments/utils/ \
    verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py
```

**Step 3: Grep for dangling imports**

```bash
grep -r "from.*sepa_operations_simple import SimpleSEPAOperation" vereinigingen/ --include="*.py"
grep -r "IBAN_PATTERN" verenigingen/utils/validation/api_validators.py
grep -r "EMAIL_PATTERN" verenigingen/utils/validation/api_validators.py
```

**Step 4: Update audit report**

Update `docs/audits/codebase-dry-solid-kiss-audit-2026-02-23.md`:
- Phase 2 status → COMPLETED
- Update LOC metrics
- Mark completed items in worst offenders table

**Step 5: Commit**

```bash
git add docs/audits/codebase-dry-solid-kiss-audit-2026-02-23.md
git commit -m "docs: update audit report with Phase 2 deduplication results"
```

---

## Verification Checklist

After all tasks, confirm:

- [ ] `python -m py_compile` passes on all modified files
- [ ] `ruff check` passes on all modified files
- [ ] No dangling imports (grep for removed class/function names)
- [ ] SEPA test files still compile (even if we can't run them without bench)
- [ ] Audit report updated with Phase 2 results
