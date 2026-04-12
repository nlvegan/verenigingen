"""
One-time document import from MijnRood's document organizer.

Fetches files via SFTP, creates Organization Document records with
deduplication via SHA256 file hashes. Not part of the regular
checksum-based polling pipeline.
"""

import hashlib
import logging
import re
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import now_datetime

logger = logging.getLogger("verenigingen.mijnrood_sync.document_import")


class DocumentImportService:
    """Orchestrates one-time document import from MijnRood.

    Workflow:
    1. Load folder mapping from MijnRood Sync Settings child table
    2. Connect to MijnRood DB, fetch folder tree + document list
    3. Build folder_id -> root_folder_id lookup
    4. Connect SFTP, download each file
    5. Dedup via SHA256 hash against existing Organization Documents
    6. Save file to hierarchical storage, create Organization Document record
    """

    def __init__(self, settings=None):
        if settings is None:
            settings = frappe.get_single("MijnRood Sync Settings")
        self.settings = settings
        self.folder_mapping: dict[int, dict] = {}  # mijnrood_folder_id -> mapping row data
        self.folder_tree: dict[int, dict] = {}  # folder_id -> folder dict
        self.root_cache: dict[int, int | None] = {}  # folder_id -> root_folder_id

    def fetch_and_populate_folders(self) -> dict:
        """Fetch document folders from MijnRood and populate the mapping table.

        Shows ALL folders (root + children) so subfolders under container
        folders like "Afdelingen" or "Landelijk" can be individually mapped
        to specific chapters/teams. Year-only subfolders (names matching
        20xx) are excluded since they just group files by date.

        Returns:
            Summary dict with success, message, counts.
        """
        from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient

        client = MijnRoodDatabaseClient(settings=self.settings)
        try:
            with client:
                folders = client.fetch_document_folders()
        except Exception as e:
            error_msg = str(e)[:500]
            frappe.log_error(frappe.get_traceback(), "MijnRood Fetch Document Folders Failed")
            return {"success": False, "message": _("Connection failed: {0}").format(error_msg)}

        if not folders:
            return {"success": False, "message": _("No document folders found in MijnRood")}

        # Build tree for path computation
        tree = {f["id"]: f for f in folders}

        # Build existing mapping lookup
        existing = {}
        for row in self.settings.document_folder_mapping or []:
            existing[row.mijnrood_folder_id] = row

        created = 0
        updated = 0
        skipped_years = 0
        for folder in folders:
            fid = folder["id"]
            name = folder.get("name", "")

            # Skip year-only subfolders (e.g. "2023", "2024") — these just
            # group files by date. The parent folder's mapping applies.
            if re.match(r"^20\d{2}$", name):
                skipped_years += 1
                continue

            folder_path = self._compute_folder_path(fid, tree)

            if fid in existing:
                row = existing[fid]
                row.folder_name = name
                row.folder_path = folder_path
                updated += 1
            else:
                # Pre-fill with national chapter as default — most MijnRood
                # folders are org-wide. Admin adjusts the exceptions.
                defaults = self._get_default_mapping()
                self.settings.append(
                    "document_folder_mapping",
                    {
                        "mijnrood_folder_id": fid,
                        "folder_name": name,
                        "folder_path": folder_path,
                        **defaults,
                    },
                )
                created += 1

        self.settings.save()

        message = _("Fetched {0} folders ({1} new, {2} updated, {3} year-folders skipped)").format(
            created + updated, created, updated, skipped_years
        )
        return {"success": True, "message": message}

    def auto_classify_folder_mappings(self) -> dict:
        """Auto-classify document_type and chapter on folder mapping rows.

        Only fills in rows where document_type is blank (preserves manual edits).
        Uses folder path keywords to infer document_type from Board Document
        Categories, and matches chapter names against folder path segments.

        Subfolders that would inherit the same classification as their parent
        are left blank — the import's _resolve_mapped_folder() handles inheritance.

        Returns:
            Summary dict with success, message, counts.
        """
        rows = self.settings.document_folder_mapping or []
        if not rows:
            return {"success": False, "message": _("No folder mappings found. Fetch folders first.")}

        keyword_map = self._load_category_keywords()
        chapter_names = self._load_chapter_names()
        national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")

        # Build parent lookup from folder paths
        row_by_id = {row.mijnrood_folder_id: row for row in rows}
        parent_map = self._build_parent_map(rows)

        # Pre-compute inferred values for all rows so parent lookups are consistent
        inferred: dict[int, tuple[str, str | None]] = {}
        for row in rows:
            path = (row.folder_path or row.folder_name or "").lower()
            inferred[row.mijnrood_folder_id] = (
                self._infer_document_type(path, keyword_map),
                self._infer_chapter(path, chapter_names, national_chapter),
            )

        # Track which rows were already manually configured before this run
        manually_set = {row.mijnrood_folder_id for row in rows if row.document_type}

        classified = 0
        skipped_inherited = 0
        skipped_already_set = 0

        # Sort by path depth so parents are processed before children
        sorted_rows = sorted(rows, key=lambda r: (r.folder_path or "").count("/"))

        for row in sorted_rows:
            if row.mijnrood_folder_id in manually_set:
                skipped_already_set += 1
                continue

            inferred_type, inferred_chapter = inferred[row.mijnrood_folder_id]

            # Check if parent has the same classification — if so, leave blank (inherit)
            parent_id = parent_map.get(row.mijnrood_folder_id)
            if parent_id and parent_id in row_by_id:
                parent_row = row_by_id[parent_id]
                # Use parent's actual values if manually set, otherwise inferred
                if parent_id in manually_set:
                    parent_type = parent_row.document_type
                    parent_chapter = parent_row.chapter
                else:
                    parent_type = parent_row.document_type or inferred[parent_id][0]
                    parent_chapter = inferred[parent_id][1]

                if inferred_type == parent_type and inferred_chapter == parent_chapter:
                    skipped_inherited += 1
                    continue

            row.organization_type = "Chapter"
            row.chapter = inferred_chapter or national_chapter
            row.document_type = inferred_type
            classified += 1

        self.settings.save()

        message = _(
            "Auto-classified {0} folders ({1} left blank for inheritance, {2} already configured)"
        ).format(classified, skipped_inherited, skipped_already_set)
        return {"success": True, "message": message}

    def _build_parent_map(self, rows: list) -> dict[int, int | None]:
        """Build folder_id -> parent_folder_id map from folder paths.

        Walks the path segments to find the parent row. A folder with path
        "A / B / C" has parent path "A / B".
        """
        path_to_id: dict[str, int] = {}
        for row in rows:
            if row.folder_path:
                path_to_id[row.folder_path] = row.mijnrood_folder_id

        parent_map: dict[int, int | None] = {}
        for row in rows:
            if not row.folder_path or " / " not in row.folder_path:
                parent_map[row.mijnrood_folder_id] = None
                continue

            # Walk up: "A / B / C" -> try "A / B", skip year folders not in table
            parent_path = row.folder_path.rsplit(" / ", 1)[0]
            while parent_path and parent_path not in path_to_id:
                if " / " not in parent_path:
                    parent_path = None
                    break
                parent_path = parent_path.rsplit(" / ", 1)[0]

            parent_map[row.mijnrood_folder_id] = path_to_id.get(parent_path) if parent_path else None

        return parent_map

    @staticmethod
    def _load_category_keywords() -> dict[str, list[str]]:
        """Load category -> keywords from Board Document Categories."""
        from verenigingen.utils.folder_category_detector import _load_keyword_map

        return _load_keyword_map()

    @staticmethod
    def _load_chapter_names() -> dict[str, str]:
        """Load lowercase chapter name -> actual chapter name mapping."""
        chapters = frappe.get_all("Chapter", fields=["name"], filters={"status": "Active"})
        return {c.name.lower(): c.name for c in chapters}

    @staticmethod
    def _infer_document_type(path_lower: str, keyword_map: dict[str, list[str]]) -> str:
        """Match folder path against category keywords. Returns best match or 'Other'."""
        if not path_lower:
            return "Other"

        for category, keywords in keyword_map.items():
            for keyword in keywords:
                if keyword in path_lower:
                    return category

        return "Other"

    @staticmethod
    def _infer_chapter(
        path_lower: str, chapter_names: dict[str, str], national_chapter: str | None
    ) -> str | None:
        """Infer chapter from folder path segments.

        Checks path segments against chapter names. National synonyms
        (landelijk, landelijk bestuur, commissies, etc.) map to the
        national chapter. Returns None if no match found.
        """
        national_synonyms = {
            "landelijk",
            "landelijk bestuur",
            "commissies",
            "congrescommissie",
            "strijdterreinen",
            "de socialisten",
            "nationaal",
            "algemeen",
            "congres",
        }

        # Split path into segments and check each
        segments = [s.strip() for s in path_lower.split("/")]

        for segment in segments:
            if segment in national_synonyms:
                return national_chapter

            if segment in chapter_names:
                return chapter_names[segment]

            # Partial match: segment contains a chapter name
            for ch_lower, ch_name in chapter_names.items():
                if ch_lower in segment:
                    return ch_name

        return national_chapter

    def import_all(self, dry_run: bool = False) -> dict:
        """Main entry point for document import.

        Args:
            dry_run: If True, compute counts without creating records or downloading files.

        Returns:
            Summary dict with imported, skipped, errors counts.
        """
        from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient
        from verenigingen.mijnrood_sync.sftp_client import MijnRoodSFTPClient

        # 1. Load folder mapping
        self._load_folder_mapping()
        if not self.folder_mapping:
            return {
                "success": False,
                "imported": 0,
                "skipped": 0,
                "errors": ["No folder mappings configured. Fetch folders and configure mappings first."],
            }

        # 2. Fetch folder tree + document list from MijnRood DB
        db_client = MijnRoodDatabaseClient(settings=self.settings)
        try:
            with db_client:
                folders = db_client.fetch_document_folders()
                documents = db_client.fetch_documents()
        except Exception as e:
            error_msg = str(e)[:500]
            return {"success": False, "imported": 0, "skipped": 0, "errors": [error_msg]}

        # 3. Build folder tree
        self.folder_tree = {f["id"]: f for f in folders}

        if not documents:
            return {"success": True, "imported": 0, "skipped": 0, "errors": []}

        # Dry run: just count what would be imported
        if dry_run:
            return self._dry_run_summary(documents)

        # 4. Connect SFTP and import
        sftp_client = MijnRoodSFTPClient(settings=self.settings)
        imported = 0
        skipped = 0
        errors = []

        try:
            with sftp_client:
                total = len(documents)
                for idx, doc in enumerate(documents, 1):
                    try:
                        result = self._import_single_document(doc, sftp_client)
                        if result == "imported":
                            imported += 1
                        elif result == "skipped":
                            skipped += 1
                        # Commit per document so we don't lose progress
                        frappe.db.commit()
                    except Exception as e:
                        error_msg = f"Document {doc.get('id')} ({doc.get('name')}): {e}"
                        errors.append(error_msg)
                        logger.error(error_msg, exc_info=True)
                        frappe.db.rollback()

                    # Publish progress via realtime
                    if idx % 5 == 0 or idx == total:
                        frappe.publish_realtime(
                            "document_import_progress",
                            {"current": idx, "total": total, "imported": imported, "skipped": skipped},
                            doctype="MijnRood Sync Settings",
                        )
        except Exception as e:
            errors.append(f"SFTP connection error: {e}")

        # Update status on settings
        status_msg = f"Imported: {imported}, Skipped: {skipped}, Errors: {len(errors)}"
        if errors:
            status_msg += f"\nLast errors: {'; '.join(errors[-3:])}"
        self.settings.db_set("document_import_status", status_msg[:1000])
        self.settings.db_set("last_document_import", now_datetime())
        frappe.db.commit()

        return {
            "success": len(errors) == 0,
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        }

    def _load_folder_mapping(self):
        """Load folder mapping from settings child table.

        Rows missing organization_type or document_type are skipped with a
        warning so the admin can see which folders still need configuration.
        """
        self.folder_mapping = {}
        skipped = []
        for row in self.settings.document_folder_mapping or []:
            if row.organization_type and row.document_type:
                self.folder_mapping[row.mijnrood_folder_id] = {
                    "organization_type": row.organization_type,
                    "chapter": row.chapter,
                    "team": row.team,
                    "movement": row.movement,
                    "document_type": row.document_type,
                }
            else:
                skipped.append(f"{row.folder_name or row.mijnrood_folder_id} (row {row.idx})")

        if skipped:
            logger.warning(
                "Skipped %d folder mapping rows with incomplete config: %s",
                len(skipped),
                ", ".join(skipped),
            )

    def _resolve_mapped_folder(self, folder_id: int) -> int | None:
        """Walk parent chain to find nearest ancestor with a mapping.

        For a document in folder X, checks X first, then X's parent, etc.
        Year-only subfolders (2023, 2024) are skipped in the mapping table,
        so a file in "Financien/2024" resolves to the "Financien" mapping.

        Returns the mapped folder ID, or None if no ancestor has a mapping.
        Uses a cache to avoid repeated traversals.
        """
        if folder_id in self.root_cache:
            return self.root_cache[folder_id]

        visited = []
        current = folder_id
        seen = set()
        while current is not None and current not in seen:
            seen.add(current)

            if current in self.root_cache:
                result = self.root_cache[current]
                for fid in visited:
                    self.root_cache[fid] = result
                return result

            # Check if this folder has a configured mapping
            if current in self.folder_mapping:
                for fid in visited:
                    self.root_cache[fid] = current
                self.root_cache[current] = current
                return current

            visited.append(current)
            folder = self.folder_tree.get(current)
            if folder is None:
                break
            current = folder.get("parent_id")

        # No mapped ancestor found
        for fid in visited:
            self.root_cache[fid] = None
        return None

    @staticmethod
    def _get_default_mapping() -> dict:
        """Return sensible defaults for new folder mapping rows.

        Pre-fills Chapter + national board chapter + "Other" so the admin only
        needs to adjust document_type (and occasionally organization) rather
        than filling every field from scratch.

        Returns empty dict if no national board chapter is configured.
        """
        national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        if national_chapter and frappe.db.exists("Chapter", national_chapter):
            return {
                "organization_type": "Chapter",
                "chapter": national_chapter,
                "document_type": "Other",
            }
        return {}

    def _get_mapping_for_document(self, doc: dict) -> dict | None:
        """Resolve a document's folder_id to a folder mapping.

        Walks up the parent chain to find the nearest mapped ancestor.
        Year subfolders (not in the mapping table) inherit from their parent.

        Returns the mapping dict or None if no mapping exists.
        """
        folder_id = doc.get("folder_id")
        if folder_id is None:
            return None

        mapped_id = self._resolve_mapped_folder(folder_id)
        if mapped_id is None:
            return None

        return self.folder_mapping.get(mapped_id)

    def _import_single_document(self, doc: dict, sftp_client) -> str:
        """Import a single document. Returns 'imported' or 'skipped'."""
        # Resolve mapping
        mapping = self._get_mapping_for_document(doc)
        if mapping is None:
            logger.debug(
                "Skipping document %s (folder_id=%s): no mapping for root folder",
                doc.get("id"),
                doc.get("folder_id"),
            )
            return "skipped"

        upload_filename = doc.get("upload_file_name")
        if not upload_filename:
            logger.warning("Skipping document %s: no upload_file_name", doc.get("id"))
            return "skipped"

        # Download file
        content = sftp_client.download_file(upload_filename)

        # Compute SHA256 for dedup
        file_hash = hashlib.sha256(content).hexdigest()

        # Check dedup
        existing = frappe.db.exists("Organization Document", {"file_hash": file_hash})
        if existing:
            logger.debug(
                "Skipping document %s: hash %s already exists as %s",
                doc.get("id"),
                file_hash[:12],
                existing,
            )
            return "skipped"

        # Determine organization name from mapping
        org_type = mapping["organization_type"]
        org_name = mapping.get(org_type.lower()) or ""  # chapter, team, or movement
        if not org_name:
            logger.warning(
                "Skipping document %s: mapping has organization_type=%s but no entity set",
                doc.get("id"),
                org_type,
            )
            return "skipped"

        # Validate the target organization exists
        if not frappe.db.exists(org_type, org_name):
            logger.warning(
                "Skipping document %s: %s '%s' does not exist",
                doc.get("id"),
                org_type,
                org_name,
            )
            return "skipped"

        doc_type = mapping["document_type"]
        original_name = doc.get("name") or upload_filename

        from verenigingen.utils.date_extraction import extract_date_from_text, extract_year_from_text
        from verenigingen.utils.folder_category_detector import detect_category_from_folder_path

        # 1. Try MijnRood's date_uploaded first
        upload_date = self._parse_upload_date(doc)

        # 2. If no DB date, try extracting from document name / upload filename
        if not upload_date:
            upload_date = extract_date_from_text(original_name)

        # 3. If still no date, try the folder path
        folder_path = self._get_folder_path(doc.get("folder_id"))
        if not upload_date and folder_path:
            upload_date = extract_date_from_text(folder_path)

        # 4. Year from full date, or from text patterns, or "Other"
        if upload_date:
            year = str(upload_date.year)
        else:
            year = extract_year_from_text(original_name, default="Other")

        # 5. Auto-detect category from folder path if currently "Other"
        doc_type = detect_category_from_folder_path(folder_path or "", doc_type)

        # Save file to hierarchical storage
        from verenigingen.utils.file_storage import save_organization_document

        file_result = save_organization_document(
            content=content,
            filename=original_name,
            organization_type=org_type,
            organization_name=org_name,
            category=doc_type,
            year=year,
            is_private=1,
        )

        # Create Organization Document record
        org_doc = frappe.get_doc(
            {
                "doctype": "Organization Document",
                "organization_type": org_type,
                "chapter": mapping.get("chapter") if org_type == "Chapter" else None,
                "team": mapping.get("team") if org_type == "Team" else None,
                "movement": mapping.get("movement") if org_type == "Movement" else None,
                "document_name": original_name,
                "document_type": doc_type,
                "document_file": file_result["file_url"],
                "upload_date": upload_date.strftime("%Y-%m-%d") if upload_date else None,
                "uploaded_by": "Administrator",
                "file_hash": file_hash,
            }
        )
        # Security: Admin-initiated background job importing from trusted MijnRood DB.
        # Runs as Administrator; OrganizationDocument.validate checks board membership
        # which doesn't apply to system-level data migration.
        org_doc.flags.ignore_permissions = True
        org_doc.insert()

        logger.info(
            "Imported document %s → %s (%s, %s/%s)",
            doc.get("id"),
            org_doc.name,
            original_name,
            org_type,
            org_name,
        )
        return "imported"

    def _parse_upload_date(self, doc: dict) -> datetime | None:
        """Parse date_uploaded from MijnRood document record.

        Falls back to extracting year from folder name if date is missing.
        """
        date_str = doc.get("date_uploaded")
        if not date_str:
            return None

        if isinstance(date_str, datetime):
            return date_str

        # Handle ISO format from _serialize_row
        try:
            return datetime.fromisoformat(str(date_str))
        except (ValueError, TypeError):
            return None

    def _compute_folder_path(self, folder_id: int, tree: dict) -> str:
        """Compute full folder path like 'Financien / 2024'."""
        parts = []
        current = folder_id
        seen = set()
        while current is not None and current not in seen:
            seen.add(current)
            folder = tree.get(current)
            if folder is None:
                break
            parts.append(folder.get("name", str(current)))
            current = folder.get("parent_id")
        parts.reverse()
        return " / ".join(parts)

    def _get_folder_path(self, folder_id: int | None) -> str | None:
        """Compute the folder path string for a document's folder_id.

        Uses the already-loaded folder_tree to build the path.
        Returns None if folder_id is missing or not in the tree.
        """
        if folder_id is None or not self.folder_tree:
            return None
        if folder_id not in self.folder_tree:
            return None
        return self._compute_folder_path(folder_id, self.folder_tree)

    def _dry_run_summary(self, documents: list[dict]) -> dict:
        """Compute what would be imported without actually importing."""
        mappable = 0
        unmapped = 0
        already_exists = 0

        for doc in documents:
            mapping = self._get_mapping_for_document(doc)
            if mapping is None:
                unmapped += 1
                continue

            org_type = mapping["organization_type"]
            org_name = mapping.get(org_type.lower()) or ""
            if not org_name:
                unmapped += 1
                continue

            mappable += 1

        return {
            "success": True,
            "imported": 0,
            "would_import": mappable,
            "unmapped": unmapped,
            "total_documents": len(documents),
            "skipped": 0,
            "errors": [],
            "dry_run": True,
        }


def import_all(dry_run: bool = False) -> dict:
    """Module-level entry point for bench execute.

    Usage:
        bench --site dev.veganisme.net execute \
            verenigingen.mijnrood_sync.services.document_import_service.import_all \
            --kwargs '{"dry_run": true}'
    """
    service = DocumentImportService()
    return service.import_all(dry_run=dry_run)
