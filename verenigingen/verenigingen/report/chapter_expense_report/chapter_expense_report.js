/**
 * @fileoverview Chapter Expense Report - JavaScript Configuration
 *
 * This file provides comprehensive expense tracking and analysis capabilities for chapter and team
 * financial management within the association management system.
 *
 * BUSINESS PURPOSE:
 * Enables detailed expense monitoring and financial oversight across organizational units:
 * - Track expenses by chapter, team, or volunteer
 * - Monitor approval workflows and identify bottlenecks
 * - Analyze spending patterns by category and time period
 * - Support financial compliance and budget management
 * - Provide audit trails for expense approvals
 *
 * KEY FEATURES:
 * - Multi-dimensional filtering (date range, status, organization, volunteer, category)
 * - Dynamic organization linking (Chapter or Team selection)
 * - Approval level categorization (Basic, Financial, Admin)
 * - Amount range filtering for expense size analysis
 * - Color-coded status indicators and overdue highlighting
 * - Integration with ERPNext Expense Claims system
 *
 * APPROVAL WORKFLOW:
 * - Basic Level: Standard operational expenses (green indicator)
 * - Financial Level: Significant expenses requiring financial review (orange indicator)
 * - Admin Level: Strategic or high-value expenses requiring administrative approval (red indicator)
 *
 * REPORTING CAPABILITIES:
 * - Real-time status tracking with visual indicators
 * - Overdue expense identification (>7 days: red, >3 days: orange)
 * - Excel export functionality for detailed analysis
 * - Automated reminder system for overdue approvals
 * - Direct navigation to ERPNext Expense Claims
 *
 * INTEGRATION ARCHITECTURE:
 * - Links to Volunteer DocType for expense submitter tracking
 * - Connects with Chapter and Team DocTypes via Dynamic Link
 * - Integrates with Expense Category for classification
 * - Synchronizes with ERPNext Expense Claim workflows
 * - Utilizes expense notification utilities for automated reminders
 *
 * @author Your Organization
 * @since 2025
 * @category Financial Management
 * @requires frappe.query_reports
 * @requires verenigingen.utils.expense_notifications
 */

// Copyright (c) 2025, Your Organization and contributors
// For license information, please see license.txt

frappe.query_reports['Chapter Expense Report'] = {
	filters: [
		{
			fieldname: 'from_date',
			label: __('From Date'),
			fieldtype: 'Date',
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
			reqd: 0
		},
		{
			fieldname: 'to_date',
			label: __('To Date'),
			fieldtype: 'Date',
			default: frappe.datetime.get_today(),
			reqd: 0
		},
		{
			fieldname: 'status',
			label: __('Status'),
			fieldtype: 'Select',
			options: '\nSubmitted\nApproved\nRejected\nDraft',
			default: ''
		},
		{
			fieldname: 'organization_type',
			label: __('Organization Type'),
			fieldtype: 'Select',
			options: '\nChapter\nTeam',
			default: ''
		},
		{
			fieldname: 'organization',
			label: __('Organization'),
			fieldtype: 'Dynamic Link',
			options: 'organization_type',
			get_query() {
				const organization_type = frappe.query_report.get_filter_value('organization_type');
				if (organization_type) {
					return {
						doctype: organization_type
					};
				}
			}
		},
		{
			fieldname: 'volunteer',
			label: __('Volunteer'),
			fieldtype: 'Link',
			options: 'Volunteer'
		},
		{
			fieldname: 'category',
			label: __('Category'),
			fieldtype: 'Link',
			options: 'Expense Category'
		},
		{
			fieldname: 'approval_level',
			label: __('Required Approval Level'),
			fieldtype: 'Select',
			options: '\nBasic\nFinancial\nAdmin',
			default: ''
		},
		{
			fieldname: 'amount_min',
			label: __('Minimum Amount'),
			fieldtype: 'Currency',
			default: ''
		},
		{
			fieldname: 'amount_max',
			label: __('Maximum Amount'),
			fieldtype: 'Currency',
			default: ''
		}
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Format status column with colors
		if (column.fieldname === 'status_indicator') {
			return value; // Already contains HTML formatting
		}

		// Highlight overdue pending expenses
		if (column.fieldname === 'days_to_approval' && data.status === 'Submitted') {
			if (value > 7) {
				return `<span style="color: #e74c3c; font-weight: bold;">${value}</span>`;
			} else if (value > 3) {
				return `<span style="color: #f39c12;">${value}</span>`;
			}
		}

		// Format approval level with colors
		if (column.fieldname === 'approval_level') {
			if (value === 'Admin') {
				return `<span style="color: #e74c3c; font-weight: bold;">${value}</span>`;
			} else if (value === 'Financial') {
				return `<span style="color: #f39c12; font-weight: bold;">${value}</span>`;
			} else if (value === 'Basic') {
				return `<span style="color: #27ae60; font-weight: bold;">${value}</span>`;
			}
		}

		// Format amount with currency
		if (column.fieldname === 'amount' && data.currency) {
			return `${data.currency} ${value}`;
		}

		return value;
	},

	onload(report) {
		// Add custom buttons
		report.page.add_inner_button(__('Export to Excel'), () => {
			frappe.utils.export_query(
				frappe.query_report.report_name,
				frappe.query_report.get_filter_values(),
				'Chapter Expense Report'
			);
		});

		report.page.add_inner_button(__('Send Overdue Reminders'), () => {
			frappe.call({
				method: 'verenigingen.utils.expense_notifications.send_overdue_reminders',
				args: { days_overdue: 7 },
				callback() {
					frappe.show_alert(__('Overdue reminders sent'));
				}
			});
		});

		report.page.add_inner_button(__('Open ERPNext Expense Claims'), () => {
			frappe.set_route('List', 'Expense Claim');
		});
	}
};
