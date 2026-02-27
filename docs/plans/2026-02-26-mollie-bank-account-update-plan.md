# Mollie Bank Account Update — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let members update their bank account on an active Mollie subscription via the payment dashboard.

**Architecture:** New API endpoint in `api/mollie_payment.py` creates a Mollie mandate then PATCHes the subscription's `mandateId`. New service method in `MollieDebugService` wraps the PATCH call with audit logging. Frontend adds a button + inline form to the Mollie subscription card in `payment_dashboard.html`.

**Tech Stack:** Frappe Python API, Mollie Python SDK, Jinja2/JS frontend

**Design doc:** `docs/plans/2026-02-26-mollie-bank-account-update-design.md`

---

## Task 1: Service method — `update_subscription_mandate()`

Add a method to `MollieDebugService` that PATCHes a subscription's `mandateId`. Follows the exact pattern of the existing `update_subscription_webhook()` method (line 363 of the same file).

**Files:**
- Modify: `verenigingen/services/mollie_debug_service.py` (insert after `update_subscription_webhook()`, ~line 442)

**Step 1: Write `update_subscription_mandate()`**

Insert this method right after `update_subscription_webhook()` (after line 442), before `admin_revoke_mandate()`:

```python
def update_subscription_mandate(
    self, customer_id, subscription_id, new_mandate_id, reason="Bank account update"
):
    """
    Update the mandate (bank account) for a subscription via Mollie PATCH API.

    Args:
        customer_id: Mollie customer ID (cst_xxx)
        subscription_id: Mollie subscription ID (sub_xxx)
        new_mandate_id: Mollie mandate ID to switch to (mdt_xxx)
        reason: Reason for the update (for audit trail)

    Returns:
        Dict with success/error status (via create_success_response)
    """
    if not customer_id or not subscription_id:
        raise ValueError(_("Customer ID and Subscription ID are required"))

    if not new_mandate_id:
        raise ValueError(_("New Mandate ID is required"))

    try:
        client = self.mollie_client.sdk_client
        customer_obj = client.customers.get(customer_id)

        # Verify subscription exists and capture old mandate ID
        current_subscription = customer_obj.subscriptions.get(subscription_id)
        old_mandate_id = getattr(current_subscription, "mandateId", None)

        # PATCH the subscription with the new mandate
        customer_obj.subscriptions.update(
            subscription_id, {"mandateId": new_mandate_id}
        )

        self.audit_trail.log_event(
            AuditEventType.CONFIGURATION_CHANGED,
            AuditSeverity.INFO,
            f"Updated mandate for subscription {subscription_id}",
            details={
                "action": "subscription_mandate_update",
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "old_mandate_id": old_mandate_id,
                "new_mandate_id": new_mandate_id,
                "reason": reason,
                "updated_by": frappe.session.user,
            },
            entity_type="Mollie Subscription",
            entity_id=subscription_id,
        )

        self.logger.info(
            f"MANDATE UPDATE: User {frappe.session.user} updated mandate for subscription "
            f"{subscription_id} (customer {customer_id}). Old: {old_mandate_id}, New: {new_mandate_id}"
        )

        return create_success_response(
            "Subscription mandate updated successfully",
            {
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "old_mandate_id": old_mandate_id,
                "new_mandate_id": new_mandate_id,
                "updated_by": frappe.session.user,
                "timestamp": frappe.utils.now(),
            },
        )

    except Exception as api_error:
        error_message = str(api_error)
        self.logger.error(
            f"MANDATE UPDATE FAILED: User {frappe.session.user} failed to update mandate for "
            f"subscription {subscription_id} (customer {customer_id}): {error_message}"
        )
        raise api_error
```

**Step 2: Verify no syntax errors**

Run: `cd ~/frappe-bench && python -c "from verenigingen.services.mollie_debug_service import MollieDebugService; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```
feat(mollie): add update_subscription_mandate() service method
```

---

## Task 2: API endpoint — `update_mollie_bank_account()`

New whitelisted endpoint in `api/mollie_payment.py`. Orchestrates: validate IBAN → create Mollie mandate → patch subscription → update member → cleanup old mandate.

**Files:**
- Modify: `verenigingen/api/mollie_payment.py` (append after `cancel_specific_subscription()`)

**Step 1: Write the endpoint**

Append after the `cancel_specific_subscription` function (after ~line 400). Follow the same security patterns as `cancel_specific_subscription`: `@frappe.whitelist` outermost, member ownership validation, authorized customer ID check.

```python
@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def update_mollie_bank_account(iban: str = None, account_holder_name: str = None):
    """
    Update the bank account (mandate) on the member's active Mollie subscription.

    Creates a new Mollie SEPA Direct Debit mandate with the provided IBAN, then
    PATCHes the active subscription to use the new mandate.

    Args:
        iban: New IBAN for the bank account
        account_holder_name: Name on the bank account

    Returns:
        Dict with status, message, and masked IBAN on success
    """
    from verenigingen.utils.validation.iban_validator import derive_bic_from_iban, validate_iban

    # Get form data if not provided as parameters
    if not iban:
        iban = frappe.local.form_dict.get("iban", "")
    if not account_holder_name:
        account_holder_name = frappe.local.form_dict.get("account_holder_name", "")

    # Clean input
    iban = iban.replace(" ", "").upper().strip() if iban else ""
    account_holder_name = account_holder_name.strip() if account_holder_name else ""

    # Validate required fields
    if not iban:
        return {"status": "error", "message": _("IBAN is required")}
    if not account_holder_name:
        return {"status": "error", "message": _("Account holder name is required")}

    # Validate IBAN format
    validation_result = validate_iban(iban)
    if not validation_result.get("valid"):
        return {"status": "error", "message": validation_result.get("message", _("Invalid IBAN format"))}

    # Get and validate member
    member_name = get_current_user_member_name_required()
    validate_member_ownership(member_name, _("You can only update your own bank account"))

    member = frappe.get_doc("Member", member_name)

    # Verify member has Mollie subscription
    if not member.mollie_customer_id or not member.mollie_subscription_id:
        return {"status": "error", "message": _("No active Mollie subscription found")}

    customer_id = parse_mollie_customer_ids(member.mollie_customer_id, max_ids=1)[0]
    subscription_id = member.mollie_subscription_id
    old_mandate_id = member.mollie_mandate_id

    # Derive BIC for Dutch IBANs
    bic = derive_bic_from_iban(iban) or None

    try:
        from verenigingen.services.mollie_debug_service import MollieDebugService

        service = MollieDebugService()

        # Step 1: Verify subscription is active
        client = service.mollie_client.sdk_client
        customer_obj = client.customers.get(customer_id)
        subscription = customer_obj.subscriptions.get(subscription_id)

        if subscription.status != "active":
            return {
                "status": "error",
                "message": _("Your subscription is not active. Cannot update bank account."),
            }

        # Step 2: Create new Mollie mandate with the new IBAN
        mandate_data = {
            "method": "directdebit",
            "consumerName": account_holder_name,
            "consumerAccount": iban,
        }
        if bic:
            mandate_data["consumerBic"] = bic

        new_mandate = customer_obj.mandates.create(mandate_data)
        new_mandate_id = new_mandate.id

        # Step 3: PATCH subscription with new mandate
        try:
            service.update_subscription_mandate(
                customer_id=customer_id,
                subscription_id=subscription_id,
                new_mandate_id=new_mandate_id,
                reason=f"Bank account update by {frappe.session.user}",
            )
        except Exception as patch_error:
            # Rollback: revoke the newly created mandate
            try:
                customer_obj.mandates.delete(new_mandate_id)
            except Exception:
                frappe.logger().warning(
                    f"Could not revoke new mandate {new_mandate_id} after failed subscription update"
                )
            raise patch_error

        # Step 4: Update member record
        member.db_set("mollie_mandate_id", new_mandate_id, update_modified=False)
        frappe.db.commit()

        # Step 5: Best-effort cleanup of old mandate
        if old_mandate_id:
            try:
                customer_obj.mandates.delete(old_mandate_id)
            except Exception as revoke_error:
                frappe.logger().warning(
                    f"Could not revoke old mandate {old_mandate_id}: {str(revoke_error)}"
                )

        # Mask IBAN for response
        masked_iban = f"{iban[:2]}{'*' * (len(iban) - 6)}{iban[-4:]}" if len(iban) >= 6 else "****"

        frappe.logger().info(
            f"BANK ACCOUNT UPDATE: User {frappe.session.user} updated Mollie bank account "
            f"for member {member_name}. IBAN: {masked_iban}"
        )

        return {
            "status": "success",
            "message": _("Bank account updated successfully. Your next payment will use the new account."),
            "masked_iban": masked_iban,
        }

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(
            f"Mollie bank account update failed for member {member_name}: {error_msg}",
            "Mollie Bank Account Update",
        )
        return {
            "status": "error",
            "message": _("Failed to update bank account. Please try again or contact support."),
        }
```

**Step 2: Verify import works**

Run: `cd ~/frappe-bench && python -c "from verenigingen.api.mollie_payment import update_mollie_bank_account; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```
feat(mollie): add update_mollie_bank_account API endpoint
```

---

## Task 3: Frontend — Button + inline form + JS handler

Add "Update Bank Account" button to the Mollie subscription card and the JS handler. All changes are within the existing `payment_dashboard.html`.

**Files:**
- Modify: `verenigingen/templates/pages/payment_dashboard.html`

**Step 1: Add the button to the subscription card**

In the `updateMollieDisplay()` function, find the button row (the `<div class="mt-4 pt-3 border-t border-gray-200">` at ~line 1301). Replace that div to include both buttons and the hidden inline form.

Find this block (~line 1301-1307):
```html
<div class="mt-4 pt-3 border-t border-gray-200">
    <button onclick="cancelMollieSubscription('${customerId}', '${subscriptionId}')"
            class="inline-flex items-center px-4 py-2 text-sm font-medium text-danger-700 bg-danger-50 border border-danger-300 rounded-lg hover:bg-danger-100 transition-colors duration-200">
        <i class="fa fa-times-circle mr-2"></i>
        {{ _("Cancel Subscription") }}
    </button>
</div>
```

Replace with:
```html
<div class="mt-4 pt-3 border-t border-gray-200">
    <div class="flex flex-wrap gap-2">
        <button onclick="toggleBankAccountForm('${customerId}', '${subscriptionId}')"
                id="update-bank-btn-${subscriptionId}"
                class="inline-flex items-center px-4 py-2 text-sm font-medium text-primary-700 bg-primary-50 border border-primary-300 rounded-lg hover:bg-primary-100 transition-colors duration-200">
            <i class="fa fa-university mr-2"></i>
            {{ _("Update Bank Account") }}
        </button>
        <button onclick="cancelMollieSubscription('${customerId}', '${subscriptionId}')"
                class="inline-flex items-center px-4 py-2 text-sm font-medium text-danger-700 bg-danger-50 border border-danger-300 rounded-lg hover:bg-danger-100 transition-colors duration-200">
            <i class="fa fa-times-circle mr-2"></i>
            {{ _("Cancel Subscription") }}
        </button>
    </div>
    <div id="bank-account-form-${subscriptionId}" class="hidden mt-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
        <p class="text-sm text-gray-600 mb-3">
            {{ _("This will update the bank account used for your recurring payments.") }}
        </p>
        <div class="mb-3">
            <label class="block text-sm font-medium text-gray-700 mb-1">
                {{ _("IBAN") }} <span class="text-red-500">*</span>
            </label>
            <input type="text"
                   id="mollie-iban-${subscriptionId}"
                   class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                   placeholder="{{ _('NL91 ABNA 0417 1643 00') }}"
                   maxlength="42"
                   oninput="formatIbanInput(this)">
        </div>
        <div class="mb-3">
            <label class="block text-sm font-medium text-gray-700 mb-1">
                {{ _("Account holder name") }} <span class="text-red-500">*</span>
            </label>
            <input type="text"
                   id="mollie-holder-${subscriptionId}"
                   class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                   value="${escapeHtml('{{ member_doc.full_name if member_doc else "" }}')}"
                   maxlength="70">
        </div>
        <div class="flex gap-2">
            <button onclick="submitBankAccountUpdate('${customerId}', '${subscriptionId}')"
                    id="submit-bank-btn-${subscriptionId}"
                    class="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 transition-colors duration-200">
                <i class="fa fa-check mr-2"></i>
                {{ _("Confirm") }}
            </button>
            <button onclick="toggleBankAccountForm('${customerId}', '${subscriptionId}')"
                    class="inline-flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors duration-200">
                {{ _("Cancel") }}
            </button>
        </div>
    </div>
</div>
```

**Step 2: Add the JS functions**

Insert these functions after the `cancelMollieSubscription()` function (~line 1535), before the `downloadReceipt()` function:

```javascript
// Toggle bank account update form
function toggleBankAccountForm(customerId, subscriptionId) {
    const form = document.getElementById('bank-account-form-' + subscriptionId);
    if (form) {
        form.classList.toggle('hidden');
        // Focus IBAN input when opening
        if (!form.classList.contains('hidden')) {
            const ibanInput = document.getElementById('mollie-iban-' + subscriptionId);
            if (ibanInput) ibanInput.focus();
        }
    }
}

// Format IBAN input with spaces every 4 characters
function formatIbanInput(input) {
    let value = input.value.replace(/\s/g, '').toUpperCase();
    // Insert space every 4 characters
    let formatted = '';
    for (let i = 0; i < value.length; i++) {
        if (i > 0 && i % 4 === 0) formatted += ' ';
        formatted += value[i];
    }
    input.value = formatted;
}

// Submit bank account update to Mollie
function submitBankAccountUpdate(customerId, subscriptionId) {
    const ibanInput = document.getElementById('mollie-iban-' + subscriptionId);
    const holderInput = document.getElementById('mollie-holder-' + subscriptionId);
    const submitBtn = document.getElementById('submit-bank-btn-' + subscriptionId);

    const iban = ibanInput ? ibanInput.value.replace(/\s/g, '') : '';
    const holder = holderInput ? holderInput.value.trim() : '';

    // Client-side validation
    if (!iban || iban.length < 15 || !/^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/.test(iban)) {
        showMessage(__("Please enter a valid IBAN"), 'error');
        if (ibanInput) ibanInput.focus();
        return;
    }
    if (!holder) {
        showMessage(__("Please enter the account holder name"), 'error');
        if (holderInput) holderInput.focus();
        return;
    }

    // Disable button during request
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin mr-2"></i>' + __("Updating...");
    }

    frappe.call({
        method: 'verenigingen.api.mollie_payment.update_mollie_bank_account',
        args: {
            iban: iban,
            account_holder_name: holder
        },
        callback: function(r) {
            if (r.message && r.message.status === 'success') {
                showMessage(r.message.message || __("Bank account updated successfully"), 'success');
                // Hide form and reload Mollie status
                toggleBankAccountForm(customerId, subscriptionId);
                loadMollieStatus();
            } else {
                const errorMsg = r.message && r.message.message ? r.message.message : __("Failed to update bank account");
                showMessage(errorMsg, 'error');
            }
            // Re-enable button
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fa fa-check mr-2"></i>' + __("Confirm");
            }
        },
        error: function() {
            showMessage(__("An error occurred. Please try again or contact support."), 'error');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fa fa-check mr-2"></i>' + __("Confirm");
            }
        }
    });
}
```

**Step 3: Verify the page loads**

Visit `/payment_dashboard` in the browser, confirm the Mollie card renders with the new button (no JS errors in console).

**Step 4: Commit**

```
feat(mollie): add update bank account UI to payment dashboard
```

---

## Task 4: Manual end-to-end test

This feature touches the live Mollie API, so automated testing would require extensive mocking of the SDK. A manual test against the Mollie test environment is more valuable.

**Preconditions:**
- Mollie test API key configured in Verenigingen Payments Settings
- A member with an active Mollie test subscription (`mollie_customer_id`, `mollie_subscription_id`, `mollie_mandate_id` all set)

**Steps:**
1. Log in as the member
2. Go to `/payment_dashboard`
3. In the Mollie subscription card, click "Update Bank Account"
4. Enter a valid test IBAN (e.g., `NL91 ABNA 0417 1643 00`) and account holder name
5. Click "Confirm"
6. Verify success message appears
7. Verify in Mollie dashboard (test mode): subscription now has a new `mandateId`
8. Verify in Frappe: member's `mollie_mandate_id` field updated
9. Test error cases:
   - Invalid IBAN → error shown, nothing changed
   - Empty holder name → error shown
   - Member without subscription → button should not appear (subscription not active)

**Step 1: Commit all tasks together if not already committed**

```
feat(mollie): allow members to update bank account on active subscription

Members can now update their bank account (IBAN) for an active Mollie
subscription directly from the payment dashboard. Creates a new Mollie
mandate and patches the subscription without cancel/recreate.
```
