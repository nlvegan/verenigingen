/**
 * @fileoverview Members Without Active Memberships Report - JavaScript Configuration
 *
 * This file configures the frontend behavior for the "Members Without Active Memberships" report,
 * a critical administrative tool for membership retention and compliance monitoring.
 *
 * BUSINESS PURPOSE:
 * Identifies members who lack active membership records, helping administrators:
 * - Track members who may have fallen through administrative cracks
 * - Identify revenue leakage from inactive memberships
 * - Monitor compliance with membership renewal processes
 * - Support member retention and re-engagement campaigns
 *
 * REPORT CAPABILITIES:
 * - Filter by member status (Active, Pending, Suspended, Terminated)
 * - Include/exclude terminated and suspended members
 * - Optional dues schedule information for payment tracking
 * - Color-coded status indicators for quick visual assessment
 * - Chapter-based filtering (disabled due to computed HTML fields)
 *
 * STATUS INDICATORS:
 * - Red: Terminated members, cancelled memberships, critical overdue payments
 * - Orange: Suspended members, expired memberships, minor overdue payments
 * - Blue: Pending members awaiting activation
 * - Green: Active dues schedules
 *
 * INTEGRATION POINTS:
 * - Links to Member DocType for detailed member information
 * - Connects with Membership records for status tracking
 * - Integrates with Dues Schedule system for payment monitoring
 * - Supports Chapter-based organizational structure
 *
 * @author Frappe Technologies Pvt. Ltd.
 * @since 2025
 * @category Membership Management
 * @requires frappe.query_reports
 */

// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports['Members Without Active Memberships'] = {
	filters: [
		{
			fieldname: 'include_terminated',
			label: __('Include Terminated Members'),
			fieldtype: 'Check',
			default: 0,
			description: 'Include members with status \'Terminated\''
		},
		{
			fieldname: 'include_suspended',
			label: __('Include Suspended Members'),
			fieldtype: 'Check',
			default: 1,
			description: 'Include members with status \'Suspended\''
		},
		{
			fieldname: 'member_status',
			label: __('Member Status'),
			fieldtype: 'Select',
			options: 'Active\nPending\nSuspended\nTerminated',
			description: 'Filter by specific member status'
		},
		{
			fieldname: 'include_dues_schedule_info',
			label: __('Include Dues Schedule Information'),
			fieldtype: 'Check',
			default: 0,
			description: 'Add columns showing dues schedule status, next invoice date, and coverage gaps'
		}
		// Chapter filter disabled - field is computed/HTML
		// {
		// 	"fieldname": "chapter",
		// 	"label": __("Chapter"),
		// 	"fieldtype": "Link",
		// 	"options": "Chapter",
		// 	"description": "Filter by specific chapter"
		// }
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Color code based on member status and last membership status
		if (column.fieldname === 'member_status') {
			if (value === 'Terminated') {
				value = `<span style="color: red;">${value}</span>`;
			} else if (value === 'Suspended') {
				value = `<span style="color: orange;">${value}</span>`;
			} else if (value === 'Pending') {
				value = `<span style="color: blue;">${value}</span>`;
			}
		}

		if (column.fieldname === 'last_membership_status') {
			if (value === 'Cancelled') {
				value = `<span style="color: red;">${value}</span>`;
			} else if (value === 'Expired') {
				value = `<span style="color: orange;">${value}</span>`;
			}
		}

		// Format dues schedule status
		if (column.fieldname === 'dues_schedule_status') {
			if (value === 'None') {
				value = `<span style="color: red;">${value}</span>`;
			} else if (value === 'Active') {
				value = `<span style="color: green;">${value}</span>`;
			}
		}

		// Format days overdue
		if (column.fieldname === 'days_overdue' && value && value > 0) {
			if (value > 7) {
				value = `<span style="color: red; font-weight: bold;">${value}</span>`;
			} else {
				value = `<span style="color: orange;">${value}</span>`;
			}
		}

		return value;
	}
};
