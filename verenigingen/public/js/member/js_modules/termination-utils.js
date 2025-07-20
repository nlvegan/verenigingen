// Termination-related utility functions for Member doctype
// Updated to use the Membership Dues Schedule system.

function show_termination_dialog(member_id, member_name) {
	get_termination_impact(member_id, function(impact_data) {
		const dialog = new frappe.ui.Dialog({
			title: __('Terminate Membership for {0}', [member_name]),
			size: 'extra-large',
			fields: [
				{
					fieldtype: 'HTML',
					options: generate_impact_assessment_html(impact_data)
				},
				{
					fieldtype: 'Section Break',
					label: __('Termination Details')
				},
				{
					fieldname: 'termination_type',
					fieldtype: 'Select',
					label: __('Termination Type'),
					options: 'Voluntary\nNon-payment\nDeceased\n--- Disciplinary ---\nPolicy Violation\nDisciplinary Action\nExpulsion',
					reqd: 1,
					onchange: function() {
						update_termination_dialog_fields(dialog);
					}
				},
				{
					fieldname: 'termination_reason',
					fieldtype: 'Text Editor',
					label: __('Termination Reason'),
					reqd: 1
				},
				{
					fieldname: 'execution_date',
					fieldtype: 'Date',
					label: __('Execution Date'),
					default: frappe.datetime.get_today(),
					reqd: 1
				},
				{
					fieldtype: 'Section Break',
					label: __('Actions to Take')
				},
				{
					fieldname: 'deactivate_sepa_mandates',
					fieldtype: 'Check',
					label: __('Deactivate SEPA Mandates'),
					default: impact_data.sepa_mandates > 0 ? 1 : 0,
					description: impact_data.sepa_mandates > 0 ?
						__('Will deactivate {0} SEPA mandate(s)', [impact_data.sepa_mandates]) :
						__('No SEPA mandates found')
				},
				{
					fieldname: 'end_board_positions',
					fieldtype: 'Check',
					label: __('End Board Positions'),
					default: impact_data.board_positions > 0 ? 1 : 0,
					description: impact_data.board_positions > 0 ?
						__('Will end {0} active board position(s)', [impact_data.board_positions]) :
						__('No active board positions found')
				},
				{
					fieldname: 'cancel_memberships',
					fieldtype: 'Check',
					label: __('Cancel Active Memberships'),
					default: impact_data.active_memberships > 0 ? 1 : 0,
					description: impact_data.active_memberships > 0 ?
						__('Will cancel {0} active membership(s)', [impact_data.active_memberships]) :
						__('No active memberships found')
				},
				{
					fieldname: 'process_invoices',
					fieldtype: 'Check',
					label: __('Process Outstanding Invoices'),
					default: impact_data.outstanding_invoices > 0 ? 1 : 0,
					description: impact_data.outstanding_invoices > 0 ?
						__('Will process {0} outstanding invoice(s)', [impact_data.outstanding_invoices]) :
						__('No outstanding invoices found')
				},
				{
					// Updated to use dues schedule system
					fieldname: 'cancel_dues_schedules',
					fieldtype: 'Check',
					label: __('Cancel Subscriptions'),
					// Updated to use dues schedule system
					default: impact_data.dues_schedules > 0 ? 1 : 0,
					// Updated to use dues schedule system
					description: impact_data.dues_schedules > 0 ?
						__('Will cancel {0} active dues schedule(s)', [impact_data.dues_schedules]) :
						__('No active dues schedules found')
				},
				{
					fieldtype: 'Section Break',
					label: __('Disciplinary Actions'),
					depends_on: 'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(doc.termination_type)'
				},
				{
					fieldname: 'appeal_deadline',
					fieldtype: 'Date',
					label: __('Appeal Deadline'),
					default: frappe.datetime.add_days(frappe.datetime.get_today(), 30),
					description: __('Last date for filing appeals'),
					depends_on: 'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(doc.termination_type)'
				},
				{
					fieldname: 'disciplinary_documentation',
					fieldtype: 'Small Text',
					label: __('Disciplinary Documentation'),
					description: __('Reference to supporting documentation'),
					depends_on: 'eval:["Policy Violation", "Disciplinary Action", "Expulsion"].includes(doc.termination_type)'
				}
			],
			primary_action_label: __('Create Termination Request'),
			primary_action: function(values) {
				create_termination_request_v2(member_id, member_name, values, dialog);
			}
		});

		dialog.show();
	});
}

function update_termination_dialog_fields(dialog) {
	// The depends_on expressions in field definitions handle visibility automatically
	// Just refresh the dialog to update field visibility
	dialog.refresh();
}

function create_termination_request_v2(member_id, member_name, values, dialog) {
	const termination_data = {
		doctype: 'Membership Termination Request',
		member: member_id,
		member_name: member_name,
		termination_type: values.termination_type,
		termination_reason: values.termination_reason,
		execution_date: values.execution_date,
		deactivate_sepa_mandates: values.deactivate_sepa_mandates,
		end_board_positions: values.end_board_positions,
		cancel_memberships: values.cancel_memberships,
		process_invoices: values.process_invoices,
		cancel_dues_schedules: values.cancel_dues_schedules
	};

	// Add disciplinary fields if applicable
	const disciplinary_types = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
	const is_disciplinary = disciplinary_types.includes(values.termination_type);

	if (is_disciplinary) {
		if (values.appeal_deadline) {
			termination_data.appeal_deadline = values.appeal_deadline;
		}
		if (values.disciplinary_documentation) {
			termination_data.disciplinary_documentation = values.disciplinary_documentation;
		}
	}

	const confirmation_msg = create_confirmation_message(values, termination_data);

	frappe.confirm(
		confirmation_msg,
		function() {
			frappe.call({
				method: 'frappe.client.insert',
				args: {
					doc: termination_data
				},
				callback: function(r) {
					if (r.message) {
						dialog.hide();
						frappe.set_route('Form', 'Membership Termination Request', r.message.name);
						frappe.show_alert({
							message: __('Termination request created successfully'),
							indicator: 'green'
						}, 5);
					}
				}
			});
		}
	);
}

function create_confirmation_message(values, termination_data) {
	let msg = __('Are you sure you want to terminate membership for {0}?', [values.member_name || 'this member']);

	msg += '<br><br><strong>' + __('Termination Details:') + '</strong><br>';
	msg += __('Type: {0}', [values.termination_type]) + '<br>';
	msg += __('Date: {0}', [frappe.datetime.str_to_user(values.execution_date)]) + '<br>';

	if (values.termination_reason) {
		msg += __('Reason: {0}', [values.termination_reason.substring(0, 100) + '...']) + '<br>';
	}

	msg += '<br><strong>' + __('Actions to be taken:') + '</strong><br>';

	const actions = [];
	if (values.deactivate_sepa_mandates) actions.push(__('Deactivate SEPA mandates'));
	if (values.end_board_positions) actions.push(__('End board positions'));
	if (values.cancel_memberships) actions.push(__('Cancel memberships'));
	if (values.process_invoices) actions.push(__('Process outstanding invoices'));
	if (values.cancel_dues_schedules) actions.push(__('Cancel dues schedules'));

	if (actions.length > 0) {
		msg += '• ' + actions.join('<br>• ');
	} else {
		msg += __('No automatic actions selected');
	}

	return msg;
}

function show_termination_history(member_id) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_member_termination_history',
		args: {
			member: member_id
		},
		callback: function(r) {
			if (r.message) {
				display_termination_history_dialog(r.message);
			} else {
				frappe.msgprint(__('No termination history found for this member.'));
			}
		}
	});
}

function display_termination_history_dialog(termination_records) {
	let html = '<div class="termination-history">';
	html += '<h5>' + __('Termination History') + '</h5>';

	if (termination_records.length === 0) {
		html += '<p>' + __('No termination requests found.') + '</p>';
	} else {
		html += '<div class="table-responsive">';
		html += '<table class="table table-bordered">';
		html += '<thead><tr><th>' + __('Date') + '</th><th>' + __('Type') + '</th><th>' + __('Status') + '</th><th>' + __('Action') + '</th></tr></thead>';
		html += '<tbody>';

		termination_records.forEach(record => {
			const status_color = {
				'Draft': 'gray',
				'Pending Approval': 'orange',
				'Approved': 'green',
				'Rejected': 'red',
				'Executed': 'blue',
				'Cancelled': 'red'
			};

			const type_color = ['Policy Violation', 'Disciplinary Action', 'Expulsion'].includes(record.termination_type) ? 'red' : 'blue';

			html += `<tr>
                <td>${frappe.datetime.str_to_user(record.creation)}</td>
                <td><span style="color: ${type_color};">${record.termination_type}</span></td>
                <td><span style="color: ${status_color[record.status] || 'gray'};">${record.status}</span></td>
                <td><a href="/app/membership-termination-request/${record.name}">${__('View')}</a></td>
            </tr>`;
		});

		html += '</tbody></table>';
		html += '</div>';
	}

	html += '</div>';

	const dialog = new frappe.ui.Dialog({
		title: __('Termination History'),
		size: 'large',
		fields: [
			{
				fieldtype: 'HTML',
				options: html
			}
		]
	});

	dialog.show();
}

function generate_impact_assessment_html(impact_data) {
	let html = '<div class="impact-assessment" style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0;">';
	html += '<h5 style="margin: 0 0 15px 0; color: #495057;">📊 Termination Impact Assessment</h5>';

	const impacts = [
		{ label: 'SEPA Mandates', count: impact_data.sepa_mandates, icon: '💳' },
		{ label: 'Active Memberships', count: impact_data.active_memberships, icon: '📝' },
		{ label: 'Board Positions', count: impact_data.board_positions, icon: '👔' },
		{ label: 'Outstanding Invoices', count: impact_data.outstanding_invoices, icon: '💰' },
		{ label: 'Active Dues Schedules', count: impact_data.dues_schedules, icon: '🔄' },
		{ label: 'Volunteer Records', count: impact_data.volunteer_records || 0, icon: '🤝' },
		{ label: 'Pending Volunteer Expenses', count: impact_data.pending_volunteer_expenses || 0, icon: '💸' },
		{ label: 'Employee Records', count: impact_data.employee_records || 0, icon: '👥' },
		{ label: 'User Account', count: impact_data.user_account ? 1 : 0, icon: '👤' }
	];

	html += '<div class="row">';

	impacts.forEach(impact => {
		const color = impact.count > 0 ? '#dc3545' : '#28a745';
		html += '<div class="col-md-6 col-lg-4" style="margin-bottom: 10px;">';
		html += `<div style="padding: 8px; border-left: 3px solid ${color}; background: white; border-radius: 3px;">`;
		html += `<span style="font-size: 14px;">${impact.icon} <strong>${impact.label}:</strong> ${impact.count}</span>`;
		html += '</div></div>';
	});

	html += '</div>';

	if (!impact_data.customer_linked) {
		html += '<div style="background: #fff3cd; padding: 8px; margin-top: 10px; border-radius: 3px; font-size: 13px;">';
		html += '⚠️ <strong>Note:</strong> No customer account linked - some system updates may not apply.';
		html += '</div>';
	}

	html += '</div>';
	return html;
}

function get_termination_impact(member_id, callback) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_termination_impact_preview',
		args: {
			member: member_id
		},
		callback: function(r) {
			if (r.message && callback) {
				callback(r.message);
			}
		}
	});
}

// Export functions for use in member.js
window.TerminationUtils = {
	show_termination_dialog,
	show_termination_history,
	get_termination_impact
};
