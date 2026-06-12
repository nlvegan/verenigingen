/**
 * @fileoverview Donor List View Settings - List view configuration for Donor DocType
 *
 * This module configures the list view behavior for the Donor DocType,
 * defining additional fields to display for enhanced donor management
 * and quick identification of donor types and information.
 *
 * Key Features:
 * - Enhanced field display for donor identification
 * - Donor type categorization visible at glance
 * - Image display for visual donor recognition
 * - Streamlined donor management interface
 *
 * List View Enhancements:
 * - Donor name prominently displayed for easy identification
 * - Donor type (Individual/Organization) clearly shown
 * - Profile images for visual donor recognition
 * - Clean, organized presentation of donor data
 *
 * Business Context:
 * - Facilitates quick donor identification and categorization
 * - Supports donor relationship management workflows
 * - Enables efficient donor communication and engagement
 * - Assists in donation tracking and reporting
 * - Helps maintain donor database integrity
 *
 * Usage:
 * This configuration is automatically applied when users view the
 * Donor list view in the Frappe framework. The enhanced display
 * helps administrators and fundraising staff quickly identify
 * and work with donor records.
 *
 * Integration:
 * - Works with Donation DocType for contribution tracking
 * - Supports donor communication workflows
 * - Integrates with fundraising campaign management
 * - Enables donor segmentation and analysis
 *
 * @module donor_list
 * @version 1.0.0
 * @since 1.0.0
 * @requires frappe
 * @see {@link https://frappeframework.com/docs/user/en/desk/list-view|Frappe List View}
 * @see {@link donor.js|Donor Controller}
 * @see {@link ../donation/donation.js|Donation Controller}
 *
 * @author Verenigingen System
 * @copyright 2024 Verenigingen
 */

/**
 * Donor List View Settings
 *
 * Configures the list view display for Donor records, including
 * additional fields for enhanced donor identification and management.
 *
 * @namespace frappe.listview_settings.Donor
 */
frappe.listview_settings['Donor'] = {
	/**
	 * Additional fields to display in list view beyond the standard fields
	 *
	 * Includes donor name for identification, donor type for categorization,
	 * and image for visual recognition of donors.
	 *
	 * @type {Array<string>}
	 */
	add_fields: ['donor_name', 'donor_type', 'image']
};
