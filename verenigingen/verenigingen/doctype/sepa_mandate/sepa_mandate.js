frappe.ui.form.on('SEPA Mandate', {
	refresh: function(frm) {
		// Add custom buttons based on status
		if (frm.doc.docstatus === 0) {  // Draft state
			// Only show these buttons for unsaved/unsubmitted docs

			// Draft → Active button
			if (frm.doc.status === 'Draft') {
				frm.add_custom_button(__('Activate'), function() {
					frm.set_value('status', 'Active');
					frm.set_value('is_active', 1);
					frm.save();
				}, __('Status'));
			}

			// Add status action buttons
			if (frm.doc.status === 'Active' && frm.doc.is_active) {
				frm.add_custom_button(__('Suspend'), function() {
					frm.set_value('status', 'Suspended');
					frm.set_value('is_active', 0);
					frm.save();
				}, __('Status'));

				frm.add_custom_button(__('Cancel'), function() {
					// Add confirmation dialog for cancelling
					frappe.confirm(
						__('Cancelling a mandate is permanent. Are you sure?'),
						function() {
							// On Yes
							frm.set_value('status', 'Cancelled');
							frm.set_value('is_active', 0);
							frm.set_value('cancelled_date', frappe.datetime.get_today());
							frm.save();
						}
					);
				}, __('Status'));
			}

			if (frm.doc.status === 'Suspended') {
				frm.add_custom_button(__('Reactivate'), function() {
					frm.set_value('status', 'Active');
					frm.set_value('is_active', 1);
					frm.save();
				}, __('Status'));
			}
		}

		// Add indicator based on status
		if (frm.doc.status) {
			let indicator = 'gray';
			if (frm.doc.status === 'Active') indicator = 'green';
			else if (frm.doc.status === 'Suspended') indicator = 'orange';
			else if (frm.doc.status === 'Cancelled') indicator = 'red';
			else if (frm.doc.status === 'Expired') indicator = 'red';
			else if (frm.doc.status === 'Draft') indicator = 'blue';

			frm.page.set_indicator(frm.doc.status, indicator);
		}

		// Add button to view related member
		if (frm.doc.member) {
			frm.add_custom_button(__('Member'), function() {
				frappe.set_route('Form', 'Member', frm.doc.member);
			}, __('View'));
		}
	},

	status: function(frm) {
		// When status changes, update is_active flag for consistency
		if (frm.doc.status === 'Active') {
			frm.set_value('is_active', 1);
		} else if (['Suspended', 'Cancelled', 'Expired'].includes(frm.doc.status)) {
			frm.set_value('is_active', 0);
		}

		// If status is set to Cancelled, prompt for cancellation reason
		if (frm.doc.status === 'Cancelled' && !frm.doc.cancelled_date) {
			frm.set_value('cancelled_date', frappe.datetime.get_today());
			setTimeout(() => frm.scroll_to_field('cancellation_reason'), 500);
		}
	},

	is_active: function(frm) {
		// Update status when is_active changes
		if (frm.doc.is_active) {
			if (frm.doc.status === 'Suspended') {
				frm.set_value('status', 'Active');
			}
		} else {
			if (frm.doc.status === 'Active') {
				frm.set_value('status', 'Suspended');
			}
		}
	},

	sign_date: function(frm) {
		// Validate sign date
		if (frm.doc.sign_date) {
			const today = frappe.datetime.get_today();
			if (frappe.datetime.str_to_obj(frm.doc.sign_date) > frappe.datetime.str_to_obj(today)) {
				frappe.msgprint(__('Sign date cannot be in the future'));
				frm.set_value('sign_date', today);
			}
		}
	},

	iban: function(frm) {
		// Format IBAN
		if (frm.doc.iban) {
			// Remove spaces and convert to uppercase
			let iban = frm.doc.iban.replace(/\s/g, '').toUpperCase();
			// Add spaces every 4 characters for readability
			iban = iban.replace(/(.{4})/g, '$1 ').trim();
			frm.set_value('iban', iban);
		}
	}
});
