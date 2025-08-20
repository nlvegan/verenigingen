/**
 * @fileoverview Contribution Amendment Request Controller
 * @description Manages membership fee and billing modifications with approval workflows
 *
 * Business Context:
 * Handles member requests for changes to their contribution amounts, billing
 * intervals, and payment schedules. Provides structured approval workflows
 * and impact analysis for membership fee modifications.
 *
 * Key Features:
 * - Multi-type amendment support (fee changes, billing intervals)
 * - Comprehensive approval workflow with role-based access
 * - Real-time impact preview for financial changes
 * - Automated effective date management
 * - Integration with dues schedule system
 *
 * Workflow Management:
 * - Draft → Pending Approval → Approved → Applied progression
 * - Role-based approval restrictions for financial oversight
 * - Automated validation for required fields and business rules
 * - Historical tracking of amendment decisions
 *
 * Financial Impact Analysis:
 * - Real-time calculation of payment changes
 * - Future billing schedule adjustments
 * - Impact visualization for informed decisions
 * - Integration with membership billing systems
 *
 * Amendment Types:
 * - Fee Change: Modify contribution amounts with impact analysis
 * - Billing Interval Change: Adjust payment frequency
 * - Custom amendments with extensible field visibility
 *
 * Security Features:
 * - Role-based action restrictions
 * - Approval audit trails
 * - Irreversible application controls
 * - Member consent tracking
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module ContributionAmendmentRequest
 * @requires frappe.ui.form, frappe.call
 */

frappe.ui.form.on('Contribution Amendment Request', {
	refresh(frm) {
		// Add custom buttons based on status
		add_amendment_buttons(frm);

		// Load impact preview
		if (frm.doc.amendment_type === 'Fee Change' && frm.doc.requested_amount) {
			load_impact_preview(frm);
		}

		// Set field visibility
		set_field_visibility(frm);
	},

	membership(frm) {
		if (frm.doc.membership) {
			// Load current membership details
			load_membership_details(frm);
		}
	},

	amendment_type(frm) {
		set_field_visibility(frm);
		if (frm.doc.amendment_type === 'Fee Change') {
			load_impact_preview(frm);
		}
	},

	requested_amount(frm) {
		if (frm.doc.amendment_type === 'Fee Change' && frm.doc.requested_amount) {
			load_impact_preview(frm);
		}
	},

	effective_date(frm) {
		if (frm.doc.amendment_type === 'Fee Change') {
			load_impact_preview(frm);
		}
	}
});

function add_amendment_buttons(frm) {
	if (frm.doc.status === 'Pending Approval') {
		// Add approval buttons for authorized users
		if (frappe.user.has_role(['System Manager', 'Verenigingen Manager'])) {
			frm.add_custom_button(__('Approve'), () => {
				approve_amendment(frm);
			}, __('Actions')).addClass('btn-success');

			frm.add_custom_button(__('Reject'), () => {
				reject_amendment(frm);
			}, __('Actions')).addClass('btn-danger');
		}
	}

	if (frm.doc.status === 'Approved') {
		// Add apply button for system managers
		if (frappe.user.has_role(['System Manager', 'Verenigingen Manager'])) {
			frm.add_custom_button(__('Apply Amendment'), () => {
				apply_amendment(frm);
			}).addClass('btn-primary');
		}

		// Show apply info
		if (frm.doc.effective_date) {
			const today = frappe.datetime.get_today();
			if (frm.doc.effective_date <= today) {
				frm.dashboard.add_comment(__('This amendment is ready to be applied'), 'blue');
			} else {
				frm.dashboard.add_comment(__('This amendment will be applied on {0}', [frappe.datetime.str_to_user(frm.doc.effective_date)]), 'orange');
			}
		}
	}

	if (frm.doc.status === 'Draft') {
		frm.add_custom_button(__('Submit for Approval'), () => {
			submit_for_approval(frm);
		}).addClass('btn-warning');

		frm.add_custom_button(__('Preview Impact'), () => {
			preview_amendment_impact(frm);
		});
	}
}

function set_field_visibility(frm) {
	// Show/hide fields based on amendment type
	const is_fee_change = frm.doc.amendment_type === 'Fee Change';
	const is_billing_change = frm.doc.amendment_type === 'Billing Interval Change';

	frm.toggle_display('requested_amount', is_fee_change);
	frm.toggle_display('new_billing_interval', is_billing_change);
	frm.toggle_display('impact_preview', is_fee_change);
}

function load_membership_details(frm) {
	if (!frm.doc.membership) { return; }

	frappe.call({
		method: 'frappe.client.get',
		args: {
			doctype: 'Membership',
			name: frm.doc.membership
		},
		callback(r) {
			if (r.message) {
				const membership = r.message;

				// Set member details
				frm.set_value('member', membership.member);

				// Subscription system removed - using dues schedule system

				// Set current amount
				frappe.call({
					method: 'get_billing_amount',
					doc: membership,
					callback(amount_result) {
						if (amount_result.message) {
							frm.set_value('current_amount', amount_result.message);
						}
					}
				});
			}
		}
	});
}

// Subscription loading functions removed - using dues schedule system

function load_impact_preview(frm) {
	if (!frm.doc.membership || frm.doc.amendment_type !== 'Fee Change') {
		return;
	}

	frappe.call({
		method: 'get_impact_preview',
		doc: frm.doc,
		callback(r) {
			if (r.message && r.message.html) {
				frm.fields_dict.impact_preview.$wrapper.html(r.message.html);
			}
		}
	});
}

function approve_amendment(frm) {
	frappe.prompt([
		{
			label: __('Approval Notes'),
			fieldname: 'approval_notes',
			fieldtype: 'Small Text',
			description: __('Optional notes about the approval')
		}
	], (values) => {
		frappe.call({
			method: 'approve_amendment',
			doc: frm.doc,
			args: {
				approval_notes: values.approval_notes
			},
			callback(r) {
				if (!r.exc) {
					frm.reload_doc();
				}
			}
		});
	}, __('Approve Amendment'), __('Approve'));
}

function reject_amendment(frm) {
	frappe.prompt([
		{
			label: __('Rejection Reason'),
			fieldname: 'rejection_reason',
			fieldtype: 'Small Text',
			reqd: 1,
			description: __('Please provide a reason for rejection')
		}
	], (values) => {
		frappe.call({
			method: 'reject_amendment',
			doc: frm.doc,
			args: {
				rejection_reason: values.rejection_reason
			},
			callback(r) {
				if (!r.exc) {
					frm.reload_doc();
				}
			}
		});
	}, __('Reject Amendment'), __('Reject'));
}

function apply_amendment(frm) {
	frappe.confirm(
		__('Are you sure you want to apply this amendment? This action cannot be undone.'),
		() => {
			frappe.call({
				method: 'apply_amendment',
				doc: frm.doc,
				callback(r) {
					if (!r.exc && r.message) {
						const response = r.message;

						// Handle different response types
						if (response.status === 'success') {
							frm.reload_doc();
							frappe.show_alert({
								message: __('Amendment applied successfully'),
								indicator: 'green'
							});
						} else if (response.status === 'warning') {
							// Warning is already shown via msgprint in Python
							// Just show a brief alert as well
							frappe.show_alert({
								message: __('Amendment is scheduled for future application'),
								indicator: 'orange'
							});
						} else if (response.status === 'error') {
							// Error message is already shown via msgprint in Python
							frappe.show_alert({
								message: __('Amendment application failed'),
								indicator: 'red'
							});
						}
					} else if (!r.exc) {
						// Fallback for old-style responses
						frm.reload_doc();
						frappe.show_alert({
							message: __('Amendment applied successfully'),
							indicator: 'green'
						});
					}
				}
			});
		}
	);
}

function submit_for_approval(frm) {
	// Validate required fields
	if (!frm.doc.reason) {
		frappe.msgprint(__('Please provide a reason for the amendment'));
		return;
	}

	if (frm.doc.amendment_type === 'Fee Change' && !frm.doc.requested_amount) {
		frappe.msgprint(__('Please specify the requested amount'));
		return;
	}

	frappe.confirm(
		__('Submit this amendment for approval?'),
		() => {
			frm.set_value('status', 'Pending Approval');
			frm.save();
		}
	);
}

function preview_amendment_impact(frm) {
	if (frm.doc.amendment_type !== 'Fee Change') {
		frappe.msgprint(__('Impact preview is only available for fee changes'));
		return;
	}

	frappe.call({
		method: 'get_impact_preview',
		doc: frm.doc,
		callback(r) {
			if (r.message && r.message.html) {
				frappe.msgprint({
					title: __('Amendment Impact Preview'),
					message: r.message.html,
					wide: true
				});
			}
		}
	});
}
