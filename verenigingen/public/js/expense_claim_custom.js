// Custom script for Expense Claim to add member ledger link

frappe.ui.form.on('Expense Claim', {
	refresh: function(frm) {
		// Add "View Member Record" button if employee is linked
		if (frm.doc.employee && !frm.doc.__islocal) {
			// Check if this employee is linked to a member
			frappe.call({
				method: 'verenigingen.setup.document_links.get_member_from_expense_claim',
				args: {
					expense_claim: frm.doc.name
				},
				callback: function(r) {
					if (r.message) {
						// Employee is linked to a member - add button
						frm.add_custom_button(__('View Member Record'), function() {
							frappe.set_route('Form', 'Member', r.message);
						}, __('Links'));

						// Also add a button to view all expenses for this member
						frm.add_custom_button(__('View Member Expense History'), function() {
							frappe.set_route('List', 'Expense Claim', {
								'employee': frm.doc.employee
							});
						}, __('Links'));
					}
				}
			});
		}
	}
});
