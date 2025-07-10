#!/usr/bin/env python3
"""
Analyze why the cleanup function missed eBoekhouden Payment Entries
"""

import frappe


@frappe.whitelist()
def analyze_missed_payments():
    """Analyze why Payment Entries were missed by cleanup"""
    try:
        company = "Ned Ver Vegan"

        # Get sample Payment Entries that were missed
        sample_pes = frappe.db.sql(
            """SELECT name, payment_type, party_type, party, paid_amount,
                      reference_no, remarks, creation, docstatus
               FROM `tabPayment Entry`
               WHERE company = %s
               ORDER BY creation DESC
               LIMIT 10""",
            (company,),
            as_dict=True,
        )

        analysis = {
            "company": company,
            "sample_entries": sample_pes,
            "pattern_analysis": {},
            "detection_issues": [],
        }

        # Analyze the patterns that were used in cleanup
        for pe in sample_pes:
            entry_analysis = {
                "name": pe["name"],
                "party": pe["party"],
                "reference_no": pe["reference_no"],
                "remarks": pe["remarks"],
                "pattern_matches": {},
            }

            # Check each pattern that was used in cleanup
            remarks = pe["remarks"] or ""
            reference_no = pe["reference_no"] or ""
            name = pe["name"] or ""

            # Pattern 1: remarks LIKE '%eBoekhouden%'
            entry_analysis["pattern_matches"]["remarks_eBoekhouden"] = "eBoekhouden" in remarks.lower()

            # Pattern 2: remarks LIKE '%E-Boekhouden%'
            entry_analysis["pattern_matches"]["remarks_E_Boekhouden"] = "E-Boekhouden" in remarks

            # Pattern 3: reference_no LIKE '%EBH-%'
            entry_analysis["pattern_matches"]["reference_EBH"] = "EBH-" in reference_no

            # Pattern 4: name LIKE '%EBH-%'
            entry_analysis["pattern_matches"]["name_EBH"] = "EBH-" in name

            # Check if ANY pattern matched
            any_match = any(entry_analysis["pattern_matches"].values())
            entry_analysis["would_be_detected"] = any_match

            if not any_match:
                analysis["detection_issues"].append("Entry {name} not detected by any pattern")

            analysis["pattern_analysis"][pe["name"]] = entry_analysis

        # Check for custom fields
        custom_field_analysis = {}
        try:
            # Check if eboekhouden_mutation_nr field exists
            custom_field_analysis["eboekhouden_mutation_nr_exists"] = frappe.db.has_column(
                "Payment Entry", "eboekhouden_mutation_nr"
            )

            if custom_field_analysis["eboekhouden_mutation_nr_exists"]:
                # Check if any of the sample entries have this field populated
                sample_names = [pe["name"] for pe in sample_pes]
                if sample_names:
                    placeholder = ",".join(["%s"] * len(sample_names))
                    custom_field_data = frappe.db.sql(
                        f"SELECT name, eboekhouden_mutation_nr FROM `tabPayment Entry` WHERE name IN ({placeholder})",
                        sample_names,
                        as_dict=True,
                    )
                    custom_field_analysis["sample_custom_field_data"] = custom_field_data
        except Exception as e:
            custom_field_analysis["error"] = str(e)

        analysis["custom_field_analysis"] = custom_field_analysis

        # Suggest better patterns
        suggested_patterns = []

        # Pattern analysis from sample data
        for pe in sample_pes:
            remarks = pe["remarks"] or ""
            reference_no = pe["reference_no"] or ""

            # Look for mutation references
            if "M2025" in reference_no or "M2024" in reference_no:
                suggested_patterns.append("reference_no contains M20XX pattern")

            # Look for "Transaction reference no" in remarks
            if "Transaction reference no" in remarks:
                suggested_patterns.append("remarks contains 'Transaction reference no'")

            # Look for "Amount EUR" in remarks
            if "Amount EUR" in remarks:
                suggested_patterns.append("remarks contains 'Amount EUR'")

        analysis["suggested_patterns"] = list(set(suggested_patterns))

        return analysis

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
