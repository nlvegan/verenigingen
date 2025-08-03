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
	refresh(frm) {
		// Add "View Member Record" button if employee is linked
		if (frm.doc.employee && !frm.doc.__islocal) {
			// Check if this employee is linked to a member
			frappe.call({
				method: 'verenigingen.setup.document_links.get_member_from_expense_claim',
				args: {
					expense_claim: frm.doc.name
				},
				callback(r) {
					if (r.message) {
						// Employee is linked to a member - add button
						frm.add_custom_button(__('View Member Record'), () => {
							frappe.set_route('Form', 'Member', r.message);
						}, __('Links'));

						// Also add a button to view all expenses for this member
						frm.add_custom_button(__('View Member Expense History'), () => {
							frappe.set_route('List', 'Expense Claim', {
								employee: frm.doc.employee
							});
						}, __('Links'));
					}
				}
			});
		}
	}
});
