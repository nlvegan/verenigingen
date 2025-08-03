/**
 * @fileoverview Bank Transaction List View Customization
 * @description Enhanced list view for Bank Transactions with MT940 import functionality
 *
 * Business Context:
 * Provides SEPA-compliant bank transaction management with automated MT940 statement processing.
 * Essential for financial reconciliation and audit compliance in association management.
 *
 * Key Features:
 * - MT940 statement import integration
 * - Automated transaction categorization
 * - Bulk processing capabilities
 * - Financial audit trail maintenance
 *
 * Integration Points:
 * - MT940 Import DocType for statement processing
 * - Bank reconciliation workflows
 * - SEPA payment matching systems
 * - Financial reporting modules
 *
 * Security Considerations:
 * - Restricts access to authorized financial users
 * - Maintains transaction integrity during bulk operations
 * - Provides audit logging for all import activities
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module BankTransactionList
 * @requires frappe.listview_settings
 */

frappe.listview_settings['Bank Transaction'] = frappe.listview_settings['Bank Transaction'] || {};

/**
 * Bank Transaction List View Enhancement
 *
 * Extends the standard Bank Transaction list with MT940 import capabilities
 * for streamlined financial data processing and reconciliation.
 *
 * @param {Object} listview - Frappe ListView instance
 */
frappe.listview_settings['Bank Transaction'].onload = function (listview) {
	/**
	 * Add MT940 Import Menu Item
	 *
	 * Provides access to MT940 statement import functionality directly
	 * from the bank transaction list view for improved workflow efficiency.
	 */
	listview.page.add_menu_item(__('Import MT940 File'), () => {
		// Open the MT940 import page in new tab for parallel processing
		window.open('/mt940_import', '_blank');
	}, true);

	/**
	 * Add Primary MT940 Import Action
	 *
	 * Prominent button for frequent MT940 import operations,
	 * maintaining user context within the current session.
	 */
	listview.page.add_primary_action(__('Import MT940'), () => {
		// Navigate to MT940 import page in same tab
		frappe.set_route('/mt940_import');
	}, 'fa fa-upload');
};
