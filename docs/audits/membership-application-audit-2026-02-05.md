# Membership Application Logic — Architecture Audit Report

**Date:** 2026-02-05
**Scope:** DRY violations, separation of concerns, tech debt, future maintainability
**Files Reviewed:** 30+ files, ~14,000 LOC in core flow
**Branch:** develop (commit 33ba6e40)

---

## Executive Summary

The membership application flow spans ~14,000 lines across 10 core files and 20+ supporting files. The architecture shows a partially-completed migration from monolithic API files toward a service layer pattern. This migration has left the codebase in a transitional state where **three competing approval orchestrators** coexist, **business logic is duplicated across layers**, and **deprecated code remains in production paths**.

The most impactful issues are:
1. `create_membership_and_invoice()` duplicated across 3 files with diverging logic
2. Three parallel approval flows that set status fields differently
3. ~650 lines of validation endpoint boilerplate that could be a generic wrapper
4. Two parallel notification systems (deprecated + current) both active in production
5. `fraud_detection.py` with 17 stub methods giving a false sense of security

---

## Table of Contents

1. [File Inventory & Line Counts](#1-file-inventory--line-counts)
2. [High Priority Findings (Score 85+)](#2-high-priority-findings)
3. [Medium Priority Findings (Score 70-84)](#3-medium-priority-findings)
4. [Lower Priority Findings (Score 60-69)](#4-lower-priority-findings)
5. [Structural Observations](#5-structural-observations)
6. [Cross-Layer Issues](#6-cross-layer-issues)
7. [Recommended Refactoring Roadmap](#7-recommended-refactoring-roadmap)

---

## 1. File Inventory & Line Counts

### Core Application Flow

| File | LOC | Role |
|------|-----|------|
| `api/membership_application.py` | 1,903 | Public-facing application endpoints |
| `api/membership_application_review.py` | 2,318 | Admin review/approval endpoints (LARGEST) |
| `utils/application_helpers.py` | 1,505 | Mixed utilities + business logic |
| `utils/application_notifications.py` | 594 | Notification functions (many deprecated) |
| `api/background_approval_api.py` | 334 | Background approval processing |
| `public/js/membership_application.js` | 4,960 | Frontend application form |
| `templates/pages/apply_for_membership.py` | 215 | Page context builder |
| `templates/pages/membership_application.py` | ~250 | Alternative page context builder |
| `verenigingen/doctype/member/member.py` | 963 | Member DocType controller |
| **Total core** | **~13,042** | |

### Service Layer

| File | LOC | Role |
|------|-----|------|
| `services/member/approval/member_approval_service.py` | 510 | Module-level approval functions |
| `services/member/approval/membership_creation_service.py` | 610 | Membership creation on approval |
| `services/member/core/member_lifecycle_service.py` | 702 | Class-based lifecycle service |
| `services/member/core/member_status_service.py` | ~160 | Status field synchronization |
| `services/member/validation/member_validation_service.py` | ~284 | Validation orchestration |
| `services/member/validation/member_duplicate_detection_service.py` | 541 | Duplicate member detection |
| `services/member/lifecycle/member_before_save_service.py` | ~200 | Before-save hook handler |
| `services/member/lifecycle/member_event_emission_service.py` | ~150 | Event emission on status change |
| `services/member/lifecycle/member_status_notification_service.py` | 178 | Status change notifications |
| `services/member/lifecycle/member_cleanup_service.py` | 379 | Cascade deletion handler |
| `services/member/account/member_user_account_service.py` | ~420 | User account creation |
| `services/member/account/member_role_service.py` | ~180 | Role assignment |
| `services/member/chapter/chapter_management_service.py` | ~450 | Chapter membership queries |
| `services/member/core/member_fee_change_service.py` | ~183 | Fee override tracking |
| `services/member/financial/member_fee_calculation_service.py` | ~200 | Fee calculation |
| **Total services** | **~5,147** | |

### Supporting Files

| File | LOC | Role |
|------|-----|------|
| `utils/fraud_detection.py` | 589 | Fraud detection (mostly stubs) |
| `utils/application_payments.py` | ~300 | Payment processing utilities |
| `setup/membership_application_workflow_setup.py` | ~350 | Workflow configuration |
| `notification_registry.py` | ~100 | Notification key definitions |
| `services/communication/email_service.py` | ~450 | Email delivery service |

---

## 2. High Priority Findings

### 2.1 `create_membership_and_invoice()` Duplicated Across 3 Files — RESOLVED

**Status:** Resolved 2026-02-05. Duplicates deleted; canonical path is `MembershipCreationService.create_membership_on_approval()`.

**Confidence:** 95/100
**Category:** DRY violation
**Estimated waste:** ~380 LOC

The same function exists in THREE locations with near-identical but subtly diverging logic:

#### Location A: `api/membership_application_review.py:68-123`

```python
def create_membership_and_invoice(member, membership_type):
    existing_membership = frappe.db.get_value(
        "Membership", {"member": member.name, "status": ["in", ["Active", "Draft"]]}, "name"
    )
    if existing_membership:
        membership = frappe.get_doc("Membership", existing_membership)
        if membership.membership_type != membership_type:
            membership.membership_type = membership_type
            membership.save()
    else:
        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": member.name,
            "membership_type": membership_type,
            "start_date": today(),
            "status": "Draft",
        })
        membership.insert()

    membership_type_doc = frappe.get_doc("Membership Type", membership_type)
    billing_amount = 0
    if hasattr(member, "dues_rate") and member.dues_rate:
        billing_amount = member.dues_rate
    elif membership_type_doc.dues_schedule_template:
        template = frappe.get_doc("Membership Dues Schedule", membership_type_doc.dues_schedule_template)
        billing_amount = template.dues_rate or template.suggested_amount or 0
    if not billing_amount:
        billing_amount = membership_type_doc.minimum_amount

    membership.submit()  # <-- SUBMITS membership
    return membership, membership_type_doc, billing_amount
```

#### Location B: `services/member/approval/member_approval_service.py:183-310`

```python
def create_membership_and_invoice(member, membership_type, create_invoice=True):
    # Same existing membership check...
    # Same membership creation...

    # ADDITIONAL: Respects application_dues_schedule (user's selection during application)
    application_dues_schedule = getattr(member, "application_dues_schedule", None)
    if application_dues_schedule:
        if frappe.db.exists("Membership Dues Schedule", application_dues_schedule):
            schedule_doc = frappe.get_doc("Membership Dues Schedule", application_dues_schedule)
            if schedule_doc.is_template:
                dues_schedule_template = application_dues_schedule
    # Falls back to membership type default...

    # Does NOT submit membership (different from Location A)
    # Returns create_service_result() dict instead of tuple
```

#### Location C: `services/member/approval/membership_creation_service.py`

```python
class MembershipCreationService:
    def create_membership_on_approval(self, member_doc, ...):
        # Yet another wrapper with additional parameters:
        # - custom_dues_rate, custom_rate_reason, is_csv_import, approval_fields
        # Contains its own membership creation + dues schedule logic
```

#### Divergences

| Behavior | Review API (A) | Approval Service (B) | Creation Service (C) |
|----------|---------------|---------------------|---------------------|
| Submits membership | Yes | No | Configurable |
| Respects `application_dues_schedule` | No | Yes | Unknown |
| Return type | `tuple(membership, type_doc, amount)` | `dict` via `create_service_result()` | Via service method |
| Invoice creation | External | Delegated to `application_payments` | Internal |
| CSV import support | No | No | Yes |

#### Risk

A bug fix in Location B (e.g., the `application_dues_schedule` logic added at line 233) was never backported to Location A. Any future changes to billing logic must be applied in all three places.

#### Recommendation

Delete Locations A and B. Make `MembershipCreationService` the single canonical entry point. The review API should call the service.

---

### 2.2 Three Competing Approval Orchestrators — RESOLVED

**Status:** Resolved 2026-02-05. Unified into single canonical path via `member.create_membership_on_approval()`. Commit `ad5582ad`.

**Confidence:** 95/100
**Category:** Separation of concerns
**Estimated confusion surface:** ~800 LOC across 3 paths

#### Path 1: `MemberLifecycleService.approve_application()` (lifecycle service)

**File:** `services/member/core/member_lifecycle_service.py:96-179`
**Called by:** `Member.approve_application()` (DocType method, line 378)

```
Member.approve_application()
  → MemberLifecycleService.approve_application()
    → FOR UPDATE row lock
    → _validate_application_approval()
    → member.generate_member_id()
    → Set: application_status="Approved", status="Active", reviewed_by, review_date
    → member.flags.ignore_status_validation = True
    → _save_member_with_retry()
    → _perform_post_approval_setup()
      → Create user account
      → Create customer
      → Activate pending chapter memberships
```

#### Path 2: `process_member_approval()` (approval service)

**File:** `services/member/approval/member_approval_service.py:395-454`
**Imported by:** `api/membership_application_review.py` (line 16)

```
process_member_approval(member_name, ...)
  → frappe.get_doc("Member", member_name)
  → resolve_membership_type()
  → create_member_iban_history()
  → create_membership_and_invoice()  ← service version
  → finalize_member_approval()
    → Set: application_status="Approved", status="Active", member_since, reviewed_by, review_date
    → _system_update = True
    → member.save() with retry
```

#### Path 3: `approve_membership_application()` (review API)

**File:** `api/membership_application_review.py:126-267+`
**Called by:** Frontend admin review page

```
approve_membership_application(member_name, ...)
  → Input sanitization (APIValidator)
  → Idempotency check (already approved?)
  → validate_chapter_permission_or_throw()
  → resolve_membership_type()  ← from approval service
  → validate_membership_type_for_approval()
  → member.approve_application()  ← triggers Path 1
  → create_membership_and_invoice()  ← LOCAL copy (Location A), NOT service version
  → Chapter assignment
  → Volunteer activation
  → Notification sending
```

#### The Problem

Path 3 calls into Path 1 (via `member.approve_application()`) but then also calls its own local `create_membership_and_invoice()` — NOT the service layer version. This means:

- Status fields are set by Path 1 (lifecycle service)
- Membership/invoice creation is done by Path 3's local function
- `process_member_approval()` from the approval service is imported but its orchestration overlaps with Path 3
- Post-approval setup (user, customer, chapter) happens in Path 1 AND partially in Path 3

#### Recommendation

1. Make the review API a thin HTTP layer: input validation, permission checks, response formatting
2. Route all business logic through ONE orchestrator (lifecycle service or approval service, not both)
3. Delete the local `create_membership_and_invoice()` from the review API

---

### 2.3 Triple Fee Query Duplication — RESOLVED

**Status:** Resolved 2026-02-05. See `docs/plans/2026-02-05-consolidate-fee-queries.md` for implementation details.

**Confidence:** 92/100
**Category:** DRY violation
**Estimated waste:** ~270 LOC (3 business functions + 3 endpoint wrappers + 3 legacy aliases = 9 functions)

#### Three business functions in `utils/application_helpers.py`:

**`get_membership_fee_info()` (lines 905-938)**
```python
def get_membership_fee_info(membership_type):
    membership_type_doc = frappe.get_doc("Membership Type", membership_type)
    if membership_type_doc.dues_schedule_template:
        template = frappe.get_doc("Membership Dues Schedule", ...)
        base_amount = template.dues_rate or template.suggested_amount or 0
        billing_frequency = template.billing_frequency or "Annual"
    # Returns: {amount, billing_frequency, minimum_amount, ...}
```

**`get_membership_type_details()` (lines 941-1001)**
```python
def get_membership_type_details(membership_type):
    membership_type_doc = frappe.get_doc("Membership Type", membership_type)
    if membership_type_doc.dues_schedule_template:
        template = frappe.get_doc("Membership Dues Schedule", ...)
        # Same resolution logic as above, plus description/name fields
    # Returns: {name, description, amount, billing_frequency, ...}
```

**`suggest_membership_amounts()` (lines 1019-1083)**
```python
def suggest_membership_amounts(membership_type_name):
    membership_type_doc = frappe.get_doc("Membership Type", membership_type_name)
    if membership_type_doc.dues_schedule_template:
        template = frappe.get_doc("Membership Dues Schedule", ...)
        # Same resolution logic, plus suggested amounts list
    # Returns: {suggested_amounts: [...], minimum, maximum, ...}
```

All three:
1. Load `frappe.get_doc("Membership Type", membership_type)`
2. Check `membership_type_doc.dues_schedule_template`
3. Load the template doc
4. Resolve `dues_rate` vs `suggested_amount` with same fallback

#### Three endpoint wrappers in `api/membership_application.py`:

- `get_membership_fee_info_endpoint()` (line 869) → calls `get_membership_fee_info()`
- `get_membership_type_details_endpoint()` (line 888) → calls `get_membership_type_details()`
- `suggest_membership_amounts_endpoint()` (line 907) → calls `suggest_membership_amounts()`

#### Three legacy aliases in `api/membership_application.py`:

- `get_membership_fee_info()` (line 1686) → calls `get_membership_fee_info_endpoint()`
- `get_membership_type_details()` (line 1679) → calls `get_membership_type_details_endpoint()`
- `suggest_membership_amounts()` (line 1693) → calls `suggest_membership_amounts_endpoint()`

#### Also duplicated in template page:

- `templates/pages/membership_application.py:222` has its own `get_membership_type_details()`

#### Recommendation

Create `MembershipFeeService.get_fee_details(membership_type)` that returns all data in one query. The 9 functions become 1 service + 3 thin endpoint wrappers.

---

### 2.4 Validation Endpoint Boilerplate (~650 LOC) — RESOLVED

**Status:** Resolved 2026-02-05. Three helper functions (`_wrap_validation`, `_wrap_data_fetch`, `_wrap_success_check`) extract repeated try/except/OperationResult boilerplate from 14 endpoints. `check_application_eligibility_endpoint` kept as-is due to unique error shape.

**Confidence:** 90/100
**Category:** DRY violation
**Estimated waste:** ~650 LOC (reduced by ~125 LOC with centralized wrappers)

`api/membership_application.py` lines 193-850 contains 20+ validation endpoints. Every one follows this identical pattern:

```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def validate_XXX(arg):
    try:
        validated_arg = APIValidator.validate_XXX(arg)
        result = validate_XXX_util(validated_arg)
        if result.get("valid"):
            return OperationResult.ok(result, message=_("XXX is valid"))
        else:
            return OperationResult.fail(
                _(result.get("message", "Validation failed")),
                errors=[result.get("type", "validation_error")],
                context=result,
            )
    except ValidationError as e:
        return OperationResult.fail(str(e), errors=["validation_error"])
    except Exception as e:
        log_error(f"Validation error: {str(e)}", "Validation Error")
        return OperationResult.fail(_("Validation service error"), errors=[str(e)])
```

Affected endpoints: `validate_email`, `validate_phone_number`, `validate_birth_date`, `validate_postal_code`, `validate_name`, `validate_custom_amount`, `validate_iban`, `validate_address`, and 12+ more.

#### Recommendation

```python
def _wrap_validation(validator_fn, *args, field_name="field"):
    """Generic validation wrapper eliminating 600+ lines of boilerplate."""
    try:
        result = validator_fn(*args)
        if result.get("valid"):
            return OperationResult.ok(result, message=_(f"{field_name} is valid"))
        return OperationResult.fail(
            _(result.get("message", "Validation failed")),
            errors=[result.get("type", "validation_error")],
            context=result,
        )
    except ValidationError as e:
        return OperationResult.fail(str(e), errors=["validation_error"])
    except Exception as e:
        frappe.log_error(f"Validation error for {field_name}: {str(e)}")
        return OperationResult.fail(_("Validation service error"))

@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def validate_email(email):
    validated = APIValidator.validate_email(email)
    return _wrap_validation(validate_email_util, validated, field_name="Email")
```

---

## 3. Medium Priority Findings

### 3.1 Deprecated Notifications Still in Production (594 LOC) -- RESOLVED

**Confidence:** 85/100
**Category:** Tech debt
**Status:** RESOLVED — All 9 deprecated functions deleted, 3 callers migrated to modern services.

All deprecated inline HTML notification functions have been removed from `utils/application_notifications.py`:
- **Deleted (dead code):** `format_email_subject`, `send_application_confirmation_email`, `notify_reviewers_of_new_application`, `notify_admins_of_new_application`, `send_simple_notification`, `get_application_reviewers`
- **Migrated then deleted:** `send_rejection_email` → `send_rejection_notification` (review API), `send_payment_confirmation_email` → `MemberStatusNotificationService`, `send_approval_email` → `send_approval_notification` (review API)

The module now contains only `check_overdue_applications()` (active scheduled task). ~470 LOC removed.

Remaining notification architecture (not in scope — working correctly):
- `send_approval_notification()` / `send_rejection_notification()` in review API use `EmailService`
- `MemberStatusNotificationService` handles status change notifications
- `notification_registry.py` defines notification keys

---

### 3.2 Custom Amount Handling Duplicated (~120 LOC) -- RESOLVED

**Confidence:** 82/100
**Category:** DRY violation
**Status:** RESOLVED (2026-02-06)

Extracted 3 shared helper functions in `utils/application_helpers.py`:

1. **`_sanitize_application_names(data)`** -- Validates and sanitizes 4 name fields, returns tuple. Replaces ~52 LOC of duplication.
2. **`_apply_custom_contribution_fee(member, data, context_label)`** -- Applies custom fee override fields with 3-tier user fallback and parameterized reason message. Replaces ~92 LOC of duplication.
3. **`_append_chapter_notes(member, selected_chapter, label)`** -- Appends chapter display info to member notes with parameterized label. Replaces ~30 LOC of duplication.

Both `create_member_from_application()` and `update_member_from_reapplication()` now call these helpers. Characterization tests in `tests/backend/unit/utils/test_application_helpers_reapplication.py` (7 tests) serve as safety net.

---

### 3.3 Payment Methods Defined in 5 Separate Files

**Status:** CONFIRMED — deferred to dedicated planning session (complex, high-risk refactor)
**Confidence:** 80/100
**Category:** DRY violation, no single source of truth

| File | Function/Definition | LOC |
|------|-------------------|-----|
| `api/membership_application.py:980` | `get_payment_methods_endpoint()` | API wrapper |
| `api/membership_application.py:1700` | `get_payment_methods()` | Legacy alias |
| `templates/pages/apply_for_membership.py:101` | `get_payment_methods(settings)` | Page context with defaults |
| `utils/application_helpers.py:125` | `map_payment_method()` | Bidirectional mapping dict |
| `utils/application_payments.py:280` | `get_payment_methods()` | Payment utility |
| `verenigingen_payments/hooks/api.py:19` | `get_payment_methods()` | Payment module API |

The `map_payment_method()` function contains a mapping that includes both slug→display AND display→display entries:

```python
payment_method_map = {
    "bank_transfer": "Bank Transfer",
    "sepa_direct_debit": "SEPA Direct Debit",
    # ... plus identity mappings:
    "Bank Transfer": "Bank Transfer",
    "SEPA Direct Debit": "SEPA Direct Debit",
}
```

JavaScript also hardcodes payment method names (line 3368-3435):
```javascript
const is_direct_debit = methodName === 'SEPA Direct Debit' || normalizedMethod === 'sepadirectdebit';
```

#### Investigation Findings (2026-02-06)

**5 locations confirmed** with the following inconsistencies:

1. **Snake_case vs Title Case**: Form sends `"bank_transfer"`, database stores `"Bank Transfer"`. `map_payment_method()` is the single conversion point — if it fails, application submission fails.
2. **Multiple fallback chains**: Template defaults (3 methods), API descriptions (4 methods), and `ensure_payment_modes_exist()` (4 methods) don't stay in sync.
3. **Incomplete recovery**: `ensure_payment_modes_exist()` only creates Bank Transfer, SEPA Direct Debit, Mollie, Cash — but `Application Payment Method` options include ideal, credit_card, paypal (no recovery path for those 3).
4. **3 different `get_payment_methods()` functions**: `application_payments.py` queries Mode of Payment, `apply_for_membership.py` reads Settings child table, `verenigingen_payments/hooks/api.py` uses PaymentHook abstraction.
5. **Description mismatch**: Template defaults and API descriptions list different methods with different descriptions.

**Deferred because:** The bidirectional conversion is load-bearing, JavaScript hardcodes Title Case values throughout, and the `Application Payment Method` child DocType already partially exists. Needs careful planning to avoid breaking the application submission flow.

#### Recommendation

Create a single `PAYMENT_METHODS` configuration constant (or a `Payment Method` DocType) that all layers import from.

---

### 3.4 Chapter Membership State Transitions Scattered

**Status:** NOT A DRY VIOLATION — different workflows, correctly separated
**Confidence:** 78/100 (original) → revised down after investigation
**Category:** Separation of concerns

Chapter membership operations live in `utils/application_helpers.py`:

| Function | Lines | Purpose |
|----------|-------|---------|
| `create_pending_chapter_membership()` | 1208-1278 | Create Pending record |
| `activate_pending_chapter_membership()` | 1280-1355 | Pending → Active |
| `create_active_chapter_membership()` | 1357-1455 | Create Active directly |
| `remove_pending_chapter_membership()` | 1457-1527 | Remove on rejection |

These are called from:
- `member_lifecycle_service.py:560` (post-approval setup)
- `member_lifecycle_service.py:596` (post-rejection cleanup)
- `events/subscribers/approval_subscribers.py:100` (background job on approval)
- Application submission flow in `membership_application.py:686`

There's also a `ChapterMembershipManager` and a `ChapterManagementService` that handle similar operations through different interfaces.

#### Investigation Findings (2026-02-06)

**These are NOT true duplication.** The standalone functions and `ChapterMembershipManager` serve fundamentally different workflows:

| Aspect | Standalone Functions | ChapterMembershipManager |
|--------|---------------------|--------------------------|
| **Purpose** | Application lifecycle state machine | General chapter management |
| **State model** | Pending → Active (two-phase) | Direct Active assignment (no Pending) |
| **Callers** | submit_application, approve, reject | Manual management, bulk imports |
| **History** | Explicit two-phase history updates | Single-step via MemberManager |
| **Delegation** | Direct child table manipulation | Via Chapter.member_manager property |

The Pending status concept only exists in the application workflow. `ChapterMembershipManager.assign_member_to_chapter()` creates Active members directly — it doesn't support the Pending state at all. `ChapterManagementService` is purely read/query operations — no overlap.

Good test coverage exists: `test_chapter_member_status.py`, `test_chapter_membership_workflow.py`, `test_chapter_membership_approval_integration.py`.

#### Recommendation

~~Consolidate into `ChapterMembershipManager` as the single entry point. Remove the 4 standalone functions from `application_helpers.py`. All call sites should use the manager.~~

**Revised:** Keep separate. The 4 standalone functions implement a Pending→Active state machine specific to the application workflow. Could optionally extract into an `ApplicationChapterWorkflow` service class for better organization, but this is cosmetic not a DRY fix. No code changes needed.

---

### 3.5 Fraud Detection Module — 589 Lines of Mostly Stubs — RESOLVED

**Status:** RESOLVED (2026-02-06) — Module deleted. No production code imported or called it. Admin tools card and whitelist entry removed.
**Confidence:** 75/100
**Category:** Tech debt / false sense of security

~~`utils/fraud_detection.py` contained 17 helper methods returning hardcoded values (empty lists, False, 0, True), making all risk scoring ineffective. No production code actually imported or called `FraudPreventionService.validate_membership_application()`. The duplicate detection service (`duplicate_detection_service.py`) already handles the most relevant check (duplicate applications).~~

#### ~~Recommendation~~

~~Either implement the methods fully, or gate them behind a feature flag.~~

**Resolution:** Deleted entirely. Duplicate detection (the real concern) lives in a separate, functional service.

---

### 3.6 Status Setting Logic Duplicated Across 3 Services — PARTIALLY RESOLVED

**Confidence:** 85/100
**Category:** DRY violation
**Status:** PARTIALLY RESOLVED (2026-02-06) — 2 of 4 locations eliminated:
- `finalize_member_approval()` deleted in audit item 2.2
- `set_application_status_defaults()` in lifecycle service deleted — orphaned method with zero callers; canonical version lives in `member_status_service` (commit: `refactor: delete orphaned set_application_status_defaults from lifecycle service`)

**Remaining (not true duplication — different flows):**
- `approve_application()` in lifecycle service sets status fields during approval workflow (deprecated but has test callers — scoped to unification plan)
- `set_member_application_status_defaults()` in `member_status_service` sets defaults during before_save (canonical)

These two remaining locations serve different purposes: one is the approval action (setting Approved/Active), the other is the before-save default (setting Pending/Approved for new documents). They are not candidates for further consolidation.

**`member_lifecycle_service.py:96-179` (`approve_application`)** — deprecated, test-only callers
```python
member.application_status = "Approved"
member.status = "Active"
member.reviewed_by = frappe.session.user
member.review_date = now_datetime()
member.flags.ignore_status_validation = True
# Does NOT set member_since or _system_update
```

**`member_status_service.py:26-64` (`set_member_application_status_defaults`)** — CANONICAL
```python
if not getattr(member_doc, "application_status", ""):
    if not member_doc.name or member_doc.is_new():
        member_doc.application_status = "Pending"
    else:
        member_doc.application_status = "Approved"
```

---

### 3.7 ~~Duplicate Role and Permission Logic~~ RESOLVED

**Confidence:** 78/100
**Category:** DRY violation
**Status:** RESOLVED (2026-02-06) — Removed redundant `frappe.has_permission("User", "write")` check from private `_assign_individual_member_roles()`. The caller `add_member_roles_to_user()` already performs this check before invoking the private method. The role clearing patterns (lines 83-101 and 154-171) are intentionally different — one assigns a role profile, the other appends individual roles — so those remain as-is. Commit: `refactor: remove redundant permission check from private _assign_individual_member_roles`.

---

### 3.8 ~~Duplicate Member Existence Validation~~ RESOLVED

**Confidence:** 75/100
**Category:** DRY violation
**Status:** RESOLVED (2026-02-06) — Extracted `_validate_member_exists()` private helper method in `ChapterManagementService`. 4 inline checks replaced with single-line calls. Null/empty checks left inline (different return values per method). Commit: `refactor: extract _validate_member_exists to DRY 4 identical checks`.

---

## 4. Lower Priority Findings

### 4.1 Legacy Endpoint Aliases (75 LOC)

**Confidence:** 72/100

`api/membership_application.py:1656-1731` contains 16 functions that simply redirect:

```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def get_membership_type_details(membership_type):
    """Legacy endpoint"""
    return get_membership_type_details_endpoint(membership_type)
```

These maintain backward compatibility but add 75 lines of pure boilerplate. Consider URL routing aliases or a single dispatch function.

### 4.2 Duplicate Context Fetching in Template Pages

**Confidence:** 70/100

Both `apply_for_membership.py` and `membership_application.py` fetch identical context:

```python
# Both files contain:
settings = frappe.get_single("Verenigingen Settings")
context.enable_income_calculator = getattr(settings, "enable_income_calculator", 0)
context.income_percentage_rate = getattr(settings, "income_percentage_rate", 0.5)
context.calculator_description = getattr(settings, "calculator_description", "...")
```

Should be extracted to a shared `build_membership_application_context()` function.

### 4.3 Billing Period Resolution in 3 Places

**Confidence:** 70/100

Billing period is resolved differently in Python and JavaScript:

- **Python** (`membership_application.py:318`): Explicit map `{"Monthly": "per month", ...}`
- **JavaScript** (`membership_application.js:106`): Cascading fallback `billing_frequency || billing_period || legacy_period`
- **JavaScript** (`membership_application.js:2589`): Inline formatting `period.toLowerCase() === 'quarterly' ? 'Quarterly' : \`per ${period}\``

### 4.4 Contribution Validation in 4 Places with Different Rules

**Confidence:** 72/100

Minimum amount rules differ by location:

| Location | Minimum Rule |
|----------|-------------|
| Python API (line 489-506) | 30% of `minimum_amount`, fallback €5.00 |
| JavaScript step validation (line 670) | 50% of standard amount |
| JavaScript custom validation (line 650) | 50% of `typeData.amount` |
| Server-side form validation | Different again |

No single source of truth for contribution bounds.

### 4.5 Error Handling Pattern Duplication

**Confidence:** 68/100

`safe_log_error` is defined in two places:
- `utils/application_helpers.py:15-19`
- `api/background_approval_api.py:330-334`

The `frappe.log_error(f"Error in {op}: {str(e)}\n{traceback.format_exc()}", "...")` pattern appears 20+ times across the codebase with inconsistent formatting.

### 4.6 `OperationResult` vs `create_service_result()` Inconsistency — RESOLVED

**Confidence:** 80/100

Migrated all 3 service files (21 usages) from `create_service_result()` dicts to `OperationResult`:
- `member_approval_service.py` — 4 calls migrated
- `membership_duration_service.py` — 1 call migrated + 2 callers updated
- `email_service.py` — 14 calls migrated + ~15 callers updated across 13 files (including 4 pre-existing bugs in member_subscribers.py fixed)

Also fixed `email_api.py` which was double-wrapping email results in `OperationResult.ok(dict_result)`.
Net: -63 LOC across 22 files. `create_service_result()` is no longer imported by any of the 3 target files.

**Remaining:** `membership_creation_service.py` and `member_id_service.py` import `create_service_result` but don't call it (unused imports).

**Follow-up observations (code review 2026-02-06):**
- `compatibility.py` `isinstance(result, dict)` guard (lines 86-93) is now dead code for email paths — email service returns `OperationResult` directly. Guard still needed for other services that haven't migrated yet.
- 130+ other locations across non-email services still use `result.get("success")` dict-pattern. Out of scope — they use services not in the 3 target files.
- Exception handlers upgraded from `OperationResult.fail(str(e))` to `OperationResult.from_exception(e)` for richer error metadata (exception type, traceback).

### 4.7 Circular Invocation in Event Emission — RESOLVED

**Status:** RESOLVED (2026-02-06) — Event emission service now calls MemberStatusNotificationService directly instead of bouncing through the member document.

~~Three layers of indirection with a callback to the document. The event emission service should call the notification service directly.~~

### 4.8 Workflow Setup Variable Name Bugs — RESOLVED

**Status:** RESOLVED (2026-02-06) — Fixed `action_data` → `action`, `state_data` → `state`, added missing `DocumentExistenceValidator` import.

~~These will crash at runtime if the workflow creation codepath is exercised.~~

---

## 5. Structural Observations

### 5.1 `application_helpers.py` Is a Shadow Service Layer

At 1,505 lines, `utils/application_helpers.py` is the third-largest file and contains:
- Form data assembly (`get_form_data`)
- Payment method mapping (`map_payment_method`)
- Member creation (`create_member_from_application`) — 200+ LOC
- Member update (`update_member_from_reapplication`) — 130+ LOC
- Fee calculations (`get_membership_fee_info`, `get_membership_type_details`, `suggest_membership_amounts`)
- Chapter membership state management (4 functions, ~320 LOC)
- Address creation

This is effectively a second service layer that bypasses the `services/member/` architecture. Code in the service layer even imports FROM `application_helpers` (e.g., `member_lifecycle_service.py:579` imports `activate_pending_chapter_membership`).

### 5.2 Import Cycle Pressure

The codebase uses lazy imports (`from X import Y` inside function bodies) extensively. This is a symptom of circular dependency pressure. Examples:

```python
# member_lifecycle_service.py:555
from verenigingen.services.member.account.member_user_account_service import get_member_user_account_service

# member_lifecycle_service.py:579
from verenigingen.utils.application_helpers import activate_pending_chapter_membership
```

The dependency direction should be: API → Service → Repository/Utils. Currently, services import from utils that contain business logic, creating bidirectional dependencies.

### 5.3 The `membership_application_review.py` God File

At 2,318 lines, this is the largest file and combines:
- API endpoint definitions (7+ `@frappe.whitelist()` functions)
- Business logic (`create_membership_and_invoice`, approval flow)
- Notification functions (5 separate functions, ~400 LOC)
- Overdue checking and scheduler logic (~200 LOC)
- Chapter management (`assign_member_to_chapter`)
- Volunteer management
- Batch approval

### 5.4 Notification Architecture (Current State)

```
┌─────────────────────────────────────────────────────────────┐
│                   Notification Sources                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  application_notifications.py (DEPRECATED, still called)     │
│    ├── send_application_confirmation_email()                │
│    ├── notify_reviewers_of_new_application()                │
│    ├── send_approval_email()                                │
│    ├── send_rejection_email()                               │
│    ├── send_payment_confirmation_email()                    │
│    ├── notify_admins_of_new_application() [DEPRECATED]      │
│    ├── send_simple_notification() [DEPRECATED]              │
│    └── check_overdue_applications()                         │
│                                                              │
│  membership_application_review.py (inline)                   │
│    ├── send_approval_notification()                         │
│    ├── send_rejection_notification()                        │
│    ├── send_overdue_notifications()                         │
│    ├── notify_chapter_of_overdue_applications()             │
│    └── notify_managers_of_overdue_applications()            │
│                                                              │
│  MemberStatusNotificationService (service layer)             │
│    └── send_status_change_notification()                    │
│                                                              │
│  notification_registry.py (defines keys, not used)           │
│    ├── member_application_submitted                         │
│    ├── member_application_approved                          │
│    ├── member_application_rejected                          │
│    └── member_application_confirmation                      │
│                                                              │
│  EmailService (delivery layer)                               │
│    ├── send_templated_email()                               │
│    ├── send_simple_email()                                  │
│    └── send_notification()                                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Cross-Layer Issues

### 6.1 Python-JavaScript Consistency Gaps

| Concern | Python | JavaScript | Divergence |
|---------|--------|------------|------------|
| Min contribution | 30% of minimum | 50% of standard | Different rules |
| Payment method names | slug format `"bank_transfer"` | Display format `"Bank Transfer"` | Inconsistent |
| Billing period | Explicit map | Cascading fallback chain | Different resolution |
| Required fields per payment method | Not defined | Hardcoded in `handlePaymentMethodChange()` | Business rules in UI only |

### 6.2 State Management Dual Systems (JavaScript)

The frontend maintains state in two parallel systems:

```javascript
// New system (structured):
this.state.set('membership', { type, amount, isCustom });

// Legacy system (flat):
this.state.set('selected_membership_type', membershipType);
this.state.set('custom_contribution_fee', finalAmount);
this.state.set('uses_custom_amount', usesCustomAmount);
```

Both are written on every state change (lines 3201-3210). Form data collection has three overlapping methods: `StepManager.getAllData()`, `collectFormDataDirectly()`, and `getAdditionalFormData()`.

---

## 7. Recommended Refactoring Roadmap

### Phase 1: Eliminate Highest-Risk Duplication (2-3 days) — COMPLETED

| Task | Files Affected | Status |
|------|---------------|--------|
| ~~**Unify approval path**: Delete local `create_membership_and_invoice()` from review API. Route through `MembershipCreationService`.~~ | `membership_application_review.py`, `member_approval_service.py` | DONE (see 2.1) |
| ~~**Establish canonical approval orchestrator**: Choose lifecycle service OR approval service. Delete the other. Update review API to be a thin HTTP wrapper.~~ | `member_lifecycle_service.py`, `member_approval_service.py`, `membership_application_review.py` | DONE (see 2.2) |
| ~~**Extract validation wrapper**: Create `_wrap_validation()` generic function. Reduce 20+ endpoints to thin one-liners.~~ | `membership_application.py` | DONE (see 2.4) |

### Phase 2: Consolidate Fee & Notification Logic (2-3 days) — PARTIALLY COMPLETED

| Task | Files Affected | Status |
|------|---------------|--------|
| ~~**Create `MembershipFeeService`**: Combine `get_membership_fee_info`, `get_membership_type_details`, `suggest_membership_amounts` into one service.~~ | `application_helpers.py`, `membership_application.py` | DONE (see 2.3) |
| **Clean up notification layer**: Delete deprecated functions. Move review API notifications into `ApplicationNotificationService`. Integrate `notification_registry`. | `application_notifications.py`, `membership_application_review.py` | TODO (see 3.1) |
| ~~**Extract custom amount logic**: Create `_apply_custom_amount_to_member(member, data)`.~~ | `application_helpers.py` | DONE (see 3.2) |

### Phase 3: Structural Improvements (3-5 days)

| Task | Files Affected | Risk Reduction |
|------|---------------|----------------|
| **Consolidate chapter membership**: Route all chapter operations through `ChapterMembershipManager`. Remove 4 standalone functions from `application_helpers.py`. | `application_helpers.py`, `member_lifecycle_service.py`, `membership_application_review.py` | Single chapter state machine |
| **Single payment method source**: Create constants or config DocType. All layers import from there. | 4+ files | Eliminates name mismatches |
| **Decide on fraud detection**: Implement stubs or gate behind feature flag. | `fraud_detection.py` | Eliminates false security |
| ~~**Unify return types**: Standardize on `OperationResult` everywhere. Remove `create_service_result()`.~~ **DONE** | 22 files | Predictable error handling |

### Phase 4: Long-Term Architecture (ongoing)

| Task | Description |
|------|-------------|
| **Decompose `membership_application_review.py`** | Extract business logic to services, keep only HTTP concerns |
| **Decompose `application_helpers.py`** | Distribute functions to proper service modules, delete the file |
| **Remove legacy aliases** | After confirming no external consumers |
| **Shared context builder** | For template page context duplication |
| **JavaScript state unification** | Remove legacy dual-state pattern |

---

## Appendix: Confidence Scoring Methodology

| Score Range | Meaning |
|-------------|---------|
| 90-100 | Certain issue with clear evidence across multiple files |
| 75-89 | High confidence, well-documented with specific line references |
| 60-74 | Probable issue, may have intentional reasons or mitigating factors |
| Below 60 | Not included in this report |

---

*Report generated from analysis of 30+ files across the vereinigingen app codebase on the `develop` branch.*
