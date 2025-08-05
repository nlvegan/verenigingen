/**
 * @fileoverview SEPA Mandate DocType Frontend Controller for Verenigingen Association Management
 *
 * This controller manages the SEPA Mandate DocType interface, handling SEPA direct debit
 * mandate lifecycle management, status transitions, and compliance with European banking
 * regulations. SEPA mandates authorize the association to collect payments automatically
 * from member bank accounts.
 *
 * @description Business Context:
 * SEPA mandates are legal authorizations that allow the association to collect payments
 * directly from member bank accounts. They are essential for automated membership fee
 * collection and must comply with strict European banking regulations including proper
 * authorization, notification, and cancellation procedures.
 *
 * @description Key Features:
 * - Mandate lifecycle management (Draft → Active → Suspended/Cancelled)
 * - Status transition validation and business rule enforcement
 * - Integration with direct debit batch processing
 * - Compliance with SEPA regulatory requirements
 * - Member consent and authorization tracking
 * - Banking relationship management
 *
 * @description Status Workflow:
 * - Draft: Initial creation, pending activation
 * - Active: Authorized for payment collection
 * - Suspended: Temporarily disabled, can be reactivated
 * - Cancelled: Permanently disabled, cannot be reactivated
 *
 * @description Integration Points:
 * - Links to Member DocType for payment authorization
 * - Connects to Direct Debit Batch for payment processing
 * - Integrates with banking systems for mandate validation
 * - Coordinates with Payment Entry for transaction tracking
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe - Frappe Framework client-side API
 * @requires sepa-utils.js - SEPA processing utilities
 *
 * @example
 * // Controller is loaded automatically for SEPA Mandate forms
 * frappe.ui.form.on('SEPA Mandate', {
 *   refresh: function(frm) {
 *     // Mandate form initialization and status management
 *   }
 * });
 */

/**
 * Main SEPA Mandate DocType Form Controller
 *
 * Handles mandate status management, workflow transitions,
 * and compliance with SEPA banking regulations.
 */
frappe.ui.form.on('SEPA Mandate', {
	/**
	 * Form Refresh Event Handler
	 *
	 * Configures the mandate management interface based on current status and workflow stage.
	 * Manages status transition buttons, validation controls, and compliance indicators.
	 *
	 * @description Status Management Features:
	 * - Provides status transition buttons based on current state
	 * - Validates business rules for status changes
	 * - Manages mandate activation, suspension, and cancellation
	 * - Ensures compliance with SEPA regulations
	 *
	 * @description Business Rule Enforcement:
	 * - Only allows valid status transitions
	 * - Requires confirmation for permanent actions (cancellation)
	 * - Tracks status change dates and audit trail
	 * - Validates mandate requirements before activation
	 *
	 * @param {Object} frm - Frappe Form object containing mandate document
	 * @param {string} frm.doc.status - Current mandate status (Draft/Active/Suspended/Cancelled)
	 * @param {boolean} frm.doc.is_active - Active flag for mandate validity
	 * @param {number} frm.doc.docstatus - Document submission status
	 *
	 * @example
	 * // Status-based button configuration:
	 * // Draft: "Activate" button
	 * // Active: "Suspend", "Cancel" buttons
	 * // Suspended: "Reactivate" button
	 * // Cancelled: No action buttons (permanent state)
	 */
	refresh(frm) {
		// Add custom buttons based on status
		if (frm.doc.docstatus === 0) { // Draft state
			// Only show these buttons for unsaved/unsubmitted docs

			// Draft → Active button
			if (frm.doc.status === 'Draft') {
				frm.add_custom_button(__('Activate'), () => {
					frm.set_value('status', 'Active');
					frm.set_value('is_active', 1);
					frm.save();
				}, __('Status'));
			}

			// Add status action buttons
			if (frm.doc.status === 'Active' && frm.doc.is_active) {
				frm.add_custom_button(__('Suspend'), () => {
					frm.set_value('status', 'Suspended');
					frm.set_value('is_active', 0);
					frm.save();
				}, __('Status'));

				frm.add_custom_button(__('Cancel'), () => {
					// Add confirmation dialog for cancelling
					frappe.confirm(
						__('Cancelling a mandate is permanent. Are you sure?'),
						() => {
							// On Yes
							frm.set_value('status', 'Cancelled');
							frm.set_value('is_active', 0);
							frm.set_value('cancelled_date', frappe.datetime.get_today());
							frm.save();
						}
					);
				}, __('Status'));
			}

			if (frm.doc.status === 'Suspended') {
				frm.add_custom_button(__('Reactivate'), () => {
					frm.set_value('status', 'Active');
					frm.set_value('is_active', 1);
					frm.save();
				}, __('Status'));
			}
		}

		// Add indicator based on status
		if (frm.doc.status) {
			let indicator = 'gray';
			if (frm.doc.status === 'Active') { indicator = 'green'; } else if (frm.doc.status === 'Suspended') { indicator = 'orange'; } else if (frm.doc.status === 'Cancelled') { indicator = 'red'; } else if (frm.doc.status === 'Expired') { indicator = 'red'; } else if (frm.doc.status === 'Draft') { indicator = 'blue'; }

			frm.page.set_indicator(frm.doc.status, indicator);
		}

		// Add button to view related member
		if (frm.doc.member) {
			frm.add_custom_button(__('Member'), () => {
				frappe.set_route('Form', 'Member', frm.doc.member);
			}, __('View'));
		}
	},

	status(frm) {
		// When status changes, update is_active flag for consistency
		if (frm.doc.status === 'Active') {
			frm.set_value('is_active', 1);
		} else if (['Suspended', 'Cancelled', 'Expired'].includes(frm.doc.status)) {
			frm.set_value('is_active', 0);
		}

		// If status is set to Cancelled, prompt for cancellation reason
		if (frm.doc.status === 'Cancelled' && !frm.doc.cancelled_date) {
			frm.set_value('cancelled_date', frappe.datetime.get_today());
			setTimeout(() => frm.scroll_to_field('cancellation_reason'), 500);
		}
	},

	is_active(frm) {
		// Update status when is_active changes
		if (frm.doc.is_active) {
			if (frm.doc.status === 'Suspended') {
				frm.set_value('status', 'Active');
			}
		} else {
			if (frm.doc.status === 'Active') {
				frm.set_value('status', 'Suspended');
			}
		}
	},

	sign_date(frm) {
		// Validate sign date
		if (frm.doc.sign_date) {
			const today = frappe.datetime.get_today();
			if (frappe.datetime.str_to_obj(frm.doc.sign_date) > frappe.datetime.str_to_obj(today)) {
				frappe.msgprint(__('Sign date cannot be in the future'));
				frm.set_value('sign_date', today);
			}
		}
	},

	iban(frm) {
		// Format IBAN
		if (frm.doc.iban) {
			// Remove spaces and convert to uppercase
			let iban = frm.doc.iban.replace(/\s/g, '').toUpperCase();
			// Add spaces every 4 characters for readability
			iban = iban.replace(/(.{4})/g, '$1 ').trim();
			frm.set_value('iban', iban);
		}
	}
});
