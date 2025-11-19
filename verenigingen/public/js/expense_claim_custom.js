/**
 * @fileoverview Expense Claim Member Integration - Association Member Expense Tracking
 *
 * This module extends ERPNext's standard Expense Claim functionality to integrate with
 * association member records, providing seamless expense tracking and reporting for
 * member volunteers and staff. Enables direct navigation between expense claims and
 * member profiles for comprehensive volunteer activity tracking.
 *
 * ## Core Business Functions
 * - **Member-Employee Linkage**: Automatic detection of member associations with employees
 * - **Expense Attribution**: Links expense claims to specific member volunteer activities
 * - **Activity Tracking**: Integrates with volunteer activity and chapter expense reporting
 * - **Cross-Reference Navigation**: Quick access between member records and expense claims
 * - **Historical Analysis**: Member-specific expense history and trend analysis
 *
 * ## Technical Architecture
 * - **Dynamic Button Injection**: Context-aware UI enhancement based on data relationships
 * - **API Integration**: Leverages verenigingen.setup.document_links for member detection
 * - **Route Management**: Seamless navigation between different document types
 * - **Permission Respect**: Honors existing ERPNext permission systems
 * - **Performance Optimization**: Efficient member lookup without blocking UI
 *
 * ## Integration Points
 * - ERPNext Employee master data
 * - Verenigingen Member management system
 * - Expense Claim standard workflow
 * - Member volunteer activity tracking
 * - Chapter-based expense allocation
 *
 * ## User Experience Features
 * - **Contextual Actions**: Relevant buttons appear only when member links exist
 * - **Quick Navigation**: Direct access to related member information
 * - **Expense History**: Comprehensive view of member-related expenses
 * - **Activity Correlation**: Links expenses to specific volunteer activities
 * - **Chapter Attribution**: Connects expenses to relevant chapter operations
 *
 * ## Business Value
 * - **Volunteer Recognition**: Tracks member contributions including expenses
 * - **Chapter Accounting**: Proper allocation of expenses to organizational units
 * - **Activity Costing**: Understanding true cost of volunteer activities
 * - **Member Engagement**: Comprehensive view of member involvement
 * - **Financial Transparency**: Clear audit trail for member-related expenses
 *
 * @company R.S.P. (Verenigingen Association Management)
 * @version 2025.1.0
 * @since 2024.1.0
 * @license Proprietary
 *
 * @requires frappe>=15.0.0
 * @requires erpnext>=15.0.0
 * @requires verenigingen.member
 * @requires verenigingen.setup.document_links
 */

// Custom script for Expense Claim to add member ledger link

frappe.ui.form.on('Expense Claim', {
	setup(frm) {
		// Filter custom_chapter to only show chapters the user has board access to
		frm.set_query('custom_chapter', () => {
			return {
				query: 'verenigingen.api.expense_claim_queries.get_user_accessible_chapters_for_expenses'
			};
		});

		// Set up the expense_approver query filter
		// This needs to be in setup() to be applied before the form loads
		frm.set_query('expense_approver', () => {
			// If custom_chapter is set, filter by chapter board members
			if (frm.doc.custom_chapter) {
				return {
					query: 'verenigingen.api.expense_claim_queries.get_chapter_expense_approvers',
					filters: {
						chapter: frm.doc.custom_chapter
					}
				};
			}

			// If custom_team is set, filter by team's chapter board members
			if (frm.doc.custom_team) {
				return {
					query: 'verenigingen.api.expense_claim_queries.get_team_expense_approvers',
					filters: {
						team: frm.doc.custom_team
					}
				};
			}

			// Default: show all users with Expense Approver role
			// Note: We can't easily filter by role using standard filters
			// This will show all users, but the custom query will be used when chapter/team is set
			return {};
		});
	},

	refresh(frm) {
		// Add "View Member Record" button if employee is linked
		if (frm.doc.employee && !frm.doc.__islocal) {
			// Check if this employee is linked to a member
			frappe.call({
				method:
          'verenigingen.setup.document_links.get_member_from_expense_claim',
				args: {
					expense_claim: frm.doc.name
				},
				callback(r) {
					if (r.message) {
						// Employee is linked to a member - add button
						frm.add_custom_button(
							__('View Member Record'),
							() => {
								frappe.set_route('Form', 'Member', r.message);
							},
							__('Links')
						);

						// Also add a button to view all expenses for this member
						frm.add_custom_button(
							__('View Member Expense History'),
							() => {
								frappe.set_route('List', 'Expense Claim', {
									employee: frm.doc.employee
								});
							},
							__('Links')
						);
					}
				}
			});
		}
	},

	custom_chapter(frm) {
		// Refresh the expense_approver field when chapter changes
		frm.set_value('expense_approver', null);
		frm.refresh_field('expense_approver');
	},

	custom_team(frm) {
		// Refresh the expense_approver field when team changes
		frm.set_value('expense_approver', null);
		frm.refresh_field('expense_approver');
	},

	validate(frm) {
		// Client-side validation before save
		// Check if approval_status is set when submitting
		if (frm.doc.docstatus === 1 && (!frm.doc.approval_status || frm.doc.approval_status === 'Draft')) {
			frappe.msgprint({
				title: __('Approval Required'),
				indicator: 'red',
				message: __('Please set the Approval Status to "Approved" or "Rejected" before submitting this expense claim.')
			});
			frappe.validated = false;
			return false;
		}
	}
});
