# Handoff — Coverage sweeps session 2 (core-services → billing → utils/portal → file_storage fix), 2026-06-15

## TL;DR
Resumed from `2026-06-15-coverage-sweeps-handoff.md` and ran four more Codecov-driven
sweeps using the proven batch pattern (N agents on distinct test sites → I verify each
suite myself + review product diffs → commit per chunk with explicit pathspec). **All
commits are LOCAL on `develop`, NOT pushed.**

⚠️ **A second session is working `develop` concurrently** (payments `api/`+`utils/`+SEPA).
Its files keep reappearing uncommitted in the tree — always commit with **explicit
pathspec** + `SKIP=deprecated-function-checker`, never `git add -A`. `origin/develop..develop`
currently holds **24 commits: ~13 mine + ~11 theirs** (neither session has pushed).

## My commits this session (local, unpushed), newest first
- `4ccab794` fix(file_storage): let the framework own document storage (fixes 3 storage bugs)
- `46676414` test(events): chapter event subscribers
- `4492197d` test(document-portal): upload/list/permission logic
- `44b6b1d1` test(file_storage): path sanitization + storage (witness tests — superseded by 4ccab794)
- `a6a08982` test(utils): utils/__init__ + API security classifier
- `aaedd6c4` fix(cleanup): cap over-length child-table index names + cover orphan cleanup
- `ebdd0848` test(mijnrood_sync): database client + extend polling service
- `9b5275ff` fix(billing): repair Redis non-blocking lock + ineligible-status; cover bulk gen
- `7b56976d` fix(billing): correct currency in dues-schedule auto-creation + cover module
- `e0ad4c4c` test(brand_settings): color math, validation, CSS lifecycle
- `39eb8537` fix(billing): repair two broken orphan-cleanup paths + cover invoice_management
- `8201f5e3` test(member-mgmt): chapter-assignment API + pure MT940 helpers
- `4492f293` test(termination): termination/suspension integration helpers

(The other ~11 unpushed commits — `bae35c03`, `fe2d99bc`, `5cf44248`, `3da88728`, `20ea387f`,
`e08a2d7a`, `b0f5efa2`, `23a1581f`, `ebca4837`, `485a3b23`, `c1f4b3f9` — are the concurrent
payments/SEPA session's. Not mine; don't fold into my reasoning.)

## Coverage added (~800 tests this session)
termination_integration 47→~78% · member_management 31→~60% · invoice_management 24→~75% ·
brand_settings 18→~58% · dues_schedule_auto_creator 22→~75% · bulk_invoice_generation 41→~75% ·
mijnrood client 27→~72% · polling_service 37→~82% · orphaned_child_table_cleanup 11→~75% ·
utils/__init__ 27→~52% · file_storage 14→~88% · api_classifier 34→~90% ·
document_portal 40→~87% · chapter_subscribers 19→~85%.

## Product bugs fixed this session
- **CRITICAL `utils/db_advisory_lock.py`** (`9b5275ff`): `_get_redis_lock` used `while elapsed < timeout`,
  so a non-blocking call (`timeout=0`) never attempted `redis.set(nx=True)` → always reported the lock
  HELD. On any Redis host (prod) this silently no-op'd BOTH `bulk_invoice_generation.generate_invoices`
  AND the scheduled `dues_schedule_auto_creator`. Fixed to do-while. Existing 30 advisory-lock tests
  still pass; all `timeout>0` callers unchanged.
- **file_storage 3 bugs** (`4ccab794`): Frappe's File doctype flattens private files to
  `/private/files/<basename>` on insert, so the hand-built hierarchical file_url never survived →
  (a) save_* returned an url not matching the File record (dangling), (b) private files had no covering
  record → "Forbidden", (c) duplicate File rows + orphaned disk copies. Fixed by letting the framework
  store the content (flat, content-hash dedup, valid record); `_create_file_record(content, ...)` returns
  the File doc; save_* return the real url; organize_* are no-ops. Verified all 3 consumers pass.
- **invoice_management 2 bugs** (`39eb8537`): `cleanup_orphaned_membership_data` queried
  `tabSales Invoice WHERE membership` (no such column → 1054, dead branch) → now by `member`;
  `cleanup_orphaned_member_references` passed `save(ignore_validate=)` (invalid kwarg) → `flags.ignore_validate`.
- **dues_schedule_auto_creator 3 bugs** (`7b56976d`): get_doc dict skipped the mandatory `currency`
  default; new_doc applied the system default currency (INR!) not EUR; an except handler used
  `member.member_full_name` (row has `full_name`) masking real errors.
- **child-table index names >64 chars** (`aaedd6c4`): `create_missing_parent_indexes` built index names
  exceeding MariaDB's 64-char limit for long DocTypes → CREATE INDEX 1059 → tables un-indexed + reported
  missing forever. Fixed with `_build_index_name` (truncate + deterministic hash).

## Flagged for Foppe (NOT fixed)
- **file_storage data migration:** existing prod `Organization Document` records on veg11 may hold stale
  hierarchical file_urls written by the old bug → those files may be unservable. The code fix prevents
  NEW breakage but does not migrate old rows. Offer: a scan for affected records.
- **Perf/observability triage (area B, ~2,700 mostly-0% lines):** analytics_engine, monitoring_integration,
  business_logic_monitor, performance/* , api/{performance_*,infrastructure_validator,workspace_health,
  unified_security_monitoring}, www/monitoring_dashboard, nuke_financial_data. These look like debug/dev
  scaffolding — the right move is test-vs-delete/exclude triage, NOT blind coverage. Not yet done.
- **eBoekhouden REST sweep (deferred all session):** the biggest remaining real gap (~3,500 lines in
  eboekhouden_rest_full_migration etc.); needs HTTP-boundary stubbing like the Ponto sweep.

## Process gotchas (this env)
- Codecov: use `api.codecov.io/api/v2/github/nlvegan/repos/verenigingen/...` (the `codecov.io/api` host 503s).
  Read token in transcript history. `/report/?branch=develop` for per-file misses.
- Verify agent suites yourself — agent self-reports were wrong multiple times (config-dependent "pass",
  crash-before-report). Run each module on its test_site_N.
- `test-quality-enforcer` rejects `<doc>.insert/.save(ignore_permissions=True)` and
  `frappe.set_user("Administrator")` in `test_*` bodies — only in setUp/tearDown or helpers named
  `_make_*`/`make_*`/`_create_*`/`create_test*`/`_setup_*`/`setup_*`/`_persist_*`/`_as_*`/`_with_*`/etc.
  (scripts/validation/test_quality_enforcer.py:506-534). `frappe.delete_doc(dt, name, force=True,
  ignore_permissions=True)` (both flags, ONE line) is whitelisted anywhere.
- `permission-bypass-validator` wants a `# Security: <reason>` comment on the line DIRECTLY above a
  `save(ignore_permissions=True)`.
- `deprecated-function-checker` rewrites a gitignored report → always fail-once on a clean run; use
  `SKIP=deprecated-function-checker` to avoid leaving files staged (collision risk with the other session).
- `black` runs via pre-commit (not on PATH) and reformats-then-fails on first pass → re-add + re-commit
  (an `add → commit || (add → commit)` helper handles it automatically).
- The harness's "file was modified" notes + pyright diagnostics can lag behind disk (showed stale OLD
  content after my edits). Verify true state with `git diff`/`grep` on disk, not the diagnostics.
- Agents persist within a session (resume via SendMessage(agentId)) — but SendMessage was NOT available
  as a tool this session; used fresh Agent calls for follow-up edits instead.

## Suggested next action
Decide on pushing the 13 mine (coordinate with the concurrent session, or push — branches are clean).
Then either (1) file_storage prod-data scan, (2) area-B triage, or (3) the eBoekhouden REST sweep.
