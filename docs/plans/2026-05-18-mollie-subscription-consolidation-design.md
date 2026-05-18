# Consolidate Mollie subscription create/cancel logic

**Date:** 2026-05-18
**Status:** Design — phased implementation
**Context:** Audit T4.4 follow-up. Retiring `MollieConnector` (PR #44) unblocked this.

## 1. Problem

Mollie subscription create/cancel is fragmented. A full call-graph trace found
**two genuinely-independent bottom-level SDK implementations** and **six
mid-level wrappers** that delegate to them inconsistently.

### Bottom-level (real SDK calls)

| Impl | Location | Behaviour |
|------|----------|-----------|
| **Modern** | `mollie/core/client.py` `MollieClient.create_subscription` / `cancel_subscription` | thin SDK wrapper; customer must pre-exist; returns the SDK object; raises `MolliePaymentError` |
| **Legacy** | `doctype/mollie_settings/mollie_settings.py` `create_subscription` / `cancel_subscription` | creates customer + (optionally) a SEPA **mandate from an IBAN** + subscription in one call; returns a dict / a bool; raises `frappe.ValidationError` |

The legacy `MollieSettings` pair is called by **exactly one** consumer:
`MollieGateway` in `verenigingen_payments/utils/payment_gateways.py`
(lines ~574, ~653). Everything else is on the modern path.

### Correction (found during Phase 1 investigation)

`SubscriptionService.create_membership_subscription` /
`create_donation_subscription` are **dead and broken**: they have zero
callers and they call `MollieClient.create_subscription` with keyword
args (`amount=`, `interval=`, …) while that method's signature is
`(customer_id, subscription_data: dict)` — any call would `TypeError`.
They are NOT a usable "modern path". `SubscriptionService` is only
reached for `cancel_subscription` / status / payment-processing.

The genuinely-working modern create service is
**`CompletePaymentService.create_customer_subscription(customer_data,
subscription_data)`** — same call shape as the legacy `MollieSettings`
path, and it calls `MollieClient.create_subscription` correctly. The
consolidation target is therefore `CompletePaymentService`, not
`SubscriptionService`; and the dead `SubscriptionService.create_*`
methods are deleted as part of this work.

### Mid-level wrappers and their divergences

`SubscriptionService`, `CompletePaymentService`, `MollieGateway`,
`MollieSubscriptionSyncService`, `MollieDebugService`. They differ on:

- **Row locking** — `SubscriptionService` and `CompletePaymentService` take
  `SELECT … FOR UPDATE` on Member/Donor; `MollieGateway` and the sync service
  do not (duplicate-subscription race risk).
- **Mandate validation** — `SubscriptionService` requires a valid SEPA mandate;
  `MollieGateway` creates one from IBAN; `CompletePaymentService` requires one
  to pre-exist; others do nothing.
- **DocType updates** — some update Member/Donor on create *and* cancel; some
  update nothing and rely on the caller.
- **Return shape** — subscription object vs `dict` vs `bool`.

## 2. Target architecture

```
leaf callers (whitelisted endpoints, templates, Member controller)
        │
        ▼
mid-level services  ──  one standard contract:
  SubscriptionService           - takes row lock
  CompletePaymentService        - validates / provisions mandate
  MollieSubscriptionSyncService - owns the DocType updates
  MollieDebugService            - returns a uniform result shape
        │
        ▼
one bottom-level: MollieClient.create_subscription / cancel_subscription
        │
        ▼
mollie SDK
```

**One bottom-level implementation** (`MollieClient`). **One mid-level contract:**
every create/cancel path locks the row, reconciles the mandate, updates the
owning DocType, and returns the same result shape.

## 3. Key design decision — mandate reconciliation

The legacy path's one capability the modern path lacks: **creating a SEPA
mandate from an IBAN** when none exists. To delete the legacy path without
regressing `MollieGateway`, that capability must live on the modern path.

**Decision:** add an explicit, opt-in mandate-provisioning step to the modern
create flow — `CompletePaymentService.create_customer_subscription` gains an
optional IBAN/`consumerAccount` input; when supplied and no usable mandate
exists, it provisions one via the SDK before creating the subscription. This
keeps mandate provisioning explicit (not a hidden side effect of "create
subscription") and removes the only behavioural reason the legacy path exists.

## 4. Phased plan

Each phase is its own double-reviewed PR.

### Phase 1 — collapse the two bottom-level implementations

Branch: `refactor/mollie-subscription-consolidation-phase1` (this doc lives
there). TDD each step — payment code.

Precise task list:

1. **`mollie/core/client.py` `MollieClient`** — add
   `create_mandate(customer_id, mandate_data)` wrapping
   `customer.mandates.create(data=mandate_data)` (same error-handling shape
   as the existing `create_subscription`).
2. **`mollie/services/complete_payment_service.py`
   `create_customer_subscription`** — opt-in mandate provisioning: when
   `subscription_data` carries a truthy `consumerAccount`, build the legacy
   mandate payload and provision a mandate before creating the subscription,
   then strip `consumerAccount` from `subscription_data`. Legacy payload
   shape (from the soon-deleted `MollieSettings.create_subscription`):
   ```python
   mandate_data = {
       "method": "directdebit",
       "consumerName": customer_data.get("name", ""),
       "consumerAccount": subscription_data["consumerAccount"],
       "signatureDate": frappe.utils.today(),
       "mandateReference": f"MANDATE-{frappe.utils.random_string(8)}",
   }
   ```
3. **`verenigingen_payments/utils/payment_gateways.py`
   `MollieGateway.create_subscription`** — replace
   `self.settings.create_subscription(customer_data, mollie_subscription_data)`
   with `CompletePaymentService().create_customer_subscription(...)`. NOTE the
   return-shape difference: `CompletePaymentService` returns
   `subscription_status` (not `status` — its `status` key is the literal
   `"success"`). Map `result["subscription_status"]` onto the member's
   `subscription_status` field.
4. **`MollieGateway.cancel_subscription`** — replace
   `self.settings.cancel_subscription(...)` (returns `bool`) with
   `MollieClient().cancel_subscription(customer_id, subscription_id)` (returns
   the cancelled object, *raises* on failure). Adapt: success path on no
   exception; the `except` already handles failure.
5. **Delete** `MollieSettings.create_subscription` and `cancel_subscription`
   (keep `get_subscription`, `create_customer`, etc.).
6. **Delete** `SubscriptionService.create_membership_subscription`,
   `create_donation_subscription`, and their now-orphaned private helpers —
   all used only by those two: `_ensure_customer_exists`,
   `_ensure_donor_customer_exists`, `_has_valid_mandate`, `_get_webhook_url`,
   `_update_member_subscription_info`, `_update_donor_subscription_info`.
   KEEP `cancel_subscription` and `_update_*_subscription_canceled` (live).
7. **Tests** — `MollieGateway` create/cancel currently has zero coverage; add
   TDD tests: create-with-IBAN provisions a mandate, create-without does not,
   cancel.
- Net: one SDK path (`MollieClient`).

### Phase 2 — standardise the mid-level contract
- Make row locking mandatory on every create path (port the
  `SELECT … FOR UPDATE` pattern into `CompletePaymentService` and the sync
  service create path).
- Single mandate-validation helper used by all create paths.
- Service layer always updates the owning Member/Donor record on create and
  cancel (eliminate the "caller is responsible" gaps).
- One result dataclass / shape for create and for cancel.
- **`enable_subscriptions` gate lives only at the caller.** After Phase 1
  the gate survives because `MollieGateway.create_subscription` checks
  `settings.enable_subscriptions` itself, but `CompletePaymentService.`
  `create_customer_subscription` — the consolidation target — has no such
  check. Any caller wired straight to the service (e.g. the Phase 3 debug
  service) would bypass the gate. Phase 2 should move the check into the
  standardised create contract. (Found during Phase 1 review.)
- **Customer resolution is Donor-only today.** `CompletePaymentService.`
  `_create_or_get_customer` resolves the Mollie customer by looking up a
  `Donor` on `donor_email`. After Phase 1, `MollieGateway` (membership dues)
  routes through this method, so a member whose email matches a `Donor` row
  binds the membership subscription to that Donor's Mollie customer and
  writes `mollie_customer_id` back onto the Donor. The legacy path always
  created a fresh Mollie customer. Phase 2 must make customer resolution
  owner-aware (Member vs Donor) so each owning DocType resolves against its
  own record. (Found during Phase 1 review; deferred here by decision.)

### Phase 3 — fold in the debug-service paths
- Route `MollieDebugService.create_subscription` / `admin_cancel_subscription`
  through the standardised services so the admin tooling cannot drift.

## 5. Risks & test strategy

- **Payment code** — behaviour regressions here are high-impact. Every phase is
  TDD: a failing test for the behaviour first, then the change.
- **Mandate semantics** — Phase 1's reconciliation is the riskiest step; it gets
  explicit tests for "mandate exists" and "mandate provisioned from IBAN".
- **Test gap** — there are currently no tests for `MollieGateway`,
  `MollieSettings.create/cancel_subscription`, or the public API endpoints.
  Phase 1 adds coverage for the `MollieGateway` path as part of the change.
- Each phase keeps the public whitelisted endpoints' signatures stable.

## 6. Out of scope

- `payment_gateways.py` is also audit item T4.7 (god-module split); this
  consolidation touches only its subscription methods, not the split.
- A separate "payments v2" migration effort is in progress; subscriptions are
  not part of payments v2 today, so this consolidation is orthogonal to it.
