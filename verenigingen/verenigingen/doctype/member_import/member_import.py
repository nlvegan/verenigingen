# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import json
import traceback
from typing import Dict, List, Tuple

import frappe

from verenigingen.utils.csv.base_csv_import import (
    BaseCSVImport,
    format_truncated_error_log,
    mark_import_failed,
    prepare_background_import,
    run_csv_validation,
)
from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator
from verenigingen.utils.csv_import_processor import (
    CSVImportBackgroundProcessor,
    bulk_member_operations,
    ensure_bulk_import_members_set,
)
from verenigingen.utils.error_handling import sanitize_error_for_audit
from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
)

ADDRESS_TYPE_MAP = {
    "Standaardadres": "Personal",
    "Postadres": "Postal",
    "Factuuradres": "Billing",
}

COUNTRY_NAME_MAP = {
    "nederland": "Netherlands",
    "belgie": "Belgium",
    "belgië": "Belgium",
    "duitsland": "Germany",
    "frankrijk": "France",
    "verenigd koninkrijk": "United Kingdom",
}


class MemberImport(BaseCSVImport):
    _BACKGROUND_METHOD = (
        "verenigingen.verenigingen.doctype.member_import.member_import.process_import_background"
    )

    @property
    def _validator(self) -> ProcuriosDataValidator:
        # Cache slot is `_validator_instance` (single underscore) to match
        # the BaseCSVImport name-mangling-safe pattern. See base class
        # docstring + TestMemberImportPropertyCache.
        if not hasattr(self, "_validator_instance"):
            self._validator_instance = ProcuriosDataValidator(
                import_gender=bool(self.import_gender),
            )
        return self._validator_instance

    def _validate_and_map_data(self, csv_data: List[Dict]) -> Tuple[List[Dict], List[str]]:
        return self._validator.validate_and_map_data(csv_data)

    def _validate_and_preview_csv(self):
        self.db_set("import_status", "Validating")
        frappe.db.commit()

        try:
            csv_data = self._read_csv_file()
            if not csv_data:
                mark_import_failed(self, "CSV file is empty or could not be read")
                return

            mapped_data, errors = self._validate_and_map_data(csv_data)

            if errors:
                self.db_set("error_log", format_truncated_error_log(errors))

            if mapped_data:
                preview = []
                for row in mapped_data[:5]:
                    preview_row = {
                        k: v for k, v in row.items() if k not in ("procurios_data", "addresses", "row_number")
                    }
                    preview_row["_procurios_fields"] = len(row.get("procurios_data", []))
                    preview_row["_addresses"] = len(row.get("addresses", []))
                    preview.append(preview_row)
                self.db_set("preview_data", json.dumps(preview, indent=2, default=str))

            self.db_set("total_rows", len(csv_data))
            self.db_set("descriptive_name", f"Procurios import - {len(csv_data)} rows")

            if mapped_data:
                self.db_set("import_status", "Ready for Import")
            else:
                self.db_set("import_status", "Failed")
                if not errors:
                    self.db_set("error_log", "No valid rows found in CSV")

            frappe.db.commit()

        except Exception as e:
            mark_import_failed(self, str(e))
            raise

    def _get_status_mapping(self) -> Dict[str, str]:
        """Build a lookup dict from the status_mapping child table."""
        mapping = {}
        for row in self.status_mapping or []:
            if row.procurios_value and row.member_status:
                mapping[row.procurios_value.strip().lower()] = row.member_status
        return mapping

    def _process_single_member(self, row: Dict, error_log: List[str]) -> Tuple[str, str]:
        """Create a single Member from a mapped row. Returns (status, member_name).

        The row is one savepointed unit of work (#570). Without the savepoint a row
        that failed anywhere after ``member_doc.insert()`` -- ``Member.after_insert``
        raising because the ERPNext Customer could not be created is the live case,
        and it re-raises deliberately under ``bulk_member_operations`` so the importer
        can report it -- was left written, then committed by the batch loop
        (``csv_import_processor.process_import``: ``if batch_commit: frappe.db.commit()``)
        while being reported "skipped". A systematic misconfiguration therefore
        produced N orphaned Members under a summary saying nothing had been created.

        The two sibling importers -- ``member_import_service._create_new_member``
        and ``vip_import._process_single_row`` -- already had a savepoint per row.
        This one does NOT copy their spelling: both roll back with raw
        ``frappe.db.sql("ROLLBACK TO SAVEPOINT ...")`` under a silent
        ``except Exception: pass``, which is the masking shape
        ``utils/transaction_errors`` exists to eliminate and which the AST ratchet
        cannot see (#701). The canonical helpers are used here instead.
        """
        savepoint = f"member_import_row_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(savepoint)
        member_doc = None
        try:
            member_id = row.get("member_id", "")
            status_mapping = self._get_status_mapping()

            # Determine member status from Type field
            type_value = row.get("_type_value", "")
            if type_value and type_value.strip().lower() in status_mapping:
                member_status = status_mapping[type_value.strip().lower()]
            else:
                member_status = self.default_status or "Active"

            # Create the member doc
            member_doc = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_id": member_id,
                    "procurios_id": row.get("procurios_id", ""),
                    "first_name": row.get("first_name", ""),
                    "last_name": row.get("last_name", ""),
                    "tussenvoegsel": row.get("tussenvoegsel", ""),
                    "email": row.get("email", ""),
                    "birth_date": row.get("birth_date"),
                    "contact_number": row.get("contact_number", ""),
                    "iban": row.get("iban", ""),
                    "member_since": row.get("member_since"),
                    "status": member_status,
                }
            )

            # Set gender if mapped
            if row.get("gender"):
                member_doc.gender = row["gender"]

            # Add procurios_data child rows
            for item in row.get("procurios_data", []):
                member_doc.append(
                    "procurios_data",
                    {
                        "field_label": item["field_label"],
                        "field_value": item.get("field_value", ""),
                        "field_category": item.get("field_category", "Other"),
                    },
                )

            member_doc.flags.ignore_mandatory = True
            # Security: Background job creating members from admin-uploaded CSV
            member_doc.flags.ignore_permissions = True
            member_doc.insert()

            # Track for bulk import
            ensure_bulk_import_members_set().add(member_doc.name)

            # Create addresses if enabled
            if self.import_addresses and row.get("addresses"):
                self._create_addresses(member_doc, row["addresses"])

        except NON_RESUMABLE_DB_ERRORS:
            # 1213/1205: the server has already thrown the transaction away,
            # savepoints included. What this buys is precise, and worth stating
            # because it is less than it looks: it stops `rollback_to_savepoint`
            # running against a savepoint that no longer exists, whose 1305 would
            # REPLACE the deadlock and defeat every guard keyed on the error's
            # type (#561). `process_import`'s row loop (#700, fixed) now abandons
            # the import on this re-raise instead of counting it as one skipped
            # row and carrying on against a dead transaction.
            raise
        except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
            # UniqueValidationError is the one that actually fires here: `member_id`
            # is a unique FIELD, and frappe raises DuplicateEntryError only for a
            # primary-key collision. The two are unrelated classes
            # (DuplicateEntryError derives from NameError), so listing only the
            # latter sent every duplicate down the catch-all below and showed the
            # operator a raw IntegrityError repr instead of the offending member_id.
            # This rollback is not merely defensive. `Member.autoname` is
            # `format:...{####}`, which increments the shared `tabSeries` row named
            # '' in `set_new_name`, BEFORE `db_insert()`. InnoDB rolls back only the
            # failed statement, so that increment SURVIVES the constraint violation
            # and this rollback is what undoes it. Measured on test_site_4: series
            # 15519 -> 15520 on the failed insert, back to 15519 after the rollback.
            # The Member row itself really is absent, which is why
            # `_rejected_row_message` has to check before naming it.
            rolled_back = rollback_to_savepoint(savepoint)
            error_log.append(
                self._rejected_row_message(
                    row, f"Duplicate member_id {row.get('member_id', '')}", member_doc, rolled_back
                )
            )
            return ("skipped", "")
        except Exception as e:
            rolled_back = rollback_to_savepoint(savepoint)
            error_log.append(
                self._rejected_row_message(row, sanitize_error_for_audit(str(e)), member_doc, rolled_back)
            )
            return ("skipped", "")
        else:
            release_savepoint_if_present(savepoint)
            return ("created", member_doc.name)

    def _rejected_row_message(self, row: Dict, reason: str, member_doc, rolled_back: bool) -> str:
        """The operator-facing line for a row that was not imported.

        ``rollback_to_savepoint`` returns False when the savepoint is already gone,
        which a nested commit anywhere under the insert would do. The row's writes
        are durable at that point, so the plain "not imported" wording would be a
        claim about the database that is not true: name the surviving Member instead
        so somebody can act on it.
        """
        prefix = f"Row {row.get('row_number', '?')}: {reason}"
        member_name = getattr(member_doc, "name", None)
        if rolled_back or not member_name or not frappe.db.exists("Member", member_name):
            return prefix
        return (
            f"{prefix} -- this row could NOT be rolled back, so Member {member_name} "
            "is still in the database and needs manual review."
        )

    def _create_addresses(self, member_doc, addresses: List[Dict]):
        """Create Address records and link the preferred one as primary_address."""
        primary_address_name = None

        for addr_data in addresses:
            addr_type = addr_data.get("address_type", "")
            frappe_addr_type = ADDRESS_TYPE_MAP.get(addr_type, "Other")

            street = addr_data.get("street", "")
            house_number = addr_data.get("house_number", "")
            address_line1 = f"{street} {house_number}".strip() if street else house_number

            if not address_line1 and not addr_data.get("city"):
                continue

            country_raw = addr_data.get("country", "")
            country = COUNTRY_NAME_MAP.get(country_raw.lower(), country_raw) if country_raw else "Netherlands"

            try:
                address_doc = frappe.get_doc(
                    {
                        "doctype": "Address",
                        "address_title": addr_data.get("addressee")
                        or member_doc.full_name
                        or f"{member_doc.first_name} {member_doc.last_name}",
                        "address_type": frappe_addr_type,
                        "address_line1": address_line1,
                        "city": addr_data.get("city", ""),
                        "pincode": addr_data.get("pincode", ""),
                        "country": country,
                        "links": [
                            {
                                "link_doctype": "Member",
                                "link_name": member_doc.name,
                            }
                        ],
                    }
                )
                # Security: Background job creating addresses from admin-uploaded CSV
                address_doc.flags.ignore_permissions = True
                address_doc.insert()

                if addr_type == (self.preferred_address_type or "Standaardadres"):
                    primary_address_name = address_doc.name

            except NON_RESUMABLE_DB_ERRORS:
                # Swallowing a 1213/1205 here would hide it from the guard in
                # _process_single_member and leave the rest of the row running
                # against a transaction the server has already discarded.
                raise
            except Exception:
                pass  # Address creation failure should not block member import

        if primary_address_name:
            frappe.db.set_value(
                "Member",
                member_doc.name,
                "primary_address",
                primary_address_name,
                update_modified=False,
            )

    def _finalize_import_results(
        self,
        created_count: int,
        _updated_count: int,
        skipped_count: int,
        error_log: List[str],
        _created_members=None,
        _updated_members=None,
        _skipped_members=None,
    ):
        """Update the import document with final results."""
        self.reload()
        self.members_created = created_count
        self.members_skipped = skipped_count
        self.import_status = "Completed"

        if error_log:
            self.error_log = format_truncated_error_log(error_log)

        # Security: Background job updating its own import status document
        self.save(ignore_permissions=True)
        frappe.db.commit()


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation."""
    return run_csv_validation("Member Import", import_doc_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def process_import_background(import_doc_name: str, test_mode=False):
    """Background job: process the validated CSV and create members."""
    doc, test_mode = prepare_background_import("Member Import", import_doc_name, test_mode)

    try:
        csv_data = doc._read_csv_file()
        mapped_data, _errors = doc._validate_and_map_data(csv_data)

        if not mapped_data:
            mark_import_failed(doc, "No valid rows to import")
            return

        if test_mode:
            mapped_data = mapped_data[:25]

        # Extract Type field for status mapping
        for row in mapped_data:
            for item in row.get("procurios_data", []):
                if item["field_label"].lower() == "type":
                    row["_type_value"] = item["field_value"]
                    break

        processor = CSVImportBackgroundProcessor(import_doc_name, "Member Import")
        processor.load_import_doc()

        # `bulk_member_operations` is the sibling-specific flag. The CM
        # owns its full lifecycle (sets True on entry, resets False on
        # exit — including on exception). Setting it earlier was
        # redundant: nothing in the prologue above writes a Member doc,
        # so the flag's hook-suppression effect would never have fired.
        # Resetting it in the outer `finally` was likewise redundant.
        with bulk_member_operations(import_doc_name):
            processor.process_import(
                data_rows=mapped_data,
                process_row_callback=doc._process_single_member,
                finalize_callback=doc._finalize_import_results,
                batch_size=50,
                batch_commit=True,
            )

    except Exception:
        mark_import_failed(doc, traceback.format_exc())

    finally:
        frappe.flags.in_background_job = False
        frappe.flags.ignore_version_changes = False
