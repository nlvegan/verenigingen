# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class EBoekhoudenAccountMapping(Document):
    def validate(self):
        # Validate account range if specified
        if self.account_range_start and self.account_range_end:
            if self.account_range_start > self.account_range_end:
                frappe.throw("Account Range Start must be less than or equal to Account Range End")

        # If specific account code is provided, clear ranges
        if self.account_code:
            self.account_range_start = None
            self.account_range_end = None

    def matches_account(self, account_code):
        """Check if this mapping matches the given account code"""
        if not self.is_active:
            return False

        if not account_code:
            return False

        # Check specific account code
        if self.account_code:
            return self.account_code == account_code

        # Check account range
        if self.account_range_start and self.account_range_end:
            return self.account_range_start <= account_code <= self.account_range_end

        return False

    def matches_description(self, description):
        """Check if this mapping matches the given description"""
        if not self.is_active:
            return False

        if not description or not self.description_patterns:
            return False

        description_lower = description.lower()
        patterns = [p.strip().lower() for p in self.description_patterns.split("\n") if p.strip()]

        return any(pattern in description_lower for pattern in patterns)

    def record_usage(self, description=None):
        """Record that this mapping was used"""
        self.usage_count = (self.usage_count or 0) + 1
        self.last_used = now()

        # Add to sample descriptions
        if description:
            existing_samples = self.sample_descriptions or ""
            samples = [s.strip() for s in existing_samples.split("\n") if s.strip()]

            # Keep only unique samples, max 5
            if description not in samples:
                samples.append(description[:100])  # Truncate long descriptions
                samples = samples[-5:]  # Keep last 5
                self.sample_descriptions = "\n".join(samples)

        self.save(ignore_permissions=True)


@frappe.whitelist()
def get_mapping_for_mutation(account_code, description):
    """Get the appropriate mapping for a mutation based on account code and description"""
    # First try to find by account code
    if account_code:
        # Check specific account mappings
        mapping = frappe.db.get_value(
            "E-Boekhouden Account Mapping",
            {"is_active": 1, "account_code": account_code},
            ["name", "document_type", "transaction_category"],
            as_dict=True,
            order_by="priority desc",
        )

        if mapping:
            return mapping

        # Check account ranges
        mappings = frappe.get_all(
            "E-Boekhouden Account Mapping",
            filters={"is_active": 1, "account_range_start": ["!=", ""], "account_range_end": ["!=", ""]},
            fields=[
                "name",
                "document_type",
                "transaction_category",
                "account_range_start",
                "account_range_end",
                "priority",
            ],
            order_by="priority desc",
        )

        for m in mappings:
            if m.account_range_start <= account_code <= m.account_range_end:
                return {
                    "name": m.name,
                    "document_type": m.document_type,
                    "transaction_category": m.transaction_category,
                }

    # Then try description patterns
    if description:
        mappings = frappe.get_all(
            "E-Boekhouden Account Mapping",
            filters={"is_active": 1, "description_patterns": ["!=", ""]},
            fields=["name", "document_type", "transaction_category", "description_patterns", "priority"],
            order_by="priority desc",
        )

        description_lower = description.lower()
        for m in mappings:
            patterns = [p.strip().lower() for p in m.description_patterns.split("\n") if p.strip()]
            if any(pattern in description_lower for pattern in patterns):
                return {
                    "name": m.name,
                    "document_type": m.document_type,
                    "transaction_category": m.transaction_category,
                }

    # Default to Purchase Invoice
    return {"name": None, "document_type": "Purchase Invoice", "transaction_category": "General Expenses"}


@frappe.whitelist()
def create_default_mappings():
    """Create default mappings based on common Dutch accounting patterns"""
    default_mappings = [
        # Wages and salaries
        {
            "account_range_start": "40000",
            "account_range_end": "40999",
            "account_name": "Wages and Salaries",
            "document_type": "Journal Entry",
            "transaction_category": "Wages and Salaries",
            "priority": 100,
        },
        # Social charges
        {
            "account_range_start": "41000",
            "account_range_end": "41999",
            "account_name": "Social Charges",
            "document_type": "Journal Entry",
            "transaction_category": "Social Charges",
            "priority": 100,
        },
        # Tax payments - description based
        {
            "description_patterns": "belastingdienst\nloonheffing\nbtw aangifte\nomzetbelasting",
            "account_name": "Tax Payments",
            "document_type": "Journal Entry",
            "transaction_category": "Tax Payments",
            "priority": 90,
        },
        # Pension - description based
        {
            "description_patterns": "pensioenfonds\npensioen\noudedagsvoorziening",
            "account_name": "Pension Contributions",
            "document_type": "Journal Entry",
            "transaction_category": "Pension Contributions",
            "priority": 90,
        },
        # Bank charges
        {
            "description_patterns": "bank\nkosten\nfee\nprovisie",
            "account_name": "Bank Charges",
            "document_type": "Journal Entry",
            "transaction_category": "Bank Charges",
            "priority": 80,
        },
    ]

    created = 0
    for mapping_data in default_mappings:
        if not frappe.db.exists(
            "E-Boekhouden Account Mapping", {"account_name": mapping_data["account_name"]}
        ):
            doc = frappe.new_doc("E-Boekhouden Account Mapping")
            doc.update(mapping_data)
            doc.insert(ignore_permissions=True)
            created += 1

    return {"created": created, "message": f"Created {created} default mappings"}
