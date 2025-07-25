# Copyright (c) 2025, Nederlandse Vereniging voor Veganisme and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PartyEnrichmentQueue(Document):
    """Party Enrichment Queue for managing E-Boekhouden relation data enhancement"""

    def validate(self):
        """Validate the party enrichment queue entry"""
        # Set creation date if not set
        if not self.creation_date:
            self.creation_date = frappe.utils.now()

        # Initialize retry count
        if not self.retry_count:
            self.retry_count = 0

    def process_enrichment(self):
        """Process this enrichment queue entry"""
        try:
            from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

            resolver = EBoekhoudenPartyResolver()
            debug_info = []

            # Update status
            self.status = "In Progress"
            self.save()
            frappe.db.commit()

            # Fetch relation details
            relation_details = resolver.fetch_relation_details(self.eboekhouden_relation_id, debug_info)

            if relation_details:
                # Enrich the party
                resolver.enrich_party(self.party_doctype, self.party_name, relation_details, debug_info)

                # Mark as completed
                self.status = "Completed"
                self.completion_date = frappe.utils.now()
                self.notes = "; ".join(debug_info[-5:])  # Last 5 debug messages
            else:
                # Mark as failed
                self.status = "Failed"
                self.completion_date = frappe.utils.now()
                self.notes = "Could not fetch relation details from API"
                self.retry_count += 1

            self.save()
            return self.status == "Completed"

        except Exception as e:
            # Mark as failed
            self.status = "Failed"
            self.completion_date = frappe.utils.now()
            self.error_log = str(e)
            self.retry_count += 1
            self.save()
            return False

    @frappe.whitelist()
    def retry_enrichment(self):
        """Retry enrichment for failed entries"""
        if self.status == "Failed" and self.retry_count < 3:
            self.status = "Pending"
            self.completion_date = None
            self.error_log = None
            self.save()
            return True
        return False
