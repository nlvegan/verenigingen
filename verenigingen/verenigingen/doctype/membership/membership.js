// Membership form controller with dues schedule integration
frappe.ui.form.on('Membership', {
	refresh: function(frm) {
		// Set up dues schedule buttons
		if (frm.doc.docstatus === 1) {
			// Check for any active dues schedule for this member
			if (frm.doc.member) {
				frappe.db.get_value('Membership Dues Schedule', {
					'member': frm.doc.member,
					'is_template': 0,
					'status': ['in', ['Active', 'Paused']]
				}, 'name').then(function(result) {
					if (result.message && result.message.name) {
						frm.add_custom_button(__('View Active Dues Schedule'), function() {
							frappe.set_route('Form', 'Membership Dues Schedule', result.message.name);
						}, __('Dues Schedule'));
					}
				});
			}

			// Note: dues_schedule field no longer exists on Membership
			// Dues schedules are managed separately and linked through member
		}

		// Add custom button for creating dues schedule if not exists
		if (frm.doc.docstatus === 1 && !frm.doc.dues_schedule) {
			// Check if member already has an active dues schedule before showing create button
			if (frm.doc.member) {
				frappe.db.get_value('Membership Dues Schedule', {
					'member': frm.doc.member,
					'is_template': 0,
					'status': 'Active'
				}, 'name').then(function(result) {
					if (!result.message || !result.message.name) {
						// No active dues schedule exists, show create button
						frm.add_custom_button(__('Create Dues Schedule'), function() {
							frm.call('create_dues_schedule_from_membership').then(function(response) {
								if (response.message) {
									frappe.show_alert({
										message: __('Dues Schedule created successfully'),
										indicator: 'green'
									});
									frm.refresh();
								}
							});
						}, __('Dues Schedule'));
					}
				});
			}
		}
	},

	membership_type: function(frm) {
		// Handle membership type change
		if (frm.doc.membership_type) {
			// Note: Dues/fee data is now stored in Membership Dues Schedule
			// This change will trigger dues schedule creation/update on save
			frm.trigger('refresh_dues_schedule_info');
		}
	},

	start_date: function(frm) {
		frm.trigger('calculate_renewal_date');
	},

	// Button handlers for dues schedule integration
	create_dues_schedule: function(frm) {
		if (frm.doc.docstatus === 1) {
			frm.call('create_dues_schedule_from_membership').then(function(r) {
				if (r.message) {
					frappe.msgprint(__('Dues schedule created successfully'));
					frm.reload_doc();
				}
			});
		}
	},

	view_dues_schedule: function(frm) {
		if (frm.doc.dues_schedule) {
			frappe.set_route('Form', 'Membership Dues Schedule', frm.doc.dues_schedule);
		}
	},

	view_payments: function(frm) {
		if (frm.doc.dues_schedule) {
			frm.call('show_payment_history').then(function(r) {
				if (r.message) {
					// Display payment history in a dialog
					let d = new frappe.ui.Dialog({
						title: __('Payment History'),
						fields: [
							{
								fieldname: 'payment_history',
								fieldtype: 'HTML'
							}
						]
					});

					let html = '<table class="table table-striped"><tr><th>Invoice</th><th>Date</th><th>Amount</th><th>Status</th></tr>';
					r.message.forEach(function(payment) {
						html += `<tr><td>${payment.invoice}</td><td>${payment.date}</td><td>${payment.amount}</td><td>${payment.status}</td></tr>`;
					});
					html += '</table>';

					d.fields_dict.payment_history.$wrapper.html(html);
					d.show();
				}
			});
		}
	},

	payment_method: function(frm) {
		const is_direct_debit = frm.doc.payment_method === 'SEPA Direct Debit';
		frm.toggle_reqd(['sepa_mandate'], is_direct_debit);
	}
});
