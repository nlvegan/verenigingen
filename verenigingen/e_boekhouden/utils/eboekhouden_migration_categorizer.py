"""
Enhanced categorization for E-Boekhouden migration results
Provides more accurate descriptions of transaction processing outcomes
"""

from collections import defaultdict


class MigrationCategorizer:
    """Categorizes migration results into meaningful categories"""

    def __init__(self):
        self.categories = {
            # Successfully processed
            "imported": {
                "label": "Successfully Imported",
                "description": "New records created in ERPNext",
                "count": 0,
                "color": "green",
            },
            # Skipped - Already exists
            "already_exists": {
                "label": "Already Exists",
                "description": "Records previously imported, skipped to avoid duplicates",
                "count": 0,
                "color": "blue",
            },
            # Skipped - Unmatched but handled
            "unmatched_handled": {
                "label": "Unmatched (Handled)",
                "description": "Payments without invoices, created as unreconciled entries",
                "count": 0,
                "color": "orange",
            },
            # Skipped - Business rules
            "business_skip": {
                "label": "Business Rules Skip",
                "description": "Skipped due to business rules (zero amount, already paid, etc.)",
                "count": 0,
                "subcategories": {"zero_amount": 0, "already_paid": 0, "no_reference": 0},
                "color": "gray",
            },
            # Validation errors
            "validation_error": {
                "label": "Validation Errors",
                "description": "Failed due to data validation issues",
                "count": 0,
                "subcategories": {
                    "missing_required_field": 0,
                    "invalid_date": 0,
                    "invalid_amount": 0,
                    "missing_party": 0,
                    "negative_stock": 0,
                },
                "color": "yellow",
            },
            # System errors
            "system_error": {
                "label": "System Errors",
                "description": "Failed due to system issues (should be investigated)",
                "count": 0,
                "subcategories": {
                    "database_error": 0,
                    "configuration_error": 0,
                    "unknown_error": 0,
                    "missing_supplier": 0,
                    "missing_customer": 0,
                    "cost_center_not_group": 0,
                    "missing_reference": 0,
                    "permission_error": 0,
                    "invalid_link": 0,
                    "accounting_error": 0,
                },
                "color": "red",
            },
            # Retry attempts
            "retry_attempt": {
                "label": "Retry Attempts",
                "description": "Duplicate processing attempts (not actual failures)",
                "count": 0,
                "color": "purple",
            },
            # Unhandled mutation types
            "unhandled_type": {
                "label": "Unhandled Types",
                "description": "Mutation types not supported by this migration",
                "count": 0,
                "color": "gray",
            },
        }

        self.error_to_category_map = {
            # Business skips
            "outstanding amount": ("business_skip", "already_paid"),
            "already paid": ("business_skip", "already_paid"),
            "zero amount": ("business_skip", "zero_amount"),
            "No amount found": ("business_skip", "zero_amount"),
            # Validation errors
            "Paid Amount is mandatory": ("validation_error", "missing_required_field"),
            "Due Date cannot be before": ("validation_error", "invalid_date"),
            "is mandatory": ("validation_error", "missing_required_field"),
            # System errors - Missing entities
            "Could not find Party: Supplier": ("system_error", "missing_supplier"),
            "Could not find Party: Customer": ("system_error", "missing_customer"),
            "does not exist": ("system_error", "configuration_error"),
            "Stock Received But Not Billed": ("system_error", "configuration_error"),
            "is not a group node": ("system_error", "cost_center_not_group"),
            "not found": ("system_error", "missing_reference"),
            # Permission errors
            "Not permitted": ("system_error", "permission_error"),
            "insufficient permissions": ("system_error", "permission_error"),
            # Financial errors
            "negative stock": ("validation_error", "negative_stock"),
            "Cannot create accounting entries": ("system_error", "accounting_error"),
            # Retry attempts
            "Duplicate entry": ("retry_attempt", None),
            "already exists": ("already_exists", None),
            # Link validation errors
            "LinkValidationError": ("system_error", "invalid_link"),
            "Link Error": ("system_error", "invalid_link"),
        }

    def categorize_result(self, success, error_msg=None, skip_reason=None):
        """Categorize a single transaction result"""

        if success and not skip_reason:
            return "imported"

        if skip_reason:
            if skip_reason == "already_imported":
                return "already_exists"
            elif skip_reason == "invoice_not_found":
                return "unmatched_handled"
            elif skip_reason in ["zero_amount", "already_paid", "no_invoice_number"]:
                return "business_skip"

        if error_msg:
            # Check error patterns
            for pattern, (category, subcategory) in self.error_to_category_map.items():
                if pattern in error_msg:
                    return category

            # Default to system error if unknown
            return "system_error"

        return "imported"

    def add_result(self, category, subcategory=None):
        """Add a result to the appropriate category"""
        if category in self.categories:
            self.categories[category]["count"] += 1

            if subcategory and "subcategories" in self.categories[category]:
                self.categories[category]["subcategories"][subcategory] += 1

    def get_summary(self):
        """Get a formatted summary of results"""
        total = sum(cat["count"] for cat in self.categories.values())

        summary = {"total_processed": total, "categories": {}}

        for key, cat in self.categories.items():
            if cat["count"] > 0:
                summary["categories"][key] = {
                    "label": cat["label"],
                    "description": cat["description"],
                    "count": cat["count"],
                    "percentage": round((cat["count"] / total * 100), 1) if total > 0 else 0,
                    "color": cat["color"],
                }

                if "subcategories" in cat:
                    summary["categories"][key]["breakdown"] = {
                        k: v for k, v in cat["subcategories"].items() if v > 0
                    }

        return summary

    def get_improved_message(self):
        """Get an improved migration summary message"""
        summary = self.get_summary()

        lines = []
        lines.append(f"Processed {summary['total_processed']} records:")

        # Show in order of importance
        order = [
            "imported",
            "unmatched_handled",
            "already_exists",
            "business_skip",
            "validation_error",
            "system_error",
            "retry_attempt",
            "unhandled_type",
        ]

        for key in order:
            if key in summary["categories"]:
                cat = summary["categories"][key]
                lines.append("- {cat['labelf']}: {cat['count']} ({cat['percentage']}%)")

                if "breakdown" in cat and cat["breakdown"]:
                    for sub_key, sub_count in cat["breakdown"].items():
                        lines.append("  • {sub_key.replace('_', ' ').title()}: {sub_count}")

        return "\n".join(lines)


def categorize_migration_results(stats, skip_reasons, errors):
    """
    Categorize migration results into meaningful categories

    Args:
        stats: Dictionary with counts like invoices_created, payments_processed, etc.
        skip_reasons: Dictionary with skip reason counts
        errors: List of error messages

    Returns:
        Dictionary with categorized results
    """
    categorizer = MigrationCategorizer()

    # Add successful imports
    imported = (
        stats.get("invoices_created", 0)
        + stats.get("payments_processed", 0)
        + stats.get("journal_entries_created", 0)
    )
    for _ in range(imported):
        categorizer.add_result("imported")

    # IMPORTANT: Do NOT count unhandled mutations as part of the categorization
    # They are mutations of types we don't process (e.g., BeginBalans, etc.)

    # Add skipped records
    for reason, count in skip_reasons.items():
        if reason == "already_imported":
            for _ in range(count):
                categorizer.add_result("already_exists")
        elif reason == "invoice_not_found":
            for _ in range(count):
                categorizer.add_result("unmatched_handled")
        elif reason in ["zero_amount", "already_paid", "no_invoice_number"]:
            for _ in range(count):
                categorizer.add_result("business_skip", reason)
        elif reason == "duplicate_entry":
            for _ in range(count):
                categorizer.add_result("retry_attempt")

    # Analyze errors
    error_counts = defaultdict(int)
    for error in errors:
        categorized = False
        for pattern, (category, subcategory) in categorizer.error_to_category_map.items():
            if pattern in error:
                categorizer.add_result(category, subcategory)
                error_counts[f"{category}:{subcategory}"] += 1
                categorized = True
                break

        if not categorized:
            categorizer.add_result("system_error", "unknown_error")
            error_counts["system_error:unknown"] += 1

    # Add unhandled mutations if present
    unhandled_count = stats.get("unhandled_mutations", 0)
    for _ in range(unhandled_count):
        categorizer.add_result("unhandled_type")

    summary = categorizer.get_summary()
    summary["improved_message"] = categorizer.get_improved_message()

    return summary
