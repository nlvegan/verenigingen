# Test Inventory — Domain MJ: mijnrood_sync sub-app + stray co-located service tests

> **Audit complete (21/21 files).** Read-only classification of every class-level `def test_*` method.
> Categories: HAPPY (nominal success) · UNHAPPY (error/throw/validation/auth failure) · EDGE (boundary/empty/dup/idempotency/malformed/retry/SFTP-SSH auth edges) · OTHER (smoke/import-only/tautology/mock-into-tautology/live-gated/skipped).

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| e_boekhouden/services/tests/test_account_migration_service.py | 34 | 20 | 2 | 12 | 0 |
| e_boekhouden/services/tests/test_relation_migration_service.py | 16 | 11 | 0 | 5 | 0 |
| events/subscribers/test_chapter_subscribers.py | 38 | 16 | 0 | 22 | 0 |
| mijnrood_sync/doctype/mijnrood_sync_event/test_mijnrood_sync_event.py | 20 | 9 | 8 | 2 | 1 |
| mijnrood_sync/doctype/mijnrood_sync_log/test_mijnrood_sync_log.py | 0 | 0 | 0 | 0 | 0 |
| mijnrood_sync/doctype/mijnrood_sync_state/test_mijnrood_sync_state.py | 0 | 0 | 0 | 0 | 0 |
| mijnrood_sync/doctype/mijnrood_sync_settings/test_mijnrood_sync_settings.py | 27 | 10 | 13 | 4 | 0 |
| mijnrood_sync/doctype/mijnrood_sync_settings/test_mijnrood_sync_settings_remote.py | 23 | 12 | 3 | 8 | 0 |
| mijnrood_sync/services/event_application/test_dispatcher.py | 25 | 12 | 8 | 5 | 0 |
| mijnrood_sync/services/event_application/test_sync_services.py | 47 | 17 | 6 | 24 | 0 |
| mijnrood_sync/services/test_application_approval_correlator.py | 19 | 5 | 5 | 9 | 0 |
| mijnrood_sync/services/test_document_import_coverage.py | 31 | 9 | 5 | 17 | 0 |
| mijnrood_sync/services/test_document_import_service.py | 37 | 15 | 1 | 21 | 0 |
| mijnrood_sync/services/test_source_folder_backfill.py | 9 | 2 | 2 | 5 | 0 |
| mijnrood_sync/test_client_coverage.py | 22 | 9 | 8 | 5 | 0 |
| mijnrood_sync/test_client_unit.py | 33 | 19 | 3 | 11 | 0 |
| mijnrood_sync/test_field_mapping_and_utils.py | 29 | 10 | 1 | 14 | 4 |
| mijnrood_sync/test_polling_service_coverage.py | 34 | 12 | 0 | 22 | 0 |
| mijnrood_sync/test_sftp_client.py | 28 | 6 | 11 | 11 | 0 |
| mijnrood_sync/test_ssh_auth.py | 36 | 16 | 5 | 14 | 1 |
| mijnrood_sync/test_tasks.py | 3 | 2 | 0 | 1 | 0 |
| **DOMAIN TOTALS** | **511** | **212** | **81** | **212** | **6** |

## Observations

- **Coverage shape is well-rounded, with genuinely strong negative-path testing.** Across all 21 files the split is HAPPY 212 / UNHAPPY 81 / EDGE 212 / OTHER 6 — a ~41/16/41/1 mix. The 16% UNHAPPY headline understates real rejection coverage because, per the app's convention, "absence of data / graceful fallback" cases (missing file, empty config, unmatched FK, unknown host TOFU) are folded into EDGE; only genuine rejections (SQL-injection/allowlist guards, path traversal, oversized files, wrong passphrase, changed host key, auth failure) are counted UNHAPPY. OTHER is near-zero (6/511) — almost every method exercises real product logic.
- **The new 7 top-level `mijnrood_sync/*.py` files are the security/boundary core of the sub-app.** They concentrate the domain's UNHAPPY weight: `test_sftp_client.py` (11 UNHAPPY — path-traversal + size-cap + precondition rejections) and `test_ssh_auth.py` (5 UNHAPPY — wrong/absent passphrase, garbage/empty key, changed host key = MITM tripwire) are the strongest negative-path files in the whole domain. `test_client_coverage.py`/`test_client_unit.py` add allowlist + identifier SQL-injection guards. Boundary mocking is disciplined throughout — only paramiko `Transport`/`SFTPClient`/`pymysql.connect` (the true network seam) are stubbed; all validation, serialization, column-resolution and retry logic runs for real against `_Fake*` data fixtures.
- **Three zero-method files remain in the table** — `mijnrood_sync/doctype/mijnrood_sync_log/test_mijnrood_sync_log.py` and `.../mijnrood_sync_state/test_mijnrood_sync_state.py` are empty scaffolds (0 methods). Note `mijnrood_sync_settings` is NOT zero: it has two populated test files (`test_mijnrood_sync_settings.py` 27 methods + `test_mijnrood_sync_settings_remote.py` 23 methods, together the domain's densest UNHAPPY block at 16 combined). The Log and State doctypes — both write-only sync bookkeeping records — are the real coverage gap.
- **EDGE-heavy pure-transform files.** `test_polling_service_coverage.py` (22/34 EDGE, 0 UNHAPPY) and `test_field_mapping_and_utils.py` (14/29 EDGE) are dominated by change-tag/summary/diff transforms and config-vs-defaults fallbacks — inherently boundary-shaped (empty data, unmapped fields, none-vs-empty normalization, truncation overflow, priority ordering). These are meaningful behavior tests, not filler.
- **Only weak spot flagged: `test_field_mapping_and_utils.py::TestStaticMappingConstants` (4 OTHER).** These assert static module constants (`TABLE_COLUMNS`/`TABLE_PRIMARY_KEY` key parity, all-pk-is-"id", two mapping-value pins) without executing product code — regression tripwires on data rather than behavior. Legitimate as drift guards but classified OTHER (no code path exercised). This is 4 of the domain's 6 total OTHER methods.
- **Base classes are consistent.** DB-touching files use `EnhancedTestCase` (from `tests/fixtures/enhanced_test_factory`) with proper Single-doctype snapshot/restore in setUp/tearDown and factory `track_document` for created rows; pure-unit files (`test_client_*.py`, `test_sftp_client.py`, `test_ssh_auth.py`) use plain `unittest.TestCase` since they mock only the external network boundary and need no site fixtures. `test_ssh_auth.py` notably generates REAL RSA/Ed25519/ECDSA/DSS cryptographic material rather than mocking key parsing.

## Zero-method / missing files

- **`mijnrood_sync/doctype/mijnrood_sync_log/test_mijnrood_sync_log.py`** — 0 class-level test methods (empty scaffold). Coverage gap for the sync-run audit-log doctype.
- **`mijnrood_sync/doctype/mijnrood_sync_state/test_mijnrood_sync_state.py`** — 0 class-level test methods (empty scaffold). Coverage gap for the per-row sync-state bookkeeping doctype (its `raw_data` JSON is read by `polling_service._resolve_division_name`, tested indirectly there but the doctype's own controller is untested).
- All other 19 files contain at least one class-level test method and were audited.
- Module-level `def test_*` helpers and the `_Fake*`/`_make_client` fixtures were correctly excluded from counts (not class-level test methods).
