"""Re-apply MijnRood folder mapping + extracted date to existing
Organization Documents.

Same backend serves both the single-doc form button and the list-view
bulk action. Dry-run produces a diff structure; apply mode writes via
db.set_value (bypassing OrganizationDocument.validate's board-membership
check, which would fail for sweeps across multiple chapters — entry is
already gated to admin roles via frappe.only_for).
"""

import json
import logging

import frappe
from frappe import _

logger = logging.getLogger("verenigingen.mijnrood_sync.document_reclassify")

MAX_BATCH = 500
ADMIN_ROLES = ["System Manager", "Verenigingen Administrator"]
DIFF_FIELDS = (
    "organization_type",
    "chapter",
    "team",
    "movement",
    "document_type",
    "applies_on",
    "applies_on_precision",
)


def _fetch_folder_tree() -> dict[int, dict]:
    """Fetch all MijnRood folders, return {folder_id: folder_dict}.

    Used to walk parent chains when a doc's source_folder_id points to a
    folder not directly in the mapping table (e.g., year subfolders that
    fetch_and_populate_folders deliberately skips).

    Mocked in tests.
    """
    from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient

    settings = frappe.get_single("MijnRood Sync Settings")
    client = MijnRoodDatabaseClient(settings=settings)
    with client:
        folders = client.fetch_document_folders()
    return {f["id"]: f for f in folders}


def _resolve_mapped_folder(folder_id, mapping_by_id, folder_tree):
    """Walk parent chain to find the nearest ancestor folder that has a mapping.

    Returns the mapping row, or None if no ancestor is mapped.

    Args:
        folder_id: starting folder id
        mapping_by_id: {mijnrood_folder_id: mapping_row}
        folder_tree: {folder_id: folder_dict} from MijnRood

    Mirrors DocumentImportService._resolve_mapped_folder. Standalone (not a
    method) so callers don't need a service instance and so it's trivially
    testable in isolation.
    """
    if folder_id in mapping_by_id:
        return mapping_by_id[folder_id]

    seen: set[int] = set()
    current = folder_id
    while current is not None and current not in seen:
        seen.add(current)
        if current in mapping_by_id:
            return mapping_by_id[current]
        folder = folder_tree.get(current)
        if folder is None:
            break
        current = folder.get("parent_id")

    return None


@frappe.whitelist()
def reclassify_documents(names, dry_run: bool = True) -> dict:
    """Re-apply MijnRood folder mapping + extracted date to existing docs.

    Args:
        names: List of Organization Document names (or JSON-encoded string).
        dry_run: If True, return preview only; no writes.

    Returns:
        {
          "dry_run": bool,
          "total": int,
          "applied": int,           # 0 in dry_run
          "changes": [...],         # per-doc diff
          "skipped": [...],         # per-doc skip reasons
        }
    """
    frappe.only_for(ADMIN_ROLES)

    # JSON-decode if called via HTTP (Frappe passes lists as JSON strings)
    if isinstance(names, str):
        names = json.loads(names)
    if not isinstance(names, list):
        frappe.throw(_("`names` must be a list of Organization Document names"))

    # Coerce dry_run when called via HTTP (it arrives as str "true"/"false")
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() == "true"

    if len(names) > MAX_BATCH:
        frappe.throw(
            _("Too many documents in one call ({0} > {1}); split into smaller batches.").format(
                len(names), MAX_BATCH
            )
        )

    settings = frappe.get_single("MijnRood Sync Settings")
    mapping_by_id = {row.mijnrood_folder_id: row for row in (settings.document_folder_mapping or [])}

    # Lazy folder-tree fetch — only triggered if a doc needs parent walking.
    # Single-element list so the inner closure can mutate it.
    _folder_tree_cache: list[dict[int, dict] | None] = [None]

    def get_folder_tree():
        if _folder_tree_cache[0] is None:
            try:
                _folder_tree_cache[0] = _fetch_folder_tree()
            except Exception as e:
                logger.warning(
                    "reclassify_documents: failed to fetch folder tree (%s); parent walking disabled", e
                )
                _folder_tree_cache[0] = {}
        return _folder_tree_cache[0]

    changes: list[dict] = []
    skipped: list[dict] = []
    applied = 0

    for name in names:
        try:
            doc = frappe.get_doc("Organization Document", name)
        except frappe.DoesNotExistError:
            skipped.append({"name": name, "reason": "document not found"})
            continue

        result = _process_doc(doc, mapping_by_id, get_folder_tree, dry_run)
        if result["status"] == "changed":
            changes.append(result["change"])
            if not dry_run:
                applied += 1
        else:
            skipped.append({"name": name, "reason": result["reason"]})

    logger.info(
        "reclassify_documents: total=%d applied=%d skipped=%d dry_run=%s",
        len(names),
        applied,
        len(skipped),
        dry_run,
    )
    return {
        "dry_run": dry_run,
        "total": len(names),
        "applied": applied,
        "changes": changes,
        "skipped": skipped,
    }


def _process_doc(doc, mapping_by_id: dict, get_folder_tree, dry_run: bool) -> dict:
    """Resolve mapping → compute diff → optionally write. Returns a status dict.

    `get_folder_tree` is a zero-arg callable that returns the folder tree
    dict from MijnRood, fetched lazily only if parent walking is required.
    """
    from verenigingen.utils.date_extraction import extract_date_with_precision

    if not doc.source_folder_id:
        return {"status": "skipped", "reason": "no source_folder_id (run backfill first)"}

    # Direct hit on the mapping table is the common case — try that first
    # to avoid any MijnRood DB round-trip.
    mapping_row = mapping_by_id.get(doc.source_folder_id)
    if mapping_row is None:
        # Fall back to parent-chain walk (e.g. for year-subfolder docs)
        folder_tree = get_folder_tree()
        mapping_row = _resolve_mapped_folder(doc.source_folder_id, mapping_by_id, folder_tree)

    if mapping_row is None:
        return {"status": "skipped", "reason": "no folder mapping"}

    org_type = mapping_row.organization_type or doc.organization_type

    # Defensive: if the mapping row sets organization_type but leaves the
    # corresponding chapter/team/movement blank, skip rather than clear
    # the doc's existing link field with None. Mirrors document_import_service.
    org_link_value = (
        mapping_row.chapter
        if org_type == "Chapter"
        else mapping_row.team
        if org_type == "Team"
        else mapping_row.movement
        if org_type == "Movement"
        else None
    )
    if not org_link_value:
        return {
            "status": "skipped",
            "reason": f"mapping has organization_type={org_type!r} but no entity set",
        }

    proposed = {
        "organization_type": org_type,
        "chapter": mapping_row.chapter if org_type == "Chapter" else None,
        "team": mapping_row.team if org_type == "Team" else None,
        "movement": mapping_row.movement if org_type == "Movement" else None,
        "document_type": mapping_row.document_type or doc.document_type,
    }

    # Date cascade: filename → folder_path (from mapping row)
    applies_on, precision = extract_date_with_precision(doc.document_name or "")
    if applies_on is None:
        applies_on, precision = extract_date_with_precision(mapping_row.folder_path or "")

    proposed["applies_on"] = applies_on.strftime("%Y-%m-%d") if applies_on else None
    proposed["applies_on_precision"] = precision if applies_on else (doc.applies_on_precision or "Day")

    current = {f: doc.get(f) for f in DIFF_FIELDS}
    # Normalise current applies_on to ISO string for comparison
    if current["applies_on"] is not None:
        current["applies_on"] = frappe.utils.formatdate(current["applies_on"], "yyyy-MM-dd")

    diff_fields = [f for f in DIFF_FIELDS if (current.get(f) or None) != (proposed.get(f) or None)]
    if not diff_fields:
        return {"status": "skipped", "reason": "unchanged"}

    write_errors: list[str] = []
    if not dry_run:
        for f in diff_fields:
            try:
                frappe.db.set_value(
                    "Organization Document",
                    doc.name,
                    f,
                    proposed[f],
                    update_modified=False,
                )
            except Exception as e:
                write_errors.append(f"{f}: {e}")
                logger.warning(
                    "reclassify_documents: failed to set %s on %s — %s",
                    f,
                    doc.name,
                    e,
                )
        frappe.db.commit()

    change = {
        "name": doc.name,
        "current": current,
        "proposed": proposed,
        "diff_fields": diff_fields,
    }
    if write_errors:
        change["write_errors"] = write_errors

    return {"status": "changed", "change": change}
