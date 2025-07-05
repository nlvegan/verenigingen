// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Donor', {
	refresh: function(frm) {
		frappe.dynamic_link = {doc: frm.doc, fieldname: 'name', doctype: 'Donor'};

		frm.toggle_display(['address_html','contact_html'], !frm.doc.__islocal);

		if(!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);

			// Add donation history functionality
			setup_donation_history(frm);
		} else {
			frappe.contacts.clear_address_and_contact(frm);
		}
	}
});

function setup_donation_history(frm) {
	// Add sync button for donation history
	frm.add_custom_button(__('Sync Donation History'), function() {
		sync_donation_history(frm);
	}, __('Actions'));

	// Add new donation button
	frm.add_custom_button(__('New Donation'), function() {
		frappe.new_doc('Donation', {
			donor: frm.doc.name
		});
	}, __('Create'));

	// Load and display donation summary
	load_donation_summary(frm);
}

function sync_donation_history(frm) {
	frappe.show_alert({
		message: __('Syncing donation history...'),
		indicator: 'blue'
	});

	frappe.call({
		method: 'verenigingen.utils.donation_history_manager.sync_donor_history',
		args: {
			donor_name: frm.doc.name
		},
		callback: function(r) {
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: __(r.message.message),
					indicator: 'green'
				});
				frm.reload_doc();
			} else {
				frappe.show_alert({
					message: __('Error syncing donation history: ') + (r.message.error || 'Unknown error'),
					indicator: 'red'
				});
			}
		}
	});
}

function load_donation_summary(frm) {
	frappe.call({
		method: 'verenigingen.utils.donation_history_manager.get_donor_summary',
		args: {
			donor_name: frm.doc.name
		},
		callback: function(r) {
			if (r.message && !r.message.error) {
				display_donation_summary(frm, r.message);
			}
		}
	});
}

function display_donation_summary(frm, summary) {
	// Create summary HTML
	let summary_html = `
		<div class="row" style="margin-bottom: 15px;">
			<div class="col-sm-12">
				<h5 style="margin-bottom: 10px;">Donation Summary</h5>
			</div>
		</div>
		<div class="row">
			<div class="col-sm-3">
				<div class="text-center">
					<h4 class="text-primary">${summary.total_donations}</h4>
					<p class="text-muted">Total Donations</p>
				</div>
			</div>
			<div class="col-sm-3">
				<div class="text-center">
					<h4 class="text-success">€${(summary.total_amount || 0).toFixed(2)}</h4>
					<p class="text-muted">Total Amount</p>
				</div>
			</div>
			<div class="col-sm-3">
				<div class="text-center">
					<h4 class="text-info">€${(summary.paid_amount || 0).toFixed(2)}</h4>
					<p class="text-muted">Paid Amount</p>
				</div>
			</div>
			<div class="col-sm-3">
				<div class="text-center">
					<h4 class="text-warning">€${(summary.unpaid_amount || 0).toFixed(2)}</h4>
					<p class="text-muted">Unpaid Amount</p>
				</div>
			</div>
		</div>
	`;

	if (summary.last_donation_date) {
		summary_html += `
			<div class="row" style="margin-top: 10px;">
				<div class="col-sm-12">
					<p><strong>Last Donation:</strong> ${frappe.datetime.str_to_user(summary.last_donation_date)}</p>
				</div>
			</div>
		`;
	}

	// Add payment methods breakdown if available
	if (summary.payment_methods && Object.keys(summary.payment_methods).length > 0) {
		let methods_html = '<p><strong>Payment Methods:</strong> ';
		let methods = [];
		for (let method in summary.payment_methods) {
			methods.push(`${method} (${summary.payment_methods[method]})`);
		}
		methods_html += methods.join(', ') + '</p>';
		summary_html += `
			<div class="row">
				<div class="col-sm-12">
					${methods_html}
				</div>
			</div>
		`;
	}

	// Find the donation history section and add summary before it
	let $donation_tab = frm.get_field('donor_history').$wrapper.closest('.tab-pane');
	if ($donation_tab.length) {
		// Remove existing summary if it exists
		$donation_tab.find('.donation-summary').remove();

		// Add new summary at the top of the tab
		$donation_tab.prepend(`<div class="donation-summary" style="margin-bottom: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 5px;">${summary_html}</div>`);
	}
}
