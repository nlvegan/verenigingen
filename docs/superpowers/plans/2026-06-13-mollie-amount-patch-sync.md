# Mollie PATCH-Based Amendment Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Amount-only member amendments PATCH the existing Mollie subscription (repairing drifted description/webhookUrl in the same call) instead of replace-and-cancel; the broken mandate-id gate and the stuck-status handler get fixed; the 3 stuck veg11 amendments get re-synced.

**Architecture:** A new `MollieClient.update_subscription` wrapper and a shared description helper feed a PATCH path inside `MollieSubscriptionSyncService.sync_subscription_for_amendment`, taken when the amendment leaves the billing interval unchanged. The replacement path remains for interval changes, with its mandate validation re-sourced from the live subscription. The amendment event handler maps every sync outcome to a visible `mollie_sync_status` (new options: Skipped, Needs Review). A v2_2 patch re-enqueues the latest stuck amendment per member.

**Tech Stack:** Frappe v16, mollie-api-python SDK (fake-SDK test harness already in `verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py`), bench run-tests on test_site_1.

**Spec:** `docs/superpowers/specs/2026-06-13-mollie-amount-patch-sync-design.md`

**Conventions for all tasks:**
- Run tests with: `cd ~/frappe-bench && bench --site test_site_1 run-tests --module <module>` (cwd resets to the app root afterwards; all file paths below are relative to `~/frappe-bench/apps/verenigingen`).
- Every commit triggers pre-commit hooks; they are expected to pass without SKIP.
- Line numbers refer to the files BEFORE this plan starts; locate edits by the quoted code.

---

### Task 1: Shared description helper

**Files:**
- Create: `verenigingen/verenigingen_payments/mollie/services/subscription_description.py`
- Test: `verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py` (inside a new test class at the end of the file):

```python
class TestSubscriptionDescription(EnhancedTestCase):
    """Canonical member-subscription description from Verenigingen Payments Settings."""

    def _member(self):
        token = frappe.generate_hash(length=8)
        return self.create_test_member(
            first_name="Desc",
            last_name=f"Helper{token}",
            email=f"desc-{token}@example.com",
            birth_date="1990-01-01",
        )

    def test_description_uses_default_template(self):
        from verenigingen.verenigingen_payments.mollie.services.subscription_description import (
            get_member_subscription_description,
        )

        frappe.db.set_single_value(
            "Verenigingen Payments Settings", "mollie_subscription_description_template", ""
        )
        member = self._member()
        self.assertEqual(
            get_member_subscription_description(member),
            f"Contribution payment for member {member.member_id}",
        )

    def test_description_substitutes_custom_template(self):
        from verenigingen.verenigingen_payments.mollie.services.subscription_description import (
            get_member_subscription_description,
        )

        frappe.db.set_single_value(
            "Verenigingen Payments Settings",
            "mollie_subscription_description_template",
            "Dues MEMBER_NAME (MEMBER_ID)",
        )
        member = self._member()
        self.assertEqual(
            get_member_subscription_description(member),
            f"Dues {member.full_name} ({member.member_id})",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.tests.payment.test_mollie_amendment_subscription_sync`
Expected: 2 failures/errors — `ModuleNotFoundError`/`ImportError` for `subscription_description` (the 2 pre-existing tests stay green).

- [ ] **Step 3: Implement the helper**

Create `verenigingen/verenigingen_payments/mollie/services/subscription_description.py`:

```python
"""
Canonical Mollie subscription description for members.

The template lives on Verenigingen Payments Settings
(`mollie_subscription_description_template`, placeholders MEMBER_ID and
MEMBER_NAME) - the same field the payment dashboard's manual-transfer
reference renders, and the format live subscriptions were created with.
Creation and PATCH paths must build descriptions through this helper so
they cannot drift apart again.
"""

import frappe

DEFAULT_TEMPLATE = "Contribution payment for member MEMBER_ID"


def get_member_subscription_description(member) -> str:
    """Render the canonical subscription description for a Member document."""
    template = (
        frappe.db.get_single_value(
            "Verenigingen Payments Settings", "mollie_subscription_description_template"
        )
        or DEFAULT_TEMPLATE
    )
    return template.replace("MEMBER_NAME", member.full_name or "").replace(
        "MEMBER_ID", str(member.member_id or member.name)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Same command as Step 2. Expected: OK (4 tests).

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen_payments/mollie/services/subscription_description.py verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py
git commit -m "feat(mollie): canonical member subscription description helper"
```

---

### Task 2: `MollieClient.update_subscription` wrapper

**Files:**
- Modify: `verenigingen/verenigingen_payments/mollie/core/client.py` (after `get_subscription`, ~line 238)
- Test: `verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py` (extend fakes + append test)

- [ ] **Step 1: Extend the fake harness**

In `test_mollie_amendment_subscription_sync.py`, replace the existing fake classes (`_FakeSubscription` through `FakeSDKClient`, lines 27-63) with this richer harness (keeps existing behavior, adds `get`/`update`/`delete`, configurable live-subscription fields, and mandates):

```python
class _FakeSubscription:
    def __init__(
        self,
        subscription_id="sub_FAKE",
        status="active",
        amount=None,
        interval="1 month",
        description="",
        webhook_url="",
        mandate_id=None,
        next_payment_date="2026-07-01",
    ):
        self.id = subscription_id
        self.status = status
        self.amount = amount or {"value": "25.50", "currency": "EUR"}
        self.interval = interval
        self.description = description
        self.webhook_url = webhook_url
        self.mandate_id = mandate_id
        self.next_payment_date = next_payment_date
        self.metadata = {}


class _FakeMandate:
    def __init__(self, mandate_id="mdt_FAKE", status="valid"):
        self.id = mandate_id
        self.status = status


class _FakeMandates:
    def get(self, mandate_id):
        return _FakeMandate(mandate_id=mandate_id)


class _FakeSubscriptions:
    def __init__(self, sdk):
        self._sdk = sdk

    def create(self, data=None):
        self._sdk.subscriptions_created.append(data)
        return _FakeSubscription(mandate_id=(data or {}).get("mandateId"))

    def get(self, subscription_id):
        live = self._sdk.live_subscription
        live.id = subscription_id
        return live

    def update(self, subscription_id, data=None):
        self._sdk.subscriptions_updated.append((subscription_id, data))
        live = self._sdk.live_subscription
        updated = _FakeSubscription(
            subscription_id=subscription_id,
            status=live.status,
            amount=(data or {}).get("amount", live.amount),
            interval=live.interval,
            description=(data or {}).get("description", live.description),
            webhook_url=(data or {}).get("webhookUrl", live.webhook_url),
            mandate_id=live.mandate_id,
            next_payment_date=live.next_payment_date,
        )
        return updated

    def delete(self, subscription_id):
        self._sdk.subscriptions_deleted.append(subscription_id)
        return _FakeSubscription(subscription_id=subscription_id, status="canceled")


class _FakeCustomer:
    def __init__(self, sdk):
        self.subscriptions = _FakeSubscriptions(sdk)
        self.mandates = _FakeMandates()


class _FakeCustomers:
    def __init__(self, sdk):
        self._sdk = sdk
        self.fetched = []

    def get(self, customer_id):
        self.fetched.append(customer_id)
        return _FakeCustomer(self._sdk)


class FakeSDKClient:
    """Stand-in for ``mollie.api.client.Client``."""

    def __init__(self, live_subscription=None):
        self.subscriptions_created = []
        self.subscriptions_updated = []
        self.subscriptions_deleted = []
        self.live_subscription = live_subscription or _FakeSubscription()
        self.customers = _FakeCustomers(self)
```

Then update the two existing tests: `test_create_replacement_subscription_passes_subscription_data_dict` asserts `sdk.subscriptions_created` (unchanged name) and `sdk.customers.fetched` (unchanged) — both still work. No edits needed to their bodies.

- [ ] **Step 2: Write the failing wrapper test**

Append to the `TestAmendmentSubscriptionSync` class:

```python
    def test_client_update_subscription_patches_via_sdk(self):
        sdk = FakeSDKClient()
        client = _make_mollie_client(sdk)

        result = client.update_subscription(
            "cst_SYNC", "sub_LIVE", {"amount": {"value": "26.50", "currency": "EUR"}}
        )

        self.assertEqual(
            sdk.subscriptions_updated,
            [("sub_LIVE", {"amount": {"value": "26.50", "currency": "EUR"}})],
        )
        self.assertEqual(result.amount, {"value": "26.50", "currency": "EUR"})
```

- [ ] **Step 3: Run to verify failure**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.tests.payment.test_mollie_amendment_subscription_sync`
Expected: 1 error — `AttributeError: 'MollieClient' object has no attribute 'update_subscription'`. The 2 pre-existing tests must still pass (fake-harness compatibility check).

- [ ] **Step 4: Implement the wrapper**

In `verenigingen/verenigingen_payments/mollie/core/client.py`, directly after the `get_subscription` method (match the surrounding wrappers' style — same try/except shape as `get_subscription`/`cancel_subscription`, same `MolliePaymentError` import already present):

```python
    def update_subscription(
        self, customer_id: str, subscription_id: str, update_data: Dict[str, Any]
    ) -> Any:
        """
        PATCH fields on an existing subscription (amount, description,
        webhookUrl, ...) without replacing it.

        Args:
            customer_id: The Mollie customer ID
            subscription_id: The subscription ID
            update_data: Fields to update, in Mollie API shape

        Returns:
            The updated Mollie subscription object

        Raises:
            MolliePaymentError: When the subscription cannot be updated
        """
        try:
            client = self._get_mollie_client()
            customer = client.customers.get(customer_id)
            return customer.subscriptions.update(subscription_id, update_data)
        except Exception as e:
            error_msg = f"Failed to update subscription {subscription_id}: {e}"
            frappe.log_error(error_msg, "Mollie Subscription Update")
            raise MolliePaymentError(error_msg, original_error=e)
```

(If `get_subscription`'s body uses a different client-access idiom — e.g. `self.sdk_client` — mirror that idiom instead; the error-wrapping shape is the contract.)

- [ ] **Step 5: Run to verify pass, commit**

Same command. Expected: OK (5 tests).

```bash
git add verenigingen/verenigingen_payments/mollie/core/client.py verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py
git commit -m "feat(mollie): add MollieClient.update_subscription PATCH wrapper"
```

---

### Task 3: Expose `webhook_url` + `mandate_id` in `get_subscription_status`

**Files:**
- Modify: `verenigingen/verenigingen_payments/mollie/services/subscription_service.py:54-79`
- Test: `verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `TestAmendmentSubscriptionSync`:

```python
    def test_get_subscription_status_exposes_webhook_and_mandate(self):
        from verenigingen.verenigingen_payments.mollie.services.subscription_service import (
            SubscriptionService,
        )

        sdk = FakeSDKClient(
            live_subscription=_FakeSubscription(
                webhook_url="https://old.example/hook", mandate_id="mdt_LIVE"
            )
        )
        service = SubscriptionService(_make_mollie_client(sdk))

        status = service.get_subscription_status("cst_SYNC", "sub_LIVE")

        self.assertEqual(status["webhook_url"], "https://old.example/hook")
        self.assertEqual(status["mandate_id"], "mdt_LIVE")
```

- [ ] **Step 2: Run to verify failure**

Expected: `KeyError: 'webhook_url'`.

- [ ] **Step 3: Implement**

In `subscription_service.py`, inside the dict returned by `get_subscription_status` (after the `"metadata"` line):

```python
            "webhook_url": subscription.webhook_url,
            "mandate_id": subscription.mandate_id,
```

- [ ] **Step 4: Run to verify pass, commit**

Expected: OK (6 tests).

```bash
git add verenigingen/verenigingen_payments/mollie/services/subscription_service.py verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py
git commit -m "feat(mollie): expose webhook_url and mandate_id in subscription status"
```

---

### Task 4: Sync service — gate fix, PATCH path, mandate re-sourcing

**Files:**
- Modify: `verenigingen/verenigingen_payments/mollie/services/mollie_subscription_sync_service.py`
- Test: `verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py` (append)

- [ ] **Step 1: Write the failing tests**

Append a new test class. Notes on fixtures: the amendment doc is built with `frappe.get_doc({...})` and **never inserted** — the sync only reads its fields. The membership comes from the factory. `Fee Change` with no dues schedule computes interval `"1 month"`, so a fake live subscription with interval `"1 month"` exercises the PATCH path and one with `"3 months"` exercises the replacement path.

```python
class TestAmendmentSyncPatchPath(EnhancedTestCase):
    """Amount-only amendments PATCH the live subscription; drifted
    description/webhookUrl are repaired in the same call."""

    def _member_with_subscription(self, mandate_id=None):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Patch",
            last_name=f"Sync{token}",
            email=f"patch-{token}@example.com",
            birth_date="1990-01-01",
        )
        values = {
            "mollie_customer_id": "cst_SYNC",
            "mollie_subscription_id": "sub_LIVE",
        }
        if mandate_id:
            values["mollie_mandate_id"] = mandate_id
        frappe.db.set_value("Member", member.name, values, update_modified=False)
        member.reload()
        membership = self.create_test_membership(member_name=member.name)
        return member, membership

    def _fee_change_amendment(self, membership, member, amount=26.5):
        return frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": amount,
                "status": "Applied",
            }
        )

    def _canonical_pair(self, member):
        from verenigingen.verenigingen_payments.mollie.services.subscription_description import (
            get_member_subscription_description,
        )

        settings = frappe.get_single("Mollie Settings")
        return get_member_subscription_description(member), settings.get_subscription_webhook_url()

    def test_amount_only_amendment_patches_without_replacing(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription()  # NO mandate id: gate must not skip
        canonical_desc, canonical_hook = self._canonical_pair(member)
        sdk = FakeSDKClient(
            live_subscription=_FakeSubscription(
                interval="1 month",
                description=canonical_desc,
                webhook_url=canonical_hook,
                mandate_id="mdt_LIVE",
            )
        )
        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))

        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_LIVE")
        # PATCH happened; nothing was created or canceled.
        self.assertEqual(len(sdk.subscriptions_updated), 1)
        self.assertEqual(sdk.subscriptions_created, [])
        self.assertEqual(sdk.subscriptions_deleted, [])
        sub_id, payload = sdk.subscriptions_updated[0]
        self.assertEqual(sub_id, "sub_LIVE")
        # No drift -> amount is the only key.
        self.assertEqual(payload, {"amount": {"value": "26.50", "currency": "EUR"}})
        # Member keeps the same subscription id.
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "mollie_subscription_id"), "sub_LIVE"
        )

    def test_patch_repairs_drifted_description_and_webhook(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription()
        canonical_desc, canonical_hook = self._canonical_pair(member)
        sdk = FakeSDKClient(
            live_subscription=_FakeSubscription(
                interval="1 month",
                description="Membership dues - Stale Format",
                webhook_url="https://dev.veganisme.net/api/method/old.path?env=test",
                mandate_id="mdt_LIVE",
            )
        )
        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))

        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "success")
        _, payload = sdk.subscriptions_updated[0]
        self.assertEqual(payload["description"], canonical_desc)
        self.assertEqual(payload["webhookUrl"], canonical_hook)

    def test_interval_change_takes_replacement_path(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription(mandate_id="mdt_LIVE")
        # Live interval differs from the computed "1 month" -> replacement.
        sdk = FakeSDKClient(live_subscription=_FakeSubscription(interval="3 months"))
        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))

        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        # Replacement created a new subscription and never PATCHed.
        self.assertEqual(len(sdk.subscriptions_created), 1)
        self.assertEqual(sdk.subscriptions_updated, [])
        self.assertIn(result["status"], ("success", "warning"))

    def test_patch_amount_mismatch_returns_warning(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription()
        canonical_desc, canonical_hook = self._canonical_pair(member)
        live = _FakeSubscription(
            interval="1 month",
            description=canonical_desc,
            webhook_url=canonical_hook,
        )
        sdk = FakeSDKClient(live_subscription=live)

        # Make the fake's update() echo a WRONG amount back.
        class _WrongAmountSubscriptions(_FakeSubscriptions):
            def update(self, subscription_id, data=None):
                self._sdk.subscriptions_updated.append((subscription_id, data))
                return _FakeSubscription(
                    subscription_id=subscription_id,
                    amount={"value": "99.99", "currency": "EUR"},
                    interval="1 month",
                )

        class _WrongAmountCustomer(_FakeCustomer):
            def __init__(self, sdk):
                super().__init__(sdk)
                self.subscriptions = _WrongAmountSubscriptions(sdk)

        sdk.customers.get = lambda cid: _WrongAmountCustomer(sdk)

        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))
        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "warning")
        self.assertTrue(result["requires_admin_review"])

    def test_member_without_subscription_id_is_skipped(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="NoSub",
            last_name=f"Sync{token}",
            email=f"nosub-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value(
            "Member", member.name, "mollie_customer_id", "cst_SYNC", update_modified=False
        )
        member.reload()
        membership = self.create_test_membership(member_name=member.name)
        service = MollieSubscriptionSyncService(client=_make_mollie_client(FakeSDKClient()))

        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_mollie_subscription")

    def test_replacement_mandate_resolves_from_subscription_first(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        service = MollieSubscriptionSyncService(client=_make_mollie_client(FakeSDKClient()))
        member = frappe._dict(mollie_mandate_id="mdt_FIELD")

        self.assertEqual(
            service._mandate_id_for_replacement(member, {"mandate_id": "mdt_SUB"}), "mdt_SUB"
        )
        self.assertEqual(
            service._mandate_id_for_replacement(member, {"mandate_id": None}), "mdt_FIELD"
        )
```

- [ ] **Step 2: Run to verify failures**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.tests.payment.test_mollie_amendment_subscription_sync`
Expected: 5 of the 6 new tests fail (skip results where success expected — the mandate gate still blocks — and `AttributeError` for `_mandate_id_for_replacement`); `test_member_without_subscription_id_is_skipped` already passes (that gate behavior is retained), as do the 6 earlier tests.

- [ ] **Step 3: Implement the sync-service changes**

All in `mollie_subscription_sync_service.py`.

**(a) Import the description helper** (top of file, with the other service imports):

```python
from verenigingen.verenigingen_payments.mollie.services.subscription_description import (
    get_member_subscription_description,
)
```

**(b) Gate fix** — replace (currently ~line 77):

```python
            if not member.mollie_subscription_id or not member.mollie_mandate_id:
                frappe.logger().info(
                    f"⚠️ Member {member.name} has no Mollie subscription or mandate, skipping sync"
                )
```

with (the mandate field is populated for almost nobody — requiring it silently skipped every sync):

```python
            if not member.mollie_subscription_id:
                frappe.logger().info(
                    f"⚠️ Member {member.name} has no Mollie subscription, skipping sync"
                )
```

**(c) Remove the up-front mandate validation block** (~lines 87-110, from `# Validate SEPA mandate is still active via Mollie API` through the `mandate_validation_failed` return) — it moves into the replacement branch in (e).

**(d) Insert the PATCH-path branch.** After the existing lines

```python
            # Determine new subscription parameters from amendment
            new_amount, new_interval = self._get_subscription_parameters(amendment_doc, membership)
```

insert:

```python
            # Amount-only change: PATCH the live subscription in place.
            # The subscription id stays stable; drifted description/webhook
            # values are repaired in the same call.
            if new_interval == old_subscription.get("interval"):
                return self._patch_subscription_amount(
                    member, amendment_doc, old_subscription, new_amount
                )

            # Interval changed: replacement path. Validate the mandate that
            # the NEW subscription will charge against. The live subscription
            # is the authoritative mandate source; the Member field is only a
            # fallback (it was historically never populated).
            replacement_mandate_id = self._mandate_id_for_replacement(member, old_subscription)
            if replacement_mandate_id:
                try:
                    raw_mollie_client = self.client._get_mollie_client()
                    customer_obj = raw_mollie_client.customers.get(member.mollie_customer_id)
                    mandate = customer_obj.mandates.get(replacement_mandate_id)
                    if mandate.status not in ["valid", "pending"]:
                        return {
                            "status": "error",
                            "reason": "invalid_mandate",
                            "message": f"SEPA mandate is {mandate.status}. Cannot create new subscription. Please renew mandate first.",
                            "requires_admin_review": True,
                        }
                except Exception as mandate_error:
                    return {
                        "status": "error",
                        "reason": "mandate_validation_failed",
                        "message": f"Could not validate SEPA mandate: {str(mandate_error)}",
                        "requires_admin_review": True,
                    }
```

**(e) Add the two new methods** (place after `sync_subscription_for_amendment`, before `_create_replacement_subscription`):

```python
    def _patch_subscription_amount(self, member, amendment_doc, live_subscription, new_amount):
        """PATCH the live subscription's amount, repairing drifted
        description/webhookUrl in the same call. Returns a sync-result dict."""
        payload = self._build_amount_patch_payload(member, live_subscription, new_amount)
        subscription_id = live_subscription["id"]

        try:
            updated = self.client.update_subscription(
                member.mollie_customer_id, subscription_id, payload
            )
        except Exception as patch_error:
            return {
                "status": "error",
                "reason": "patch_failed",
                "subscription_id": subscription_id,
                "message": f"Mollie PATCH failed: {str(patch_error)}",
                "requires_admin_review": True,
            }

        updated_amount = extract_amount_float(updated.amount)
        if abs(updated_amount - float(new_amount)) > 0.005:
            return {
                "status": "warning",
                "subscription_id": subscription_id,
                "message": (
                    f"PATCH returned amount {updated_amount}, expected {new_amount}. "
                    "Manual verification required."
                ),
                "requires_admin_review": True,
            }

        member.db_set(
            {
                "subscription_status": updated.status,
                "next_payment_date": getattr(updated, "next_payment_date", None),
            },
            update_modified=False,
        )

        repaired = [key for key in ("description", "webhookUrl") if key in payload]
        frappe.logger().info(
            f"✅ PATCHed subscription {subscription_id} for amendment {amendment_doc.name}: "
            f"amount -> {new_amount}"
            + (f", repaired drifted {', '.join(repaired)}" if repaired else "")
        )
        return {
            "status": "success",
            "subscription_id": subscription_id,
            "patched_fields": list(payload.keys()),
            "message": f"Subscription amount updated to {new_amount} via PATCH",
        }

    def _build_amount_patch_payload(self, member, live_subscription, new_amount) -> dict:
        """Amount always; description/webhookUrl only when the live values
        differ from the canonical ones (drift repair)."""
        payload = {"amount": format_mollie_amount(new_amount, "EUR")}

        canonical_description = get_member_subscription_description(member)
        if (live_subscription.get("description") or "") != canonical_description:
            payload["description"] = canonical_description

        canonical_webhook = frappe.get_single("Mollie Settings").get_subscription_webhook_url()
        if (live_subscription.get("webhook_url") or "") != canonical_webhook:
            payload["webhookUrl"] = canonical_webhook

        return payload

    def _mandate_id_for_replacement(self, member, live_subscription):
        """The live subscription's mandate is authoritative; the Member
        field is a fallback for subscriptions Mollie reports without one."""
        return live_subscription.get("mandate_id") or member.mollie_mandate_id
```

(`extract_amount_float` and `format_mollie_amount` are already imported by this module — verify at the top of the file; add to the existing import line if missing.)

**(f) Switch the replacement description to the helper** — in `_create_replacement_subscription`, replace:

```python
            "description": f"Membership dues - {member.first_name} {member.last_name}",
```

with:

```python
            "description": get_member_subscription_description(member),
```

**(g) Canonical webhook for replacement** — replace the body of `_get_webhook_url` (currently builds a hardcoded unified-handler URL):

```python
    def _get_webhook_url(self) -> str:
        """Canonical subscription webhook URL (Mollie Settings owns it)."""
        return frappe.get_single("Mollie Settings").get_subscription_webhook_url()
```

- [ ] **Step 4: Run to verify pass**

Same command. Expected: OK (12 tests). Note: `test_create_replacement_subscription_passes_subscription_data_dict` does not assert the description value, so (f)/(g) cannot break it — if it fails, read the assertion before touching anything.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen_payments/mollie/services/mollie_subscription_sync_service.py verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py
git commit -m "feat(mollie): PATCH amount-only amendments in place with drift repair

The mandate-id gate silently skipped every amendment sync (the field was
never populated); amount-only changes now PATCH the live subscription
(id stable, no churn) and repair drifted description/webhookUrl in the
same call. Replacement remains for interval changes, with its mandate
validation re-sourced from the live subscription."
```

---

### Task 5: Gateway creation path uses the canonical description

**Files:**
- Modify: `verenigingen/verenigingen_payments/utils/payment_gateways.py` (`MollieGateway.create_subscription`, line 511; description default ~line 563)
- Test: `verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py` (append)

- [ ] **Step 1: Write the failing test**

`MollieGateway.create_subscription(member, subscription_data)` builds the Mollie payload and hands it to `CompletePaymentService.create_customer_subscription`. The test patches that service boundary (external-call orchestrator — the same seam the portal-endpoint unit tests patch) to capture the payload and asserts the default description comes from the helper.

Append to the test module:

```python
class TestGatewayDescriptionDefault(EnhancedTestCase):
    """MollieGateway.create_subscription defaults the description to the
    canonical helper output instead of a hardcoded format."""

    def test_gateway_defaults_description_to_canonical_helper(self):
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.services.subscription_description import (
            get_member_subscription_description,
        )
        from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Gateway",
            last_name=f"Desc{token}",
            email=f"gateway-{token}@example.com",
            birth_date="1990-01-01",
        )

        captured = {}

        def _capture(self_service, customer_data, subscription_data):
            captured["subscription_data"] = subscription_data
            return {
                "status": "success",
                "customer_id": "cst_CAP",
                "subscription_id": "sub_CAP",
                "subscription_status": "active",
            }

        gateway = MollieGateway.__new__(MollieGateway)  # skip __init__ (loads live settings)
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.complete_payment_service.CompletePaymentService.create_customer_subscription",
            _capture,
        ), patch.object(
            MollieGateway, "settings", create=True
        ) as fake_settings:
            fake_settings.get_subscription_webhook_url.return_value = "https://x.example/hook"
            gateway.create_subscription(
                member, {"amount": 15.0, "interval": "1 month"}
            )

        self.assertEqual(
            captured["subscription_data"]["description"],
            get_member_subscription_description(member),
        )
```

Note for the executor: if `MollieGateway.__new__` + patched `settings` does not satisfy `create_subscription`'s internals (it may read other instance attributes), instantiate the gateway normally with `MollieGateway("Default")` inside the same patch context and patch whatever construction-time call hits Mollie — adapt the *setup*, never the assertion.

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.tests.payment.test_mollie_amendment_subscription_sync`
Expected: the new test FAILS with the captured description equal to `"Membership dues for Gateway Desc<token>"` (the old hardcoded format), not the helper output.

- [ ] **Step 3: Implement**

In the member-subscription creation payload (search for `"description": subscription_data.get(`), replace:

```python
                "description": subscription_data.get(
                    "description", f"Membership dues for {member.first_name} {member.last_name}"
                ),
```

with:

```python
                "description": subscription_data.get(
                    "description", get_member_subscription_description(member)
                ),
```

and add the import at the top of the file with the other verenigingen imports:

```python
from verenigingen.verenigingen_payments.mollie.services.subscription_description import (
    get_member_subscription_description,
)
```

(If a circular-import error appears at Step 4, move the import inside the method instead — `payment_gateways.py` is a large legacy module with heavy import traffic.)

- [ ] **Step 4: Run to verify pass**

```bash
cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.tests.payment.test_mollie_amendment_subscription_sync
cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.tests.payment.test_mollie_subscription_consolidation
```
Expected: both OK. (The consolidation suite's gateway tests pass an explicit description or assert other fields; if one asserts the old default format, update that assertion to call the helper.)

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen_payments/utils/payment_gateways.py verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py
git commit -m "refactor(mollie): gateway subscription creation uses canonical description helper"
```

---

### Task 6: Handler status lifecycle + new Select options

**Files:**
- Modify: `verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.json` (`mollie_sync_status` options)
- Modify: `verenigingen/verenigingen_payments/mollie/events/amendment_events.py`
- Test: `verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py` (append)

- [ ] **Step 1: Write the failing test**

```python
class TestSyncResultStatusMapping(EnhancedTestCase):
    """Every sync outcome maps to a visible mollie_sync_status."""

    def test_status_mapping(self):
        from verenigingen.verenigingen_payments.mollie.events.amendment_events import (
            _sync_status_update_for_result,
        )

        self.assertEqual(
            _sync_status_update_for_result({"status": "success"}), ("Completed", 1, False)
        )
        self.assertEqual(
            _sync_status_update_for_result({"status": "skipped", "reason": "x"}),
            ("Skipped", 0, False),
        )
        self.assertEqual(
            _sync_status_update_for_result(
                {"status": "warning", "requires_admin_review": True}
            ),
            ("Needs Review", 0, True),
        )
        # error notifies admins even without the explicit review flag
        self.assertEqual(
            _sync_status_update_for_result({"status": "error"}), ("Failed", 0, True)
        )
```

- [ ] **Step 2: Run to verify failure**

Expected: `ImportError: cannot import name '_sync_status_update_for_result'`.

- [ ] **Step 3: Update the DocType options**

In `contribution_amendment_request.json`, change the `mollie_sync_status` field's options from:

```
"options": "Not Started\nQueued\nIn Progress\nCompleted\nFailed"
```

to:

```
"options": "Not Started\nQueued\nIn Progress\nCompleted\nFailed\nSkipped\nNeeds Review"
```

Then: `cd ~/frappe-bench && bench --site test_site_1 reload-doctype "Contribution Amendment Request"`

- [ ] **Step 4: Implement the mapper and rewire the handler**

In `amendment_events.py`, add above `sync_mollie_subscription_on_amendment_applied`:

```python
def _sync_status_update_for_result(result):
    """Map a sync-result dict to (mollie_sync_status, completed_flag, notify_admins).

    Errors always notify - the previous behavior (notify only with
    requires_admin_review, status left 'In Progress') hid every failure.
    """
    status = result.get("status")
    if status == "success":
        return "Completed", 1, False
    if status == "skipped":
        return "Skipped", 0, False
    if status == "warning":
        return "Needs Review", 0, bool(result.get("requires_admin_review"))
    return "Failed", 0, True
```

Then replace the four `if/elif` result branches inside the handler (from `if result["status"] == "success":` through the end of the `elif result["status"] == "error":` block) with:

```python
        status_value, completed, notify = _sync_status_update_for_result(result)

        frappe.logger().info(
            f"Mollie subscription sync for amendment {doc.name}: "
            f"{result.get('status')} -> {status_value} ({result.get('message') or result.get('reason') or ''})"
        )

        frappe.db.set_value(
            "Contribution Amendment Request",
            doc.name,
            {"mollie_sync_completed": completed, "mollie_sync_status": status_value},
            update_modified=False,
        )
        frappe.db.commit()

        if notify:
            notify_administrators_of_sync_issue(doc, result)
```

(The `except Exception` block below stays unchanged — exceptions still mark Failed via `handle_mollie_sync_failure` and re-raise.)

- [ ] **Step 5: Run to verify pass, commit**

Run the module. Expected: OK (14 tests).

```bash
git add verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.json verenigingen/verenigingen_payments/mollie/events/amendment_events.py verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py
git commit -m "fix(mollie): amendment sync outcomes always land in a visible status

skipped -> Skipped, warning -> Needs Review, error -> Failed (+ admin
notification, previously silent); no more amendments stuck at In
Progress forever."
```

---

### Task 7: One-time repair patch for stuck amendments

**Files:**
- Create: `verenigingen/patches/v2_2/resync_stuck_mollie_amendment_syncs.py`
- Modify: `verenigingen/patches.txt` (append)
- Test: `verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py` (append)

- [ ] **Step 0: Write the failing test for the selection logic**

The latest-per-member partition is the logic that can silently corrupt amounts (an older amendment re-synced after a newer one). It lives in a pure function so it is testable without DB fixtures:

```python
class TestStuckAmendmentPartition(EnhancedTestCase):
    """Repair patch re-syncs only the latest stuck amendment per member."""

    def test_partition_keeps_latest_per_member(self):
        from verenigingen.patches.v2_2.resync_stuck_mollie_amendment_syncs import (
            partition_stuck_amendments,
        )

        rows = [  # already in ascending creation order, as execute() queries
            frappe._dict(name="AMEND-1", member="M-A"),
            frappe._dict(name="AMEND-2", member="M-B"),
            frappe._dict(name="AMEND-3", member="M-A"),
        ]

        resync, skip = partition_stuck_amendments(rows)

        self.assertEqual(sorted(resync), ["AMEND-2", "AMEND-3"])
        self.assertEqual(skip, ["AMEND-1"])

    def test_partition_empty(self):
        from verenigingen.patches.v2_2.resync_stuck_mollie_amendment_syncs import (
            partition_stuck_amendments,
        )

        self.assertEqual(partition_stuck_amendments([]), ([], []))
```

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.tests.payment.test_mollie_amendment_subscription_sync`
Expected: 2 errors — `ModuleNotFoundError` for the patch module. Everything else green.

- [ ] **Step 1: Write the patch**

```python
# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Re-sync Contribution Amendment Requests whose Mollie sync silently died.

The sync gated on Member.mollie_mandate_id (never populated), so applied
amendments stayed at mollie_sync_status="In Progress" forever. With the
gate fixed, re-enqueue the LATEST stuck amendment per member (so an older
amount cannot overwrite a newer one) and mark older stuck ones Skipped.
"""

import frappe


def partition_stuck_amendments(rows):
    """Split stuck amendments (ascending creation order) into
    (resync_names, skip_names): the latest per member is re-synced, older
    ones are skipped so a stale amount can never overwrite a newer one."""
    latest_per_member = {}
    for row in rows:  # ascending creation -> last write wins
        latest_per_member[row.member] = row.name
    resync = list(latest_per_member.values())
    skip = [row.name for row in rows if row.name not in set(resync)]
    return resync, skip


def execute():
    stuck = frappe.get_all(
        "Contribution Amendment Request",
        filters={
            "status": "Applied",
            "mollie_sync_completed": 0,
            "mollie_sync_status": ["in", ["Queued", "In Progress", "Failed"]],
        },
        fields=["name", "member"],
        order_by="creation asc",
    )
    if not stuck:
        return

    resync, skip = partition_stuck_amendments(stuck)

    for name in skip:
        frappe.db.set_value(
            "Contribution Amendment Request",
            name,
            "mollie_sync_status",
            "Skipped",
            update_modified=False,
        )

    for name in resync:
        frappe.db.set_value(
            "Contribution Amendment Request",
            name,
            "mollie_sync_status",
            "Not Started",
            update_modified=False,
        )
        frappe.enqueue(
            "verenigingen.verenigingen_payments.mollie.events.amendment_events.sync_mollie_subscription_on_amendment_applied",
            queue="default",
            timeout=60,
            doc={"doctype": "Contribution Amendment Request", "name": name},
            is_async=True,
            job_name=f"mollie_sync_{name}",
            job_id=f"mollie_sync_resync_{name}",
            deduplicate=True,
            enqueue_after_commit=True,
        )

    frappe.db.commit()
    print(f"Re-enqueued Mollie sync for {len(resync)} amendment(s), skipped {len(skip)} older one(s)")
```

- [ ] **Step 2: Register in patches.txt**

```bash
echo "verenigingen.patches.v2_2.resync_stuck_mollie_amendment_syncs" >> verenigingen/patches.txt
```

- [ ] **Step 3: Run tests to verify they pass**

Run the module. Expected: OK (16 tests).

- [ ] **Step 4: Dry-run on test_site_1**

```bash
cd ~/frappe-bench && bench --site test_site_1 execute verenigingen.patches.v2_2.resync_stuck_mollie_amendment_syncs.execute
```
Expected: no output (test_site_1 has no stuck amendments) and exit 0.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/patches/v2_2/resync_stuck_mollie_amendment_syncs.py verenigingen/patches.txt verenigingen/tests/payment/test_mollie_amendment_subscription_sync.py
git commit -m "fix(mollie): patch to re-sync amendments stuck by the mandate-id gate"
```

---

### Task 8: Full verification

**Files:** none modified.

- [ ] **Step 1: Run the three affected suites**

```bash
cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.tests.payment.test_mollie_amendment_subscription_sync
cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.tests.payment.test_mollie_subscription_consolidation
cd ~/frappe-bench && bench --site test_site_1 run-tests --module verenigingen.verenigingen_payments.mollie.tests.test_mollie_portal_endpoints_unit
```
Expected: all OK (16 + 50 + 9).

- [ ] **Step 2: Deployment notes (manual, after push)**

On veg11: `bench --site veg11.veganisme.org migrate` runs the reload + repair patch; workers then PATCH Foppe's subscription to €26.50 and repair its dead `dev.veganisme.net` webhook + stale description. Verify afterwards in the Mollie dashboard or:

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org mariadb -e "SELECT name, mollie_sync_status, mollie_sync_completed FROM \`tabContribution Amendment Request\` WHERE status='Applied' ORDER BY creation DESC LIMIT 5"
```
Expected: latest amendments Completed (or Skipped for superseded ones); none In Progress.
