/**
 * @fileoverview Donation Type List View Settings - List view configuration for Donation Type DocType
 *
 * This module configures the list view behavior for the Donation Type DocType,
 * defining additional fields to display for enhanced donation type management
 * and categorization of different donation categories within the system.
 *
 * Key Features:
 * - Enhanced field display for donation type identification
 * - Clear categorization of donation types
 * - Streamlined donation type management interface
 * - Quick access to donation type information
 *
 * List View Enhancements:
 * - Donation type name prominently displayed
 * - Easy identification of different donation categories
 * - Clean presentation of donation type data
 * - Support for donation workflow management
 *
 * Business Context:
 * - Facilitates donation categorization and tracking
 * - Supports fundraising campaign organization
 * - Enables donation reporting by type
 * - Assists in donor communication customization
 * - Helps maintain donation taxonomy consistency
 *
 * Usage:
 * This configuration is automatically applied when users view the
 * Donation Type list view in the Frappe framework. The enhanced
 * display helps administrators manage different types of donations
 * such as general donations, memorial gifts, event sponsorships, etc.
 *
 * Integration:
 * - Works with Donation DocType for contribution categorization
 * - Supports fundraising campaign management
 * - Integrates with donor communication workflows
 * - Enables donation analytics and reporting
 *
 * Common Donation Types:
 * - General Donation
 * - Memorial Gift
 * - Sponsorship
 * - Event Donation
 * - Recurring Donation
 * - Major Gift
 *
 * @module donation_type_list
 * @version 1.0.0
 * @since 1.0.0
 * @requires frappe
 * @see {@link https://frappeframework.com/docs/user/en/desk/list-view|Frappe List View}
 * @see {@link donation_type.js|Donation Type Controller}
 * @see {@link ../donation/donation.js|Donation Controller}
 *
 * @author Verenigingen System
 * @copyright 2024 Verenigingen
 */

/**
 * Donation Type List View Settings
 *
 * Configures the list view display for Donation Type records,
 * including additional fields for enhanced type identification
 * and management.
 *
 * @namespace frappe.listview_settings.DonationType
 */
frappe.listview_settings['Donation Type'] = {
	/**
	 * Additional fields to display in list view beyond the standard fields
	 *
	 * Includes the donation type name for clear identification and
	 * categorization of different donation types in the system.
	 *
	 * @type {Array<string>}
	 */
	add_fields: ['donation_type']
};
