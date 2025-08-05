/**
 * @fileoverview Volunteer Expense DocType Controller for Verenigingen Association Management
 *
 * This controller manages volunteer expense claims, providing comprehensive workflow
 * management for expense submission, approval, rejection, and reimbursement tracking
 * within the association's volunteer program.
 *
 * @description Business Context:
 * Volunteer Expense management enables volunteers to submit expense claims for
 * association-related activities with proper approval workflows and financial tracking:
 * - Expense submission with supporting documentation
 * - Multi-level approval workflow with role-based permissions
 * - Organization assignment (Chapter or Team) for proper cost allocation
 * - Reimbursement tracking and status management
 * - Integration with financial reporting and budget management
 *
 * @description Key Features:
 * - Role-based approval workflow with permission validation
 * - Automated volunteer and organization assignment
 * - Expense date validation and business rule enforcement
 * - Status-driven UI with contextual action buttons
 * - Integration with Chapter and Team management systems
 * - Comprehensive audit trail for financial compliance
 *
 * @description Integration Points:
 * - Volunteer management system for automatic user assignment
 * - Chapter and Team systems for organization tracking
 * - Permission system for approval workflow control
 * - Financial reporting for expense analytics and budgeting
 * - User management for current user volunteer lookup
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe.ui.form
 * @requires frappe.call
 * @requires frappe.user
 *
 * @example
 * // The controller automatically handles:
 * // - Expense workflow with approval/rejection buttons
 * // - Organization assignment based on volunteer membership
 * // - Validation of expense dates and business rules
 * // - Status-based UI updates and action availability
 */

frappe.ui.form.on('Volunteer Expense', {
	refresh(frm) {
		// Add custom buttons based on status
		if (frm.doc.status === 'Submitted' && !frm.doc.__islocal) {
			// Add approve/reject buttons for authorized users
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.can_approve_expense',
				args: {
					expense: frm.doc
				},
				callback(r) {
					if (r.message) {
						frm.add_custom_button(__('Approve'), () => {
							approve_expense(frm);
						}, __('Actions'));

						frm.add_custom_button(__('Reject'), () => {
							reject_expense(frm);
						}, __('Actions'));
					}
				}
			});
		}

		// Add reimbursed button for approved expenses
		if (frm.doc.status === 'Approved' && frappe.user.has_role(['Verenigingen Administrator', 'Chapter Board Member'])) {
			frm.add_custom_button(__('Mark as Reimbursed'), () => {
				mark_reimbursed(frm);
			}, __('Actions'));
		}

		// Set volunteer based on current user if creating new
		if (frm.doc.__islocal && !frm.doc.volunteer) {
			set_current_user_volunteer(frm);
		}
	},

	volunteer(frm) {
		if (frm.doc.volunteer) {
			// Auto-set organization if volunteer has only one
			auto_set_organization(frm);
		}
	},

	organization_type(frm) {
		// Clear opposite organization field when type changes
		if (frm.doc.organization_type === 'Chapter') {
			frm.set_value('team', '');
		} else if (frm.doc.organization_type === 'Team') {
			frm.set_value('chapter', '');
		}
	},

	category(frm) {
		// Update currency based on company default if needed
		if (frm.doc.category && !frm.doc.currency) {
			frm.set_value('currency', 'EUR');
		}
	},

	expense_date(frm) {
		// Validate expense date
		if (frm.doc.expense_date) {
			const expense_date = new Date(frm.doc.expense_date);
			const today = new Date();

			if (expense_date > today) {
				frappe.msgprint(__('Expense date cannot be in the future'));
				frm.set_value('expense_date', '');
			}
		}
	}
});

/**
 * Approves Volunteer Expense Claim
 *
 * Processes approval of a submitted volunteer expense claim through the backend
 * approval workflow, updating the expense status and triggering appropriate
 * notifications and audit trail entries.
 *
 * @description Approval Process:
 * - Validates current user has approval permissions
 * - Updates expense status to 'Approved'
 * - Creates audit trail entry for approval action
 * - Triggers notifications to relevant stakeholders
 * - Refreshes form to show updated status and available actions
 *
 * @description Business Logic:
 * - Only authorized users can approve expenses
 * - Approval moves expense to next workflow stage
 * - Approved expenses become eligible for reimbursement
 * - Integration with financial reporting systems
 *
 * @param {Object} frm - Frappe form instance containing expense data
 *
 * @example
 * // Called when authorized user clicks 'Approve' button
 * approve_expense(frm);
 * // Results in expense approval and form refresh
 *
 * @see {@link reject_expense} For expense rejection workflow
 * @see {@link mark_reimbursed} For reimbursement processing
 */
function approve_expense(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.approve_expense',
		args: {
			expense_name: frm.doc.name
		},
		callback(r) {
			if (!r.exc) {
				frm.reload_doc();
			}
		}
	});
}

/**
 * Rejects Volunteer Expense Claim with Reason
 *
 * Processes rejection of a submitted volunteer expense claim, requiring
 * a mandatory rejection reason for audit purposes and volunteer feedback.
 *
 * @description Rejection Process:
 * - Prompts user for mandatory rejection reason
 * - Validates current user has rejection permissions
 * - Updates expense status to 'Rejected'
 * - Records rejection reason in audit trail
 * - Sends notification to volunteer with feedback
 * - Refreshes form to reflect rejected status
 *
 * @description User Experience:
 * - Modal dialog for rejection reason input
 * - Required field validation for reason
 * - Clear action labeling and confirmation
 * - Immediate feedback on rejection completion
 *
 * @description Business Logic:
 * - Rejection reason required for transparency
 * - Rejected expenses cannot be resubmitted without modification
 * - Audit trail maintains complete rejection history
 * - Volunteer receives constructive feedback
 *
 * @param {Object} frm - Frappe form instance containing expense data
 *
 * @example
 * // Called when authorized user clicks 'Reject' button
 * reject_expense(frm);
 * // Shows reason dialog, then processes rejection with audit trail
 *
 * @see {@link approve_expense} For expense approval workflow
 */
function reject_expense(frm) {
	frappe.prompt({
		label: 'Rejection Reason',
		fieldname: 'reason',
		fieldtype: 'Text',
		reqd: 1
	}, (data) => {
		frappe.call({
			method: 'verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense.reject_expense',
			args: {
				expense_name: frm.doc.name,
				reason: data.reason
			},
			callback(r) {
				if (!r.exc) {
					frm.reload_doc();
				}
			}
		});
	}, __('Reject Expense'), __('Reject'));
}

/**
 * Marks Expense as Reimbursed
 *
 * Updates an approved volunteer expense to reimbursed status with optional
 * reimbursement details for tracking payment method and reference information.
 *
 * @description Reimbursement Process:
 * - Prompts for optional reimbursement details
 * - Updates expense status to 'Reimbursed'
 * - Records reimbursement details if provided
 * - Saves expense record with updated information
 * - Completes the expense lifecycle workflow
 *
 * @description Financial Integration:
 * - Marks expense as financially processed
 * - Provides reference for accounting reconciliation
 * - Enables expense reporting and analytics
 * - Supports audit trail completion
 *
 * @description User Experience:
 * - Optional details field for payment tracking
 * - Clear action confirmation dialog
 * - Immediate status update feedback
 * - Seamless workflow completion
 *
 * @param {Object} frm - Frappe form instance containing approved expense
 *
 * @example
 * // Called when authorized user clicks 'Mark as Reimbursed' button
 * mark_reimbursed(frm);
 * // Shows details dialog, then updates status to completed
 *
 * @see {@link approve_expense} For expense approval prerequisite
 */
function mark_reimbursed(frm) {
	frappe.prompt({
		label: 'Reimbursement Details',
		fieldname: 'details',
		fieldtype: 'Text',
		reqd: 0
	}, (data) => {
		frm.set_value('status', 'Reimbursed');
		if (data.details) {
			frm.set_value('reimbursement_details', data.details);
		}
		frm.save();
	}, __('Mark as Reimbursed'), __('Update'));
}

/**
 * Sets Current User as Volunteer
 *
 * Automatically assigns the current user's volunteer record to the expense
 * form when creating a new expense, streamlining the submission process
 * for volunteers creating their own expense claims.
 *
 * @description User Experience Enhancement:
 * - Eliminates manual volunteer field selection for own expenses
 * - Reduces form completion time and potential errors
 * - Provides immediate context for expense submission
 * - Enables seamless expense creation workflow
 *
 * @description Data Retrieval:
 * - Looks up volunteer record by current user session
 * - Handles cases where user has no volunteer record gracefully
 * - Uses efficient client.get_value for minimal data transfer
 * - Provides silent fallback if volunteer record not found
 *
 * @param {Object} frm - Frappe form instance for new expense
 *
 * @example
 * // Called automatically during form refresh for new expenses
 * set_current_user_volunteer(frm);
 * // Sets volunteer field to current user's volunteer record if available
 *
 * @see {@link auto_set_organization} For automatic organization assignment
 */
function set_current_user_volunteer(frm) {
	// Try to get volunteer record for current user
	frappe.call({
		method: 'frappe.client.get_value',
		args: {
			doctype: 'Volunteer',
			filters: {
				user: frappe.session.user
			},
			fieldname: 'name'
		},
		callback(r) {
			if (r.message && r.message.name) {
				frm.set_value('volunteer', r.message.name);
			}
		}
	});
}

/**
 * Automatically Sets Organization Assignment
 *
 * Intelligently assigns the expense to the appropriate organization (Chapter or Team)
 * based on the volunteer's active memberships, prioritizing Chapter assignments
 * and falling back to Team assignments when applicable.
 *
 * @description Assignment Logic:
 * - Prioritizes Chapter assignment over Team assignment
 * - Only auto-assigns when volunteer has exactly one active membership
 * - Prevents ambiguous assignments for multi-organization volunteers
 * - Uses active membership status for accurate organization selection
 *
 * @description Data Flow:
 * 1. Retrieves volunteer record to get associated member
 * 2. Queries active Chapter memberships for the member
 * 3. If single Chapter found, assigns Chapter organization
 * 4. If no single Chapter, queries active Team memberships
 * 5. If single Team found, assigns Team organization
 * 6. If multiple or no memberships, leaves assignment for manual selection
 *
 * @description Business Logic:
 * - Ensures expense is properly allocated to correct cost center
 * - Supports volunteer participation in multiple organizations
 * - Maintains financial reporting accuracy
 * - Reduces manual data entry while preserving data integrity
 *
 * @param {Object} frm - Frappe form instance with volunteer selected
 *
 * @example
 * // Called automatically when volunteer field changes
 * auto_set_organization(frm);
 * // Results in organization_type and chapter/team fields being set
 * // if volunteer has exactly one active membership
 *
 * @see {@link set_current_user_volunteer} For volunteer assignment
 */
function auto_set_organization(frm) {
	// Auto-set organization if volunteer has only one chapter or team
	frappe.call({
		method: 'frappe.client.get',
		args: {
			doctype: 'Volunteer',
			name: frm.doc.volunteer
		},
		callback(r) {
			if (r.message && r.message.member) {
				// Check chapters first
				frappe.call({
					method: 'frappe.client.get_list',
					args: {
						doctype: 'Chapter Member',
						filters: {
							member: r.message.member,
							status: 'Active'
						},
						fields: ['parent']
					},
					callback(chapters) {
						if (chapters.message && chapters.message.length === 1) {
							frm.set_value('organization_type', 'Chapter');
							frm.set_value('chapter', chapters.message[0].parent);
						} else {
							// Check teams if no single chapter
							frappe.call({
								method: 'frappe.client.get_list',
								args: {
									doctype: 'Team Member',
									filters: {
										volunteer: frm.doc.volunteer,
										status: 'Active'
									},
									fields: ['parent']
								},
								callback(teams) {
									if (teams.message && teams.message.length === 1) {
										frm.set_value('organization_type', 'Team');
										frm.set_value('team', teams.message[0].parent);
									}
								}
							});
						}
					}
				});
			}
		}
	});
}
