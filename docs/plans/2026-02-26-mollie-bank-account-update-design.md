# Design: Update Mollie Bank Account for Active Subscription

**Date:** 2026-02-26
**Status:** Approved

## Problem

When a member has an active Mollie subscription and wants to change their bank account, there is no way to do so. Cancelling and recreating the subscription reuses the same mandate (picks the first valid one), so the old bank account stays attached.

## Solution

Add an "Update Bank Account" button to the Mollie subscription card on `/payment_dashboard`. The member enters a new IBAN, and the system creates a new Mollie mandate and patches the existing subscription's `mandateId` — no cancel/recreate needed.

## Scope

**Mollie-only.** This does not touch SEPA Direct Debit mandates, the local SEPA setup flow, or the member's `iban` field. Mollie mandates are managed via the Mollie API, separate from local SEPA Mandate DocTypes.

## User Flow

1. Member visits `/payment_dashboard`
2. In the Mollie subscription card (active subscription), clicks **"Update Bank Account"**
3. Inline form expands with:
   - IBAN input (auto-formatted, validated client-side)
   - Account holder name (pre-filled with member's full name)
   - Explanation text: "This will update the bank account used for your recurring payments"
   - Submit + Cancel buttons
4. On submit: system validates → creates Mollie mandate → patches subscription → done
5. Success/error feedback shown inline

## Backend

### New API Endpoint

**File:** `api/mollie_payment.py`

```python
@frappe.whitelist(allow_guest=False)
def update_mollie_bank_account(iban: str, account_holder_name: str):
```

Steps:
1. Validate IBAN (reuse `iban_validator.validate_iban()`)
2. Get member via `get_current_user_member_name_required()` + `validate_member_ownership()`
3. Verify member has `mollie_customer_id` and `mollie_subscription_id`
4. Verify subscription is active via Mollie API
5. Create new Mollie mandate: `customer.mandates.create({method: "directdebit", consumerName, consumerAccount, consumerBic})`
6. Patch subscription: `customer.subscriptions.update(sub_id, {"mandateId": new_mandate_id})`
7. Update `member.mollie_mandate_id` with new mandate ID via `db_set()`
8. Revoke old Mollie mandate (best-effort cleanup)
9. Return success with masked IBAN

### New Service Method

**File:** `services/mollie_debug_service.py`

```python
def update_subscription_mandate(self, customer_id, subscription_id, new_mandate_id, reason="Bank account update"):
```

Thin wrapper around `customer.subscriptions.update(subscription_id, {"mandateId": new_mandate_id})`. Follows the same pattern as existing `update_subscription_webhook()` — validates inputs, calls API, logs audit trail.

### Frontend Changes

**File:** `templates/pages/payment_dashboard.html`

In the JS-rendered Mollie subscription card (`updateMollieDisplay()`, line ~1276):
- Add "Update Bank Account" button next to "Cancel Subscription" button
- Add inline form (hidden by default, toggled by button)
- Add `updateMollieBankAccount()` JS function that:
  - Validates IBAN client-side (format check)
  - Calls `update_mollie_bank_account` API
  - Shows success/error message
  - Reloads Mollie status on success

## Error Handling

| Failure Point | Behavior |
|---|---|
| Invalid IBAN | Client-side + server-side rejection, nothing changed |
| No active subscription | Return error: "No active subscription to update" |
| Mollie mandate creation fails | Return error, nothing changed |
| Subscription PATCH fails | Revoke new mandate, return error, old mandate stays |
| Old mandate revocation fails | Log warning, operation still succeeds |

## Files Changed

1. `api/mollie_payment.py` — new endpoint
2. `templates/pages/payment_dashboard.html` — button + inline form + JS handler
3. `services/mollie_debug_service.py` — new `update_subscription_mandate()` method

## Not In Scope

- SEPA Direct Debit mandate changes (separate concern)
- Admin-initiated bank account changes (future)
- New portal pages
- Cancel/recreate subscription flow changes
