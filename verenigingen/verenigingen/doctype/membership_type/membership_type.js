frappe.ui.form.on('Membership Type', {
	refresh: function(frm) {
		// Add button to create dues schedule template
		if (!frm.doc.dues_schedule_template) {
			frm.add_custom_button(__('Create Dues Schedule Template'), function() {
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.membership_type.membership_type.create_dues_schedule_template',
					args: {
						'membership_type_name': frm.doc.name
					},
					callback: function(r) {
						if (r.message) {
							frm.refresh();
						}
					}
				});
			}, __('Actions'));
		}

		// Add button to view linked dues schedule template
		if (frm.doc.dues_schedule_template) {
			frm.add_custom_button(__('Dues Schedule Template'), function() {
				frappe.set_route('Form', 'Membership Dues Schedule', frm.doc.dues_schedule_template);
			}, __('View'));
		}

		// Add button to view memberships of this type
		frm.add_custom_button(__('Memberships'), function() {
			frappe.set_route('List', 'Membership', {'membership_type': frm.doc.name});
		}, __('View'));
	},

	billing_period: function(frm) {
		// Toggle custom period field
		frm.toggle_reqd('billing_period_in_months', frm.doc.billing_period === 'Custom');
		frm.toggle_display('billing_period_in_months', frm.doc.billing_period === 'Custom');

		// Clear the field if not custom
		if (frm.doc.billing_period !== 'Custom') {
			frm.set_value('billing_period_in_months', null);
		}
	},

	allow_auto_renewal: function(frm) {
		// If auto renewal is disabled, uncheck default for new members
		if (!frm.doc.allow_auto_renewal && frm.doc.default_for_new_members) {
			frm.set_value('default_for_new_members', 0);
			frappe.msgprint(__('Auto-renewal must be allowed for the default membership type'), __('Warning'));
		}
	},

	default_for_new_members: function(frm) {
		// Only one membership type can be default
		if (frm.doc.default_for_new_members) {
			frappe.call({
				method: 'frappe.client.get_list',
				args: {
					doctype: 'Membership Type',
					filters: {
						'default_for_new_members': 1,
						'name': ['!=', frm.doc.name]
					},
					fields: ['name']
				},
				callback: function(r) {
					if (r.message && r.message.length) {
						frappe.confirm(
							__('"{0}" is already set as default membership type. Do you want to make this the default instead?', [r.message[0].name]),
							function() {
								// Yes - keep this as default
								frappe.call({
									method: 'frappe.client.set_value',
									args: {
										doctype: 'Membership Type',
										name: r.message[0].name,
										fieldname: 'default_for_new_members',
										value: 0
									},
									callback: function() {
										frm.refresh();
									}
								});
							},
							function() {
								// No - revert this change
								frm.set_value('default_for_new_members', 0);
								frm.refresh_field('default_for_new_members');
							}
						);
					}
				}
			});
		}
	}
});
