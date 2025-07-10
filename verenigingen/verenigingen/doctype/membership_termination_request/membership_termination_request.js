frappe.ui.form.on('Membership Termination Request', {
	refresh: function(frm) {
		// Set indicators based on status
		set_status_indicator(frm);

		// Add custom buttons based on status
		add_action_buttons(frm);

		// Toggle field visibility based on termination type
		toggle_disciplinary_fields(frm);

		// Make audit trail read-only
		frm.set_df_property('audit_trail', 'read_only', 1);

		// Add view member button
		if (frm.doc.member) {
			frm.add_custom_button(__('View Member'), function() {
				frappe.set_route('Form', 'Member', frm.doc.member);
			}, __('View'));
		}
	},

	onload: function(frm) {
		// Set default values for new documents
		if (frm.is_new()) {
			frm.set_value('request_date', frappe.datetime.get_today());
			frm.set_value('requested_by', frappe.session.user);
			frm.set_value('status', 'Draft');
		}

		// Filter secondary approver to only show eligible users
		set_secondary_approver_filter(frm);
	},

	termination_type: function(frm) {
		// Toggle disciplinary fields based on termination type
		toggle_disciplinary_fields(frm);

		// Set approval requirements
		set_approval_requirements(frm);

		// Set default dates based on type
		set_default_dates(frm);
	},

	member: function(frm) {
		// Clear member name when member changes
		if (!frm.doc.member) {
			frm.set_value('member_name', '');
		}
	},

	before_save: function(frm) {
		// Validate required fields based on termination type
		validate_required_fields(frm);
	}
});

function set_status_indicator(frm) {
	let indicator_map = {
		'Draft': 'blue',
		'Pending': 'yellow',
		'Approved': 'green',
		'Rejected': 'red',
		'Executed': 'gray'
	};

	if (frm.doc.status && indicator_map[frm.doc.status]) {
		frm.page.set_indicator(frm.doc.status, indicator_map[frm.doc.status]);
	}
}

function add_action_buttons(frm) {
	// Clear existing custom buttons
	frm.clear_custom_buttons();

	if (frm.doc.status === 'Draft') {
		// Submit for approval button
		frm.add_custom_button(__('Submit for Approval'), function() {
			submit_for_approval(frm);
		}, __('Actions')).addClass('btn-primary');

	} else if (frm.doc.status === 'Pending') {
		// Show approval buttons if user can approve
		if (can_approve_request(frm)) {
			frm.add_custom_button(__('Approve'), function() {
				approve_request(frm, 'approved');
			}, __('Actions')).addClass('btn-success');

			frm.add_custom_button(__('Reject'), function() {
				approve_request(frm, 'rejected');
			}, __('Actions')).addClass('btn-danger');
		}

	} else if (frm.doc.status === 'Approved') {
		// Execute termination button
		frm.add_custom_button(__('Execute Termination'), function() {
			execute_termination(frm);
		}, __('Actions')).addClass('btn-warning');
	}

	// View member button
	if (frm.doc.member) {
		frm.add_custom_button(__('View Member'), function() {
			frappe.set_route('Form', 'Member', frm.doc.member);
		}, __('View'));
	}
}

function toggle_disciplinary_fields(frm) {
	const disciplinary_types = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
	const is_disciplinary = disciplinary_types.includes(frm.doc.termination_type);

	// Show/hide disciplinary documentation
	frm.toggle_display('disciplinary_documentation', is_disciplinary);
	frm.toggle_reqd('disciplinary_documentation', is_disciplinary);

	// Show/hide secondary approval fields
	frm.toggle_display('secondary_approver', is_disciplinary);
	frm.toggle_reqd('secondary_approver', is_disciplinary);

	// Update requires_secondary_approval flag
	frm.set_value('requires_secondary_approval', is_disciplinary ? 1 : 0);
}

function set_approval_requirements(frm) {
	const disciplinary_types = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
	const requires_approval = disciplinary_types.includes(frm.doc.termination_type);

	frm.set_value('requires_secondary_approval', requires_approval ? 1 : 0);
}

function set_default_dates(frm) {
	const disciplinary_types = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
	const is_disciplinary = disciplinary_types.includes(frm.doc.termination_type);

	if (is_disciplinary) {
		// Disciplinary terminations are immediate - no grace period
		if (!frm.doc.termination_date) {
			frm.set_value('termination_date', frappe.datetime.get_today());
		}
		frm.set_value('grace_period_end', null);
	} else {
		// Standard terminations may have grace period
		if (!frm.doc.termination_date) {
			frm.set_value('termination_date', frappe.datetime.get_today());
		}
		if (!frm.doc.grace_period_end && frm.doc.termination_type !== 'Deceased') {
			// 30-day grace period for non-disciplinary, non-deceased
			frm.set_value('grace_period_end', frappe.datetime.add_days(frappe.datetime.get_today(), 30));
		}
	}
}

function set_secondary_approver_filter(frm) {
	frm.set_query('secondary_approver', function() {
		return {
			query: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_eligible_approvers'
		};
	});
}

function validate_required_fields(frm) {
	const disciplinary_types = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
	const is_disciplinary = disciplinary_types.includes(frm.doc.termination_type);

	if (is_disciplinary) {
		if (!frm.doc.disciplinary_documentation) {
			frappe.throw(__('Documentation is required for disciplinary terminations'));
		}

		if (frm.doc.status === 'Pending' && !frm.doc.secondary_approver) {
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
		callback: function(r) {
			if (r.message) {
				frm.refresh();
				frappe.show_alert({
					message: __('Request submitted for approval'),
					indicator: 'green'
				}, 5);
			}
		}
	});
}

function can_approve_request(frm) {
	// Check if current user can approve this request
	const user_roles = frappe.user_roles;

	// System managers can always approve
	if (user_roles.includes('System Manager')) {
		return true;
	}

	// Association managers can approve disciplinary terminations
	if (user_roles.includes('Verenigingen Administrator') && frm.doc.requires_secondary_approval) {
		return true;
	}

	// Check if user is the designated secondary approver
	return frm.doc.secondary_approver === frappe.session.user;
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
		primary_action: function(values) {
			frappe.call({
				method: 'approve_request',
				doc: frm.doc,
				args: {
					decision: decision,
					notes: values.notes || ''
				},
				callback: function(r) {
					if (r.message) {
						// Update termination date if provided
						if (decision === 'approved' && values.termination_date) {
							frm.set_value('termination_date', values.termination_date);
						}

						frm.refresh();
						dialog.hide();

						const message = decision === 'approved' ?
							__('Request approved successfully') :
							__('Request rejected');

						frappe.show_alert({
							message: message,
							indicator: decision === 'approved' ? 'green' : 'red'
						}, 5);
					}
				}
			});
		}
	});

	dialog.show();
}

function execute_termination(frm) {
	// Show confirmation dialog
	frappe.confirm(
		__('Are you sure you want to execute this termination? This action cannot be undone and will:') +
        '<br><br>' +
        '• ' + __('Cancel all SEPA mandates') + '<br>' +
        '• ' + __('Unsubscribe from member newsletters') + '<br>' +
        '• ' + __('End all board/committee positions') + '<br>' +
        '• ' + __('Update membership status'),
		function() {
			// User confirmed
			frappe.call({
				method: 'execute_termination',
				doc: frm.doc,
				freeze: true,
				freeze_message: __('Executing termination...'),
				callback: function(r) {
					if (r.message) {
						frm.refresh();
						frappe.show_alert({
							message: __('Termination executed successfully'),
							indicator: 'green'
						}, 7);
					}
				}
			});
		}
	);
}

// Enhanced termination dialog function that can be called from Member form
window.show_enhanced_termination_dialog = function(member_id, member_name) {
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
					'--- Disciplinary ---',  // Visual separator
					'Policy Violation',
					'Disciplinary Action',
					'Expulsion'
				],
				reqd: 1,
				onchange: function() {
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
				mandatory_depends_on: 'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(termination_type)',
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
				mandatory_depends_on: 'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(termination_type)',
				get_query: function() {
					return {
						query: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_eligible_approvers'
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
		primary_action: function(values) {
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
			const disciplinary_types = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
			const is_disciplinary = disciplinary_types.includes(values.termination_type);

			if (is_disciplinary) {
				// Use disciplinary workflow
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.initiate_disciplinary_termination',
					args: {
						member_id: member_id,
						termination_data: termination_data
					},
					callback: function(r) {
						if (r.message) {
							dialog.hide();
							frappe.set_route('Form', 'Membership Termination Request', r.message.request_id);
						}
					}
				});
			} else {
				// Standard workflow - create request directly
				frappe.new_doc('Membership Termination Request', {
					member: member_id,
					member_name: member_name,
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

function toggle_dialog_fields(dialog, termination_type) {
	const disciplinary_types = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
	const is_disciplinary = disciplinary_types.includes(termination_type);

	// Toggle visibility of disciplinary-specific fields
	dialog.fields_dict.disciplinary_documentation.df.hidden = !is_disciplinary;
	dialog.fields_dict.secondary_approver.df.hidden = !is_disciplinary;

	// Refresh the dialog to show/hide fields
	dialog.refresh();
}

// Server-side query for eligible approvers
frappe.provide('verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request');

frappe.query_reports['Get Eligible Approvers'] = {
	execute: function(filters) {
		return frappe.call({
			method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_eligible_approvers',
			args: filters
		});
	}
};
