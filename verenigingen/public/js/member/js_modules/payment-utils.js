// Payment-related utility functions for Member doctype
// Updated to use the Membership Dues Schedule system.

function process_payment(frm) {
	if (!frm.doc.name) {
		frappe.msgprint(__('Please save the member record first.'));
		return;
	}

	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.process_payment',
		args: {
			member: frm.doc.name
		},
		callback: function(r) {
			if (r.message) {
				frm.refresh();
				frappe.show_alert(__('Payment processed successfully'), 5);
			}
		},
		error: function(r) {
			console.error('Error processing payment:', r);
			frappe.msgprint(__('Error processing payment. Please try again.'));
		}
	});
}

function mark_as_paid(frm) {
	frappe.confirm(
		__('Are you sure you want to mark this member as paid?'),
		function() {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member.mark_as_paid',
				args: {
					member: frm.doc.name
				},
				callback: function(r) {
					if (r.message) {
						frm.refresh();
						frappe.show_alert(__('Member marked as paid'), 5);
					}
				}
			});
		}
	);
}

function format_payment_history_row(row) {
	if (row && row.doc) {
		const statusColors = {
			'Paid': 'green',
			'Unpaid': 'red',
			'Overdue': 'orange',
			'Partially Paid': 'yellow'
		};

		const status = row.doc.payment_status;
		if (status && statusColors[status]) {
			$(row.wrapper).find('[data-fieldname="payment_status"]').css({
				'color': statusColors[status],
				'font-weight': 'bold'
			});
		}
	}
}

function refresh_financial_history(frm) {
	frappe.show_alert({
		message: __('Refreshing financial history...'),
		indicator: 'blue'
	});

	frappe.call({
		method: 'load_payment_history',
		doc: frm.doc,
		callback: function(r) {
			frm.refresh_field('payment_history');

			// Updated to refresh dues schedule summary
			frappe.call({
				method: 'refresh_dues_schedule_summary',
				doc: frm.doc,
				callback: function(r) {
					// Updated to use dues schedule system
					frm.refresh_field('dues_schedule_summary');
				}
			});

			// Count records by type
			let records = frm.doc.payment_history || [];
			let stats = calculate_financial_stats(records);

			// Show detailed message
			let message = `<div>Financial history refreshed:<br>
                ${stats.invoices + stats.membership_invoices} invoices (${stats.membership_invoices} membership, ${stats.paid} paid, ${stats.unpaid} unpaid, ${stats.overdue} overdue)<br>
                ${stats.unreconciled} unreconciled payments, ${stats.donations} linked to donations<br>
                Total: ${format_currency(stats.total_amount)}, Outstanding: ${format_currency(stats.outstanding)}</div>`;

			frappe.show_alert({
				message: message,
				indicator: stats.outstanding > 0 ? 'orange' : 'green'
			}, 10);
		}
	});
}

function calculate_financial_stats(records) {
	let stats = {
		total: records.length,
		invoices: 0,
		membership_invoices: 0,
		unreconciled: 0,
		donations: 0,
		paid: 0,
		unpaid: 0,
		overdue: 0,
		total_amount: 0,
		outstanding: 0
	};

	records.forEach(record => {
		stats.total_amount += flt(record.amount || 0);
		stats.outstanding += flt(record.outstanding_amount || 0);

		if (record.transaction_type === 'Regular Invoice') {
			stats.invoices++;
			if (record.payment_status === 'Paid') stats.paid++;
			else if (record.payment_status === 'Overdue') stats.overdue++;
			else if (['Unpaid', 'Partially Paid'].includes(record.payment_status)) stats.unpaid++;
		}
		else if (record.transaction_type === 'Membership Invoice') {
			stats.membership_invoices++;
			if (record.payment_status === 'Paid') stats.paid++;
			else if (record.payment_status === 'Overdue') stats.overdue++;
			else if (['Unpaid', 'Partially Paid'].includes(record.payment_status)) stats.unpaid++;
		}
		else if (record.transaction_type === 'Donation Payment') {
			stats.donations++;
		}
		else if (record.transaction_type === 'Unreconciled Payment') {
			stats.unreconciled++;
		}
	});

	return stats;
}

// Export functions for use in member.js
window.PaymentUtils = {
	process_payment,
	mark_as_paid,
	format_payment_history_row,
	refresh_financial_history,
	calculate_financial_stats
};
