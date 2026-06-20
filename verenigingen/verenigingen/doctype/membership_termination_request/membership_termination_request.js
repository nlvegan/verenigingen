/**
 * @fileoverview Membership Termination Request Controller - Advanced Membership Lifecycle Management
 *
 * This module provides comprehensive membership termination management with multi-level approval
 * workflows, disciplinary action support, automated system updates, and regulatory compliance
 * features. Designed to handle both voluntary and involuntary membership terminations while
 * maintaining audit trails and ensuring proper procedural compliance.
 *
 * Key Features:
 * - Multi-tier approval workflows with role-based authorization
 * - Disciplinary action support with required documentation
 * - Automated system cleanup (SEPA mandates, newsletters, positions)
 * - Comprehensive audit trail and compliance reporting
 * - Integration with expulsion reporting requirements
 * - Grace period management for different termination types
 * - Real-time status tracking and notification system
 *
 * Termination Types Supported:
 * - Voluntary: Member-initiated termination with standard processing
 * - Non-payment: Financial default with automated collection integration
 * - Deceased: Administrative closure with family notification support
 * - Policy Violation: Disciplinary action requiring documentation
 * - Disciplinary Action: Formal disciplinary process with approvals
 * - Expulsion: Final disciplinary measure with board-level approval
 *
 * Business Value:
 * - Ensures compliant membership termination procedures
 * - Automates complex administrative tasks reducing manual errors
 * - Maintains regulatory compliance with documentation requirements
 * - Provides clear audit trail for disciplinary actions
 * - Streamlines member lifecycle management processes
 * - Supports legal and procedural compliance requirements
 *
 * Technical Architecture:
 * - Advanced workflow management with conditional approval paths
 * - Integration with SEPA mandate management systems
 * - Automated email notification and communication workflows
 * - Document management integration for compliance documentation
 * - Role-based permission system with delegated authority
 * - Real-time status tracking and progress monitoring
 *
 * Compliance Features:
 * - Disciplinary action documentation requirements
 * - Multi-level approval for serious violations
 * - Audit trail preservation for legal compliance
 * - Integration with expulsion reporting systems
 * - Data retention and privacy compliance (GDPR)
 * - Procedural fairness and due process support
 *
 * @author Verenigingen Development Team
 * @version 2.5.0
 * @since 1.0.0
 *
 * @requires frappe
 * @requires verenigingen.verenigingen.doctype.member (Member management)
 * @requires verenigingen.verenigingen.doctype.sepa_mandate (SEPA integration)
 * @requires verenigingen.verenigingen.doctype.membership (Membership lifecycle)
 *
 * @example
 * // Standard voluntary termination
 * // 1. Set termination_type: 'Voluntary'
 * // 2. Provide termination_reason
 * // 3. Submit for approval (single-tier)
 * // 4. Execute termination with automated cleanup
 *
 * // Disciplinary termination workflow
 * // 1. Set termination_type: 'Expulsion'
 * // 2. Provide detailed disciplinary_documentation
 * // 3. Assign secondary_approver
 * // 4. Multi-tier approval process
 * // 5. Execute with full audit trail
 *
 * @see {@link verenigingen.verenigingen.doctype.member} Member Management
 * @see {@link verenigingen.verenigingen.doctype.expulsion_report_entry} Expulsion Reporting
 * @see {@link verenigingen.verenigingen.doctype.sepa_mandate} SEPA Integration
 */

/**
 * Configuration constants for termination workflows
 * @const {Object} TERMINATION_CONFIG
 */
const TERMINATION_CONFIG = {
	/** @type {string[]} Termination types requiring disciplinary documentation and secondary approval */
	DISCIPLINARY_TYPES: Object.freeze(['Policy Violation', 'Disciplinary Action', 'Expulsion']),

	/** @type {Object.<string, string>} Status value constants */
	STATUS: Object.freeze({
		DRAFT: 'Draft',
		PENDING: 'Pending',
		APPROVED: 'Approved',
		REJECTED: 'Rejected',
		EXECUTED: 'Executed'
	}),

	/** @type {Object.<string, string>} Status indicator colors for UI */
	INDICATOR_COLORS: Object.freeze({
		Draft: 'blue',
		Pending: 'yellow',
		Approved: 'green',
		Rejected: 'red',
		Executed: 'gray'
	}),

	/** @type {string[]} Roles authorized to override secondary approval requirements */
	ADMIN_ROLES: Object.freeze(['System Manager', 'Verenigingen Administrator'])
};

/**
 * API method paths for server-side operations
 * @const {Object} API_METHODS
 */
const API_METHODS = {
	GET_ELIGIBLE_APPROVERS:
		'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_eligible_approvers',
	INITIATE_DISCIPLINARY:
		'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.initiate_disciplinary_termination'
};

/**
 * Pure business logic functions (testable, no side effects)
 */

/**
 * Check if a termination type is disciplinary
 * @param {string} termination_type - The termination type to check
 * @returns {boolean} True if termination type requires disciplinary workflow
 */
function isDisciplinaryType(termination_type) {
	return TERMINATION_CONFIG.DISCIPLINARY_TYPES.includes(termination_type);
}

/**
 * Check if current user can approve a termination request
 * @param {string[]} user_roles - Array of user role names
 * @param {string} secondary_approver - Designated secondary approver user ID
 * @returns {boolean} True if user has approval authority
 */
function canUserApprove(user_roles, secondary_approver) {
	// Admin roles can always approve
	const has_admin_role = TERMINATION_CONFIG.ADMIN_ROLES.some((role) => user_roles.includes(role));

	if (has_admin_role) {
		return true;
	}

	// Check if user is the designated secondary approver
	return secondary_approver === frappe.session.user;
}

/**
 * @namespace MembershipTerminationController
 * @description Advanced membership termination form controller with workflow management
 */
frappe.ui.form.on('Membership Termination Request', {
	refresh(frm) {
		// Set indicators based on status
		set_status_indicator(frm);

		// Add custom buttons based on status
		add_action_buttons(frm);

		// Toggle field visibility based on termination type
		toggle_disciplinary_fields(frm);

		// Make audit trail read-only
		frm.set_df_property('audit_trail', 'read_only', 1);

		// Only admins can override secondary approval requirement
		const can_override_approval = TERMINATION_CONFIG.ADMIN_ROLES.some((role) => frappe.user_roles.includes(role));
		frm.set_df_property('requires_secondary_approval', 'read_only', !can_override_approval);
	},

	onload(frm) {
		// Set default values for new documents
		if (frm.is_new()) {
			frm.set_value('request_date', frappe.datetime.get_today());
			frm.set_value('requested_by', frappe.session.user);
			frm.set_value('status', TERMINATION_CONFIG.STATUS.DRAFT);
		}

		// Filter secondary approver to only show eligible users
		set_secondary_approver_filter(frm);
	},

	termination_type(frm) {
		// Toggle disciplinary fields based on termination type
		toggle_disciplinary_fields(frm);

		// Set default dates based on type
		set_default_dates(frm);
	},

	member(frm) {
		// Clear member name when member changes
		if (!frm.doc.member) {
			frm.set_value('member_name', '');
		}
	},

	before_save(frm) {
		// Validate required fields based on termination type
		validate_required_fields(frm);
	}
});

function set_status_indicator(frm) {
	if (frm.doc.status && TERMINATION_CONFIG.INDICATOR_COLORS[frm.doc.status]) {
		frm.page.set_indicator(frm.doc.status, TERMINATION_CONFIG.INDICATOR_COLORS[frm.doc.status]);
	}
}

function add_action_buttons(frm) {
	// Track button state to prevent race conditions and unnecessary rebuilds
	const current_state = `${frm.doc.status}|${frm.doc.member}`;

	// Only rebuild if state changed
	if (frm._button_state === current_state) {
		return;
	}

	frm._button_state = current_state;

	// Clear existing custom buttons
	frm.clear_custom_buttons();

	if (frm.doc.status === TERMINATION_CONFIG.STATUS.DRAFT) {
		// Submit for approval button
		frm.add_custom_button(
			__('Submit for Approval'),
			() => {
				submit_for_approval(frm);
			},
			__('Actions')
		).addClass('btn-primary');
	} else if (frm.doc.status === TERMINATION_CONFIG.STATUS.PENDING) {
		// Show approval buttons if user can approve
		if (can_approve_request(frm)) {
			frm.add_custom_button(
				__('Approve'),
				() => {
					approve_request(frm, 'approved');
				},
				__('Actions')
			).addClass('btn-success');

			frm.add_custom_button(
				__('Reject'),
				() => {
					approve_request(frm, 'rejected');
				},
				__('Actions')
			).addClass('btn-danger');
		}
	} else if (frm.doc.status === TERMINATION_CONFIG.STATUS.APPROVED) {
		// Execute termination button
		frm.add_custom_button(
			__('Execute Termination'),
			() => {
				execute_termination(frm);
			},
			__('Actions')
		).addClass('btn-warning');
	}

	// View member button
	if (frm.doc.member) {
		frm.add_custom_button(
			__('View Member'),
			() => {
				frappe.set_route('Form', 'Member', frm.doc.member);
			},
			__('View')
		);
	}
}

function toggle_disciplinary_fields(frm) {
	const is_disciplinary = isDisciplinaryType(frm.doc.termination_type);

	// Show/hide disciplinary documentation
	frm.toggle_display('disciplinary_documentation', is_disciplinary);
	frm.toggle_reqd('disciplinary_documentation', is_disciplinary);

	// Show/hide secondary approval fields
	frm.toggle_display('secondary_approver', is_disciplinary);
	frm.toggle_reqd('secondary_approver', is_disciplinary);

	// Update requires_secondary_approval flag - only set default for new documents
	if (frm.is_new()) {
		frm.set_value('requires_secondary_approval', is_disciplinary ? 1 : 0);
	}
}

function set_default_dates(frm) {
	// Set default termination date if not already set
	if (!frm.doc.termination_date) {
		frm.set_value('termination_date', frappe.datetime.get_today());
	}
}

function set_secondary_approver_filter(frm) {
	frm.set_query('secondary_approver', () => {
		return {
			query: API_METHODS.GET_ELIGIBLE_APPROVERS
		};
	});
}

function validate_required_fields(frm) {
	const is_disciplinary = isDisciplinaryType(frm.doc.termination_type);

	if (is_disciplinary) {
		if (!frm.doc.disciplinary_documentation) {
			frappe.throw(__('Documentation is required for disciplinary terminations'));
		}

		if (frm.doc.status === TERMINATION_CONFIG.STATUS.PENDING && !frm.doc.secondary_approver) {
			frappe.throw(__('Secondary approver is required for disciplinary terminations'));
		}
	}
}

function submit_for_approval(frm) {
	// Validate required fields first
	validate_required_fields(frm);

	frappe.call({
		method: 'submit_for_approval',
		doc: frm.doc,
		callback(r) {
			if (r.message) {
				frm.refresh();
				frappe.show_alert(
					{
						message: __('Request submitted for approval'),
						indicator: 'green'
					},
					5
				);
			} else {
				frappe.msgprint({
					title: __('Warning'),
					message: __('Request processed but no confirmation received. Please refresh to verify status.'),
					indicator: 'orange'
				});
			}
		},
		error(r) {
			frappe.msgprint({
				title: __('Submission Failed'),
				message: r.message || __('Failed to submit request. Please try again.'),
				indicator: 'red'
			});
		}
	});
}

function can_approve_request(frm) {
	// Delegate to pure business logic function
	return canUserApprove(frappe.user_roles, frm.doc.secondary_approver);
}

function approve_request(frm, decision) {
	const dialog = new frappe.ui.Dialog({
		title: __(decision === 'approved' ? 'Approve Request' : 'Reject Request'),
		fields: [
			{
				fieldtype: 'Small Text',
				fieldname: 'notes',
				label: __('Approval Notes'),
				reqd: decision === 'rejected'
			},
			{
				fieldtype: 'Date',
				fieldname: 'termination_date',
				label: __('Termination Date'),
				default: frm.doc.termination_date || frappe.datetime.get_today(),
				depends_on: `eval:"${decision}" === "approved"`
			}
		],
		primary_action_label: __(decision === 'approved' ? 'Approve' : 'Reject'),
		primary_action(values) {
			// Disable button during processing
			dialog.disable_primary_action();
			dialog.set_primary_action(__('Processing...'));

			frappe.call({
				method: 'approve_request',
				doc: frm.doc,
				args: {
					decision,
					notes: values.notes || ''
				},
				callback(r) {
					if (r.message) {
						// Update termination date if provided
						if (decision === 'approved' && values.termination_date) {
							frm.set_value('termination_date', values.termination_date);
						}

						frm.refresh();
						dialog.hide();

						const message =
							decision === 'approved' ? __('Request approved successfully') : __('Request rejected');

						frappe.show_alert(
							{
								message,
								indicator: decision === 'approved' ? 'green' : 'red'
							},
							5
						);
					} else {
						frappe.msgprint({
							title: __('Warning'),
							message: __(
								'Operation completed but no confirmation received. Please refresh to verify status.'
							),
							indicator: 'orange'
						});
						dialog.enable_primary_action();
						dialog.set_primary_action(__(decision === 'approved' ? 'Approve' : 'Reject'));
					}
				},
				error(r) {
					dialog.enable_primary_action();
					dialog.set_primary_action(__(decision === 'approved' ? 'Approve' : 'Reject'));

					frappe.msgprint({
						title: __('Operation Failed'),
						message: r.message || __('Failed to process approval. Please try again.'),
						indicator: 'red'
					});
				}
			});
		}
	});

	dialog.show();
}

function execute_termination(frm) {
	// Show confirmation dialog
	frappe.confirm(
		`${__('Are you sure you want to execute this termination? This action cannot be undone and will:')}<br><br>` +
			`• ${__('Cancel all SEPA mandates')}<br>` +
			`• ${__('Unsubscribe from member newsletters')}<br>` +
			`• ${__('End all board/committee positions')}<br>` +
			`• ${__('Update membership status')}`,
		() => {
			// User confirmed
			frappe.call({
				method: 'execute_termination',
				doc: frm.doc,
				freeze: true,
				freeze_message: __('Executing termination...'),
				callback(r) {
					if (r.message) {
						frm.refresh();
						frappe.show_alert(
							{
								message: __('Termination executed successfully'),
								indicator: 'green'
							},
							7
						);
					} else {
						frappe.msgprint({
							title: __('Warning'),
							message: __(
								'Termination processed but no confirmation received. Please refresh to verify status.'
							),
							indicator: 'orange'
						});
					}
				},
				error(r) {
					frappe.msgprint({
						title: __('Execution Failed'),
						message: r.message || __('Failed to execute termination. Please try again or contact support.'),
						indicator: 'red'
					});
				}
			});
		}
	);
}

// Enhanced termination dialog function that can be called from Member form
/**
 * Frappe namespace for membership termination operations
 * @namespace frappe.membership_termination
 */
frappe.membership_termination = frappe.membership_termination || {};

/**
 * Show enhanced termination dialog with workflow selection
 * @param {string} member_id - Member DocType name identifier
 * @param {string} member_name - Member display name for dialog title
 * @memberof frappe.membership_termination
 */
frappe.membership_termination.show_dialog = function (member_id, member_name) {
	const dialog = new frappe.ui.Dialog({
		title: __('Terminate Membership: {0}', [member_name]),
		size: 'large',
		fields: [
			{
				fieldtype: 'Section Break',
				label: __('Termination Type')
			},
			{
				fieldname: 'termination_type',
				fieldtype: 'Select',
				label: __('Termination Type'),
				options: [
					'Voluntary',
					'Non-payment',
					'Deceased',
					'--- Disciplinary ---', // Visual separator
					'Policy Violation',
					'Disciplinary Action',
					'Expulsion'
				],
				reqd: 1,
				onchange() {
					toggle_dialog_fields(dialog, this.value);
				}
			},
			{
				fieldtype: 'Section Break',
				label: __('Reason & Documentation')
			},
			{
				fieldname: 'termination_reason',
				fieldtype: 'Small Text',
				label: __('Termination Reason'),
				reqd: 1
			},
			{
				fieldname: 'disciplinary_documentation',
				fieldtype: 'Text Editor',
				label: __('Documentation Required'),
				depends_on: 'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(termination_type)',
				mandatory_depends_on:
					'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(termination_type)',
				description: __('Required for disciplinary actions - will be included in expulsion report')
			},
			{
				fieldtype: 'Section Break',
				label: __('Approval'),
				depends_on: 'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(termination_type)'
			},
			{
				fieldname: 'secondary_approver',
				fieldtype: 'Link',
				label: __('Secondary Approver'),
				options: 'User',
				depends_on: 'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(termination_type)',
				mandatory_depends_on:
					'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(termination_type)',
				get_query() {
					return {
						query: API_METHODS.GET_ELIGIBLE_APPROVERS
					};
				}
			},
			{
				fieldtype: 'Section Break',
				label: __('System Updates')
			},
			{
				fieldname: 'cancel_sepa_mandates',
				fieldtype: 'Check',
				label: __('Cancel SEPA Mandates'),
				default: 1
			},
			{
				fieldname: 'unsubscribe_newsletters',
				fieldtype: 'Check',
				label: __('Unsubscribe from Member Newsletters'),
				default: 1
			},
			{
				fieldname: 'end_board_positions',
				fieldtype: 'Check',
				label: __('End Board/Committee Positions'),
				default: 1
			}
		],
		primary_action_label: __('Create Termination Request'),
		primary_action(values) {
			// Validate input before proceeding
			const validation = validateTerminationDialogInput(values);
			if (!validation.valid) {
				frappe.msgprint({
					title: __('Validation Error'),
					message: validation.errors.join('<br>'),
					indicator: 'red'
				});
				return;
			}

			// Create the termination request
			const termination_data = {
				termination_type: values.termination_type,
				termination_reason: values.termination_reason,
				documentation: values.disciplinary_documentation,
				secondary_approver: values.secondary_approver,
				cancel_sepa_mandates: values.cancel_sepa_mandates,
				unsubscribe_newsletters: values.unsubscribe_newsletters,
				end_board_positions: values.end_board_positions
			};

			// Call the appropriate method based on termination type
			const is_disciplinary = isDisciplinaryType(values.termination_type);

			if (is_disciplinary) {
				// Use disciplinary workflow
				// Disable button during processing
				dialog.disable_primary_action();
				dialog.set_primary_action(__('Creating...'));

				frappe.call({
					method: API_METHODS.INITIATE_DISCIPLINARY,
					// Arg names must match initiate_disciplinary_termination(member, reason,
					// evidence, ..., termination_type, secondary_approver). The execution-time
					// options (cancel_sepa_mandates etc.) are applied when the request is
					// executed, not at initiation, so they are not sent here.
					args: {
						member: member_id,
						reason: termination_data.termination_reason,
						evidence: termination_data.documentation,
						termination_type: termination_data.termination_type,
						secondary_approver: termination_data.secondary_approver
					},
					callback(r) {
						if (r.message) {
							dialog.hide();
							frappe.set_route('Form', 'Membership Termination Request', r.message.request_id);
						} else {
							frappe.msgprint({
								title: __('Warning'),
								message: __('Request processed but no confirmation received.'),
								indicator: 'orange'
							});
							dialog.enable_primary_action();
							dialog.set_primary_action(__('Create Termination Request'));
						}
					},
					error(r) {
						dialog.enable_primary_action();
						dialog.set_primary_action(__('Create Termination Request'));

						frappe.msgprint({
							title: __('Creation Failed'),
							message: r.message || __('Failed to create termination request. Please try again.'),
							indicator: 'red'
						});
					}
				});
			} else {
				// Standard workflow - create request directly
				frappe.new_doc('Membership Termination Request', {
					member: member_id,
					member_name,
					termination_type: values.termination_type,
					termination_reason: values.termination_reason,
					cancel_sepa_mandates: values.cancel_sepa_mandates,
					unsubscribe_newsletters: values.unsubscribe_newsletters,
					end_board_positions: values.end_board_positions
				});
				dialog.hide();
			}
		}
	});

	dialog.show();
};

/**
 * Validate termination dialog input values
 * @param {Object} values - Dialog field values
 * @returns {Object} { valid: boolean, errors: string[] }
 */
function validateTerminationDialogInput(values) {
	const errors = [];

	// Required field validation
	if (!values.termination_type || values.termination_type.trim() === '') {
		errors.push(__('Termination type is required'));
	}

	// Prevent selecting the visual separator
	if (values.termination_type === '--- Disciplinary ---') {
		errors.push(__('Please select a valid termination type'));
	}

	if (!values.termination_reason || values.termination_reason.trim() === '') {
		errors.push(__('Termination reason is required'));
	}

	// Disciplinary-specific validation
	const is_disciplinary = isDisciplinaryType(values.termination_type);
	if (is_disciplinary) {
		if (!values.disciplinary_documentation || values.disciplinary_documentation.trim() === '') {
			errors.push(__('Documentation is required for disciplinary terminations'));
		}
		if (!values.secondary_approver || values.secondary_approver.trim() === '') {
			errors.push(__('Secondary approver is required for disciplinary terminations'));
		}
	}

	return {
		valid: errors.length === 0,
		errors
	};
}

function toggle_dialog_fields(dialog, termination_type) {
	const is_disciplinary = isDisciplinaryType(termination_type);

	// Toggle visibility of disciplinary-specific fields
	dialog.fields_dict.disciplinary_documentation.df.hidden = !is_disciplinary;
	dialog.fields_dict.secondary_approver.df.hidden = !is_disciplinary;

	// Refresh the dialog to show/hide fields
	dialog.refresh();
}

// Backward-compatible alias for existing code
// @deprecated Use frappe.membership_termination.show_dialog() instead
window.show_enhanced_termination_dialog = function (member_id, member_name) {
	console.warn(
		'window.show_enhanced_termination_dialog() is deprecated. ' +
			'Use frappe.membership_termination.show_dialog() instead.'
	);
	return frappe.membership_termination.show_dialog(member_id, member_name);
};
