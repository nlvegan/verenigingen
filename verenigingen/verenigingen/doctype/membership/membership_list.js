/**
 * @fileoverview Membership List View - JavaScript Configuration
 *
 * This file provides list view configuration for membership records, offering visual status
 * indicators for the membership lifecycle management system.
 *
 * BUSINESS PURPOSE:
 * Enables efficient membership status monitoring and management:
 * - Provide quick visual assessment of membership states
 * - Support administrative workflows for membership processing
 * - Enable bulk operations and filtering by membership status
 * - Facilitate membership lifecycle tracking and compliance monitoring
 *
 * MEMBERSHIP LIFECYCLE STATES:
 * - Draft (Gray): Initial creation, incomplete information
 * - Pending (Yellow): Awaiting approval or activation
 * - Active (Green): Current, valid membership in good standing
 * - Inactive (Orange): Temporarily suspended or on hold
 * - Expired (Gray): Past end date, requires renewal
 * - Cancelled (Red): Terminated or revoked membership
 *
 * VISUAL INDICATORS:
 * Color-coded status pills provide immediate status recognition:
 * - Green indicates healthy, active memberships
 * - Yellow highlights memberships requiring attention
 * - Orange signals potential issues or temporary states
 * - Red indicates problems or terminated memberships
 * - Gray represents inactive or transitional states
 *
 * ADMINISTRATIVE EFFICIENCY:
 * - Quick status identification for batch processing
 * - Support for status-based filtering and sorting
 * - Integration with membership workflow systems
 * - Foundation for automated membership management
 *
 * INTEGRATION POINTS:
 * - Links to Member DocType for member information
 * - Connects with Dues Schedule for payment tracking
 * - Supports membership renewal workflows
 * - Integrates with chapter and organizational structures
 *
 * @author Frappe Technologies Pvt. Ltd.
 * @since 2025
 * @category Membership Management
 * @requires frappe.listview_settings
 */

frappe.listview_settings['Membership'] = {
	get_indicator(doc) {
		if (doc.status === 'Draft') {
			return [__('Draft'), 'gray', 'status,=,Draft'];
		} else if (doc.status === 'Active') {
			return [__('Active'), 'green', 'status,=,Active'];
		} else if (doc.status === 'Pending') {
			return [__('Pending'), 'yellow', 'status,=,Pending'];
		} else if (doc.status === 'Inactive') {
			return [__('Inactive'), 'orange', 'status,=,Inactive'];
		} else if (doc.status === 'Expired') {
			return [__('Expired'), 'gray', 'status,=,Expired'];
		} else if (doc.status === 'Cancelled') {
			return [__('Cancelled'), 'red', 'status,=,Cancelled'];
		}
		// Default fallback
		return [doc.status || __('Unknown'), 'gray'];
	}
};
