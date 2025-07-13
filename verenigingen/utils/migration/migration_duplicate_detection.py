"""
Advanced duplicate detection system for eBoekhouden migration

Provides multiple strategies for detecting and handling duplicate records
during migration, including fuzzy matching and intelligent merging.
"""

import hashlib
import json
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import frappe
from frappe.utils import flt, getdate


class DuplicateDetector:
    """Advanced duplicate detection with multiple strategies"""

    def __init__(self):
        self.detection_strategies = {
            "exact": ExactMatchStrategy(),
            "fuzzy": FuzzyMatchStrategy(),
            "composite": CompositeKeyStrategy(),
            "temporal": TemporalMatchStrategy(),
        }
        self.duplicate_cache = {}

    def check_duplicate(self, doctype, record, strategies=None):
        """
        Check if a record is a duplicate using specified strategies

        Args:
            doctype: The document type to check
            record: The record data to check
            strategies: List of strategy names to use (default: all)

        Returns:
            Dict with duplicate status and matching records
        """
        if strategies is None:
            strategies = list(self.detection_strategies.keys())

        results = {"is_duplicate": False, "matches": [], "confidence": 0, "strategy_results": {}}

        # Run each strategy
        for strategy_name in strategies:
            if strategy_name in self.detection_strategies:
                strategy = self.detection_strategies[strategy_name]
                strategy_result = strategy.detect(doctype, record)

                results["strategy_results"][strategy_name] = strategy_result

                if strategy_result["matches"]:
                    results["is_duplicate"] = True
                    results["matches"].extend(strategy_result["matches"])
                    results["confidence"] = max(results["confidence"], strategy_result["confidence"])

        # Remove duplicate matches
        unique_matches = []
        seen = set()
        for match in results["matches"]:
            if match["name"] not in seen:
                unique_matches.append(match)
                seen.add(match["name"])
        results["matches"] = unique_matches

        return results

    def generate_signature(self, doctype, record):
        """Generate a unique signature for a record"""
        # Create signature based on key fields
        key_fields = self._get_key_fields(doctype)

        signature_data = {}
        for field in key_fields:
            if field in record:
                signature_data[field] = record[field]

        # Create hash
        signature_str = json.dumps(signature_data, sort_keys=True)
        return hashlib.sha256(signature_str.encode()).hexdigest()

    def _get_key_fields(self, doctype):
        """Get key fields for duplicate detection based on doctype"""
        key_field_map = {
            "Sales Invoice": ["customer", "posting_date", "grand_total", "eboekhouden_mutation_nr"],
            "Purchase Invoice": ["supplier", "posting_date", "grand_total", "eboekhouden_mutation_nr"],
            "Payment Entry": [
                "party",
                "posting_date",
                "paid_amount",
                "reference_no",
                "eboekhouden_mutation_nr",
            ],
            "Journal Entry": ["posting_date", "total_debit", "user_remark", "eboekhouden_mutation_nr"],
            "Customer": ["customer_name", "tax_id", "email_id"],
            "Supplier": ["supplier_name", "tax_id", "email_id"],
            "Account": ["account_name", "account_number", "parent_account"],
        }

        return key_field_map.get(doctype, ["name"])


class ExactMatchStrategy:
    """Detect exact duplicates based on unique fields"""

    def detect(self, doctype, record):
        """Detect exact matches"""
        matches = []
        confidence = 0

        # Check eBoekhouden mutation number (highest confidence)
        if record.get("eboekhouden_mutation_nr"):
            existing = frappe.get_all(
                doctype,
                filters={"eboekhouden_mutation_nr": record["eboekhouden_mutation_nr"]},
                fields=["name", "creation", "modified"],
            )
            if existing:
                matches.extend(
                    [{"name": e.name, "reason": "exact_mutation_nr", "confidence": 100} for e in existing]
                )
                confidence = 100

        # Check reference number
        if record.get("reference_no") and not matches:
            existing = frappe.get_all(
                doctype,
                filters={"reference_no": record["reference_no"]},
                fields=["name", "creation", "modified"],
            )
            if existing:
                matches.extend(
                    [{"name": e.name, "reason": "exact_reference", "confidence": 90} for e in existing]
                )
                confidence = max(confidence, 90)

        # Check unique combinations (e.g., supplier + invoice number)
        if doctype == "Purchase Invoice" and record.get("supplier") and record.get("bill_no"):
            existing = frappe.get_all(
                doctype,
                filters={"supplier": record["supplier"], "bill_no": record["bill_no"]},
                fields=["name", "creation", "modified"],
            )
            if existing:
                matches.extend(
                    [{"name": e.name, "reason": "supplier_bill_combo", "confidence": 95} for e in existing]
                )
                confidence = max(confidence, 95)

        return {"matches": matches, "confidence": confidence}


class FuzzyMatchStrategy:
    """Detect duplicates using fuzzy matching"""

    def detect(self, doctype, record):
        """Detect fuzzy matches"""
        matches = []
        confidence = 0

        # Define fuzzy match fields by doctype
        fuzzy_fields = {
            "Customer": ["customer_name"],
            "Supplier": ["supplier_name"],
            "Sales Invoice": ["customer", "posting_date", "grand_total"],
            "Purchase Invoice": ["supplier", "posting_date", "grand_total"],
        }

        if doctype not in fuzzy_fields:
            return {"matches": [], "confidence": 0}

        # Build filter for potential matches
        filters = {}

        # Date range filter (within 7 days)
        if record.get("posting_date"):
            date = getdate(record["posting_date"])
            filters["posting_date"] = ["between", [date - timedelta(days=7), date + timedelta(days=7)]]

        # Amount range filter (within 5%)
        if record.get("grand_total") is not None:
            amount = flt(record["grand_total"])
            if amount > 0:
                filters["grand_total"] = ["between", [amount * 0.95, amount * 1.05]]
            else:
                filters["grand_total"] = 0

        # Get potential matches
        potential_matches = frappe.get_all(
            doctype, filters=filters, fields=fuzzy_fields[doctype] + ["name"], limit=100
        )

        # Score each potential match
        for potential in potential_matches:
            score = self._calculate_similarity_score(record, potential, fuzzy_fields[doctype])

            if score >= 80:  # 80% similarity threshold
                matches.append(
                    {
                        "name": potential["name"],
                        "reason": "fuzzy_match",
                        "confidence": score,
                        "details": potential,
                    }
                )
                confidence = max(confidence, score)

        return {"matches": matches, "confidence": confidence}

    def _calculate_similarity_score(self, record1, record2, fields):
        """Calculate similarity score between two records"""
        scores = []

        for field in fields:
            val1 = str(record1.get(field, ""))
            val2 = str(record2.get(field, ""))

            if val1 and val2:
                # Use SequenceMatcher for string similarity
                similarity = SequenceMatcher(None, val1.lower(), val2.lower()).ratio()
                scores.append(similarity * 100)

        return sum(scores) / len(scores) if scores else 0


class CompositeKeyStrategy:
    """Detect duplicates based on composite keys"""

    def detect(self, doctype, record):
        """Detect matches based on composite keys"""
        matches = []
        confidence = 0

        # Define composite keys by doctype
        composite_keys = {
            "Payment Entry": ["party", "posting_date", "paid_amount"],
            "Journal Entry": ["posting_date", "total_debit", "total_credit"],
            "Sales Invoice": ["customer", "posting_date", "net_total"],
            "Purchase Invoice": ["supplier", "posting_date", "net_total"],
        }

        if doctype not in composite_keys:
            return {"matches": [], "confidence": 0}

        # Build composite filter
        filters = {}
        for key in composite_keys[doctype]:
            if record.get(key):
                filters[key] = record[key]

        if len(filters) == len(composite_keys[doctype]):
            # All composite key fields are present
            existing = frappe.get_all(doctype, filters=filters, fields=["name", "creation"])

            if existing:
                matches.extend(
                    [
                        {
                            "name": e.name,
                            "reason": "composite_key",
                            "confidence": 85,
                            "key_fields": list(filters.keys()),
                        }
                        for e in existing
                    ]
                )
                confidence = 85

        return {"matches": matches, "confidence": confidence}


class TemporalMatchStrategy:
    """Detect duplicates based on temporal proximity"""

    def detect(self, doctype, record):
        """Detect matches based on time-based patterns"""
        matches = []
        confidence = 0

        # Only applicable to transactional doctypes
        if doctype not in ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"]:
            return {"matches": [], "confidence": 0}

        # Check for records created within a very short time window
        if record.get("posting_date") and (record.get("grand_total") or record.get("paid_amount")):
            date = getdate(record["posting_date"])
            amount_field = "grand_total" if "grand_total" in record else "paid_amount"
            amount = flt(record[amount_field])

            # Look for exact amount on same date
            filters = {"posting_date": date, amount_field: amount}

            # Add party filter if available
            if record.get("customer"):
                filters["customer"] = record["customer"]
            elif record.get("supplier"):
                filters["supplier"] = record["supplier"]
            elif record.get("party"):
                filters["party"] = record["party"]

            existing = frappe.get_all(doctype, filters=filters, fields=["name", "creation", "modified"])

            # Check creation time proximity
            for e in existing:
                # If created within 5 minutes, likely duplicate
                if record.get("creation"):
                    time_diff = abs((getdate(record["creation"]) - getdate(e.creation)).total_seconds())
                    if time_diff < 300:  # 5 minutes
                        matches.append(
                            {
                                "name": e.name,
                                "reason": "temporal_proximity",
                                "confidence": 75,
                                "time_diff_seconds": time_diff,
                            }
                        )
                        confidence = max(confidence, 75)

        return {"matches": matches, "confidence": confidence}


class DuplicateMerger:
    """Handles merging of duplicate records"""

    def merge_duplicates(self, doctype, primary_record, duplicate_records):
        """
        Merge duplicate records into primary record

        Args:
            doctype: Document type
            primary_record: The record to keep
            duplicate_records: List of duplicate record names to merge

        Returns:
            Merge result with details
        """
        result = {"success": False, "merged_count": 0, "errors": [], "merge_log": []}

        try:
            # Get primary document
            primary_doc = frappe.get_doc(doctype, primary_record)

            for duplicate_name in duplicate_records:
                try:
                    duplicate_doc = frappe.get_doc(doctype, duplicate_name)

                    # Merge based on doctype
                    if doctype in ["Customer", "Supplier"]:
                        self._merge_party(primary_doc, duplicate_doc)
                    elif doctype in ["Sales Invoice", "Purchase Invoice"]:
                        self._merge_invoice(primary_doc, duplicate_doc)
                    else:
                        # Generic merge - update references
                        self._update_references(doctype, duplicate_name, primary_record)

                    # Cancel and delete duplicate
                    if duplicate_doc.docstatus == 1:
                        duplicate_doc.cancel()

                    # Delete if allowed
                    if not frappe.db.exists("GL Entry", {"voucher_no": duplicate_name}):
                        frappe.delete_doc(doctype, duplicate_name, force=True)
                        result["merge_log"].append("Deleted duplicate: {duplicate_name}")
                    else:
                        result["merge_log"].append("Cancelled duplicate: {duplicate_name} (has GL entries)")

                    result["merged_count"] += 1

                except Exception as e:
                    result["errors"].append({"duplicate": duplicate_name, "error": str(e)})

            # Save primary document with merged data
            primary_doc.save()
            result["success"] = True

        except Exception as e:
            result["errors"].append({"primary": primary_record, "error": str(e)})

        return result

    def _merge_party(self, primary, duplicate):
        """Merge customer/supplier records"""
        # Merge contact information
        if not primary.email_id and duplicate.email_id:
            primary.email_id = duplicate.email_id

        if not primary.mobile_no and duplicate.mobile_no:
            primary.mobile_no = duplicate.mobile_no

        # Merge custom fields
        for field in duplicate.meta.fields:
            if field.fieldtype not in ["Section Break", "Column Break", "Tab Break"]:
                if not primary.get(field.fieldname) and duplicate.get(field.fieldname):
                    primary.set(field.fieldname, duplicate.get(field.fieldname))

    def _merge_invoice(self, primary, duplicate):
        """Merge invoice records"""
        # Add items from duplicate if not present
        primary_items = [item.item_code for item in primary.items]

        for dup_item in duplicate.items:
            if dup_item.item_code not in primary_items:
                primary.append("items", dup_item.as_dict())

    def _update_references(self, doctype, old_name, new_name):
        """Update all references from old name to new name"""
        # Get all link fields pointing to this doctype
        link_fields = frappe.get_all(
            "DocField", filters={"fieldtype": "Link", "options": doctype}, fields=["parent", "fieldname"]
        )

        for field in link_fields:
            if frappe.db.table_exists(f"tab{field.parent}"):
                frappe.db.sql(
                    f"""
                    UPDATE `tab{field.parent}`
                    SET `{field.fieldname}` = %s
                    WHERE `{field.fieldname}` = %s
                """,
                    (new_name, old_name),
                )


@frappe.whitelist()
def detect_migration_duplicates(doctype, filters=None):
    """Detect all duplicates for a doctype"""
    detector = DuplicateDetector()

    # Get all records
    records = frappe.get_all(
        doctype, filters=filters or {}, fields=["name"] + detector._get_key_fields(doctype), limit=1000
    )

    duplicates = []
    processed = set()

    for record in records:
        if record["name"] in processed:
            continue

        result = detector.check_duplicate(doctype, record)

        if result["is_duplicate"]:
            duplicate_group = {
                "primary": record["name"],
                "duplicates": [m["name"] for m in result["matches"] if m["name"] != record["name"]],
                "confidence": result["confidence"],
                "detection_method": list(result["strategy_results"].keys()),
            }

            duplicates.append(duplicate_group)
            processed.add(record["name"])
            processed.update(duplicate_group["duplicates"])

    return {
        "doctype": doctype,
        "total_records": len(records),
        "duplicate_groups": duplicates,
        "total_duplicates": sum(len(d["duplicates"]) for d in duplicates),
    }


@frappe.whitelist()
def merge_duplicate_group(doctype, primary, duplicates):
    """Merge a group of duplicates"""
    merger = DuplicateMerger()
    return merger.merge_duplicates(doctype, primary, duplicates)
