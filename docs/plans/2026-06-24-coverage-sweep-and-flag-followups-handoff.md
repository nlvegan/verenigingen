# Handoff — 4-target coverage sweep + flag follow-ups (2026-06-24)

## TL;DR

Two pieces of work this session, both on `develop`:

1. **4-target parallel coverage sweep** (codecov "where next"): ~326 real-DB tests
   across `utils/migration`, `verenigingen_payments/mollie`, `services/member`,
   `templates/pages`, + **6 prod bugs fixed**. **Server Tests gate GREEN** after a
   3-round greening (env-gating fixes + 3 order-dependent stragglers baselined).
2. **Flag follow-ups** Foppe asked for ("1. give members that permission. 2. please
   add"): enabled **member self-service fee/type adjustment** (with a security guard
   that closed 2 CRITICAL review findings) and **added 2 Member consent fields**.

## Commit timeline (develop)

| Commit | What | Pushed? |
|---|---|---|
| `fc3ca520` | fix(eboekhouden): revive enhanced-migration framework + 102 tests (6 bugs) | yes |
| `1990a73a` | test: coverage sweep portal/mollie/member (~224 tests) | yes |
| `13541f53` | test(portal): force developer_mode in env-gated portal tests (gate fix) | yes |
| `261ac3bc` | test(ci): baseline 3 order-dependent stragglers | yes |
| `7eae3c88` | feat(member): add allow_directory_listing + allow_photo_usage | yes |
| `640bb8a1` | feat(membership): enable member self-service fee/type adjustment (guarded) | yes |
| `26a1a6c3` | docs(mollie): flag refund_handler Error Log pollution to fix before use | **LOCAL/UNPUSHED** |

## Gate status — ACTION FOR NEXT SESSION

- The coverage sweep is verified green: **run 28067696199 @ `261ac3bc` all 12 shards success.**
- The flag-follow-up features (`640bb8a1`) are verifying: **Server Tests run 28077941549
  IN PROGRESS** at handoff. **Check it first.** If red, the most likely causes are
  (a) a test that creates a Contribution Amendment Request as a non-Administrator and
  now hits the new self-service guard, or (b) rebucketing exposing another
  order-dependent straggler (see the greening playbook below). The CAR/approval suites
  (`test_contribution_amendment_request` 24, `..._conflicts` 6,
  `test_self_service_doc_method_regression` 6) + `test_page_membership_adjustment_coverage`
  19 all pass locally on veg11.
- **Then push the unpushed `26a1a6c3`** (docstring-only; held back so it wouldn't supersede
  the in-flight feature gate). It only touches a `.py` docstring so it will trigger its own
  Server Tests run; that should be a no-op pass.

## Detail: coverage sweep

4 parallel writer agents (own test sites), 3 skeptical reviews. Bugs fixed (all in
`utils/migration`, which was a largely-dead framework): dead validator framework
(`result=None`), `validate_posting_date` NameError, dry-run KeyError, a phantom column
that silently swallowed ALL error logging, a MemoryOptimizer AttributeError, ~60 broken
f-strings. The mollie/member/templates batches were already mature; added tests on genuine
gaps. Two test bugs the reviews caught and I fixed pre-commit: a **site-coupled** Mollie
payment-status test (passed on the writer's site, failed on veg11 where Mollie is
configured) and a wrong-target permission test.

### Gate greening playbook (used this session — reuse it)
- The 17 new test files reshuffled the 12-shard buckets. **Bucketing is by test-method
  count per file and is layout-coupled**; the baseline (`known_test_failures.txt`) is
  "coupled to bucket layout" (its own header says so).
- 6 failures were **mine**: portal `@self_service_api`/`@standard_api` (MEMBER_DATA→HIGH)
  endpoints are gated to the `development` environment via `frappe.conf.developer_mode`.
  veg11 is a dev bench (flag on) so they pass locally; in CI a sibling test leaves the
  shared flag off → "not available in production environment". **Fix = force
  `developer_mode=1` in setUp + restore in tearDown** (the `membership_adjustment` writer
  already did this; copied to `address_change`, `personal_details`, `simple_controllers`
  `TestWorkflowDemoPage`). One workflow test also caught a cross-test "Account Creation
  Request ... not found" async-after-rollback artifact → `assertNoErrorLog(ignore=[...])`.
- 3 were **pre-existing order-dependent stragglers** (rotated across runs, pass in
  isolation, green before the push): regression-due-date (party-account currency set by a
  sibling), volunteer_skills board lookup, chapter_permission read-access. **Baselined** in
  `verenigingen/tests/known_test_failures.txt` per Foppe's "fix clear, baseline elusive".
  FOLLOW-UP: isolation-harden these three so they can come off the baseline.
- GOTCHAS: `bench run-tests --module X --module Y` only runs the LAST module (can't
  reproduce cross-file order-dependence locally). Server Tests `paths:` filter is
  `verenigingen/**/*.py` — a `.txt`-only baseline commit does NOT auto-trigger; dispatch
  manually: `gh workflow run "Server Tests (GitHub Hosted)" --ref develop`. Read failures
  from the run-logs zip: `gh api repos/nlvegan/verenigingen/actions/runs/<id>/logs > z.zip`.

## Detail: flag follow-ups

### (2) Member consent fields — `7eae3c88`
`personal_details.update_personal_details` already tracked/wrote `allow_directory_listing`
and `allow_photo_usage`, but the Member doctype had no such fields → silently dropped.
Added both as Check fields (default 0, opt-in) after `pronouns` in `member.json`; the
personal_details coverage test now asserts they persist. Applied on deploy via `bench migrate`.

### (1) Member self-service fee/type adjustment — `640bb8a1`
Was completely broken: a "Verenigingen Member" had no create permission on Contribution
Amendment Request and couldn't escalate, so every portal request returned "Permission
denied". Granting the permission uncovered a chain (traced with an instrumented test):
CAR Fee Change `validate` does `frappe.get_doc("Membership Type", ...)` (member lacked
read) → then auto-approved CAR `after_insert` `save()` needs write (member lacked).

Permissions granted:
- CAR: Verenigingen Member **create + read (if_owner)**.
- Membership Type: Verenigingen Member **read** (catalog data, already shown in the portal
  type-change dropdown).

**SKEPTICAL REVIEW found 2 CRITICAL abuse paths** that the bare permission grant opened:
- **C1**: a member could auto-approve a self-serving fee DECREASE — `set_auto_approval_status`
  only checks the minimum floor and ignores `require_approval_for_decreases`.
- **C2**: the `create` grant is not owner-bound at the data layer (no `has_permission` hook;
  `if_owner` only scopes `owner`, not field values), so a raw `frappe.client.insert`/REST
  POST could set arbitrary `member`/`requested_amount`/`status` and skip the per-year
  frequency cap by omitting `requested_by_member`.

**GUARD added in `contribution_amendment_request.py` `before_insert`** (`_is_privileged_amendment_user`
+ `_enforce_member_self_service_guard`): a non-privileged (member) creator is bound to
**their own member** (throws on a mismatched member OR membership link), forced
`requested_by_member=1`, and the request is forced to **Pending Approval** AFTER the
auto-approval decision — members never auto-approve. Privileged staff/admin
(Administrator / `Roles.ADMIN_ROLES`) are unaffected and keep the auto-approval flow.
The 2 auto-approval system-bookkeeping saves (`after_insert`; approval-service
`cancel_conflicting_amendments`) use `ignore_permissions=True` (no-op for staff who have
write; unreachable for members now). **A 2nd review confirmed C1 + C2 are CLOSED.**

Tests: the 2 "member lacks permission" characterizations became happy-path success tests
(run as the member, assert created + owned-by-them + Pending Approval), plus a new
`test_submit_fee_adjustment_member_decrease_requires_approval` regression guard. The
existing Administrator-context auto-approval tests (24+6+6) still pass.

GOTCHA: `permission-bypass-validator` (`scripts/validation/security/`) requires a
`# Security:` comment within **5 lines** of every `ignore_permissions=True`.

## Open items / suggested next steps

- **(3) Mollie refund_handler Error Log pollution** — flagged in code (`26a1a6c3`, unpushed)
  with the concrete fix. It is **dormant** (no live caller; live path is
  `webhook_wrapper_service_unified._process_pending_refunds`). Fix the "Refund Debug" rows
  (downgrade to `frappe.logger().debug`) **before** wiring the handler in.
- **Isolation-harden the 3 baselined stragglers** (pin currency / dedicated FY+company /
  establish own board + permission state) so they can leave `known_test_failures.txt`.
- **Next codecov target**: after `utils/migration`, the remaining biggest live prod gaps
  are `services/member` (still ~76%), `templates/pages`, and the larger
  `verenigingen_payments/mollie` external-API surfaces (enforcer-constrained).
- Overall develop coverage was **81.29%** at the start of this session.
