// Copyright (c) 2026, Verenigingen and contributors
// For license information, please see license.txt

/**
 * Sales Invoice extension for ING Checkout iDEAL payments
 *
 * Adds "Pay with iDEAL" button to unpaid Sales Invoices
 */

frappe.ui.form.on('Sales Invoice', {
	refresh(frm) {
		// Only show button for submitted, unpaid invoices
		if (frm.doc.docstatus !== 1) { return; }
		if (frm.doc.status === 'Paid') { return; }
		if (frm.doc.outstanding_amount <= 0) { return; }

		// Check if ING Checkout is enabled (async)
		frappe.call({
			method:
				'verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings.is_ing_checkout_enabled',
			callback(r) {
				if (r.message && r.message.enabled) {
					frm.add_custom_button(
						__('Pay with iDEAL'),
						() => {
							ing_checkout_create_payment(frm);
						},
						__('ING Checkout')
					);
				}
			}
		});
	}
});

/**
 * Create iDEAL payment for the invoice
 */
function ing_checkout_create_payment(frm) {
	frappe.call({
		method:
			'verenigingen.verenigingen_payments.ing_checkout.api.payment.create_ideal_payment',
		args: {
			reference_doctype: 'Sales Invoice',
			reference_name: frm.doc.name,
			amount: frm.doc.outstanding_amount,
			description: frm.doc.name
		},
		freeze: true,
		freeze_message: __('Creating iDEAL payment...'),
		callback(r) {
			if (r.message && r.message.success) {
				// Show dialog with payment link
				const d = new frappe.ui.Dialog({
					title: __('iDEAL Payment Created'),
					fields: [
						{
							fieldtype: 'HTML',
							fieldname: 'payment_info',
							options: `
                                <div class="text-center">
                                    <p>${__('Payment has been created successfully.')}</p>
                                    <p><strong>${__('Transaction ID')}:</strong> ${r.message.transaction_id}</p>
                                    <p class="text-muted">${__('Click the button below to open the payment page, or copy the link to share with the customer.')}</p>
                                </div>
                            `
						},
						{
							fieldtype: 'Data',
							fieldname: 'redirect_url',
							label: __('Payment Link'),
							read_only: 1,
							default: r.message.redirect_url
						}
					],
					primary_action_label: __('Open Payment Page'),
					primary_action() {
						window.open(r.message.redirect_url, '_blank');
						d.hide();
					},
					secondary_action_label: __('Copy Link'),
					secondary_action() {
						frappe.utils.copy_to_clipboard(r.message.redirect_url);
						frappe.show_alert({
							message: __('Payment link copied to clipboard'),
							indicator: 'green'
						});
					}
				});
				d.show();

				// Refresh form to show linked transaction
				frm.reload_doc();
			} else {
				frappe.msgprint({
					title: __('Payment Creation Failed'),
					indicator: 'red',
					message:
						r.message && r.message.error
							? r.message.error
							: __('Could not create iDEAL payment. Please try again.')
				});
			}
		},
		error(r) {
			frappe.msgprint({
				title: __('Error'),
				indicator: 'red',
				message: __('Failed to create payment. Please check the error log.')
			});
		}
	});
}
