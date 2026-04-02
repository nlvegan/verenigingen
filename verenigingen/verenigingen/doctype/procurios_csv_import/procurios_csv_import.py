# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import json
import traceback
from typing import Dict, List, Tuple

import frappe
from frappe.model.document import Document
from frappe.utils import today

from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator
from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.csv_import_processor import (
    CSVImportBackgroundProcessor,
    bulk_member_operations,
    ensure_bulk_import_members_set,
)
from verenigingen.utils.error_handling import sanitize_error_for_audit

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


class ProcuriosCSVImport(Document):
    @property
    def _validator(self) -> ProcuriosDataValidator:
        if not hasattr(self, "__validator"):
            self.__validator = ProcuriosDataValidator(
                import_gender=bool(self.import_gender),
            )
        return self.__validator

    @property
    def _parser(self) -> SecureCSVParser:
        if not hasattr(self, "__parser"):
            encoding = None if self.encoding == "auto-detect" else self.encoding
            self.__parser = SecureCSVParser(encoding=encoding, delimiter=self.csv_delimiter)
        return self.__parser

    def validate(self):
        if not self.import_date:
            self.import_date = today()

    def on_submit(self):
        self.db_set("import_status", "Queued")
        frappe.enqueue(
            method="verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import.process_import_background",
            queue="long",
            timeout=3600,
            import_doc_name=self.name,
            test_mode=self.test_mode,
            now=False,
        )

    def _read_csv_file(self) -> List[Dict]:
        return self._parser.read_csv_file(self.csv_file)

    def _validate_and_map_data(self, csv_data: List[Dict]) -> Tuple[List[Dict], List[str]]:
        return self._validator.validate_and_map_data(csv_data)

    def _validate_and_preview_csv(self):
        self.db_set("import_status", "Validating")
        frappe.db.commit()

        try:
            csv_data = self._read_csv_file()
            if not csv_data:
                self.db_set("import_status", "Failed")
                self.db_set("error_log", "CSV file is empty or could not be read")
                frappe.db.commit()
                return

            mapped_data, errors = self._validate_and_map_data(csv_data)

            if errors:
                self.db_set("error_log", "\n".join(errors[:50]))

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
            self.db_set("import_status", "Failed")
            self.db_set("error_log", sanitize_error_for_audit(str(e)))
            frappe.db.commit()
            raise

    def _get_status_mapping(self) -> Dict[str, str]:
        """Build a lookup dict from the status_mapping child table."""
        mapping = {}
        for row in self.status_mapping or []:
            if row.procurios_value and row.member_status:
                mapping[row.procurios_value.strip().lower()] = row.member_status
        return mapping

    def _process_single_member(self, row: Dict, error_log: List[str]) -> Tuple[str, str]:
        """Create a single Member from a mapped row. Returns (status, member_name)."""
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

            return ("created", member_doc.name)

        except frappe.DuplicateEntryError:
            error_log.append(
                f"Row {row.get('row_number', '?')}: Duplicate member_id {row.get('member_id', '')}"
            )
            return ("skipped", "")
        except Exception as e:
            sanitized = sanitize_error_for_audit(str(e))
            error_log.append(f"Row {row.get('row_number', '?')}: {sanitized}")
            return ("skipped", "")

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
            truncated = error_log[:50]
            self.error_log = "\n".join(truncated)
            if len(error_log) > 50:
                self.error_log += f"\n... and {len(error_log) - 50} more errors"

        # Security: Background job updating its own import status document
        self.save(ignore_permissions=True)
        frappe.db.commit()


@frappe.whitelist()
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation."""
    doc = frappe.get_doc("Procurios CSV Import", import_doc_name)
    try:
        doc._validate_and_preview_csv()
        doc.reload()
        return {
            "status": "success" if doc.import_status == "Ready for Import" else "error",
            "message": f"Validation complete. Status: {doc.import_status}",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": sanitize_error_for_audit(str(e)),
        }


@frappe.whitelist()
def process_import_background(import_doc_name: str, test_mode: bool = False):
    """Background job: process the validated CSV and create members."""
    frappe.flags.in_background_job = True
    frappe.flags.bulk_member_operations = True
    frappe.flags.ignore_version_changes = True

    doc = frappe.get_doc("Procurios CSV Import", import_doc_name)

    try:
        csv_data = doc._read_csv_file()
        mapped_data, _errors = doc._validate_and_map_data(csv_data)

        if not mapped_data:
            doc.db_set("import_status", "Failed")
            doc.db_set("error_log", "No valid rows to import")
            frappe.db.commit()
            return

        if test_mode:
            mapped_data = mapped_data[:25]

        # Extract Type field for status mapping
        for row in mapped_data:
            for item in row.get("procurios_data", []):
                if item["field_label"].lower() == "type":
                    row["_type_value"] = item["field_value"]
                    break

        processor = CSVImportBackgroundProcessor(import_doc_name, "Procurios CSV Import")
        processor.load_import_doc()

        with bulk_member_operations(import_doc_name):
            processor.process_import(
                data_rows=mapped_data,
                process_row_callback=doc._process_single_member,
                finalize_callback=doc._finalize_import_results,
                batch_size=50,
                batch_commit=True,
            )

    except Exception:
        doc.reload()
        doc.db_set("import_status", "Failed")
        doc.db_set("error_log", sanitize_error_for_audit(traceback.format_exc()))
        frappe.db.commit()

    finally:
        frappe.flags.in_background_job = False
        frappe.flags.bulk_member_operations = False
        frappe.flags.ignore_version_changes = False
