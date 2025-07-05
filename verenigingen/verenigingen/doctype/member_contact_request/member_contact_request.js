frappe.ui.form.on('Member Contact Request', {
	refresh: function(frm) {
		// Set status indicator
		if (frm.doc.status) {
			frm.set_indicator_label(frm.doc.status,
				frm.doc.status === 'Open' ? 'orange' :
				frm.doc.status === 'In Progress' ? 'blue' :
				frm.doc.status === 'Waiting for Response' ? 'yellow' :
				frm.doc.status === 'Resolved' ? 'green' : 'gray');
		}

		// Add custom buttons
		if (!frm.is_new()) {
			// View member button
			if (frm.doc.member) {
				frm.add_custom_button(__('View Member'), function() {
					frappe.set_route('Form', 'Member', frm.doc.member);
				}, __('Actions'));
			}

			// View CRM Lead button
			if (frm.doc.crm_lead) {
				frm.add_custom_button(__('View CRM Lead'), function() {
					frappe.set_route('Form', 'Lead', frm.doc.crm_lead);
				}, __('Actions'));
			}

			// Create Opportunity button (if lead exists and status is in progress)
			if (frm.doc.crm_lead && frm.doc.status === 'In Progress' && !frm.doc.crm_opportunity) {
				frm.add_custom_button(__('Create Opportunity'), function() {
					create_opportunity_from_lead(frm);
				}, __('CRM'));
			}

			// Quick status update buttons
			if (frm.doc.status === 'Open') {
				frm.add_custom_button(__('Start Working'), function() {
					frm.set_value('status', 'In Progress');
					frm.save();
				}, __('Status'));
			}

			if (frm.doc.status === 'In Progress') {
				frm.add_custom_button(__('Mark Resolved'), function() {
					frm.set_value('status', 'Resolved');
					if (!frm.doc.resolution) {
						frappe.prompt({
							label: 'Resolution',
							fieldname: 'resolution',
							fieldtype: 'Small Text',
							reqd: 1
						}, function(values) {
							frm.set_value('resolution', values.resolution);
							frm.save();
						}, __('Provide Resolution'));
					} else {
						frm.save();
					}
				}, __('Status'));
			}
		}

		// Hide CRM fields for portal users
		if (frappe.user_roles.includes('Member') && !frappe.user_roles.includes('System Manager')) {
			frm.set_df_property('crm_integration_section', 'hidden', 1);
			frm.set_df_property('notes', 'hidden', 1);
			frm.set_df_property('assigned_to', 'hidden', 1);
			frm.set_df_property('resolution', 'hidden', 1);
		}
	},

	member: function(frm) {
		// Auto-populate member details when member is selected
		if (frm.doc.member) {
			frappe.db.get_doc('Member', frm.doc.member)
				.then(member => {
					frm.set_value('member_name', member.member_name);
					frm.set_value('email', member.email_address);
					frm.set_value('phone', member.phone_number);
					frm.set_value('organization', member.organization);
				});
		}
	},

	request_type: function(frm) {
		// Set urgency based on request type
		if (frm.doc.request_type === 'Complaint') {
			frm.set_value('urgency', 'High');
		} else if (frm.doc.request_type === 'Technical Support') {
			frm.set_value('urgency', 'Normal');
		}
	},

	urgency: function(frm) {
		// Set follow-up date based on urgency
		if (frm.doc.urgency && !frm.doc.follow_up_date) {
			let days = 7; // Default
			if (frm.doc.urgency === 'Urgent') days = 1;
			else if (frm.doc.urgency === 'High') days = 2;
			else if (frm.doc.urgency === 'Normal') days = 5;
			else if (frm.doc.urgency === 'Low') days = 10;

			frm.set_value('follow_up_date', frappe.datetime.add_days(frappe.datetime.now_date(), days));
		}
	},

	status: function(frm) {
		// Handle status changes
		if (frm.doc.status === 'In Progress' && !frm.doc.response_date) {
			frm.set_value('response_date', frappe.datetime.now_date());
		}

		if ((frm.doc.status === 'Resolved' || frm.doc.status === 'Closed') && !frm.doc.closed_date) {
			frm.set_value('closed_date', frappe.datetime.now_date());
		}
	}
});

function create_opportunity_from_lead(frm) {
	if (!frm.doc.crm_lead) {
		frappe.msgprint(__('No CRM Lead linked to create opportunity from'));
		return;
	}

	frappe.call({
		method: 'frappe.client.get',
		args: {
			doctype: 'Lead',
			name: frm.doc.crm_lead
		},
		callback: function(r) {
			if (r.message) {
				let lead = r.message;

				// Create new opportunity
				frappe.new_doc('Opportunity', {
					opportunity_from: 'Lead',
					party_name: lead.name,
					customer_name: lead.lead_name,
					contact_email: lead.email_id,
					contact_mobile: lead.phone,
					source: lead.source,
					opportunity_type: 'Sales',
					title: `Follow-up: ${frm.doc.subject}`,
					custom_member_contact_request: frm.doc.name,
					custom_member_id: frm.doc.member
				});
			}
		}
	});
}
