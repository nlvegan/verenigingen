# Consolidate Mollie subscription create/cancel logic

**Date:** 2026-05-18
**Status:** Phases 1 & 2 complete and merged; Phase 3 in progress.
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

### Phase 1 — collapse the two bottom-level implementations ✅ DONE

**Merged:** PR #45. A follow-up bug-fix (the amendment-sync `create_subscription`
call, found while planning Phase 2) shipped separately as PR #46.

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

### Phase 2 — standardise the mid-level contract ✅ DONE

**Merged:** PR #47 (all 7 tasks, two double-review rounds).

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

### Phase 3 — fold in the debug-service paths ⏳ IN PROGRESS

Branch: `refactor/mollie-subscription-consolidation-phase3`. TDD each step —
payment code.

#### 3.0 Findings from the Phase 3 investigation

- **`MollieDebugService` works at a different abstraction level.** Its
  `create_subscription`, `create_scheduled_subscription` and
  `admin_cancel_subscription` are admin debug tooling: every caller (the
  `mollie_payments_debug`, `mollie_bulk_payment_creation` and
  `mollie_subscription_recreation` template pages, plus `mollie_payment.py`)
  passes a **raw Mollie `customer_id`** — often with an explicit `mandate_id` —
  and consumes the debug-flavoured result dict (`create_success_response` /
  `create_error_response`). That does **not** fit
  `CompletePaymentService.create_customer_subscription`, whose contract
  resolves or creates the Mollie customer from `customer_data["email"]` and
  has no path for "use this exact existing customer id". `admin_cancel_subscription`
  also deliberately tolerates an already-cancelled subscription
  (`status: "warning"`), whereas `CompletePaymentService.cancel_subscription`
  raises on any failure.
- **Decision (confirmed with the maintainer):** the debug service routes
  through **`MollieClient`** — the single standardised bottom-level SDK
  wrapper — not through `CompletePaymentService`. This removes the real drift
  (the debug methods currently reach past even `MollieClient` to
  `self.mollie_client.sdk_client`) without forcing an ill-fitting owner/email
  create contract onto raw-customer-id admin tooling. The debug result shape
  and the "already cancelled" tolerance are preserved. `MollieClient`'s
  subscription methods carry no retry/circuit-breaker decorators, so this
  changes no runtime behaviour beyond the call path.
- **`create_member_subscription`** (the whitelisted endpoint in
  `payment_gateways.py`) has **no JS/HTML caller** — only a
  `critical_operation_rule.json` fixture entry references it — so its return
  shape is not consumed by the frontend. It routes through
  `MollieGateway.create_subscription`, which already goes through
  `CompletePaymentService` with `owner_doctype`/`owner_name`.

#### 3.1 Task list

1. **`MollieDebugService.create_subscription`** — replace the raw-SDK create
   (`self.mollie_client.sdk_client` → `customers.get` → `subscriptions.create`)
   with `self.mollie_client.create_subscription(customer_id, subscription_data)`.
   `MollieClient.create_subscription` raises `MolliePaymentError` on failure;
   the method's existing `except Exception` block already sanitises and returns
   an error response. Result shape unchanged. TDD: the create delegates to
   `MollieClient` and returns the success shape; a failure returns the
   sanitised error shape.
2. **`MollieDebugService.create_scheduled_subscription`** — same replacement.
   Not named in the original Phase 3 bullet, but it carries the identical
   raw-SDK create drift; consolidating its sibling while leaving it raw would
   re-introduce exactly the drift this phase removes.
3. **`MollieDebugService.admin_cancel_subscription`** — replace the raw-SDK
   `customers.get(...).subscriptions.delete(...)` with
   `self.mollie_client.cancel_subscription(customer_id, subscription_id)`.
   Preserve the "already cancelled → `status: "warning"`" branch:
   `MollieClient.cancel_subscription` wraps the SDK error as
   `MolliePaymentError("Failed to cancel subscription <id>: <e>")`, so the
   original phrases ("not found", "already cancelled", …) remain in the
   message and the existing `phrase in error_message.lower()` check still
   matches. TDD: the success path, and an "already cancelled" path that still
   returns `warning`.
4. **`payment_gateways.py` `create_member_subscription`** — route through
   `MollieGateway.create_subscription(member, subscription_data)` instead of
   `MollieDebugService.create_subscription`. The gateway already routes through
   `CompletePaymentService` with `owner_doctype`/`owner_name`, so the service
   owns the Member update.
   - **Remove** the redundant `member.db_set("mollie_subscription_id", …)` —
     `CompletePaymentService._update_owner_record` writes it.
   - **Keep** `member.db_set("payment_method", "Mollie")` — it is *not*
     redundant: the contract writes `mollie_customer_id`,
     `mollie_subscription_id`, `subscription_status` and `next_payment_date`,
     but not `payment_method`. (The original handoff said "remove them";
     investigation shows only one of the two is redundant.) The `member`
     object is stale after the service's `frappe.db.set_value` writes, but
     `db_set` writes straight to the DB so the `payment_method` write is
     still correct.
   - Keep the existing early-return guards (already-active subscription,
     missing `mollie_customer_id`).
   - **Known behaviour change:** the gateway path passes
     `consumerAccount = member.iban`, so `CompletePaymentService` *provisions
     a fresh SEPA mandate from the IBAN* before creating the subscription,
     whereas the old debug path passed `mandate_id=None` and let Mollie
     auto-select an existing mandate. This aligns `create_member_subscription`
     with the Phase-1-blessed `MollieGateway.create_subscription` contract
     used by the rest of the app. Flagged for review.

#### 3.2 Out of scope

- `MollieDebugService`'s other raw-SDK uses — `update_subscription_webhook`,
  the bulk "cancel all subscriptions + revoke mandate" helper, and the
  payment / mandate / customer debug methods. Phase 3 touches only the
  subscription create/cancel paths named in §4.
- **Tests:** extend `tests/payment/test_mollie_subscription_consolidation.py`
  with a `MollieDebugService` test class reusing `FakeSDKClient` / `_patch_sdk`,
  and a `create_member_subscription` test. TDD each task.

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
