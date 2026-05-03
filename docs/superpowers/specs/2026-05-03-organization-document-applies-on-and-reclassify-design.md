# Organization Document — `applies_on` field + MijnRood reclassify action

**Date:** 2026-05-03
**Status:** Design — pending implementation plan
**Owner:** foppe@veganisme.org

## Problem

`Organization Document` records the date a file was uploaded (`upload_date`,
defaulted to today), but most documents are uploaded long after the date they
actually cover (e.g. minutes from May 2024 uploaded in 2026). There is no
field for the document's own date, and the file path / filename is currently
the only place that information lives.

The MijnRood document import (`document_import_service.py`) silently papers
over this by writing the **extracted** date into `upload_date`, which means
that field's meaning depends on the source: for hand-uploaded docs it's the
record creation date, for imported docs it's the document's content date.
Reports grouping by `upload_date` cannot be trusted.

Separately, the MijnRood Sync Settings folder mapping is the source of truth
for `(folder → organization, document_type)`, but once a document is imported
there is no way to reapply the mapping when the admin later corrects a row
(e.g. discovers that a folder really belongs to chapter X, not the national
default).

## Goals

1. Add an "applies-to date" field to `Organization Document`, separate from
   `upload_date`, with explicit precision (Day / Month / Year) since most
   document dates are only month-precise.
2. Provide an admin action to reclassify existing MijnRood-imported documents
   against the current folder mapping, including (re)filling the new
   applies-on date by parsing filename + folder path.
3. Stop the `upload_date` overload: future imports write extracted dates to
   the new field, and `upload_date` reverts to "when this record was created".
4. One-shot, idempotent backfill so existing documents become addressable
   by the reclassify action.

## Non-goals

- Reorganising or moving files on disk (the existing hierarchical storage
  path is left alone — only doctype fields change). This also avoids
  aggravating known path-length issues with deep MijnRood paths.
- Reclassifying documents that were uploaded directly via the UI and have
  no MijnRood folder origin. They are skipped with a clear reason.
- Backfilling `applies_on` from arbitrary text on hand-uploaded docs.
- Schema-level constraints on the precision/date relationship beyond what
  the JS form snap-to-1 logic and `validate()` mirror enforce.

## Scope

In-scope DocTypes / files:
- `verenigingen/verenigingen/doctype/organization_document/` — JSON, JS, PY.
- `verenigingen/mijnrood_sync/services/document_import_service.py` — change
  what gets written for new imports.
- `verenigingen/mijnrood_sync/services/document_reclassify_service.py` (new).
- `verenigingen/mijnrood_sync/services/source_folder_backfill.py` (new).
- `verenigingen/utils/date_extraction.py` — add a new helper.
- New patch in `verenigingen/patches/` to clean `upload_date` on existing rows.
- New JS list-view file `organization_document_list.js`.
- New tests under the existing test directory layout.

## Design

### 1. Schema changes — `Organization Document`

Three new fields, added in a new section after the existing `metadata_section`:

| fieldname              | fieldtype     | label              | flags                                    |
|------------------------|---------------|--------------------|------------------------------------------|
| `applies_section`      | Section Break | "Document Date"    |                                          |
| `applies_on`           | Date          | "Applies On"       | `in_list_view`, `in_standard_filter`     |
| `applies_on_precision` | Select        | "Precision"        | options `Day\nMonth\nYear`, default `Day`|
| `column_break_applies` | Column Break  |                    |                                          |
| `source_folder_id`     | Int           | "MijnRood Folder ID" | `read_only`, `hidden`, `search_index`  |

Conventions:

- `applies_on` is a real `Date` for sortability, range filters, and report
  grouping.
- When precision is `Month`, the day part is stored as `1` and displayed as
  e.g. "May 2024". When `Year`, both month and day are `1` ("2024").
- Precision defaults to `Day` so manual entry behaves naturally; the import
  and reclassify actions set it from what was actually matched.
- `source_folder_id` is `Int` (not `Link`) because MijnRood folder ids are
  external — they live in MijnRood's database, not as a Frappe doctype.
  This matches `MijnRood Document Folder Mapping.mijnrood_folder_id`.
- `upload_date` keeps its existing default (`Today`, read-only) and reverts
  to its honest meaning. No schema change needed there.

### 2. Precision UI: snap-to-1 (option B)

Both client-side (immediate UX) and server-side (REST API protection):

**JS** (`organization_document.js`):
- `applies_on_precision` `onchange`:
  - `Month` → set `applies_on` day to `1`.
  - `Year`  → set `applies_on` to `YYYY-01-01`.
  - `Day`   → no change.
- `applies_on` `onchange`: if the user picks a non-1 day, set precision to
  `Day`. If the user picks day 1 with month != 1, leave precision alone
  (it might genuinely be the 1st).

**Server** (`organization_document.py.validate`): mirror the snap rules so a
REST/API client can't bypass JS:
- If `applies_on_precision == "Month"` and `applies_on.day != 1`, snap to 1.
- If `applies_on_precision == "Year"` and `(applies_on.month, applies_on.day) != (1, 1)`, snap to `(1, 1)`.

This is the only validation; we don't reject — we normalise. The "business
logic is server-side" rule from `CLAUDE.md` motivates this mirror.

### 3. Date extraction enhancement

`verenigingen/utils/date_extraction.py` gains:

```python
def extract_date_with_precision(text: str) -> tuple[date | None, str]:
    """
    Returns (date, precision_label).

    precision_label is one of "Day", "Month", "Year".
      - "Day"   for full date matches (YYYYMMDD, YYYY-MM-DD, DD-MM-YYYY,
                "DD month YYYY", etc.).
      - "Month" for year-month matches (e.g. "2024-05", "mei 2024" — patterns
                added as part of this change).
      - "Year"  for bare year matches (the existing 20\d{2} fallback).

    Returns (None, "Day") if nothing matched. The "Day" default for the
    no-match case is irrelevant since callers check the date for None first.
    """
```

Existing `extract_date_from_text()` and `extract_year_from_text()` keep their
signatures; they may be re-implemented as thin wrappers over the new helper
or kept independent — implementation detail. No changes to their behaviour
or call sites.

New patterns the helper recognises (in addition to existing ones):
- `YYYY-MM` and `MM-YYYY` (with `-`, `/`, `.`, or space separators).
- Dutch `<month> YYYY` (e.g. "mei 2024", "Mei 2024").

### 4. Reclassify action — backend

New file: `verenigingen/mijnrood_sync/services/document_reclassify_service.py`.

```python
@frappe.whitelist()
def reclassify_documents(names: list[str] | str, dry_run: bool = True) -> dict:
    """
    Re-apply MijnRood folder mapping + extracted date to existing
    Organization Documents. Returns a diff structure for dry-run, or
    applies the diff and returns a summary.
    """
```

The function:
1. Calls `frappe.only_for(["System Manager", "Verenigingen Administrator"])`
   *inside the function body* (not as a decorator) because per MEMORY.md
   `@frappe.whitelist()` must be the outermost decorator and security
   wrappers below it can break whitelist registration.
2. Decodes `names` if it arrives as JSON.
3. Caps `len(names)` at 500. Returns a clear error if exceeded; the JS bulk
   action chunks accordingly.
4. For each name, runs the per-doc algorithm below.
5. In apply mode, writes via `frappe.db.set_value(..., update_modified=False)`
   per field and commits per doc — same pattern as `document_import_service`,
   which avoids triggering `_validate_upload_permission` on docs the calling
   admin isn't a board member of. (The admin check above already gated entry.)

**Per-doc algorithm:**

1. Load the doc. If `source_folder_id` is empty → record skip with reason
   `"no source_folder_id (run backfill first)"`.
2. Resolve the folder mapping:
   - Direct match in `MijnRood Sync Settings.document_folder_mapping` by
     `mijnrood_folder_id == source_folder_id`.
   - Fallback: walk the parent chain via the folder tree (re-uses the
     `_resolve_mapped_folder` logic from `document_import_service.py`,
     extracted into a shared helper).
   - If still no mapping → skip with reason `"no folder mapping"`.
3. Compute `proposed`:
   - `organization_type`, `chapter`/`team`/`movement`, `document_type` ←
     from the resolved mapping row.
   - `applies_on` + `applies_on_precision` ← cascade:
     1. `extract_date_with_precision(document_name)`.
     2. If still no date, `extract_date_with_precision(folder_path)` —
        where `folder_path` comes from the `folder_path` column on the
        resolved mapping row (already cached there by
        `fetch_and_populate_folders`). No MijnRood DB access needed at
        reclassify time.
4. Diff `proposed` against current values for the fields above. If empty
   diff → skip with reason `"unchanged"`.
5. In `dry_run` mode, append the diff to `changes`. In apply mode, write
   each changed field via `db.set_value(..., update_modified=False)`,
   commit per doc, append the diff to `changes`.

**Return shape:**

```python
{
    "dry_run": bool,
    "total": int,                 # docs considered
    "applied": int,               # docs actually written (0 in dry_run)
    "changes": [
        {
            "name": "DOC-CHAPTER-0001",
            "current": {"document_type": "Other", "chapter": "Den Haag",
                        "applies_on": None, "applies_on_precision": "Day"},
            "proposed": {"document_type": "Notulen", "chapter": "Den Haag",
                         "applies_on": "2024-05-01", "applies_on_precision": "Month"},
            "diff_fields": ["document_type", "applies_on", "applies_on_precision"],
        },
        ...
    ],
    "skipped": [
        {"name": "DOC-CHAPTER-0042", "reason": "no source_folder_id"},
        ...
    ],
}
```

**Why `db_set` and not `doc.save()`:** `OrganizationDocument.validate()`
calls `_validate_upload_permission()`, which checks board membership for the
calling user. A System Manager running a sweep across multiple chapters'
docs would fail repeatedly if `save()` were used. `db_set` matches the
existing import service pattern (`flags.ignore_permissions = True` there).

### 5. Reclassify action — JS

**`organization_document.js` (extended):**

- `applies_on_precision` and `applies_on` `onchange` handlers — see
  Section 2.
- `refresh` handler: if `frm.doc.source_folder_id` is set, add an
  `__("Reclassify from MijnRood folder")` button under the `__("Actions")`
  group. On click: call `reclassify_documents` with `names=[frm.doc.name]`
  and `dry_run=true`, render the diff in a `frappe.confirm` dialog, on
  confirm call again with `dry_run=false`, then `frm.reload_doc()`.

**`organization_document_list.js` (new):**

```javascript
frappe.listview_settings['Organization Document'] = {
    onload(listview) {
        listview.page.add_action_item(__('Reclassify from MijnRood folder'), () => {
            const items = listview.get_checked_items();
            if (!items.length) {
                frappe.msgprint(__('Select at least one document.'));
                return;
            }
            // Same dry-run → confirm → apply flow as the form button.
        });
    },
};
```

The dry-run dialog is a single shared helper (e.g. attached to
`frappe.verenigingen.organization_document.show_reclassify_preview`) used
by both call sites — renders a small table `name | field | current → proposed`
with a footer counting changes / unchanged / skipped.

### 6. Import-side change — `_import_single_document`

In `verenigingen/mijnrood_sync/services/document_import_service.py`,
`_import_single_document`:

- **Drop** `"upload_date": upload_date.strftime("%Y-%m-%d") if upload_date else None`
  from the `frappe.get_doc({...})` payload, so the field's `default: "Today"`
  takes effect (i.e. record-creation time).
- **Add** `"applies_on"` and `"applies_on_precision"` populated from the
  new `extract_date_with_precision(...)` cascade (filename → folder path).
- **Add** `"source_folder_id": doc.get("folder_id")`, so brand-new imports
  are immediately reclassify-addressable.

The MijnRood `date_uploaded` value (when present) keeps being used for
`applies_on` when no other source produces a date — it is itself an
upload-time value in MijnRood, but it's the closest thing to "when this
document was created" we have for that source. Precision in that case is
`Day`.

### 7. Backfill command

New file: `verenigingen/mijnrood_sync/services/source_folder_backfill.py`.

```python
def backfill_source_folder_ids(dry_run: bool = False, batch_size: int = 200) -> dict:
    """
    Populate source_folder_id on existing Organization Documents by matching
    file_hash against MijnRood's document table. Idempotent.

    Run via:
      bench --site veg11.veganisme.org execute \\
        verenigingen.mijnrood_sync.services.source_folder_backfill.backfill_source_folder_ids \\
        --kwargs '{"dry_run": true}'
    """
```

Algorithm:
1. Connect to MijnRood DB via `MijnRoodDatabaseClient`.
2. Fetch all MijnRood documents in one query, build a `{file_hash: folder_id}`
   map. **Implementation note:** if MijnRood does not store SHA256s, we must
   compute them per file via SFTP — same hashing logic as
   `_import_single_document`. This is determined during implementation by
   inspecting the MijnRood schema; if SFTP hashing is required, the command
   batches and publishes progress via `frappe.publish_realtime` (same pattern
   as `import_all`).
3. For each Organization Document where `source_folder_id IS NULL`, look up
   by `file_hash`. On match, `db.set_value("Organization Document", name,
   "source_folder_id", folder_id, update_modified=False)`. Commit per batch.
4. Return `{"matched": int, "no_hash_match": int, "already_set": int, "errors": list}`.

Idempotent because rows already with `source_folder_id` set are skipped.

### 8. Cleanup patch — `upload_date` for legacy imports

New file: `verenigingen/patches/v1_0/clean_overloaded_upload_date.py`,
registered in `patches.txt`.

```python
def execute():
    """
    Old MijnRood imports wrote the document's content date into upload_date.
    For each affected row, copy upload_date → applies_on (if applies_on is
    empty), set applies_on_precision = "Day", and reset upload_date to the
    record's creation date. Idempotent: only touches rows where the original
    discrepancy still exists (upload_date != date(creation) AND applies_on is empty).
    """
```

Conditions:
- Only update rows where `applies_on IS NULL` (don't overwrite an explicit value).
- Only update rows where `DATE(upload_date) != DATE(creation)` (skip rows
  where upload_date already equals creation, i.e. correct).
- Use `frappe.db.sql(..., values=[...])` parameterised — no string formatting.
- Patch is bench-execute-driven via `bench migrate`, runs once per site.

### 9. Permissions

| Action                                           | Allowed roles                                    | Mechanism |
|--------------------------------------------------|--------------------------------------------------|-----------|
| `reclassify_documents` whitelisted method        | System Manager, Verenigingen Administrator       | `frappe.only_for(...)` inside the function body |
| `backfill_source_folder_ids`                     | bench execute only — no HTTP surface             | not whitelisted |
| List-view "Reclassify" action visibility         | same two roles                                   | JS visibility check (cosmetic; server-side enforces) |
| Form-button "Reclassify" visibility              | same two roles                                   | JS visibility check (cosmetic; server-side enforces) |
| Editing `applies_on` / `applies_on_precision` directly on a doc | unchanged from existing Organization Document permissions | DocType perms |

The existing `_validate_upload_permission` (chapter board membership etc.)
still gates manual create/edit; reclassify bypasses it via `db.set_value`,
but only after the `only_for` admin check passes.

### 10. Migration / rollout order

This sequence matters because some steps assume earlier ones:

1. Add the new fields to `organization_document.json` + reload doctype + bench migrate.
2. Add `extract_date_with_precision()` to `date_extraction.py`. Existing
   callers unchanged; no behavioural drift.
3. Run the cleanup patch (Section 8) via `bench migrate` so legacy
   `upload_date` values are healed and `applies_on` is populated for
   pre-feature rows.
4. Run `backfill_source_folder_ids` once (operator-driven). Re-run safely
   if needed.
5. Deploy the import-side change (Section 6) so future imports write
   `applies_on` + `source_folder_id` and stop overloading `upload_date`.
6. Deploy the reclassify service + JS button + list-view action.
7. Operator can now sweep any chapter's docs against the current folder mapping.

Steps 1–3 can be one deploy; 4 is operator-driven; 5–6 can be a second
deploy (or combined with 1–3 if backfill is run on the same release window).
The order avoids any window where the import writes to a field that doesn't
yet exist, or the reclassify action runs against unbackfilled rows.

### 11. Testing

Three integration test files (real DB, no business-logic mocks per
`test-quality-enforcer`):

**`test_organization_document_applies_on.py`** — schema + precision normalisation:
- Set precision Month → applies_on day snaps to 1 (server-side validate).
- Set precision Year → snaps to month=1, day=1 (server-side validate).
- New row defaults: precision = Day, applies_on = None.
- Field is in_list_view + in_standard_filter (sanity check).

**`test_document_reclassify_service.py`** — backend:
- Doc with mapped `source_folder_id` and stale `document_type` →
  dry-run returns proposed diff, apply mode writes it, re-running dry-run
  reports `unchanged`.
- Doc whose `source_folder_id` points to a year-only subfolder not in the
  mapping table → walks parent chain to mapped ancestor.
- Doc without `source_folder_id` → skipped with reason
  `"no source_folder_id"`; no writes.
- Doc whose folder has no mapping anywhere up the chain → skipped with
  reason `"no folder mapping"`.
- Date cascade: filename has date → uses filename; no filename date but
  folder path has date → uses folder path; precision matches the matched
  pattern.
- Permission: a non-admin role test user gets `frappe.PermissionError`
  (per the MEMORY.md `tests_run_as_admin` feedback — must run-as the
  target role, not Admin).
- Cap at 500: passing 501 names returns an error; passing 500 succeeds.

**`test_source_folder_backfill.py`** — backfill:
- Matches by file_hash, idempotent on re-run.
- Dry-run doesn't write.
- Rows with `source_folder_id` already set are skipped without a MijnRood
  query for them.

Test factory: use `CoreTestDataFactory` (per MEMORY.md test-factory
consolidation) to build Organization Document rows with known file hashes.

## Risks & open implementation questions

- **Does MijnRood store SHA256 of files?** Determines whether the backfill
  command can do a single SQL fetch or must SFTP-and-hash per file. The
  command's progress-publishing path covers either; only the runtime cost
  changes.
- **Path-length issues on file storage** (called out by user during
  brainstorming) are pre-existing and out of this design's scope.
  Reclassify never moves files, so it can't worsen them.
- **Year-only folders not in the mapping table** are already handled by the
  import service via parent walking; the reclassify service shares that
  helper (extracted out as part of this work) so the behaviour is identical.
- **`folder_path` on the mapping row may go stale** if the MijnRood folder
  is renamed and `fetch_and_populate_folders` hasn't been re-run. The
  reclassify date cascade trusts whatever path is currently in the mapping
  row — running fetch-folders before a reclassify sweep is the operator's
  responsibility (and matches existing import-side ergonomics).
- **Race with concurrent edits**: if a user is editing a doc at the moment
  of reclassify, the per-field `db.set_value` writes may interleave. This
  matches the import service's concurrency model and is acceptable for an
  admin-run sweep — collisions show up in `track_changes` history.
