/**
 * @fileoverview Donation List View Settings - List view configuration for Donation DocType
 *
 * This module configures the list view behavior for the Donation DocType,
 * defining which fields to display, status indicators, and visual styling
 * to provide users with quick insights into donation records and their
 * payment status.
 *
 * Key Features:
 * - Additional field display for comprehensive donation overview
 * - Visual status indicators for payment status
 * - Color-coded payment status (Paid/Pending)
 * - Quick filtering by payment status
 *
 * List View Enhancements:
 * - Donor information prominently displayed
 * - Amount and payment method visible at glance
 * - Date information for chronological sorting
 * - Payment status with intuitive color coding
 *
 * Visual Indicators:
 * - Green indicator for paid donations
 * - Orange indicator for pending donations
 * - Clickable indicators for quick filtering
 *
 * Usage:
 * This configuration is automatically applied when users view the
 * Donation list view in the Frappe framework. The settings enhance
 * the default list view to show donation-specific information.
 *
 * Business Context:
 * - Helps administrators quickly identify payment status
 * - Enables efficient donation management workflows
 * - Supports financial reporting and follow-up processes
 * - Facilitates donor relationship management
 *
 * @module donation_list
 * @version 1.1.0
 * @since 1.0.0
 * @requires frappe
 * @see {@link https://frappeframework.com/docs/user/en/desk/list-view|Frappe List View}
 * @see {@link donation.js|Donation Controller}
 * @see {@link ../../donor/donor.js|Donor Controller}
 *
 * @author Verenigingen System
 * @copyright 2024 Verenigingen
 */

/**
 * Donation List View Settings
 *
 * Configures the list view display and behavior for Donation records,
 * including additional fields, status indicators, and visual styling.
 *
 * @namespace frappe.listview_settings.Donation
 */
frappe.listview_settings['Donation'] = {
	/**
	 * Additional fields to display in list view beyond the standard fields
	 *
	 * @type {Array<string>}
	 */
	add_fields: ['donor', 'amount', 'paid', 'payment_method', 'date'],

	/**
	 * Generate status indicator for donation records based on payment status
	 *
	 * @param {Object} doc - Document object containing donation data
	 * @param {string} doc.paid - Payment status (1 for paid, 0 for pending)
	 * @returns {Array} Indicator configuration [label, color, filter]
	 */
	get_indicator(doc) {
		return [__(doc.paid ? 'Paid' : 'Pending'),
			doc.paid ? 'green' : 'orange', `paid,=,${doc.paid}`];
	}
};
