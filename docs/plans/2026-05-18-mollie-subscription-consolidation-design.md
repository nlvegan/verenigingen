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

Branch: `refactor/mollie-subscription-consolidation-phase2`. TDD each step —
payment code.

#### 2.0 Findings from the Phase 2 investigation

- **The sync-service create path is broken.**
  `MollieSubscriptionSyncService.sync_subscription_for_amendment` calls
  `self.client.create_subscription(customer_id=…, amount=Money(…),
  interval=…, description=…, webhook_url=…, start_date=…, metadata=…)` —
  keyword arguments that do not match `MollieClient.create_subscription(
  customer_id, subscription_data: dict)`. Every call raises `TypeError`.
  This is the same bug class as the dead `SubscriptionService.create_*`
  methods retired in Phase 1 — but this one is **live**: applying a
  `Contribution Amendment Request` enqueues
  `sync_mollie_subscription_on_amendment_applied`, which calls it. So a
  member changing their contribution amount currently fails the Mollie
  sync. Phase 2 must fix this as part of standardising the create path.
- **Divergences across the create/cancel paths (post-Phase-1):**
  - *Row locking* — `CompletePaymentService._create_or_get_customer` locks
    the `Donor` row for *customer* creation, but no path locks the
    Member/Donor for *subscription* creation (duplicate-subscription race).
    The sync service takes no lock at all.
  - *Mandate handling* — `CompletePaymentService` provisions a mandate from
    an IBAN; the sync service validates an *existing* mandate via the SDK;
    no shared helper.
  - *DocType updates* — `CompletePaymentService.create_customer_subscription`
    does NOT update Member/Donor (its caller `MollieGateway` does the
    `db_set`s); `cancel_subscription` calls `_update_subscription_status`,
    which is a TODO no-op; the sync service updates `mollie_subscription_id`
    itself.
  - *Return shapes* — `CompletePaymentService` returns dicts;
    `SubscriptionService.cancel_subscription` returns a `Subscription` SDK
    object; the sync service returns ad-hoc dicts with bespoke keys
    (`reason`, `requires_admin_review`, `rollback_successful`, …).
  - *`enable_subscriptions` gate* — enforced only in `MollieGateway`.

#### 2.1 Task list

1. **Fix the sync-service create call.** Rebuild
   `sync_subscription_for_amendment` to call
   `MollieClient.create_subscription(customer_id, subscription_data)` with a
   correctly-shaped dict (`amount` as `{"value","currency"}`, `interval`,
   `description`, `webhookUrl`, `startDate`, `metadata`). TDD: a test that
   currently `TypeError`s, then green.
2. **Standard result shape.** One documented dict shape for create and one
   for cancel — a plain `dict` (not a dataclass) so existing
   `result["status"]` caller access keeps working:
   - create: `{status, customer_id, subscription_id, subscription_status,
     next_payment_date, message}` (`status` ∈ `success`/`error`).
   - cancel: `{status, subscription_id, message}`.
   Every create/cancel path returns this; `SubscriptionService.`
   `cancel_subscription` stops returning a raw `Subscription` object.
3. **`enable_subscriptions` gate in the contract.** Move the check into
   `CompletePaymentService.create_customer_subscription` (and the sync
   path) so it cannot be bypassed; keep `MollieGateway`'s early check or
   let it delegate — no double error.
4. **Single mandate helper.** One helper used by every create path: provision
   from IBAN when given, otherwise validate an existing mandate.
5. **Mandatory row locking on subscription create.** Port the
   `SELECT … FOR UPDATE` pattern onto the owning Member/Donor row for the
   subscription-create paths, not just customer creation.
   - **Idempotency (intentional contract decision).** While the owner row is
     locked, if the owner already has a *live* (`active`/`pending`) Mollie
     subscription, the create returns that subscription instead of
     provisioning a second one — mirroring how customer resolution returns an
     existing customer. The `active`/`pending` gate means a re-subscribe after
     a cancellation still creates a fresh subscription. A caller that
     deliberately wants a *second concurrent* live subscription for one owner
     (e.g. a future amendment "create new before cancelling old" flow) must
     not route through this path. Confirmed during the Phase 2 review.
6. **Service owns the DocType update.** `CompletePaymentService` updates the
   owning Member/Donor on create and cancel; remove the duplicated `db_set`s
   from `MollieGateway`. Implement the `_update_subscription_status` no-op.
7. **Owner-aware customer resolution.** `_create_or_get_customer` must
   resolve against the owning DocType (Member vs Donor), not always `Donor`,
   so a member's subscription never binds to a Donor's Mollie customer.

#### 2.2 Open design decisions (confirm before implementing)

- **Result shape** — plain dict (above) vs a dataclass. Dict chosen here to
  avoid breaking `result["…"]` access in `unified_payment_api`,
  `MollieGateway` callers, and `amendment_events`. Confirm.
- **Sync-service return** — `sync_subscription_for_amendment` carries
  operational keys (`requires_admin_review`, `critical_failure`,
  `duplicate_subscriptions`) its caller `amendment_events` relies on. These
  are kept *in addition to* the standard keys, not replaced.

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
