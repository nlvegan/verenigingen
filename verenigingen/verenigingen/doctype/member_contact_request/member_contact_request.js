/**
 * @fileoverview Member Contact Request Form Controller
 * @description Comprehensive member support and communication management system
 *
 * Business Context:
 * Manages member inquiries, support requests, and communication workflows
 * with integrated CRM functionality for lead generation and opportunity
 * tracking. Essential for maintaining member satisfaction and engagement.
 *
 * Key Features:
 * - Intelligent status management with automated workflows
 * - CRM integration for lead and opportunity creation
 * - Auto-population of member details for efficiency
 * - Priority-based response scheduling
 * - Role-based field visibility for security
 *
 * Workflow Management:
 * - Request intake and categorization
 * - Automated urgency assessment and follow-up scheduling
 * - Progress tracking through defined status stages
 * - Resolution documentation and closure procedures
 *
 * CRM Integration:
 * - Automatic lead creation for non-members
 * - Opportunity generation for sales inquiries
 * - Contact synchronization across systems
 * - Cross-reference tracking for complete history
 *
 * User Experience:
 * - Context-sensitive action buttons
 * - Quick status updates with guided prompts
 * - Streamlined navigation between related records
 * - Progressive disclosure based on user roles
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module MemberContactRequest
 * @requires frappe.ui.form
 */

frappe.ui.form.on('Member Contact Request', {
	refresh(frm) {
		// Set status indicator
		if (frm.doc.status) {
			frm.set_indicator_label(frm.doc.status,
				frm.doc.status === 'Open' ? 'orange'
					: frm.doc.status === 'In Progress' ? 'blue'
						: frm.doc.status === 'Waiting for Response' ? 'yellow'
							: frm.doc.status === 'Resolved' ? 'green' : 'gray');
		}

		// Add custom buttons
		if (!frm.is_new()) {
			// View member button
			if (frm.doc.member) {
				frm.add_custom_button(__('View Member'), () => {
					frappe.set_route('Form', 'Member', frm.doc.member);
				}, __('Actions'));
			}

			// View CRM Lead button
			if (frm.doc.crm_lead) {
				frm.add_custom_button(__('View CRM Lead'), () => {
					frappe.set_route('Form', 'Lead', frm.doc.crm_lead);
				}, __('Actions'));
			}

			// Create Opportunity button (if lead exists and status is in progress)
			if (frm.doc.crm_lead && frm.doc.status === 'In Progress' && !frm.doc.crm_opportunity) {
				frm.add_custom_button(__('Create Opportunity'), () => {
					create_opportunity_from_lead(frm);
				}, __('CRM'));
			}

			// Quick status update buttons
			if (frm.doc.status === 'Open') {
				frm.add_custom_button(__('Start Working'), () => {
					frm.set_value('status', 'In Progress');
					frm.save();
				}, __('Status'));
			}

			if (frm.doc.status === 'In Progress') {
				frm.add_custom_button(__('Mark Resolved'), () => {
					frm.set_value('status', 'Resolved');
					if (!frm.doc.resolution) {
						frappe.prompt({
							label: 'Resolution',
							fieldname: 'resolution',
							fieldtype: 'Small Text',
							reqd: 1
						}, (values) => {
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

	member(frm) {
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

	request_type(frm) {
		// Set urgency based on request type
		if (frm.doc.request_type === 'Complaint') {
			frm.set_value('urgency', 'High');
		} else if (frm.doc.request_type === 'Technical Support') {
			frm.set_value('urgency', 'Normal');
		}
	},

	urgency(frm) {
		// Set follow-up date based on urgency
		if (frm.doc.urgency && !frm.doc.follow_up_date) {
			let days = 7; // Default
			if (frm.doc.urgency === 'Urgent') { days = 1; } else if (frm.doc.urgency === 'High') { days = 2; } else if (frm.doc.urgency === 'Normal') { days = 5; } else if (frm.doc.urgency === 'Low') { days = 10; }

			frm.set_value('follow_up_date', frappe.datetime.add_days(frappe.datetime.now_date(), days));
		}
	},

	status(frm) {
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
		callback(r) {
			if (r.message) {
				const lead = r.message;

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
