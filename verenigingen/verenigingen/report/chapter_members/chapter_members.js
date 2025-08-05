/**
 * @fileoverview Chapter Members Report Configuration - Regional Membership Analytics and Management
 *
 * This module provides comprehensive chapter-based member reporting with advanced filtering,
 * status visualization, and role-based access control. Designed for chapter administrators
 * and regional coordinators to monitor membership composition, track member engagement,
 * and manage chapter-specific operations effectively.
 *
 * Key Features:
 * - Role-based chapter access control with user permission filtering
 * - Real-time member status tracking and visualization
 * - Advanced filtering by membership status and chapter assignment
 * - Color-coded status indicators for quick visual assessment
 * - Integration with member portal access management
 * - Export capabilities for chapter administration
 *
 * Report Capabilities:
 * - Chapter-specific member listing with comprehensive details
 * - Member status tracking (Pending, Active, Inactive)
 * - Visual status indicators with color coding
 * - Permission-based chapter filtering
 * - Membership lifecycle monitoring
 * - Administrative action support
 *
 * Business Value:
 * - Enables effective chapter-level membership management
 * - Provides regional coordinators with actionable member insights
 * - Supports member engagement tracking and intervention
 * - Facilitates compliance monitoring at chapter level
 * - Streamlines administrative workflows for chapter operations
 * - Enhances member retention through proactive management
 *
 * Security Features:
 * - Role-based access control limiting chapter visibility
 * - User permission integration for data access
 * - Chapter-specific data isolation
 * - Audit trail for report access and usage
 *
 * Technical Architecture:
 * - Frappe Query Report framework integration
 * - Dynamic chapter filtering based on user permissions
 * - Custom formatting for enhanced visual presentation
 * - Integration with member portal backend APIs
 * - Real-time data synchronization with member status
 *
 * @author Verenigingen Development Team
 * @version 1.6.0
 * @since 1.0.0
 *
 * @requires frappe.query_reports
 * @requires verenigingen.api.member_portal (Chapter access control)
 * @requires verenigingen.verenigingen.doctype.member (Member data)
 * @requires verenigingen.verenigingen.doctype.chapter (Chapter information)
 *
 * @example
 * // Access via: Reports > Chapter Members
 * // Filter by specific chapter and member status
 * // Visual indicators show member status at a glance
 *
 * @see {@link verenigingen.api.member_portal.get_user_chapters} User Chapter Access
 * @see {@link verenigingen.verenigingen.doctype.member} Member Management
 * @see {@link verenigingen.verenigingen.doctype.chapter} Chapter Administration
 */

/**
 * @namespace ChapterMembersReport
 * @description Query report configuration for chapter-based member management
 */
frappe.query_reports['Chapter Members'] = {
	/**
	 * @property {Array} filters
	 * @description Report filter configuration with role-based access control
	 *
	 * Defines the filtering interface for chapter member reporting with integrated
	 * permission management and user access control. Ensures users can only access
	 * chapters they have permission to view and manage.
	 */
	filters: [
		{
			fieldname: 'chapter',
			label: __('Chapter'),
			fieldtype: 'Link',
			options: 'Chapter',
			reqd: 1,
			get_query() {
				// Only show chapters that user has access to
				return {
					query: 'verenigingen.api.member_portal.get_user_chapters'
				};
			}
		},
		{
			fieldname: 'status',
			label: __('Status'),
			fieldtype: 'Select',
			options: [
				'',
				'Pending',
				'Active',
				'Inactive'
			],
			default: ''
		}
	],

	/**
	 * @method formatter
	 * @description Enhanced visual formatting for member status display
	 *
	 * Applies color-coded formatting to member status values for improved
	 * visual identification and quick assessment of member states. Supports
	 * administrative workflow efficiency through visual cues.
	 *
	 * Status Color Coding:
	 * - Pending: Orange (#ff9800) - Requires attention/approval
	 * - Active: Green (#4caf50) - Normal operational state
	 * - Inactive: Red (#f44336) - Requires intervention or review
	 *
	 * @param {*} value - Original cell value
	 * @param {Object} row - Complete row data
	 * @param {Object} column - Column configuration
	 * @param {Object} data - Complete dataset
	 * @param {Function} default_formatter - Standard Frappe formatter
	 * @returns {string} Formatted HTML with status-appropriate styling
	 *
	 * @since 1.0.0
	 */
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Highlight pending members
		if (column.fieldname === 'status' && value === 'Pending') {
			value = `<span style="color: #ff9800; font-weight: bold;">${value}</span>`;
		} else if (column.fieldname === 'status' && value === 'Inactive') {
			// Highlight inactive members
			value = `<span style="color: #f44336; font-weight: bold;">${value}</span>`;
		} else if (column.fieldname === 'status' && value === 'Active') {
			// Active members in green
			value = `<span style="color: #4caf50; font-weight: bold;">${value}</span>`;
		}

		return value;
	}
};
