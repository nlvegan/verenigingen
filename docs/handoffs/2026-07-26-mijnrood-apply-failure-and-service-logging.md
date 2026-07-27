# MR-SYNC-2026-00087 apply failure + service-layer logging black hole

**Date:** 2026-07-26
**Trigger:** Applying MijnRood Sync Event `MR-SYNC-2026-00087` (an address change) on
veg11 failed with `error_message = "Member update failed"` and nothing in Error Log or
any log file.

## Root cause

Three independent defects stacked up.

### 1. Unresolvable Dynamic Link makes the Member unsavable (the actual failure)

`member.save()` raised

```
LinkValidationError: Could not find Row #1: Reference Name: Schedule-Assoc-Member-2026-01-32819-Lid-001
```

The member's `payment_history` row 1 had `reference_doctype = "Membership"` with a
`reference_name` that is a **Membership Dues Schedule** name. Frappe's `_validate_links()`
looks it up in `tabMembership`, never finds it, and throws — so the parent Member cannot
be saved by *any* full-document path, whatever field the caller meant to change.

Scope measured on veg11:

| | count |
|---|---|
| `Member Payment History` rows total | 431 |
| rows with `transaction_type = 'Membership Invoice'` | 430 |
| …of those, `reference_doctype='Membership'` → a Dues Schedule | **430 (100%)** |
| …pointing at a real `Membership` | **0** |
| distinct members blocked | **430** |

test_site_1 had 17 of the same rows, so this is not veg11-specific.

Legacy data. The retired writer `payment_mixin_optimized.py` (deleted during the
PR #174-#179 writer unification) produced exactly this shape. The current writer
(`PaymentHistoryEntryBuilder.build_from_query_row`) derives the reference from
`Sales Invoice.membership` and leaves both fields NULL when there is no membership —
verified by rebuilding this member's history, which yields `reference_doctype = None`.
There are 0 Sales Invoices site-wide whose `membership` fails to resolve, so no live
writer can reintroduce it.

All 431 rows have NULL `creation`/`modified` — that is just how `update_child_table()`
writes child rows (`d.db_update()`, not `insert()`), not a dating signal.

### 2. The reason was thrown away

`member_import_service._update_existing_member` caught `frappe.ValidationError` and
returned a bare `"failed"`, discarding `str(e)`. The caller
(`member_sync_service.apply_changed_member`) formatted `_("Member update {0}")` →
*"Member update failed"*. Unlike the generic `Exception` branch directly below it, this
branch also never called `frappe.log_error`, so nothing reached Error Log either.

### 3. Service-layer logging was unformatted and partly discarded

`BaseService.__init__` did:

```python
self.logger = logging.getLogger(f"verenigingen.services.{self.service_name}")
```

Frappe attaches its handlers inside `frappe.logger()`, under the name `"{module}-{site}"`
(`frappe/utils/logger.py:get_logger`). A bare stdlib name matches nothing and has no
handler, so records fell through to Python's `lastResort` handler. 103 `BaseService`
subclasses were affected, plus 12 module-level `logging.getLogger(...)` loggers across
`mijnrood_sync/`.

**Correction to the original diagnosis.** The first pass here claimed "zero hits across
every log file". That was wrong — the grep patterns used were `"Update failed for"` (the
generic-`Exception` branch's wording) while the actual line reads `"Update validation
error for"`. `lastResort` writes WARNING and above to stderr, which supervisor captures,
so the message *was* on disk all along:

```
logs/web.error.log:5759
Row unknown: Update validation error for Assoc-Member-2026-01-32819 - Could not find Row #1: ...
```

The accurate statement: ERROR/WARNING reached `web.error.log` / `worker.error.log`
unformatted and untimestamped; only `.info()`/`.debug()` were genuinely discarded.

**Consequence of the fix worth knowing:** `frappe.logger()` sets `propagate = False`, so
these records now go to `sites/<site>/logs/verenigingen.services.log` and **stop**
appearing in `web.error.log`. Any habit or alert watching those files loses the signal.
And Frappe defaults these loggers to ERROR (WARNING on a dev server), so the hundreds of
`self.logger.info(...)` calls remain invisible unless the site raises `log_level` — "the
logging now works" means errors are captured and formatted, not that info-level tracing
appeared.

## Changes

| Area | Change |
|---|---|
| `utils/service_logger.py` (new) | `get_service_logger(name, prefix=...)` → `LazyServiceLogger`, resolving through `frappe.logger()` on each use. Lazy because these services are module-level singletons that outlive a request, and `frappe.logger()` binds the handler to `frappe.local.site`. Falls back to the bare stdlib logger if `frappe.logger()` raises — logging must never break its caller — but warns once so the degradation is not silent. |
| `services/infrastructure/base_service.py` | Uses `get_service_logger("verenigingen.services", prefix=service_name)`. One line; fixes all 103 subclasses. **One shared name, not one per class:** `frappe.logger()` eagerly opens two `RotatingFileHandler`s per distinct name per site and caches them for the process lifetime, so per-class names would cost ~230 open fds per worker and ~115 mostly-empty files per site. The class name lives in the message prefix instead. |
| `mijnrood_sync/` (12 files) | Module-level `logging.getLogger(...)` → `get_service_logger("verenigingen.mijnrood_sync", prefix="<module>")`, same rationale. |
| `verenigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py` | `_process_single_member` now appends `"failed: <reason>"` to the import's error log. Without this the reason died one frame above where it was produced: `CSVImportBackgroundProcessor` buckets every non-created/updated status into `skipped_count` and discards the string, making a real failure indistinguishable from a legitimate duplicate skip. |
| `mijnrood_sync/doctype/mijnrood_sync_event/mijnrood_sync_event.py` | Explicitly converts `Member.dues_rate` back to cents for the review table's "Current (Frappe)" cell. Removing the field-map key would otherwise have left that cell blank, since the comparison map is derived from `MIJNROOD_TO_MEMBER_FIELD_MAP`. |
| `services/csv_import/member_import_service.py` | New `_failure_status(e)` helper; all four failure branches now return `"failed: <reason>"`, and the update-path `ValidationError` branch calls `frappe.log_error`. |
| `mijnrood_sync/.../application_sync_service.py` | `"Application promotion failed: {0}"` → `"Application promotion {0}"`, since the status already says "failed". |
| `mijnrood_sync/field_mapping.py` | Dropped `"contribution_per_period_in_cents": "dues_rate"`. The raw entry only ever won when the cents→euros conversion in `mapping_service` was skipped — i.e. when cents == 0 — turning MijnRood's "no custom amount" into a literal €0 dues rate. Reachable and observed: `apply_changed_member` → `related_records_orchestrator._create_related_records` → `_update_existing_dues_schedule` → `DuesScheduleRepository.update_schedule_rate`, whose gate is `if new_rate is not None` (`related_records_orchestrator.py:353-355`) and therefore admits 0. It writes the **Membership Dues Schedule** rate, which `Member.dues_rate` mirrors — *not* `member_import_service._set_dues_rate_fields`, which never writes `dues_rate` at all. Pre-fix dry-run printed `Rate updated from 9.0 to 0.0`; post-fix dry-run and the production apply both left it at 9.0. |
| `mijnrood_sync/.../member_sync_service.py` | New `_describe_member_id_change()`; an apply that renumbers the member now reports *"Member number changed from X to Y"*. |
| `patches/v2_2/clear_stale_membership_payment_history_links.py` (new) | Nulls `reference_doctype`/`reference_name` where `reference_doctype = 'Membership'` and the name resolves to no Membership. Leaves resolvable rows alone, so it is idempotent. Split into `clear_stale_links(parent=None)` + `execute()` so tests can scope to their own fixture; writes the discarded `(member, reference_name)` pairs to an Error Log first; calls `frappe.clear_cache()` for the console/test path that `migrate()` would otherwise cover. |

### Contract change

`create_or_update_member` now returns `"failed: <reason>"` instead of `"failed"`. All
four production callers branch on `status in ("created", "updated")` and
`csv_import_processor` buckets anything else via `else:`, so behaviour is unchanged;
only `test_mijnrood_csv_import.py`'s `assertEqual(result, "failed")` needed updating to
a prefix check.

## Tests

New/updated, all passing on `test_site_1`:

- `tests/backend/unit/utils/test_service_logger.py` — 8 tests: a logged ERROR lands in the
  site log file (via the shim and via `BaseService`), the service-name prefix survives the
  collapse to one logger name, `%`-args are not disturbed by the prefix, the logger has a
  handler, it is re-resolved per use, a logging failure warns but does not propagate, and a
  bare `logging.getLogger` still has no handler (pinning the premise of the whole fix).
  Logger names are fixed rather than hashed, and handlers/files are torn down in cleanup —
  hashed names leaked two files and two fds per test per run.
- `tests/patches/test_clear_stale_membership_payment_history_links.py` — 5 tests,
  including "the blocked Member becomes savable again", "a resolvable Membership reference
  is preserved" (the test that actually guards the `m.name IS NULL` condition — an
  assertion that NULL stays NULL cannot, since the UPDATE only ever writes NULL), a
  scoping guard, and idempotency asserting `(0, 0)` on the second run. Every test calls
  `clear_stale_links(parent=...)`, never the unscoped `execute()`, because `execute()`
  commits site-wide and was observed permanently repairing 17 unrelated rows on
  test_site_1.
- `services/csv_import/test_member_import_service.py` — the reason reaches the status
  string and a *specifically titled* Error Log row is written (a bare count would pass on
  any unrelated Error Log), plus three pure tests for `_failure_status` truncation,
  newline collapsing, and the empty-message case.
- `mijnrood_sync/test_field_mapping_and_utils.py` — asserts
  `"contribution_per_period_in_cents"` is absent from the field map, so re-adding it
  cannot silently reintroduce the shadowing.
- `tests/services/event_application/test_mapping_service.py` — 0 cents leaves
  `dues_rate` unset.
- `tests/services/event_application/test_member_sync_service.py` — the renumber notice.

Regression suites run green: `test_mijnrood_csv_import` (48), all six
`event_application` suites (140), `test_dispatcher` (25), the four `mijnrood_sync`
client/sftp/ssh/tasks suites (122), `test_service_infrastructure` (11), and a
service-layer sample (`termination_execution`, `polling`, `application_approval_correlator`,
`mollie_sync`, `member_lookup`, `member_import`).

## Applied on veg11 — 2026-07-26

Done, not pending. Backup `20260726_162159` (957 MiB) taken first, then a full
`bench migrate` (96 pending patches — 95 of them accumulated upstream ERPNext/HRMS ones,
run deliberately at Foppe's instruction) completed with exit 0 and no tracebacks. The
patch reported:

```
Cleared 430 unresolvable Membership link(s) from Member Payment History across 430 member(s)
```

`MR-SYNC-2026-00087` was then re-applied at 16:29:47. Verified after the fact:

| | value |
|---|---|
| event | `status = Applied`, `applied_at` set, `error_message` NULL |
| address | Oudlaan 65 / 3515 GA / Utrecht |
| `Member.dues_rate` | 9.0 (**not** zeroed) |
| dues schedule | 9.0, Active, Quarterly |
| `member_id` | 20, renumber reported in the applied message |
| stale rows site-wide | 0 |
| `Patch Log` entry | present |

Also cleaned up: the four failing fixture sync events `MR-SYNC-2026-00001..00004` were
deleted (each re-verified against five fixture guards first). See "Test-fixture events"
below — 80 more remain by explicit decision.

## Test-fixture events on veg11

84 events matched all three fixture markers simultaneously — `sync_run_id =
'test-run-001'`, `change_summary = 'Test approved event'`, and `@example.com` in
`old_data`/`new_data`. All `event_type = Approved`, created 2026-04-18 23:23 →
2026-05-15 09:37. None has `linked_member` set, no real Member references them in
`review_notes`, no `@example.com` Members remain, and the row-id ranges are cleanly
disjoint from real data (fixtures 880,001–24,632,554 vs real 1–69).

**The consequence:** 160 events − 84 fixtures = 76 real, broken down as 69 Pending
`admin_member` + 5 Pending `admin_division` + `00087` + `00088`. So **all 80 events
marked `Applied` were fixtures — no real MijnRood event had ever been successfully
applied on veg11** before `00087` above. Do not read the "Applied" count as evidence the
sync works.

Only the 4 failing fixtures (`00001..00004`) were deleted, by explicit decision; the 80
`Applied` ones remain and continue to inflate that count. A JSON export of all 84 was
taken before deleting, but it lives in a session scratchpad — move it somewhere durable
if those 80 are ever to be removed.

## Open items (not addressed)

1. **`MR-SYNC-2026-00088`** fails with `"No linked member found for MijnRood ID 12"` —
   a real event for MijnRood row 12 (`foppe@communisme.nu`, "Foppe de Haan", registered
   2020-04-23). All three resolution strategies miss: `linked_member` unset, no Member
   with `member_id = 12`, no Member with that email; there is also no `MijnRood Sync
   State` row for the id. Nearest local candidate is `Assoc-Member-2026-01-32851`
   ("Foppe Haan", `member_id` 1026, `fjdh@leden.socialisten.org`) — same
   member_id-namespace mismatch as `00087`, but fatal here because there is no
   `linked_member` fallback. Needs a data decision: set `linked_member` and re-apply, or
   import as new. The dues change it carries (0 → 2300 cents) is unaffected by the
   field-map fix, since 2300 converts identically either way.
2. **The `member_id` renumber is only reported at apply time.** Surfacing it at *review*
   time would need the detector to compare MijnRood's row id against
   `linked_member.member_id`; it cannot come from `changed_fields`, because MijnRood's own
   row id does not change (per Foppe: MijnRood renumbers applicant → member series on
   approval, so the change itself is expected).
3. **A Changed event applies every mapped field, not just `changed_fields`.** The dues-rate
   bug was one symptom. Anything else that drifts between MijnRood and Verenigingen will
   be silently overwritten by an event whose summary mentions unrelated fields.

## Address-change design decision (open question, no code written)

Whether an address change should edit the existing `Address` or create a new one and
retire the old. Facts gathered on veg11:

- **`Address.track_changes = 0`, and there are 0 `Version` rows for `Address`.** So
  "edit in place and keep the old data in the activity log" is not what happens today —
  the old address is simply lost. `address_import_service._find_existing_address` returns
  `member.primary_address` unconditionally and overwrites its fields.
- **8 Addresses are linked to more than one Member.** In-place editing silently
  relocates the housemate as well.
- Member already has `iban_history`, `fee_change_history`, `membership_type_history`,
  `chapter_membership_history` — the established pattern for tracked fields.
- Address fan-out: 3,175 `Customer` links and 799 `Member` links across 3,294 Addresses,
  which is the basis for Foppe's objection to create-and-retire (conditional re-linking
  logic for Member/Customer/Donor).

Recommendation: keep single-record edit (avoids the re-linking tax), and add history
separately — set `track_changes = 1` on Address, add a member-scoped `address_history`
child table written by one canonical service, and split the Address instead of editing
it in place when it is linked to another Member.
