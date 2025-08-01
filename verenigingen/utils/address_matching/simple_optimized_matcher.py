"""
Simple Optimized Address Matcher - No overhead version

This is a streamlined version of the address matcher focused purely on performance
without tracking, complex logic, or unnecessary features.
"""

from typing import Dict, List

import frappe


class SimpleOptimizedAddressMatcher:
    """Streamlined O(log N) address matcher with minimal overhead"""

    @staticmethod
    def get_other_members_at_address_simple(member_doc) -> List[Dict]:
        """
        Simple optimized O(log N) address matching with no overhead

        Args:
            member_doc: Member document with address information

        Returns:
            List[Dict]: List of member dictionaries
        """
        if not member_doc.primary_address:
            return []

        try:
            # Get computed fields from database if not in document
            fingerprint = getattr(member_doc, "address_fingerprint", None)

            if not fingerprint:
                # Quick database lookup for computed fields
                computed_fields = frappe.db.get_value(
                    "Member",
                    member_doc.name,
                    ["address_fingerprint", "normalized_address_line", "normalized_city"],
                    as_dict=True,
                )

                if computed_fields and computed_fields.address_fingerprint:
                    fingerprint = computed_fields.address_fingerprint
                else:
                    # Fallback to JOIN approach without normalization overhead
                    return SimpleOptimizedAddressMatcher._join_lookup_simple(member_doc)

            # Direct fingerprint lookup - this should be very fast
            return frappe.db.sql(
                """
                SELECT
                    m.name,
                    m.full_name,
                    m.email,
                    m.status,
                    m.member_since,
                    m.birth_date,
                    'Unknown' as relationship,
                    CASE
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) < 18 THEN 'Minor'
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) >= 65 THEN 'Senior'
                        ELSE 'Adult'
                    END as age_group,
                    m.contact_number,
                    DATEDIFF(CURDATE(), m.member_since) as days_member
                FROM `tabMember` m
                WHERE m.address_fingerprint = %(fingerprint)s
                    AND m.name != %(exclude_member)s
                    AND m.status IN ('Active', 'Pending', 'Suspended')
                ORDER BY m.member_since ASC, m.full_name ASC
                LIMIT 20
            """,
                {"fingerprint": fingerprint, "exclude_member": member_doc.name},
                as_dict=True,
            )

        except Exception as e:
            frappe.log_error(f"Error in simple optimized address matching for {member_doc.name}: {e}")
            return []

    @staticmethod
    def _join_lookup_simple(member_doc) -> List[Dict]:
        """Simple JOIN-based fallback when fingerprint is not available"""

        try:
            # Get address for comparison
            address = frappe.db.get_value(
                "Address", member_doc.primary_address, ["address_line1", "city"], as_dict=True
            )

            if not address or not address.address_line1 or not address.city:
                return []

            # Use simple normalization for comparison
            normalized_line = address.address_line1.lower().strip()
            normalized_city = address.city.lower().strip()

            return frappe.db.sql(
                """
                SELECT DISTINCT
                    m.name,
                    m.full_name,
                    m.email,
                    m.status,
                    m.member_since,
                    m.birth_date,
                    'Unknown' as relationship,
                    CASE
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) < 18 THEN 'Minor'
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) >= 65 THEN 'Senior'
                        ELSE 'Adult'
                    END as age_group,
                    m.contact_number,
                    DATEDIFF(CURDATE(), m.member_since) as days_member
                FROM `tabMember` m
                INNER JOIN `tabAddress` a ON m.primary_address = a.name
                WHERE LOWER(TRIM(a.address_line1)) = %(normalized_line)s
                    AND LOWER(TRIM(a.city)) = %(normalized_city)s
                    AND m.name != %(exclude_member)s
                    AND m.status IN ('Active', 'Pending', 'Suspended')
                ORDER BY m.member_since ASC, m.full_name ASC
                LIMIT 20
            """,
                {
                    "normalized_line": normalized_line,
                    "normalized_city": normalized_city,
                    "exclude_member": member_doc.name,
                },
                as_dict=True,
            )

        except Exception as e:
            frappe.log_error(f"Error in simple JOIN lookup: {e}")
            return []
