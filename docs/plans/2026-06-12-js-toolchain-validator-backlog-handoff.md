# Handoff — JS toolchain + validator work; remaining backlog (2026-06-12)

## Status: primary work COMPLETE and PUSHED

Everything below the "Completed" line is on `origin/develop` (synced, 0 ahead /
0 behind, working tree clean). What follows the "Remaining" line is a **deferred
backlog** — none of it is in-progress or blocking; pick up as desired.

Memory topic file with full detail + gotchas:
`memory/prettier-migration-2026-06-12.md`.

---

## Completed this session (all pushed)

1. **Prettier migration** — Prettier owns JS/Vue formatting; `eslint-config-prettier`
   wired last; 584 `no-mixed-spaces-and-tabs` errors → 0. Per-directory `style(js)`
   batches + `.prettierrc.json`/`.prettierignore` + `format`/`format:check` scripts
   + a check-only `prettier` pre-commit hook. (`a926de6e..2bdbcf3d`)
2. **Out-of-gate lint errors** — fixed ~20 real eslint errors in top-level
   `tests/` + `scripts/` that `eslint verenigingen` never checked (`2bdbcf3d`).
3. **Carried-over product items** — wired the ANBI report button, removed dead
   `format_processed`, fixed a `no-dupe-keys` bug.
4. **JS↔Python parameter validator: investigated + fixed.** All 70 priority
   findings verified (≈61 false positives). Fixed **11 real bugs** total:
   - 4 broken UI buttons (`a7741d60`): execute_termination, generate_expulsion_report,
     create_dues_schedule_template, migrate_member_id_counter.
   - 2 stale `frappe.call` refs (`58251826`): mark_email_as_seen, debug_postal_code_matching.
   - 2 missing backends implemented (`7ef5004d`): `create_organization_user`,
     `send_overdue_reminders` — **manually verified on test_site_1** (User created
     + linked + roles; reminder grouping/escaping/counts correct).
   - dupe-keys (`21dfe4de`), missing `@frappe.whitelist()` on
     `manual_retry_failed_requests`, and `include_appeals` not accepted (`4b80cc3f`).
   - **De-noised the validator itself** (`369c999e`): brace-balanced arg parsing,
     identifier-only/top-level-only keys, comment stripping, positional
     `this.call('m',{...})` parsing bound to the method, shorthand-`args` skip,
     `framework_app_prefixes` config, module-level-wins on path collisions.
     **119 noisy findings (exit 1, always SKIP'd) → 0 actionable (exit 0).**

### Push mechanics (current)
- **`whitelist-type-safety` NO LONGER needs SKIP** (item A done — the backlog is
  cleared, hook passes). It will only re-trip if a *new* whitelisted fn adds an
  un-annotated security-sensitive param, which is the hook doing its job.
- **`js-python-parameter-validator` NO LONGER needs SKIP** (it exits 0 now).
- Still pre-existing-noise on commit/push (skip when a touched file trips them on
  unrelated pre-existing issues): `import-path-validator` (e.g. stock_migration's
  dead `error_log_fix` import), `ast-field-analyzer` (custom fields it doesn't know,
  e.g. Customer.customer_sync_status, Lead.source), `test-quality-enforcer`.
- Pre-push also still needs `SKIP=whitelist-type-safety` removed but historically
  `whitelist-type-safety` (now clean), plus the JS-touching SKIPs from the prettier
  handoff if JS is involved.

### ⚠️ Pre-existing uncommitted security WIP found in the tree (2026-06-12)
The tree was NOT clean at the start of this session (the prettier handoff's "clean
tree" claim was stale). ~10 files of a **separate security-hardening effort** were
already modified/uncommitted and were left untouched:
`permissions.py` (SQL-injection escaping of user-controlled chapter/team names in
permission queries), `utils/security/{api_security_framework,audit_logging}.py`,
`verenigingen_payments/core/security/{encryption_handler,webhook_validator}.py`,
`services/{member/approval/application_helpers,volunteer/native_expense_helpers}.py`,
`utils/member_performance_optimizer.py` (@high_security_api on raw-SQL endpoints —
this one was bundled INTO commit `6121c472` per Foppe's choice, since its filters
annotation was intertwined), `doctype/event_contact_campaign/event_contact_campaign.py`,
`www/e_boekhouden_dashboard.py`, and a staged-then-unstaged deletion of
`verenigingen_payments/mollie/api/donation_status_checker.py`. **Decide what to do
with these — they are not part of items A–D.**

---

## Remaining (deferred backlog — optional, not blocking)

### A. `whitelist-type-safety` backlog — ✅ DONE (`6121c472`, 2026-06-12)
**Was 290 errors across 93 files** (the "74" estimate counted only one of
pre-commit's ~6 file batches). Added type annotations to every flagged param; the
`whitelist-type-safety` hook now **passes** at the commit gate and no longer needs
SKIP'ing.

Key learning — Frappe v16 *enforces* these annotations at runtime: `@frappe.whitelist`
wraps the fn with `validate_argument_types(apply_condition=_in_request_or_test)`, so
pydantic coerces/validates args whenever `local.request` **or `in_test`** is set
(i.e. live HTTP **and the test suite**). A wrong annotation raises `FrappeTypeError`.
So types were chosen to match each callsite/body, not blindly `str`:
- identifiers/names/ids/email/iban/bsn → `str`
- query `filters` whose body string-parses (`parse_json_filters`/`_sanitize_member_filters`)
  → `dict | str | None` (8 of these were initially mis-typed `dict | None` by the
  fan-out agents and would have rejected the frontend's JSON-string filters — caught
  and fixed; live smoke test confirms JSON-string accepted, list/object injection
  rejected with `FrappeTypeError`)
- `filters` consumed directly as a dict (e.g. membership_analytics sub-fns) → `dict | None`
- JSON-or-list params (`member_names`, `invoice_list`, `payment_ids`, …) → `str | list`
- Member-doc shim params (`create_customer(doc)` etc.) → `str | dict`; `payment_amount` → `float`
- `@high_security_api`/`@critical_api` use `@wraps`, so coercion fires through them too.

Method: 7 parallel sub-agents partitioned by directory (no file overlap) + a
main-loop AST sweep to find/fix the string-parse `filters` mismatches. `bench`
black reflowed signatures that grew past 110 chars.

### B. JS ESLint warnings — **595, non-blocking**
`npm run lint` → 0 errors / 595 warnings. Breakdown:
- 261 `no-console`, 204 `no-unused-vars`, 115 `no-redeclare`, 13 `radix`,
  1 `no-shadow`, 1 `no-case-declarations`.
- Many are judgment calls (e.g. intentional `console.log` in dashboards/dev pages,
  which are already relaxed per-path in `eslint.config.js`). Triage per category;
  don't blanket-autofix. Lowest priority.

### C. Automated tests for the two new backends (B6/B9) — ✅ DONE (`5b62a4b9`, 2026-06-12)
`verenigingen/tests/backend/integration/test_b6_b9_backends.py` — 6 real
integration tests, green on test_site_1. B6: new-user creation + member
linking + ownership transfer + role assignment, existing-user linking,
already-exists idempotency, missing-first-name rejection. B9: real Draft Expense
Claims (dedicated Expense Claim Type with a per-company account; controlled
posting_date/approver via post-insert `db.set_value`) asserting per-approver
grouping, unassigned counting, the overdue cutoff, HTML escaping of the claimant
name, and the role gate. Only `frappe.sendmail` patched (external boundary).
Created Users `track_doc`'d for teardown (secure_document_operation commits the
insert). **Enforcer gotchas:** `ignore_permissions=True` and
`set_user("Administrator")` are forbidden inside `test_*` methods (only in
setUp/helpers) — run as Administrator and `.insert()` plain instead; each
`frappe.sendmail` patch needs a `# Mock justified: External Service - …` comment.
Minimal valid Expense Claim needs `currency`+`exchange_rate=1`,
`custom_organization_type`, an Expense Claim Type with a company `default_account`,
`payable_account`, `cost_center`, and an expense row with `cost_center`.

### D. Validator minor cleanup (cosmetic)
`scripts/validation/production/js_python_parameter_validator_enhanced.py` has
pre-existing unused imports (`os`, `inspect`, `importlib.util`, `Set`, `Tuple`)
flagged by pyright. Harmless; remove when convenient.

---

## Key gotchas (also in memory)
- **Prettier is `{js,vue}`-only here** — `prettier <dir>` reformats Frappe-managed
  `.json`/`.html`/`.md`; `format`/`format:check`/the pre-commit hook are all scoped
  to `{js,vue}`. Never widen to `prettier .`.
- **Never test on veg11** (commit-pollution cascade). Use test_site_1..4 /
  test_snapshot. Test sites already have the app code (no migrate needed for new
  Python functions — B6/B9 added no schema).
- **bench console + piped multi-line scripts** are unreliable (IPython input
  quirks). Run via `printf "exec(open('/tmp/x.py').read())\n" | bench --site X
  console`, and wrap closures in a function (exec-scope gotcha).
- The validator now treats `frappe.`/`erpnext.`/`hrms.`/`payments.` dotted paths
  as framework methods; if a real bug ever hides behind one of those, it won't be
  caught (acceptable trade-off — those apps aren't indexed).
