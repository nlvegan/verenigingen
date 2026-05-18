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
- Add IBAN-based mandate provisioning to `CompletePaymentService`'s create
  flow (§3).
- Re-point `MollieGateway.create_subscription` / `cancel_subscription` to
  `CompletePaymentService` / `MollieClient`, preserving `MollieGateway`'s
  current dict return shape and Member updates at the gateway boundary.
- Delete `MollieSettings.create_subscription` / `cancel_subscription`.
- Delete the dead+broken `SubscriptionService.create_membership_subscription`
  / `create_donation_subscription`.
- Net: one SDK path.

### Phase 2 — standardise the mid-level contract
- Make row locking mandatory on every create path (port the
  `SELECT … FOR UPDATE` pattern into `CompletePaymentService` and the sync
  service create path).
- Single mandate-validation helper used by all create paths.
- Service layer always updates the owning Member/Donor record on create and
  cancel (eliminate the "caller is responsible" gaps).
- One result dataclass / shape for create and for cancel.

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
