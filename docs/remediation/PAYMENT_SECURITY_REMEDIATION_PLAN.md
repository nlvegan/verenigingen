# Payment/Financial API Security Remediation Plan

## Executive Summary

**Audit Date**: 2026-01-17
**Branch**: fix/notification-pr6-followup
**Status**: ✅ Phase 1, 2 & 3 COMPLETE (All Endpoints Secured + CI Gate Added)

### Key Findings

**Contrary to the external review's claim**, the files `payment_sync_system.py` and `payment_audit.py` are **already protected** with `@critical_api(operation_type=OperationType.FINANCIAL)` decorators.

However, the audit identified **26 HIGH-RISK** and **23 MEDIUM-RISK** unprotected `@frappe.whitelist()` endpoints across payment and financial modules that lack security framework protection.

### Coverage Statistics

| Risk Level | Unprotected Endpoints | Priority | Status |
|------------|----------------------|----------|--------|
| HIGH       | 26                   | P1 - Immediate | ✅ SECURED |
| MEDIUM     | 23                   | P2 - Short-term | ✅ SECURED (4 new + 19 already protected) |

---

## Completed Remediation (2026-01-17)

All 26 HIGH-RISK endpoints have been secured with appropriate security decorators:

### Files Modified

| File | Functions Secured | Decorator Applied |
|------|-------------------|-------------------|
| `payment_entry_cleanup.py` | 3 | `@critical_api(FINANCIAL)` |
| `payment_processing_recovery.py` | 4 | `@critical_api(FINANCIAL)` |
| `settlement_processing.py` | 3 | `@critical_api(FINANCIAL)` |
| `validation_service.py` | 4 | `@public_api(PUBLIC)` + `allow_guest=True` |
| `ponto_payment_link.py` | 3 | `@high_security_api(FINANCIAL)` |
| `ponto_payment_request.py` | 1 | `@high_security_api(FINANCIAL)` |
| `ponto_settings.py` | 4 | `@high_security_api(FINANCIAL)` |
| `ing_checkout_settings.py` | 1 | `@public_api(PUBLIC)` + `allow_guest=True` |
| `mollie_bulk_payment_discovery.py` | 3 | `@critical_api(FINANCIAL)` |

### Guest Access Preserved

The following endpoints remain guest-accessible for donation/payment forms:
- `validate_iban_api` - IBAN validation during payment entry
- `validate_bank_details_api` - Bank details validation
- `validate_payment_method_api` - Payment method availability check
- `validate_payment_amount_api` - Amount validation
- `is_ing_checkout_enabled` - Payment method availability check

These use `@public_api` with `@frappe.whitelist(allow_guest=True)` to allow guest access while still providing audit logging.

### Phase 2 Completed (2026-01-17)

The medium-risk endpoints audit revealed most were already protected:

**Already Protected (19 endpoints):**
- `chapter_dashboard_api.py` - All 15 debug functions have `@development_only()` or appropriate security decorators
- `debug_opening_balance.py` - Has `@development_only()`
- `donation_reset.py` - Has `@development_only()`
- `test_specific_transaction.py` - Has `@development_only()`
- `test_webhook_signature.py` - Has `@development_only()`

**Newly Secured (4 endpoints):**

| File | Function | Decorator Applied |
|------|----------|-------------------|
| `service_integration.py` | `get_service_infrastructure_status` | `@high_security_api(ADMIN)` |
| `service_integration.py` | `run_service_integration_tests` | `@high_security_api(ADMIN)` |
| `member_merge_service.py` | `get_merge_preview` | `@critical_api(MEMBER_DATA)` |
| `member_merge_service.py` | `execute_merge` | `@critical_api(MEMBER_DATA)` |

### Phase 3 Completed (2026-01-17)

**CI Security Gate Added:**

A new `api-security-audit` job has been added to `.github/workflows/ci.yml` that:
- Scans all `@frappe.whitelist()` endpoints in high-risk files (payment, sepa, invoice, financial, settlement, batch, mandate, sync, audit)
- Fails the build if any high-risk endpoint lacks a security decorator
- Generates an API security report artifact with protection metrics

**Features:**
- Runs on every push to main/develop and every PR
- Checks for `@critical_api`, `@high_security_api`, `@standard_api`, `@public_api`, `@development_only`, `@utility_api`, and `@require_role` decorators
- Produces JSON report with endpoint counts and protection rate

---

## Priority 1: Critical Security Gaps (HIGH-RISK)

### 1.1 Payment Entry Cleanup (`verenigingen/utils/payment_entry_cleanup.py`)

**Functions requiring protection:**
- `bulk_delete_payment_entries` - Bulk delete operations
- `delete_payment_entries_by_date_range` - Date-range deletion
- `get_payment_entry_cleanup_preview` - Preview operation

**Recommended decorator:**
```python
@critical_api(operation_type=OperationType.FINANCIAL)
```

**Required test:** Verify unauthorized users cannot delete payment entries.

---

### 1.2 Payment Processing Recovery (`verenigingen/utils/payment_processing_recovery.py`)

**Functions requiring protection:**
- `get_incomplete_payments`
- `complete_partial_payments`
- `analyze_payment_gaps`
- `repair_invoices_missing_gl_entries`

**Recommended decorator:**
```python
@critical_api(operation_type=OperationType.FINANCIAL)
```

---

### 1.3 Settlement Processing (`verenigingen/verenigingen_payments/api/settlement_processing.py`)

**Functions requiring protection:**
- `process_settlement_deposit` - Creates financial deposits
- `batch_process_recent_settlements` - Batch financial operations
- `get_settlement_status` - Settlement data access

**Recommended decorator:**
```python
@critical_api(operation_type=OperationType.FINANCIAL)
```

---

### 1.4 Payment Validation Service (`verenigingen/services/payment/validation_service.py`)

**Functions requiring protection:**
- `validate_iban_api`
- `validate_bank_details_api`
- `validate_payment_method_api`
- `validate_payment_amount_api`

**Recommended decorator:**
```python
@high_security_api(operation_type=OperationType.FINANCIAL)
```

---

### 1.5 Ponto Payment DocTypes

**Files:**
- `verenigingen/verenigingen_payments/doctype/ponto_payment_link/ponto_payment_link.py`
- `verenigingen/verenigingen_payments/doctype/ponto_payment_request/ponto_payment_request.py`
- `verenigingen/verenigingen_payments/doctype/ponto_settings/ponto_settings.py`
- `verenigingen/verenigingen_payments/doctype/ing_checkout_settings/ing_checkout_settings.py`

**Functions requiring protection:**
- `refresh_status` - Payment status refresh
- `get_payment_url` - Payment URL generation
- `send_payment_link` - Payment link distribution
- `fetch_ponto_accounts` - Account data access
- `test_connection` - API connection testing
- `trigger_manual_sync` - Manual sync trigger
- `refresh_user_info` - User info refresh
- `is_ing_checkout_enabled` - Settings check

**Recommended decorator:**
```python
@high_security_api(operation_type=OperationType.FINANCIAL)
```

---

### 1.6 Mollie Bulk Payment Discovery (`verenigingen/verenigingen_payments/page/mollie_bulk_payment_discovery/`)

**Functions requiring protection:**
- `run_discovery` - Payment discovery
- `process_payment` - Single payment processing
- `process_bulk_payments` - Bulk payment operations

**Recommended decorator:**
```python
@critical_api(operation_type=OperationType.FINANCIAL)
```

---

## Priority 2: Medium-Risk Endpoints

### 2.1 Debug/Development APIs

Multiple debug functions in:
- `vereiningen/api/chapter_dashboard_api.py`
- `verenigingen/api/debug_opening_balance.py`
- `vereiningen/api/donation_reset.py`
- `verenigingen/api/test_specific_transaction.py`

**Recommended decorator:**
```python
@development_only_api(operation_type=OperationType.ADMIN)
```

---

### 2.2 Service Infrastructure

- `verenigingen/services/infrastructure/service_integration.py`
  - `get_service_infrastructure_status`
  - `run_service_integration_tests`

**Recommended decorator:**
```python
@high_security_api(operation_type=OperationType.ADMIN)
```

---

### 2.3 Member Merge Service

- `vereiningen/services/member_merge_service.py`
  - `get_merge_preview`
  - `execute_merge`

**Recommended decorator:**
```python
@critical_api(operation_type=OperationType.MEMBER_DATA)
```

---

## Remediation Actions

### A. Immediate Fixes (P1)

#### A.1 Add Security Decorators

For each unprotected function, add the appropriate decorator:

```python
# Example for payment_entry_cleanup.py
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
)

@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def bulk_delete_payment_entries(batch_id):
    # existing implementation
```

**Import order matters:** The security decorator must be applied AFTER `@frappe.whitelist()` (closer to the function).

#### A.2 Add Authorization Tests

Create test file: `verenigingen/tests/backend/security/test_payment_api_security.py`

```python
"""
Tests to verify unauthorized users are denied access to payment APIs
"""
import frappe
from frappe.tests.utils import FrappeTestCase

class TestPaymentAPISecurity(FrappeTestCase):
    def test_bulk_delete_requires_admin(self):
        """Verify unprivileged user cannot delete payment entries"""
        frappe.set_user("test_member@example.com")

        with self.assertRaises(frappe.PermissionError):
            from verenigingen.utils.payment_entry_cleanup import bulk_delete_payment_entries
            bulk_delete_payment_entries(batch_id="TEST-001")

    def test_settlement_processing_requires_admin(self):
        """Verify unprivileged user cannot process settlements"""
        frappe.set_user("test_member@example.com")

        with self.assertRaises(frappe.PermissionError):
            from verenigingen.verenigingen_payments.api.settlement_processing import process_settlement_deposit
            process_settlement_deposit(settlement_id="TEST-001")
```

---

### B. CI Security Gate Integration

#### B.1 Add Security Audit Job to CI

Create or update `.github/workflows/ci.yml`:

```yaml
  security-audit:
    name: API Security Audit
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
    - name: Checkout code
      uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Run API Security Validator
      run: |
        cd ${{ github.workspace }}
        python scripts/validation/security/api_security_validator.py --json-output security-audit-results.json

    - name: Check for HIGH-RISK unprotected APIs
      run: |
        python -c "
        import json
        with open('security-audit-results.json') as f:
            report = json.load(f)

        high_risk_failures = [
            v for v in report['validations']
            if v['result'] == 'fail' and v['impact'] in ['critical', 'high']
            and any(kw in v['file_path'].lower() for kw in ['payment', 'sepa', 'invoice', 'financial', 'settlement'])
        ]

        if high_risk_failures:
            print('HIGH-RISK SECURITY FAILURES DETECTED:')
            for failure in high_risk_failures:
                print(f'  - {failure[\"file_path\"]}:{failure[\"function_name\"]}')
            exit(1)
        else:
            print('All high-risk financial APIs are protected.')
        "

    - name: Upload Security Audit Results
      uses: actions/upload-artifact@v4
      if: always()
      with:
        name: security-audit-results
        path: security-audit-results.json
```

#### B.2 Update PR Checklist

Create `.github/PULL_REQUEST_TEMPLATE.md` update:

```markdown
## Security Checklist (for PRs touching payment_*, sepa_*, invoice_* files)

- [ ] All `@frappe.whitelist()` functions have a security decorator (`@critical_api`, `@high_security_api`, etc.)
- [ ] Security tests added for new endpoints (test that unauthorized users are denied)
- [ ] Audit logging is enabled for sensitive operations
- [ ] No hardcoded secrets or credentials
```

---

### C. Security Framework Hardening

#### C.1 Document Security Decorator Requirements

Add to `docs/development/security_framework.md`:

| File Pattern | Required Decorator | Minimum Security Level |
|--------------|-------------------|----------------------|
| `payment*.py` | `@critical_api` | CRITICAL |
| `sepa*.py` | `@critical_api` | CRITICAL |
| `invoice*.py` | `@critical_api` | CRITICAL |
| `settlement*.py` | `@critical_api` | CRITICAL |
| `*validation*.py` | `@high_security_api` | HIGH |
| `*debug*.py` | `@development_only_api` | DEVELOPMENT |

#### C.2 Create Allowlist for External Payment APIs

Create `verenigingen/utils/security/payment_api_allowlist.py`:

```python
"""
Explicit allowlist of modules that can call external payment APIs.

Changes to this file require security review.
"""

PAYMENT_API_CALLERS = frozenset([
    "verenigingen.vereiningen_payments.mollie.services",
    "vereiningen.vereiningen_payments.ponto.services",
    "vereiningen.vereiningen_payments.ing_checkout.services",
])
```

---

## Implementation Checklist

### Phase 1: Immediate (Week 1)

- [ ] Add `@critical_api` to all 26 HIGH-RISK endpoints
- [ ] Create `test_payment_api_security.py` with authorization tests
- [ ] Run full security audit and verify no HIGH-RISK gaps remain

### Phase 2: Short-term (Week 2)

- [ ] Add security decorators to 23 MEDIUM-RISK endpoints
- [ ] Add security-audit job to CI
- [ ] Update PR template with security checklist

### Phase 3: Ongoing

- [ ] Quarterly security audit using `api_security_validator.py`
- [ ] Code review checklist for payment-related PRs
- [ ] Monitor audit events for critical operations

---

## Files Already Protected (No Changes Needed)

The following files **already have proper protection** and were incorrectly flagged in the external review:

| File | Protection |
|------|------------|
| `payment_sync_system.py` | `@critical_api(operation_type=OperationType.FINANCIAL)` |
| `payment_audit.py` | `@critical_api(operation_type=OperationType.FINANCIAL)` |
| `payment_dashboard.py` | `@high_security_api` / `@critical_api` / `@standard_api` |
| `mollie_payment.py` | `@critical_api(operation_type=OperationType.FINANCIAL)` |
| `invoice_management.py` | `@critical_api` / `@high_security_api` / `@development_only_api` |

---

## Appendix: Full List of Unprotected Endpoints

### HIGH-RISK (26 endpoints)

| File | Function |
|------|----------|
| `payment_entry_cleanup.py` | `bulk_delete_payment_entries` |
| `payment_entry_cleanup.py` | `delete_payment_entries_by_date_range` |
| `payment_entry_cleanup.py` | `get_payment_entry_cleanup_preview` |
| `payment_processing_recovery.py` | `get_incomplete_payments` |
| `payment_processing_recovery.py` | `complete_partial_payments` |
| `payment_processing_recovery.py` | `analyze_payment_gaps` |
| `payment_processing_recovery.py` | `repair_invoices_missing_gl_entries` |
| `settlement_processing.py` | `process_settlement_deposit` |
| `settlement_processing.py` | `batch_process_recent_settlements` |
| `settlement_processing.py` | `get_settlement_status` |
| `validation_service.py` | `validate_iban_api` |
| `validation_service.py` | `validate_bank_details_api` |
| `validation_service.py` | `validate_payment_method_api` |
| `validation_service.py` | `validate_payment_amount_api` |
| `ing_checkout_settings.py` | `is_ing_checkout_enabled` |
| `ponto_payment_link.py` | `refresh_status` |
| `ponto_payment_link.py` | `get_payment_url` |
| `ponto_payment_link.py` | `send_payment_link` |
| `ponto_payment_request.py` | `refresh_status` |
| `ponto_settings.py` | `fetch_ponto_accounts` |
| `ponto_settings.py` | `test_connection` |
| `ponto_settings.py` | `trigger_manual_sync` |
| `ponto_settings.py` | `refresh_user_info` |
| `mollie_bulk_payment_discovery.py` | `run_discovery` |
| `mollie_bulk_payment_discovery.py` | `process_payment` |
| `mollie_bulk_payment_discovery.py` | `process_bulk_payments` |

### MEDIUM-RISK (23 endpoints)

| File | Function |
|------|----------|
| `chapter_dashboard_api.py` | `test_mt940_naming_logic` |
| `chapter_dashboard_api.py` | `debug_mt940_import` |
| `chapter_dashboard_api.py` | `debug_mt940_transaction_creation` |
| `chapter_dashboard_api.py` | `test_eboekhouden_framework` |
| `chapter_dashboard_api.py` | `test_eboekhouden_api_mock` |
| `chapter_dashboard_api.py` | `test_eboekhouden_complete` |
| `chapter_dashboard_api.py` | `debug_dashboard_access` |
| `chapter_dashboard_api.py` | `test_url_access` |
| `chapter_dashboard_api.py` | `create_chapter_dashboard` |
| `chapter_dashboard_api.py` | `create_simple_dashboard` |
| `chapter_dashboard_api.py` | `debug_number_cards` |
| `chapter_dashboard_api.py` | `test_number_card_format` |
| `chapter_dashboard_api.py` | `test_dashboard_access` |
| `chapter_dashboard_api.py` | `simple_test_count` |
| `chapter_dashboard_api.py` | `test_enhanced_mt940_features` |
| `debug_opening_balance.py` | `check_opening_balance_mutations` |
| `donation_reset.py` | `reset_donation_for_testing` |
| `test_specific_transaction.py` | `test_transaction_webhook` |
| `test_webhook_signature.py` | `test_signed_webhook` |
| `service_integration.py` | `get_service_infrastructure_status` |
| `service_integration.py` | `run_service_integration_tests` |
| `member_merge_service.py` | `get_merge_preview` |
| `member_merge_service.py` | `execute_merge` |

---

## References

- Security Framework: `vereinigen/utils/security/api_security_framework.py`
- Security Validator: `scripts/validation/security/api_security_validator.py`
- Detailed Audit Script: `scripts/analysis/detailed_security_audit.py`
