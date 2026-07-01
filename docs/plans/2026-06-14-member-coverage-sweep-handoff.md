# Handoff: Codecov-driven core-member coverage + bug-fix sweep (session 2)

**Date:** 2026-06-14
**Branch:** develop — **ALL PUSHED** to origin (`ed5b134a..2d27b3bf`, 15 commits, pre-push clean, no SKIP needed)
**Trigger:** "check codecov to see where the worst coverage gaps are now and prep for working on those" → user chose **core member/doctype logic** → multi-batch test+bugfix sweep.

## TL;DR

Lifted coverage across ~19 core member/chapter/membership/services modules by
writing **real-integration tests** (no business-logic mocking), fixing every
production bug the tests + reviews surfaced. **~720 new tests, ~24 production
bugs fixed, 16 skeptical reviews, all green, all pushed.** The reviews were
load-bearing — several real bugs were caught by the skeptical reviewer, not the
test-writer.

## The proven workflow (repeat this for the next batch)

1. **Find gaps via Codecov public API (no token needed; repo is public):**
   `curl -s "https://codecov.io/api/v2/github/nlvegan/repos/verenigingen/report/?sha=<full-sha>"`
   Use the **last commit with a complete upload** (9 sessions) — the in-progress
   tip is partial. Get per-file `line_coverage` (encoding: **`0`=covered, `1`=uncovered**).
   Map uncovered lines → functions with a small AST script (see git history of
   this session's bash calls).
2. **Dispatch N parallel `general-purpose` agents**, each owning a chunk of 1-3
   related files, each on a **distinct test site** (test_site_1..5 — 5 exist now).
   Agents: read code + gold-standard test files, write real-integration tests,
   run on their site **without `--coverage`**, fix in-file bugs (minimal), **do
   NOT commit**. Each returns a structured report.
3. **I (orchestrator):** lint (ruff), validate every bug-fix claim against the
   schema, run each module myself (or trust agent + reviewer), then dispatch
   **N parallel `skeptical-code-reviewer` agents** (one per chunk) to adversarially
   verify fixes + test quality + "no bugs" claims. Reviewers run on the same
   per-chunk sites.
4. **Fix review findings myself**, re-run, **commit per chunk** (prod fix + tests
   together), push at the end.

Gold-standard test files to point agents at:
`tests/member/test_member_utils_endpoints.py`, `tests/member/test_member_scheduler.py`,
`tests/chapter/test_member_manager.py`, `tests/services/test_base_role_profile_manager.py`.

## Modules covered (single-module coverage; baselines from full-suite Codecov)

| Module | Baseline → | Bugs | Commit |
|---|---|---|---|
| doctype/member/member_utils.py | 23→81% | 5 | `5edb1294`/`7ea5394b` |
| doctype/member/scheduler.py | 12→67% | 1 + deleted 400 LOC dead | `65e648ee`/`fb8dd4f3` |
| chapter/managers/member_manager.py | 48→71% | 4 | `fbeeef9d` |
| services/.../account_creation_api.py | 38→56% | 0 | `e7a85393` |
| doctype/membership/membership.py | 58%+ | 4 | `f6fef4c3` |
| services/.../base_role_profile_manager.py | 53→71% | 1 (CRITICAL) | `4fcbf241` |
| doctype/chapter/chapter.py | 61→74% | 0 | `8b51dff7` |
| doctype/membership/scheduler.py | 16→85% | 1 | `6a264b52` |
| user_role_profile_calculator + account_creation_request | ~51-53→73% | 0 | `0c04d70e` |
| membership_dues_schedule + contribution_amendment_request | ~63%→ | 0 | `d9350dd3` |
| board_manager + communication_manager | ~58→72% | 2 | `12bfbf15` |
| membership_termination_request + analytics | ~30%→high | 1 | `fcd612e8` |
| donor + donor_service + donor_auto_creation_management (+financial_service) | ~38%→high | 3 (+1 sibling) | `2d27b3bf` |

## Production bugs fixed (by class)

**Wrong column/field name → crash on first real use** (the dominant class):
- member_utils `add_manual_payment_record`: `donation_payment_account`→`donation_debit_account`.
- membership `show_payment_history`/`show_all_invoices`: read nonexistent
  `membership.dues_schedule` (getattr guard) + queried Sales Invoice `membership`
  column (real field is `member`) → guarded via `has_field`.
- membership `get_member_sepa_mandates`: `filters: str`→`dict|str` (v16 typing).
- termination `generate_expulsion_report`: selected HTML field `current_chapter_display`
  (no DB column) → `current_chapter` (Link), aliased back.
- donor_service: `Customer.donor_reference`→`donor`, `Donation.payment_status`→`paid`,
  `Donation.is_recurring`→`status=='Recurring'`; **financial_service.py** had the
  identical `donor_reference` bug in 3 places (caught by review).
- communication_manager `create_email_communication`: `communication_type='Email'`
  invalid (Select allows Communication/Automated Message) + newline-joined recipients
  (need comma) → silently returned None for multi-recipient sends.

**v16 role-profile model (CRITICAL):** base_role_profile_manager `_process_bulk_member`
wrote `frappe.db.set_value("User", ..., "role_profile_name", ...)` — the v16-deprecated
column — so **bulk role-profile assignment granted zero roles** while reporting success
(live via team.js/chapter.js bulk buttons). v16 derives roles from the `role_profiles`
child table. Fixed to write the child table (mirrors `assign_role_profile`).

**UpdateAfterSubmitError on submitted docs** (recurring): membership `auto_apply_grace_period_if_enabled`
and membership/scheduler `_process_expired_memberships_impl` set a non-`allow_on_submit`
field on a submitted doc + save → exception swallowed → feature silently dead. Fix =
`flags.ignore_validate_update_after_submit = True` (validate() still runs).

**Kwarg drift / swallowed exceptions:** member_manager approve/reject/join passed
`new_status=`/`end_date=` to `add_membership_history` (takes `status=`) → TypeError
swallowed → chapter approve/reject/join silently failed + recorded no history.
member_manager `_notify_board_of_join_request` read nonexistent `board_member.member`.
member/scheduler `enqueue_member_history_refresh` returned a raw RQ Job (caller did
`.get("success")`).

## OPEN — flagged for Foppe (real pre-existing bugs, NOT fixed; need a decision)

1. **Chapter notification emails ALL fail silently.** `communication_manager._send_templated_email`
   → `send_chapter_email` is multi-layered broken: (a) `reference_doctype`/`reference_name`
   land in `**kwargs` and collide with the hardcoded `reference_doctype="Chapter"`
   ("got multiple values..."); (b) `send_chapter_email` returns an `OperationResult`
   but the caller does `result.get("success")` (no `.get()` on OperationResult). Both
   are swallowed → `False`. Needs a proper fix + a test strategy for the no-SMTP test
   env (EmailService is a no-op in tests, so "email sent" isn't deterministically
   assertable). I fixed layer (a), found (b), and **reverted** to keep the commit honest.
2. **`transition_board_role`** (board_manager.py:271) — the `add_board_member` call is
   **commented out**, so a role transition removes the member from the board and adds
   nothing, while still emailing them about the "new" role. Deliberately commented —
   don't blindly uncomment; confirm intent.
3. **Termination dead-status filters** — membership_termination_request.py filters on
   `"Pending Approval"`/`"Under Review"`, but the `status` Select only allows `"Pending"`
   (the approval service sets `"Pending"`). So `get_termination_statistics` pending count
   is always 0 and the duplicate-disciplinary guard never matches. Fix = swap to `"Pending"`
   in the 3 sites (needs confirmation it's the intended match).
4. **`get_application_invoice`** (account_creation_request.py) matches Member Payment
   History fields `invoice_type`/`description` that don't exist → always returns None →
   approval email skipped. Correct replacement field ambiguous (`transaction_type`?).
5. **Deferred (from earlier in session): membership dues-schedule linkage.** Membership
   has no `dues_schedule` forward field; the real link is `Membership Dues Schedule.membership
   → Membership` (one-directional). `Membership.create_dues_schedule_from_membership` writes
   `db_set("dues_schedule")` (nonexistent column) → broken end-to-end, AND the show_*
   dues-schedule branches are permanently dead. Needs a schema decision (add the custom
   field, or delete the dead endpoint/branches).

**Latent dead branches noted (low priority):** `student_status` (contribution_amendment_request)
and `selected_tier` (membership_dues_schedule) referenced but absent from their DocTypes;
`calculate_chapter_risk_score`'s 100 cap is unreachable; bulk_remove/deactivate swallow
per-row save failures as success.

## Key gotchas (save future debugging)

- **bench/click conflict:** if `bench` dies with `ImportError: cannot import name
  '_check_nested_chain' from 'click.core'`, semgrep downgraded the launcher's click <8.2.
  Fix: `/usr/bin/python3 -m pip install --user "click==8.2.1"`. (See memory
  `bench-click-version-conflict`.) Happened mid-session.
- **test_site_5 created this session** (the 5th parallel site). MariaDB root pw is in
  memory `test-suite-fix-2026-06-07-session2.md` (do NOT re-persist). `setup_test_sites.sh`
  needs `MARIADB_ROOT_PASSWORD`; it excludes hrms — install hrms manually to match the
  other sites.
- **v16 role profiles:** roles derive from the User `role_profiles` child table, NOT the
  deprecated `role_profile_name` Link column. Always assert role-profile assignment via
  `user_doc.role_profiles` — asserting `role_profile_name` hides the v16 no-op bug.
- **import-path-validator (pre-commit) rejects `from <doctype_pkg> import <submodule> as X`**
  for some doctype dirs (e.g. contribution_amendment_request) even though it's valid Python.
  Use the codebase convention: full path `from ...doctype.X.X import (funcs)` (direct
  function imports), single not multi-line if length allows. (The membership single-line
  `import membership as mship` form passes; the longer ones don't.)
- **Shared `sites/coverage.xml`:** never run `--coverage` on two sites concurrently
  (clobbers). Agents run WITHOUT `--coverage`; measure coverage sequentially afterward.
- **Concurrent `bench run-tests` needs distinct sites** (same-site = DB/lock collisions).
- **test-quality-enforcer:** inside `test_` methods NO `frappe.set_user("Administrator")`,
  `.save(ignore_permissions=True)`, `.insert(ignore_permissions=True)`. Tests already run
  as Administrator. `frappe.db.set_value`/`set_single_value` allowed.
- **`create_test_volunteer`:** the member LINK kwarg is `member=`, NOT `member_name=`
  (passing member_name silently mislinks to an auto-created different member).
- **`bench run-tests --module A --module B` runs only B.** One module at a time.

## What's left (next batches)

Remaining core-cluster targets (pre-session Codecov baseline, untouched):
`api/member_management.py` (30.7%), `events/subscribers/*` (8-23%, event-driven/harder),
`utils/member_portal_utils.py` (12%), `utils/membership_dues_integration.py` (9%),
`api/chapter_dashboard_api.py` (22%), `api/volunteer_application.py` (0%),
`services/volunteer/*` expense utils (24-40%), `member_user_account_service.py` (56%).
Bigger untouched subsystems (wider scope): **e_boekhouden/** (~11.4k missed, 24.8% — the
lowest-covered subsystem), verenigingen_payments internals, portal `templates/pages/`.
