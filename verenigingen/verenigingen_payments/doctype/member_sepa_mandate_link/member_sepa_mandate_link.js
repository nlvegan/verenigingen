/**
 * @fileoverview Member SEPA Mandate Link Controller
 * @description Manages the relationship between members and their SEPA payment mandates
 *
 * Business Context:
 * Handles the critical relationship between association members and their
 * authorized SEPA direct debit mandates, ensuring compliance with European
 * banking regulations and maintaining accurate payment authorization records.
 *
 * Key Features:
 * - Automatic mandate detail synchronization
 * - Mutual exclusivity for current mandate designation
 * - Validation period tracking for compliance
 * - Status inheritance from parent mandate records
 *
 * SEPA Compliance:
 * - Mandate reference tracking for audit requirements
 * - Validity period enforcement for regulatory compliance
 * - Status synchronization with banking mandate changes
 * - Historical record maintenance for disputes
 *
 * Data Integrity:
 * - Single current mandate constraint enforcement
 * - Automatic field population to prevent errors
 * - Real-time status updates from mandate source
 * - Cross-reference validation for consistency
 *
 * Integration Points:
 * - SEPA Mandate DocType for mandate details
 * - Payment processing systems for authorization
 * - Member financial records for payment history
 * - Banking interfaces for mandate validation
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module MemberSEPAMandateLink
 * @requires frappe.ui.form, frappe.db
 */

frappe.ui.form.on('Member SEPA Mandate Link', {
	sepa_mandate(frm, cdt, cdn) {
		// When a mandate is selected, fetch its details
		const row = locals[cdt][cdn];

		if (row.sepa_mandate) {
			frappe.db.get_value('SEPA Mandate', row.sepa_mandate,
				['mandate_id', 'status', 'sign_date', 'expiry_date'],
				(r) => {
					if (r) {
						frappe.model.set_value(cdt, cdn, 'mandate_reference', r.mandate_id);
						frappe.model.set_value(cdt, cdn, 'status', r.status);
						frappe.model.set_value(cdt, cdn, 'valid_from', r.sign_date);
						frappe.model.set_value(cdt, cdn, 'valid_until', r.expiry_date);
					}
				}
			);
		}
	},

	is_current(frm, cdt, cdn) {
		// When setting a mandate as current, unset others
		const row = locals[cdt][cdn];

		if (row.is_current) {
			// Unset current on other mandates
			frm.doc.sepa_mandates.forEach((mandate) => {
				if (mandate.name !== cdn && mandate.is_current) {
					frappe.model.set_value(mandate.doctype, mandate.name, 'is_current', 0);
				}
			});
		}
	}
});
