// Customer to Member Navigation Enhancement
frappe.ui.form.on('Customer', {
	refresh: function(frm) {
		if (!frm.is_new()) {
			// Add Member navigation button
			frappe.call({
				method: 'verenigingen.api.customer_member_link.get_member_from_customer',
				args: {
					customer: frm.doc.name
				},
				callback: function(r) {
					if (r.message) {
						// Add button to navigate to Member
						frm.add_custom_button(__('View Member'), function() {
							frappe.set_route('Form', 'Member', r.message.name);
						}, __('Links'));

						// Show member info in dashboard
						const status_color = r.message.status === 'Active' ? 'green' :
							r.message.status === 'Terminated' ? 'red' : 'orange';

						frm.dashboard.add_indicator(
							__('Member: {0} ({1})', [r.message.full_name, __(r.message.status)]),
							status_color
						);

						// Add to connections
						frm.dashboard.add_section({
							title: __('Membership'),
							items: [
								{
									label: __('Member'),
									value: r.message.full_name,
									route: ['Form', 'Member', r.message.name]
								}
							]
						});
					}
				}
			});
		}
	}
});
