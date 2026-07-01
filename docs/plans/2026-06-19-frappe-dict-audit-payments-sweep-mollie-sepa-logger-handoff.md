# Handoff — 2026-06-19 — frappe._dict audit · payments/utils sweep · Mollie donation fix · SEPA mandate fix · PaymentLogger adoption

## TL;DR
Five workstreams, **all pushed to `origin/develop` (HEAD `7c657a28`)**. Working tree
clean except a pre-existing, unrelated `verenigingen/public/css/email_brand.css`
change (not ours). Commits `9ff0c4f5..7c657a28`:

1. **`@standard_api`/`frappe._dict` audit** — hardened the API response wrapper
   against a latent `TypeError` class (the whole-class fix). **CI-green.**
2. **`verenigingen_payments/utils` coverage sweep** — 313 tests / 12 files,
   1 prod bug fixed + 3 characterized. **CI-green** (after a rebucketing round).
3. **Mollie recurring-donation subscription** — was completely dead; rewrote it
   to source from the Donation + fixed the Yearly→monthly interval bug. **CI-green.**
4. **SEPA `validate_mandate_status_batch`** — phantom-column 1054 → fixed to real
   columns. **CI-green.**
5. **PaymentLogger adoption** — wired the unused structured-logging util into 5
   money-path events via brainstorm→spec→plan→subagent-driven execution + a
   sink-hardening pass. **CI run `27850044906` IN FLIGHT at handoff time** (watch
   for shard rebucketing from +~13 tests).

## Commit ledger (oldest→newest, all on `origin/develop`)
| Commit | What | CI |
|---|---|---|
| `9ff0c4f5` | fix(security): harden API wrapper vs `frappe._dict` `to_dict` TypeError | ✅ green (27833253853) |
| `56829401` | docs(security): note the `scrub_sensitive` to_dict contract | (docs) |
| `6e5be186` | test(payments): coverage sweep of `verenigingen_payments/utils` (+313) | superseded |
| `9c711d4c` | fix(donations): create Mollie subscription for recurring donations | failed→rebucket |
| `a5d50f65` | test(ci): green the 12-shard gate after the sweep rebucketed shards | ✅ green (27842344005) |
| `1c541d6f` | fix(sepa): correct `validate_mandate_status_batch` columns (1054) | ✅ green (27845262927) |
| `77168705`,`498a9915` | docs(spec): PaymentLogger adoption design | (docs) |
| `0b5bda06` | docs(plan): PaymentLogger adoption implementation plan | (docs) |
| `bffc0890` | feat(payments): log refund_initiated + concurrent_refund_detected | part of 27850044906 |
| `dcdad4ad` | feat(payments): log signature_validation_failed | " |
| `d9f2bc61` | feat(payments): log webhook_received (Mollie/ING) | " |
| `2a65b4d9` | feat(payments): log payment_initiated (gateway-agnostic) | " |
| `7c657a28` | fix(payments): PaymentLogger sinks exception-safe | " |

---

## 1. `@standard_api` / `frappe._dict` audit (`9ff0c4f5`, `56829401`)

**The class bug:** `frappe._dict` sets `__getattr__ = dict.get`
(`apps/frappe/frappe/types/frappedict.py:22`), so `result.to_dict` returns `None`
(not absent) and `hasattr(result, "to_dict")` is `True`. The API response wrapper
did `if hasattr(result, "to_dict"): result.to_dict(scrub_sensitive=True)` → called
`None(...)` → **`TypeError` on every `@*_api` endpoint returning a `frappe._dict`**
(e.g. `frappe.db.get_value(as_dict=True)`).

**Fix:** in `verenigingen/utils/security/api_security_framework.py` (~L992), guard on
`callable(getattr(result, "to_dict", None))`. This is the single chokepoint for all
8 decorators (`critical_api`, `high_security_api`, `standard_api`, `self_service_api`,
`utility_api`, `public_api`, `development_only_api`, `webhook_api`). Also hardened the
same pattern in `member.py:961`; `volunteer_application.py:299` was already safe
(`not isinstance(result, dict)` short-circuits). 3 regression tests in
`tests/security/test_api_security_framework.py`, fail-before verified.

`56829401` (local-then-pushed) adds a one-line comment documenting the `scrub_sensitive`
to_dict contract.

---

## 2. `verenigingen_payments/utils` coverage sweep (`6e5be186`)

Codecov "where next" sweep (Foppe picked the target). Probe + 4 parallel agents +
skeptical review + serial verify. **313 tests across 12 new files in `tests/payment/`.**

**Prod bug FIXED:** `bank_integration.py:381` — PSU-IP header dereferenced
`frappe.local.request` unconditionally → AttributeError off-request (scheduler/console).
Guarded + extracted a pure `_handle_statement_response` helper for testability.

**3 money-flow bugs CHARACTERIZED** (the Mollie + SEPA ones were then fixed later this
session, see §3/§4): the third remains flagged →
`sepa_race_condition_manager.py:488` `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`
before `begin()` → MariaDB 1568 if a txn is already open. Works in prod today only
because `acquire_lock()` commits first; fragile. **Foppe said "leave it flagged"** —
do NOT reorder isolation SQL in locking code without care.

**Dead-code decision:** the "SEPA week4 monitoring" cluster (zabbix/alerting/dashboard/
perf-monitor/memory-optimizer) is internally-unreferenced, BUT **Foppe correctly KEPT it** —
internal-reference counting is the wrong test for externally-polled monitoring endpoints
(a Zabbix integration is hit by an external ops server, invisible to repo grep). Only
`payment_services/logging_utils.py` was confirmed truly dead (pure internal helper, zero
callers) — and it was then **adopted** instead of deleted (see §5).

---

## 3. Mollie recurring-donation subscription (`9c711d4c`)

`_activate_donation_subscription_after_first_payment` (payment_gateways.py) was built
against a `Donation Agreement` doctype/field that **never existed** — `donation.donation_agreement`
(real: `periodic_donation_agreement`), `"Donation Agreement"` doctype (real:
`Periodic Donation Agreement`), and `agreement.amount`/`recurring_frequency`/`next_due_date`/
`mollie_subscription_id` (none exist on the agreement). It threw `AttributeError` every call
→ swallowed → **recurring donations were charged once and never again.**

**Fix:** the Donation itself owns all needed fields (`amount`, `recurring_frequency`,
`mollie_subscription_id`, `mollie_customer_id`). Rewrote to source the subscription from the
Donation + payment metadata and persist on `donation.mollie_subscription_id`. The
`Periodic Donation Agreement` is an ANBI tax construct, not the Mollie sub store.

**Also fixed a bug this exposed:** `convert_frequency_to_mollie_interval` (mollie/utils/
common_helpers.py) didn't map Donation's `Yearly`/`Weekly`/`Bi-weekly`/`Daily` → silently
defaulted to "1 month" → **a Yearly donor billed MONTHLY.** Added the mappings (verified all
six via `bench execute`). Skeptical-reviewed Ready:Yes; 2 gateway tests + 1 converter test.

---

## 4. SEPA `validate_mandate_status_batch` (`1c541d6f`)

SELECTed `valid_from`/`valid_until`/`date_signed` from `tabSEPA Mandate` — none exist
(real: `sign_date`/`expiry_date`) → **guaranteed 1054 on any non-empty call.** No prod
callers today, so it was a latent landmine. Mapped to the real columns, mirroring the
validity rules already used by `sepa_mandate_lifecycle_service`/`_validation_service`
(future `sign_date`→not-yet-valid, past `expiry_date`→expired); dropped the unused
`date_signed`. 3 real tests replaced the @expectedFailure + crash-pin.

---

## 5. PaymentLogger adoption (`77168705`..`7c657a28`)

Foppe chose to **adopt** (not delete) the dead `PaymentLogger` structured-logging util at
**key money-path events** (not a full migration). Full superpowers flow: brainstorming →
spec (`docs/superpowers/specs/2026-06-19-payment-logger-adoption-design.md`) → writing-plans
(`docs/superpowers/plans/2026-06-19-payment-logger-adoption.md`) → subagent-driven-development
(fresh implementer + skeptical reviewer per task, fail-before verified each).

5 events wired (logging-only; tests patch the convenience fn at the call site and assert it fires):
- `log_refund_initiated` — `refund_utility.initiate_refund` success (donation refund delegates here → not double-wired).
- `log_concurrent_refund_detected` — both INSUFFICIENT_REFUNDABLE blocks.
- `log_signature_validation_failed` — `mollie/utils/webhook_security` (REPLACE) + `ing_checkout/utils/webhook_security` (ADD).
- `log_webhook_received` — Mollie LIVE chokepoint `mollie/api/unified_payment_api.handle_payment_webhook`
  (the plan-named `mollie/api/payment_webhook.py` has NO whitelisted handler — all `webhooks.py` entries
  delegate to unified) + ING `handle_payment` (REPLACE receipt log).
- `log_payment_initiated` — `hooks/payment_hook.PaymentHook.initiate_payment` (gateway-agnostic chokepoint,
  success+payment_id only; Foppe chose this over per-gateway).

**Hardening:** two reviewers flagged that the events now fire inside money-path `try/except`, so a logging
failure could mask the real outcome. Made all 4 `PaymentLogger` base sinks swallow exceptions + truncate
`frappe.log_error` title to `[:140]` (the known `CharacterLengthExceededError` crash class). 6 fail-before tests
in `test_payment_logger_exception_safety.py`. 51 feature tests green serially.

---

## Open / flagged (next-session candidates)
- **`sepa_race_condition_manager.py:488`** SERIALIZABLE-before-begin fragility — Foppe said leave flagged.
- **PaymentLogger CI gate `27850044906`** — was IN FLIGHT at handoff. If it reports NEW failures, it's almost
  certainly **shard rebucketing** from the +~13 new tests (same trap as `a5d50f65`): triage → fix ours,
  baseline pre-existing elusive order-dependence in `verenigingen/tests/known_test_failures.txt`. The
  new-failure list is between "introduces test failures not in the baseline" and the `##[error]` line.
- **`pages/membership_applications/__init__.py:16`** — `frappe.user.has_role(...)` pattern (frappe.user is a
  str, not a User object) flagged in a prior handoff; not addressed.
- **Next coverage targets** (by miss count): `e_boekhouden/utils` (dead-code triage first), `services/member`,
  `templates/pages`.

## Key gotchas (reusable)
- **`frappe._dict` + `@*_api`** → `hasattr(r,"to_dict")` True but `r.to_dict` is None → guard on `callable(...)`.
- **Rebucketing is behavioral** — a coverage sweep that changes total test count re-LPT-balances the 12 shards
  and surfaces latent order-dependence. Budget a follow-up greening round; keep fixes test-count-neutral so the
  same failures recur and your fixes land.
- **test-quality-enforcer (BLOCKING)** forbids `patch("frappe.db.*")`, `frappe.get_roles`, `frappe.session`,
  business-logic mocks — even annotated. For DB-coupled logic, extract a pure helper and test it directly.
  In `tests/security/*` it also bans auth-boundary mocks → run as default Administrator instead.
- **`frappe.log_error` raises on >140-char titles** (`CharacterLengthExceededError`) — truncate.
- **Two `log_webhook_received`** exist (canonical `payment_services` vs Mollie-internal `mollie/utils/logging.py`).
- **`bench execute <dotted.fn> --args '["x"]'`** verifies a pure helper without the local `DuplicateEntryError:
  Price List 'Standard Buying'` that kills ERPNext-bootstrap test modules locally (CI uses a fresh site).
- **Frappe worktree caveat:** tests run against the INSTALLED app at `apps/verenigingen`, so a separate git
  worktree isn't picked up by `bench run-tests` → work in-place.
- **Subagent-driven worked well** — implementers caught 2 plan inaccuracies (a docstring mistaken for code; a
  dead handler the plan named) and wired the real sites. Reviewers reproduced fail-before by deleting call sites.
- CI: `gh api repos/nlvegan/verenigingen/actions/jobs/<JOBID>/logs`; watch via `gh run watch <id> --exit-status`.
