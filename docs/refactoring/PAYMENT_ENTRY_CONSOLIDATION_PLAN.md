# Payment Entry Consolidation Plan

**Status:** 90% Complete
**Last Updated:** 2026-02-05

## Overview

This document tracks the consolidation of payment entry creation logic into a single service (`PaymentEntryCreationService`) to eliminate code duplication and ensure consistent behavior across all payment workflows.

## Service Location

```
verenigingen_payments/services/payment/payment_entry_creation_service.py
```

## Features

- **Permission-aware**: Explicit permission checking before database operations
- **Input validation**: Amount validation, invoice existence checks
- **Exception handling**: Proper error categorization (permission, validation, unexpected)
- **Flexible submission**: Optional graceful degradation to draft entries
- **Custom fields**: Support for SEPA batch tracking and other metadata

## Migration Status

### Completed Migrations

| File | Function | Status | Notes |
|------|----------|--------|-------|
| `utils/bank_integration.py` | `_create_payment_entry()` | ✅ Complete | Reduced from ~70 to ~25 lines |
| `services/batch_processing_service.py` | `_create_payment_entry_for_invoice()` | ✅ Complete | Uses service directly |
| `doctype/direct_debit_batch/direct_debit_batch.py` | `create_payment_entry_for_invoice()` | ✅ Complete | Uses service directly |
| `services/sepa_reconciliation.py` | `create_payment_entry_from_transaction()` | ✅ Complete | Uses service directly |

### Not Applicable

| File | Reason |
|------|--------|
| `services/payment/payment_plan_service.py` | Different pattern - builds PE from scratch without invoice |
| Mollie integration | Gateway-specific with clearing accounts |
| Fee entries | Uses Journal Entry, not Payment Entry |

## API Reference

### Basic Usage

```python
from verenigingen.verenigingen_payments.services.payment import payment_entry_service

payment_entry = payment_entry_service.create_payment_entry_from_invoice(
    invoice_name="SI-2024-001",
    amount=Decimal("50.00"),
    posting_date=date.today(),
    reference_no="BATCH-001",
    reference_date=date.today(),
    mode_of_payment="SEPA Direct Debit"
)
```

### With Custom Fields

```python
payment_entry = payment_entry_service.create_payment_entry_from_invoice(
    invoice_name="SI-2024-001",
    amount=Decimal("50.00"),
    posting_date=date.today(),
    reference_no="BATCH-001",
    reference_date=date.today(),
    mode_of_payment="SEPA Direct Debit",
    custom_fields={
        "custom_sepa_batch": "BATCH-001",
        "custom_sepa_batch_item": "ITEM-001",
    }
)
```

### Graceful Degradation

```python
# For reconciliation workflows where draft is acceptable
payment_entry = payment_entry_service.create_payment_entry_from_invoice(
    invoice_name="SI-2024-001",
    amount=Decimal("50.00"),
    posting_date=date.today(),
    reference_no="BANK-REF-123",
    reference_date=date.today(),
    mode_of_payment="Bank Transfer",
    bank_transaction_name="BT-001",
    allow_draft_on_permission_failure=True  # Returns draft if lacking submit permission
)
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `invoice_name` | str | Yes | Sales Invoice name |
| `amount` | Decimal | Yes | Payment amount (must be positive) |
| `posting_date` | date | Yes | Posting date for payment entry |
| `reference_no` | str | Yes | Payment reference number |
| `reference_date` | date | Yes | Reference date for payment |
| `mode_of_payment` | str | Yes | Payment method |
| `payment_type` | str | No | Default "Receive" |
| `bank_transaction_name` | str | No | Link to Bank Transaction |
| `allow_draft_on_permission_failure` | bool | No | Return draft if lacking submit permission |
| `custom_fields` | Dict | No | Custom field values to set on PE |

## Error Handling

| Exception | When Raised |
|-----------|-------------|
| `frappe.DoesNotExistError` | Invoice doesn't exist |
| `frappe.ValidationError` | Invalid amount (negative, zero) or configuration issues |
| `frappe.PermissionError` | Lacking create/submit permission |

## Metrics

### Before Consolidation
- 4 separate implementations
- ~280 total lines of duplicated logic
- Inconsistent permission checking
- No custom field support

### After Consolidation
- 1 canonical implementation
- ~150 lines in service
- Consistent permission and validation
- Full feature set available to all callers

## Future Considerations

1. **Payment Plan Integration**: Consider if payment plans can be adapted to use the service
2. **Gateway Abstraction**: Potential for Mollie/Ponto to use extended version
3. **Audit Logging**: Add structured logging for compliance

---

*Document maintained as part of ongoing refactoring efforts*
