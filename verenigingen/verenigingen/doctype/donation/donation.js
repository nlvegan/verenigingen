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
 * - ANBI (Dutch tax benefit) compliance
 * - Donor recognition and receipt generation
 * - Support for various payment methods
 *
 * @description Financial Processing:
 * A donation does NOT reach the ledger through a Payment Entry. Incoming
 * donation payments post as Bank Transaction -> Journal Entry
 * (verenigingen_payments/services/donation_journal_entry_creator.py). Payment
 * Entry was the ERPNext Non Profit module's treatment, which this app no longer
 * follows.
 *
 * @description Integration Points:
 * - Links to Donor DocType for supporter management
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
 * Handles donation lifecycle management and integration with ANBI reporting.
 */
frappe.ui.form.on('Donation', {
	/**
	 * Form Refresh Event Handler
	 *
	 * @description
	 * Intentionally empty. This handler used to add a "Create Payment Entry"
	 * button, inherited from the ERPNext Non Profit module where Donation was
	 * submittable and settled via Payment Entry. Both halves of that assumption
	 * are gone: this app's Donation has never had `is_submittable`, so the
	 * button's `docstatus === 1` gate never fired, and donation payments now post
	 * as Bank Transaction -> Journal Entry. The button and its handler were
	 * removed rather than re-gated — reinstating them would create a document
	 * type this architecture does not use for donations.
	 *
	 * @param {Object} frm - Frappe Form object containing donation document
	 */
	refresh(_frm) {
		// No Payment Entry affordance here — see the handler docstring above.
	}
});
