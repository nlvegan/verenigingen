# Handoff — Codecov per-dir triage + dead-code deletion (2026-06-16)

## TL;DR
- Established **tokenless Codecov access** and pulled a per-directory coverage map (overall **50.85%**).
- Triaged the two biggest 0%-coverage clusters (`utils/performance/`, `api/`) with 4 parallel agents + independent verification.
- Deleted a **self-contained dead "performance measurement phase 1/2" subsystem + 3 orphan validators**: 31 files (~13.3k LOC) + 7 stale fixtures + a commented-out pre-commit block.
- Landed it on local **`develop`** as commit **`6a0df274`** (cherry-pick, no side commits). **Unpushed.**
- Identified the real next coverage targets (live, untested feature APIs).

---

## 1. Codecov access (reusable)
Public repo `nlvegan/verenigingen` coverage is readable **without a token** via `api.codecov.io` (NOT `.ai`, NOT `codecov.io/api`):
```
curl -s "https://api.codecov.io/api/v2/github/nlvegan/repos/verenigingen/"            # totals
curl -s "https://api.codecov.io/api/v2/github/nlvegan/repos/verenigingen/report/"     # per-file
```
`report/` returns `{totals, files:[{name, totals:{lines,hits,misses}}]}`. No per-dir endpoint — aggregate `files[].name` by prefix yourself, sort by misses. Add `?branch=<x>` for non-default.

Snapshot 2026-06-16 (develop): overall 50.85% (1185 files / 147,811 lines). Biggest-gap dirs by missed lines: `verenigingen_payments` (57%), `utils` (46.5%), `e_boekhouden` (40.1%), `services` (63.5%), `api` (30.9%).

---

## 2. What was deleted (commit `6a0df274` on develop)
Foppe chose scope = **"dead + perf subsystem"** (keep the workspace bench commands).

**Performance subsystem (orphaned phase-1/2 tooling — only manual scripts/ imported it):**
- `utils/performance/` whole package (8): bottleneck_analyzer, cache_invalidation_strategy, config, data_retention, enhanced_background_jobs, performance_reporter, query_measurement, security_aware_cache.
- `api/` perf (6): database_index_manager_phase5a, performance_api_validator, performance_convenience, performance_measurement, performance_measurement_api, simple_measurement_test.
- 12 ops scripts under `scripts/{performance,monitoring,deployment}` that backed the above (deploy_phase_1_complete, monitor_monitoring_system_health, performance_baseline_tracker, production_deployment_validator, demo_measurement_capabilities, infrastructure_validator, phase2_profiler, run_phase1_benchmark, run_phase1_measurements, simple_measurement_test, test_measurement_tools, validate_measurement_api).

**Truly-dead validators (zero importers):**
- `api/infrastructure_validator.py`, `api/unified_security_monitoring.py`.
- `api/workspace_content_validator.py` + `scripts/validate_workspace_content.py` (only caller was a **commented-out** pre-commit hook — that block was also removed from `.pre-commit-config.yaml`).

**Fixtures:** removed 7 stale `Critical Operation Rule` entries (get_environment_config, get_performance_config, reset_performance_config, update_performance_config, get_retention_status, run_basic_data_retention, run_smart_aggregation) — verified the JSON rewrite was a pure 112-line deletion (round-trip matched original formatting; kept the adjacent `get_api_performance_summary` which points at the LIVE `performance_dashboard`).

---

## 3. CRITICAL correction to the agents' triage
The triage agents claimed the `bench workspace*` commands were unregistered ("commands/__init__.py has no commands list"). **That was wrong** — `verenigingen/hooks/__init__.py` registers them via `commands = [...]`. So these are **LIVE CLI tooling and were KEPT**, not deleted:
- `api/workspace_health.py` (← `bench workspace-health`, `bench workspace-maintenance`)
- `api/workspace_validator_enhanced.py` (← `bench workspace`)
- `utils/post_migration_hooks.py` (← `bench workspace-maintenance`)
- `commands/workspace.py`, `commands/workspace_health.py`, `commands/workspace_maintenance.py`

**Naming trap also confirmed:** the LIVE performance code is in *sibling flat files* `utils/performance_cache.py`, `utils/performance_dashboard.py` (JS-wired), `utils/cache_invalidation.py`, `utils/performance_event_handlers.py` — NOT the deleted `utils/performance/` directory. Don't confuse them.

---

## 4. Verification done
- Precise import scan + `git grep`: **no runtime or test code** imports any deleted module (the codecov 0% confirms no test exercised them). Only refs were the 12 scripts + 7 fixtures, all removed.
- Live import smoke test on `veg11.veganisme.org` console: deleted modules gone; app, `verenigingen.api`, `hooks`, the workspace commands, and all sibling perf modules import cleanly → **PASS**.
- JSON + YAML validity confirmed. Pre-commit hooks passed on commit (mostly skipped — deletions).
- Full test suite NOT run: deleted code had 0% coverage, and the working tree is polluted by a concurrent session.

---

## 5. Git state — READ THIS before touching branches
There is a **concurrent Claude session live in the SAME shared working tree.** Consequences:
- My `git checkout -b chore/remove-dead-perf-and-validators` moved the *shared* HEAD onto my branch. The main working tree is **still on `chore/remove-dead-perf-and-validators`** with ~11 uncommitted concurrent-session files.
- My branch was created on top of 2 concurrent-session hitchhiker test commits (`2fb212b1` mollie, `5848797a` dd-batch) that the other session had since **reset out of develop**. A plain merge would have dragged them back in.
- So I did **NOT** fast-forward. I cherry-picked **only** my commit `3ee15cc6` onto develop via a throwaway worktree → develop tip = **`6a0df274`** (one new commit, 31 deletions, no hitchhikers). develop is now **7 ahead of origin/develop, UNPUSHED**.
- I could **not** restore the main tree to develop: the concurrent session was mid-edit (uncommitted) on `test_dd_batch_scheduler_orchestration.py`, which differs branch-vs-develop → switching would clobber their work.

### Remaining branch hygiene (do when the tree is clean)
1. Wait until the concurrent session has committed/stashed its uncommitted work.
2. `git checkout develop` in the main tree (now safe once clean).
3. `git branch -D chore/remove-dead-perf-and-validators` (its content — my deletion — is already on develop as `6a0df274`; the only unique commits on it are the 2 hitchhikers that the other session intentionally dropped).
4. Push develop when Foppe is ready (`git push origin develop`).

---

## 6. Next coverage work (triage output — all LIVE, untested, worth covering)
Highest value (financial/compliance/destructive, with real frontend/portal callers):
- `api/anbi_operations.py` (710 LOC — ANBI/Belastingdienst tax + BSN; donor.js + web forms)
- `api/dues_invoice_workflow.py` (661 — www dues-invoice-manager)
- `api/volunteer_application.py` (guest-facing portal intake — riskiest untested endpoint type)
- `api/schedule_maintenance.py` (537 — destructive orphan-schedule cleanup)
- `api/email_template_manager.py` (747 — setup + live donation emails)
- Plus: security_monitoring_dashboard, check_account_types, periodic_donation_operations, document_portal, chapter_validation, manual_invoice_generation, membership_email_templates, dashboard_charts, get_user_chapters, update_prepare_system_button.

Biggest single source-file gap overall: `e_boekhouden/utils/eboekhouden_rest_full_migration.py` (1510 missed lines @ 18.7%).

**DIAGNOSTIC — leave (or delete-review with Foppe):** `api/team_admin_utilities.py` (only unreferenced "backward-compat" wrappers in team.py call it; one fn is `@development_only_api`).

**Function-level dead bits flagged (not removed):** `periodic_donation_operations.link_donation_to_agreement`, `dues_invoice_workflow.check_coverage_scheduling_mismatches` (no callers). Stale broken debug ref: `scripts/debug/system_status_check.py` imports a nonexistent `generate_dues_invoice_for_member`.
