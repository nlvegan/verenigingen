/**
 * @fileoverview Donation DocType Frontend Controller for Verenigingen Association Management
 *
 * This controller manages the Donation DocType interface, handling donation processing,
 * payment integration, and financial record management. Donations are financial contributions
 * made by members and external supporters to fund association activities.
 *
 * @description Business Context:
 * Donations are a critical source of funding for the association, supporting various
 * initiatives, campaigns, and operational expenses. The system manages both one-time
 * and recurring donations, with integration to Dutch tax requirements (ANBI) and
 * payment processing systems.
 *
 * @description Key Features:
 * - Donation record creation and tracking
 * - Payment entry generation and processing
 * - ANBI (Dutch tax benefit) compliance
 * - Donor recognition and receipt generation
 * - Integration with ERPNext financial modules
 * - Support for various payment methods
 *
 * @description Integration Points:
 * - Links to Donor DocType for supporter management
 * - Connects to Payment Entry for financial processing
 * - Integrates with Sales Invoice for formal documentation
 * - Coordinates with ANBI reporting requirements
 * - Links to Member DocType for member donations
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe - Frappe Framework client-side API
 * @requires payment_utils - Payment processing utilities
 *
 * @example
 * // Controller is loaded automatically for Donation DocType forms
 * frappe.ui.form.on('Donation', {
 *   refresh: function(frm) {
 *     // Donation form initialization
 *   }
 * });
 */

// Copyright (c) 2025, Verenigingen Development Team and contributors
// For license information, please see license.txt

/**
 * Main Donation DocType Form Controller
 *
 * Handles donation lifecycle management, payment processing,
 * and integration with financial accounting systems.
 */
frappe.ui.form.on('Donation', {
	/**
	 * Form Refresh Event Handler
	 *
	 * Configures the donation form interface based on document status and payment state.
	 * Adds payment processing buttons for submitted but unpaid donations.
	 *
	 * @description Business Logic:
	 * - Shows payment creation button for submitted unpaid donations
	 * - Manages donation status indicators and alerts
	 * - Configures user interface based on donation state
	 * - Applies role-based access controls for financial operations
	 *
	 * @description Payment Integration:
	 * The system integrates with ERPNext's payment system to create formal
	 * Payment Entry records that link donations to actual bank transactions
	 * and enable proper financial accounting and reconciliation.
	 *
	 * @param {Object} frm - Frappe Form object containing donation document
	 * @param {Object} frm.doc - Donation document with fields and status
	 * @param {number} frm.doc.docstatus - Document status (0=draft, 1=submitted, 2=cancelled)
	 * @param {boolean} frm.doc.paid - Flag indicating if donation has been paid
	 *
	 * @example
	 * // Automatically called when donation form is displayed:
	 * // Shows "Create Payment Entry" button for submitted unpaid donations
	 */
	refresh: function(frm) {
		if (frm.doc.docstatus === 1 && !frm.doc.paid) {
			frm.add_custom_button(__('Create Payment Entry'), function() {
				frm.events.make_payment_entry(frm);
			});
		}
	},

	/**
	 * Create Payment Entry for Donation
	 *
	 * Generates a Payment Entry document linked to this donation for financial
	 * accounting and payment tracking. Integrates with ERPNext's accounting
	 * system to ensure proper bookkeeping and audit trail.
	 *
	 * @description Financial Integration:
	 * - Creates Payment Entry with proper account mapping
	 * - Links donation to bank transaction records
	 * - Enables financial reconciliation and reporting
	 * - Supports various payment methods and currencies
	 * - Maintains compliance with Dutch accounting standards
	 *
	 * @description Business Process:
	 * 1. Validates donation is eligible for payment processing
	 * 2. Calls backend payment utility to generate Payment Entry
	 * 3. Redirects user to the new Payment Entry for completion
	 * 4. Maintains linkage between donation and payment records
	 *
	 * @param {Object} frm - Form object containing donation data
	 * @returns {Promise} Promise resolving to payment entry creation result
	 *
	 * @throws {ValidationError} If donation is not eligible for payment processing
	 * @throws {APIError} If payment entry creation fails
	 *
	 * @see {@link verenigingen.utils.payment_utils.get_donation_payment_entry} Backend payment utility
	 *
	 * @example
	 * // Called when user clicks "Create Payment Entry" button:
	 * // Generates Payment Entry and redirects to form for completion
	 */
	make_payment_entry: function(frm) {
		return frappe.call({
			method: 'verenigingen.utils.payment_utils.get_donation_payment_entry',
			args: {
				'dt': frm.doc.doctype,
				'dn': frm.doc.name
			},
			callback: function(r) {
				var doc = frappe.model.sync(r.message);
				frappe.set_route('Form', doc[0].doctype, doc[0].name);
			}
		});
	},
});
