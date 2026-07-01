# Handoff: coverage-driven bug fixes (permissions + Mollie/SEPA + MT940)

**Date:** 2026-06-14
**Branch:** develop — **ALL PUSHED** to origin (`2d41629a..ed5b134a`, 8 commits)
**Trigger:** "Does Codecov have anything to tell us about coverage gaps?"

## TL;DR

Started as a coverage-gap question, became a coverage + bug-fix sweep on the
modules Codecov flagged. **10 production bugs fixed, ~340 real-integration tests
added, full skeptical review of both test batches, everything green and pushed.**

## Codecov access (for next time)

- Live numbers need a **Codecov API read token** (personal, not the CI upload
  `CODECOV_TOKEN`). Generate at `app.codecov.io` → avatar → Settings → Access
  (`https://app.codecov.io/account/gh/<username>/access`). GitHub login here is
  `0spinboson`.
- Query: `curl -s -H "Authorization: Bearer <TOKEN>" https://codecov.io/api/v2/github/nlvegan/repos/verenigingen/...`
  Useful endpoints: `/` (totals), `/flags/`, `/report/?branch=develop` (per-file).
  The `/file_report/<path>/` endpoint kept appending a trailing slash → 404; get
  line-level by running `bench ... run-tests --module X --coverage` and parsing
  `sites/coverage.xml` instead.
- Foppe pasted a read token this session (`989a4400-…`, in the transcript) — he
  may want to rotate it.
- Baseline at session start: overall **40.4%** (python flag 40.2%, jest 96.5%).
  The flagged low-coverage product areas were `e_boekhouden/` (25%), the
  Mollie/SEPA payment internals, `permissions.py` (48%), the two Mollie debug
  pages (0%), and the MT940 import path.

## Commits (all pushed to develop)

```
3b79f7b5 fix: repair payment/permission bugs surfaced by coverage work   (7 prod files)
b5a7fa53 test: coverage for permissions, Mollie/SEPA payments, MT940 import (16 files)
0384f849 fix(permissions): correct team-leader volunteer access query
cf6cb280 test: close coverage-review gaps in permissions and payments tests (5 files)
ef008a7e fix(mt940): activate the statement-vs-bank-account IBAN guard
65daafca test(mt940): faithful IBAN-mismatch coverage for the activated guard
3954f1a1 fix(permissions): make team-leader volunteer access reachable in production
ed5b134a test(permissions): exercise team-leader access via the production path
```

## The 10 production bugs fixed

1. **permissions `has_address_permission`** — Contact-fallback passed a bare
   address-name *string* to `contact.has_common_link()` (reads `doc.links`) →
   AttributeError. Now loads the Address doc when given a name.
2. **sepa_batch_processor `get_active_mandate`** — read `schedule.active_mandate`,
   a field absent from Membership Dues Schedule → AttributeError swallowed by
   `member_has_sepa_enabled`, **silently excluding valid-mandate members from
   direct-debit batches**. Now resolves by member (defensive getattr).
3. **audit_logging** — the two per-event stores called `frappe.db.commit()`
   unconditionally mid-operation, committing callers' in-flight work and
   **clearing their savepoints** (broke MT940 import batches; risks any
   savepoint flow). Removed; mirrors `frappe.log_error` (insert, no commit);
   file-log sink preserves the trail. Scheduled-cleanup commits kept.
4. **dd_batch_scheduler** — `get_weekday()` returns a NAME (not int) on
   v16/Py3.14, so `weekday >= 5` raised TypeError → **automated SEPA batch
   creation was broken**. Added `_weekday_number()`.
5. **mt940_import self-import** — an in-function `from ...mt940_import import …`
   made module names function-local → UnboundLocalError on **every import with a
   counterparty IBAN**. Removed.
6. **mt940_import savepoint** — release/rollback now tolerant of a savepoint
   cleared by a nested commit (belt-and-suspenders for #3).
7. **mt940 legacy helpers** — `generate_mt940_transaction_hash` /
   `convert_mt940_to_csv` read `.date`/`.amount` as attributes; mt940 stores them
   in `.data`. Fixed.
8. **payment_webhook `extract_mollie_payment_data`** — dereferenced
   `payment.amount` before its `hasattr` guard → AttributeError on amount-less
   objects (dead `hasattr` branch). Read via `getattr` first.
9. **payment_gateways `CashGateway`** — reference was a non-f-string literal
   `"CASH-{donation.name}"`. f-stringed.
10. **mt940 IBAN-mismatch guard (DEAD) + permissions team-leader gate (DEAD)** —
    see "Two dead-code findings" below.

## Skeptical reviews (5 review agents total)

- **First batch** (3 reviewers: permissions / Mollie / SEPA-bank): verdicts
  positive — real integration tests, good mock discipline (SDK-boundary only in
  `*_unit.py`), both prod fixes validated. They pinpointed the bug-pinning tests
  and the `member_has_sepa_enabled` data-integrity bug (#2).
- **Last batch** (2 reviewers): bulk-importer/reconciliation/dues un-gating
  **sound**; surfaced two **dead-code** findings (below).

### Two dead-code findings from the last review (both fixed)

- **mt940 IBAN-mismatch guard was dead.** It read `account_identification` off
  per-`Transaction` `.data`, but mt940 only sets the `:25:` field on the parsed
  **container** (discarded by `list(mt940.parse())`), so the guard never fired —
  a statement could import into the wrong account. **Fixed** (`ef008a7e`): read
  `transactions.data["account_identification"]` once before the savepoint,
  normalized compare, reject before any write. Test bank account IBAN matches the
  fixtures' `:25:` (NL02ABNA0123456789) so positive imports still pass.
- **Team-leader volunteer access was dead in production.** Both branches gated on
  `Roles.TEAM_LEADER = "Team Leader"`, a role **production never assigns** —
  real leaders hold an `is_team_leader` Team Role, or are a `Team.team_lead`
  (assigned the "Team Lead" role via `_sync_team_lead_role`). **Foppe chose "drop
  the role gate"** → both branches now derive leadership from team data
  (`is_team_leader` Team Role on an active Team Member, joined via
  `tabVolunteer.member`), self-limiting to real leaders (`3954f1a1`). Folded in
  the review's MED (member-join vs single `get_volunteer_for_member`) and LOW
  (`tm1.status='Active'`) findings.

## Key gotchas (save future debugging)

- **test-quality-enforcer** blocks `frappe.set_user("Administrator")` and
  `.save(ignore_permissions=True)` **inside `test_` methods** (allowed in
  setUp/tearDown/helpers). `.insert(ignore_permissions=True)` in `test_` methods
  is ALSO flagged. Tests run as Administrator → just drop `ignore_permissions`.
  For "admin can do X" tests, create a real roled user (`create_test_user(...,
  roles=["Verenigingen Staff"])`) and `with self.set_user(u.name):` instead of
  the Administrator superuser.
- **`bench run-tests --module A --module B` runs only the LAST module** (Frappe
  quirk). Run each module separately.
- **`--coverage` not `--with-coverage`.** `sites/coverage.xml` is shared — don't
  run coverage on multiple sites concurrently (clobbers/truncates). Test sites:
  `test_site_1..4`; never veg11.
- **mt940 data model**: parsed fields (date/amount/account_identification) live
  in `Transaction.data` / `Transactions.data` (the container), NOT as attributes.
- **Role-profile hooks** (`team_role_profile_hooks` → `auto_sync_on_role_change`)
  rewrite a user's roles on Member/Volunteer/Team save, stripping roles not in the
  calculated profile — a role appended before those saves is silently dropped.
- **dues_processor tests**: build via `object.__new__(DuesPaymentProcessor)` to
  bypass the `MollieClient` constructor; the DB-only methods don't touch
  `mollie_client`/`bank_tx_creator`, so they run credential-free in CI.

## Open / not-done (low priority)

- **Audit-logging durability decision** — `docs/plans/2026-06-14-audit-logging-
  durability-followup.md`. Commit removal fixes the bug & matches Frappe core;
  only build the autonomous-connection write if compliance needs the DB audit row
  to survive a caller rollback (the file-log sink already preserves the trail).
- **INFO-level test hardening** (skipped, optional): assert
  `not hasattr(processor, "mollie_client")` lock-in on dues tests; assert a
  flipped inactive→active mandate also matches.
- **Separate latent issue noted but not chased**: production code references a
  non-existent `base_multiplier` on Membership Dues Schedule in several modules
  (the dues code uses `default_multiplier`); reconcile if it bites.
```
