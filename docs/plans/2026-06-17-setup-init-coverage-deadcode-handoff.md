# setup/__init__.py — dead-code triage + coverage sweep (handoff)

**Date:** 2026-06-17
**Branch:** develop
**Status:** DONE, all commits **PUSHED** to `origin/develop` (synced at `3eb8e59e`).
**Continues:** `docs/plans/2026-06-17-codecov-coverage-and-deadcode-handoff.md` (target #3).

---

## What this session did

Tackled next-target #3 from the prior handoff: `verenigingen/setup/__init__.py`
(was 2912 LOC, ~25–28% covered). Two-phase: delete dead diagnostic code, then
cover the genuinely-live install functions.

### Commits (mine — PUSHED)

| commit | what |
|---|---|
| `630f3bbb` | refactor(setup): remove 17 dead onboarding diagnostic endpoints (671 LOC) |
| `3eb8e59e` | test(setup): cover setup/__init__ install functions + fix 2 bugs (89 tests) |

> Two commits from a **concurrent eBoekhouden-orchestration session** are
> interleaved between mine on `origin/develop` (`c18bf895` cover REST
> orchestration, `1ee585a8` remove dead REST Mutation Cache refs). They are
> not part of this work; mine were committed with explicit pathspecs to stay
> separate.

Also pushed earlier this session: the 5 prior unpushed commits
`69f7673b..ab5854e9` (the Mollie/mt940/mijnrood/donate work from the previous
handoff).

---

## Phase 1 — dead-code deletion (`630f3bbb`)

Deleted 17 whitelisted **onboarding diagnostic/manual-fix endpoints** with zero
live callers. The only references were in auto-generated registries
(`verenigingen/fixtures/critical_operation_rule.json` and
`scripts/permission_analysis_details.json`) plus a comment in `patches.txt` —
none are real callers; none are wired as workspace/onboarding JSON actions or in
any `.js`.

Deleted: `link_module_onboarding`, `fix_onboarding_visibility`,
`check_onboarding_setup`, `test_onboarding_fix`, `check_onboarding_schema`,
`final_onboarding_verification`, `test_email_template_page`,
`add_module_onboarding_custom_field`, `test_onboarding_api`,
`debug_onboarding_visibility`, `check_module_mapping`,
`investigate_other_module_onboarding`, `check_workspace_schema`,
`force_workspace_onboarding_link`, `fix_workspace_onboarding_link`,
`examine_existing_onboarding`, `debug_onboarding_creation`.

**KEPT (live):** `reinstall_onboarding` — initially deleted by mistake; it is
called by `install_and_link_onboarding` (line ~1996) to build the Module
Onboarding document during `after_install`. Also kept `install_and_link_onboarding`
(live via `setup_workspace`), `verify_app_dependencies` (already tested), and
`ensure_required_payment_modes` (the `after_migrate` hook).

> **Lesson:** when grep'ing for callers to prove dead code, include the file
> itself — `reinstall_onboarding`'s only caller lived inside `setup/__init__.py`
> and was missed by an exclude filter.

Verified: AST parse OK, ruff clean, module imports under bench, 30 existing
`test_setup_init.py` tests pass.

---

## Phase 2 — coverage + bug fixes (`3eb8e59e`)

89 new integration tests across 5 files in
`verenigingen/tests/backend/components/`, written by 5 parallel agents (one per
cluster, each on a distinct `test_site_N`), then hardened after a skeptical
review. 119 setup tests total green (89 new + 30 existing).

| test file | covers | tests |
|---|---|---|
| `test_setup_custom_fields.py` | make_custom_fields, get_custom_fields, create_eboekhouden_custom_fields, make_custom_records, validate_app_dependencies, init-complete flags, execute_after_install guard | 19 |
| `test_setup_btw_eboekhouden.py` | install/verify/fix BTW fields, create_default_eboekhouden_settings, setup_tax_exemption_on_install | 13 |
| `test_setup_termination.py` | setup_termination_system_integration/settings/workflows/roles, manual, run_termination_diagnostics | 18 |
| `test_setup_workspace_onboarding.py` | setup_workspace, cleanup/update_workspace_links, install_and_link_onboarding, reinstall_onboarding, web pages, membership-application system, manual wrappers | 20 |
| `test_setup_reference_cors.py` | configure_website_cors, create_all_reference_data, ensure_required_payment_modes, load_application_fixtures, manual email-template wrappers, seeder branch gaps | 19 |

### Production bugs fixed (both in `setup/__init__.py`)

1. **`reinstall_onboarding()` registered onboarding under the wrong module** —
   the seed set `"module": "E-Boekhouden"` (should be `"Verenigingen"`, matching
   the committed source `verenigingen/verenigingen/module_onboarding/verenigingen/verenigingen.json`).
   The wrong value caused the doc to associate with the e-boekhouden module and
   export to a stray path. One-line fix.

2. **`create_email_templates_manual()` always returned `success=False`** — it
   computed `basic_count + enhanced_count + comprehensive_count`, but
   `create_default_email_templates()` returns a dict and
   `create_comprehensive_email_templates()` returns an `OperationResult`, so
   `int + dict` raised `TypeError`, caught by the outer `except`. Added
   `_normalize_template_count()` to coerce each helper's return shape to an int.

### Skeptical review outcome

Suite judged mostly strong. 6 weak tests fixed before commit: one tautological
"dropped-fields" guard (rewrote into a real drift guard with explicit
`KNOWN_DROPPED` sets), a `count >= 0` tautology, an unverified CORS skip-branch
(now spies on `.save`), a test asserting a re-implemented check instead of the
function, the module-value test (now asserts `Verenigingen`), and the
email-template bug guard (flipped to assert the now-correct `success=True`).

---

## Wiring reference

- `after_install` → `verenigingen.setup.execute_after_install` →
  validate_app_dependencies / create_default_verenigingen_settings /
  create_eboekhouden_custom_fields / setup_verenigingen /
  create_all_reference_data / setup_membership_application_system /
  setup_tax_exemption_on_install / setup_termination_system_integration /
  **setup_workspace → install_and_link_onboarding → reinstall_onboarding** /
  load_application_fixtures.
- `after_migrate` → `ensure_required_payment_modes`.
- Hooks live in `verenigingen/hooks/lifecycle.py` (`hooks` is a **package**,
  there is no top-level `hooks.py`).

---

## Flagged for Foppe (NOT fixed — pinned as labelled regression-guard tests)

1. **Termination workflow never persists on fresh installs.**
   `verenigingen/setup/workflow_setup.py` `create_workflow_action_masters` only
   creates the custom `Execute` action and assumes standard `Submit`/`Approve`/
   `Reject` Workflow Action Masters already exist. On a site lacking them the
   `Membership Termination Workflow` insert fails link-validation, so the
   workflow is never created — yet `setup_workflows_corrected` still returns
   `True` and prints success. `check_termination_system_status` /
   `run_termination_diagnostics` correctly report `workflows_exist=False`.
   Fix would add the standard action masters before creating the workflow.

2. **`configure_website_cors()` is a no-op on this Frappe version.** Website
   Settings has no `cors_allowed_origins`/`enable_cors`/etc. fields, so Frappe
   silently drops the writes. May be dead, or intended for a different Frappe
   build — decide whether to delete or guard.

3. **Onboarding seed writes fields the current doctype dropped.**
   `reinstall_onboarding` writes `subtitle`/`success_message`/`documentation_url`
   (Module Onboarding) and `creation_doctype`/`is_mandatory` (Onboarding Step) —
   confirmed via `get_meta` these are NOT on the current doctypes, so they are
   silently dropped (cosmetic; the committed instance JSON is stale from an
   older Frappe). Either remove the dead keys or leave for when the fields return.

---

## Gotchas verified this session

- **Export-on-save:** running these install functions in tests makes Frappe
  re-export app-owned doctype JSON into the source tree
  (`verenigingen/verenigingen/{workspace,module_onboarding,onboarding_step}/`,
  and stray `verenigingen/e_boekhouden/{module_onboarding,onboarding_step}/`).
  Clean after every run:
  `git checkout verenigingen/verenigingen/{workspace,module_onboarding,onboarding_step}/`
  then `rm -rf verenigingen/e_boekhouden/{module_onboarding,onboarding_step}/`.
  **DANGER:** use `git checkout` (not `rm`) for the `verenigingen/verenigingen/`
  paths — those are tracked source; `rm -rf` there deletes committed files.
- **Stale `.pyc`:** after editing `setup/__init__.py`, a test run executed the
  OLD bytecode and failed on the already-fixed int+dict bug. Fix:
  `find apps/verenigingen -name __pycache__ -path "*setup*" -exec rm -rf {} +`
  + `bench --site <site> clear-cache`. Confirm a prod fix via `importlib.reload`
  in `bench console` if a result looks stale.
- **Concurrent sessions** commit to `develop` mid-work. Always commit with an
  explicit pathspec; never `git add -A`.
- **AST-based deletion** (parse with `ast`, splice out functions by name + their
  decorators) is the safe way to remove many functions from a 100KB file.

---

## Next coverage targets (carried forward)

From the prior handoff's per-dir snapshot (origin `5c0d43c4`):
1. `e_boekhouden/utils/eboekhouden_rest_full_migration.py` **orchestration**
   layer — partially addressed by the concurrent session (`c18bf895`); check
   `2026-06-17-eboekhouden-rest-migration-coverage-handoff.md` for remaining gaps
   (`start_full_rest_import`, batch import, the `skipTest` force-delete defect).
2. `e_boekhouden_migration.py` controller (776 miss, 12%).
3. `setup/__init__.py` — **DONE this session** (this handoff).
