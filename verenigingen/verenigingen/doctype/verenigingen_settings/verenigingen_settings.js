// Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Verenigingen Settings', {
	refresh: function(frm) {
		frm.set_query('inv_print_format', function() {
			return {
				filters: {
					'doc_type': 'Sales Invoice'
				}
			};
		});

		frm.set_query('membership_print_format', function() {
			return {
				filters: {
					'doc_type': 'Membership'
				}
			};
		});

		frm.set_query('membership_debit_account', function() {
			return {
				filters: {
					'account_type': 'Receivable',
					'is_group': 0,
					'company': frm.doc.company
				}
			};
		});

		frm.set_query('donation_debit_account', function() {
			return {
				filters: {
					'account_type': 'Receivable',
					'is_group': 0,
					'company': frm.doc.donation_company
				}
			};
		});

		frm.set_query('membership_payment_account', function () {
			var account_types = ['Bank', 'Cash'];
			return {
				filters: {
					'account_type': ['in', account_types],
					'is_group': 0,
					'company': frm.doc.company
				}
			};
		});

		frm.set_query('donation_payment_account', function () {
			var account_types = ['Bank', 'Cash'];
			return {
				filters: {
					'account_type': ['in', account_types],
					'is_group': 0,
					'company': frm.doc.donation_company
				}
			};
		});

		let docs_url = 'https://docs.erpnext.com/docs/user/manual/en/verenigingen/membership';

		frm.set_intro(__('You can learn more about memberships in the manual. ') + `<a href='${docs_url}'>${__('ERPNext Docs')}</a>`, true);
		frm.trigger('setup_buttons_for_membership');
		frm.trigger('setup_buttons_for_donation');
		frm.trigger('setup_member_portal_buttons');
	},

	setup_buttons_for_membership: function(frm) {
		let label;

		if (frm.doc.membership_webhook_secret) {

			frm.add_custom_button(__('Copy Webhook URL'), () => {
				frappe.utils.copy_to_clipboard(`https://${frappe.boot.sitename}/api/method/verenigingen.verenigingen.doctype.membership.membership.trigger_razorpay_subscription`);
			}, __('Memberships'));

			frm.add_custom_button(__('Revoke Key'), () => {
				frm.call('revoke_key',  {
					key: 'membership_webhook_secret'
				}).then(() => {
					frm.refresh();
				});
			}, __('Memberships'));

			label = __('Regenerate Webhook Secret');

		} else {
			label = __('Generate Webhook Secret');
		}

		frm.add_custom_button(label, () => {
			frm.call('generate_webhook_secret', {
				field: 'membership_webhook_secret'
			}).then(() => {
				frm.refresh();
			});
		}, __('Memberships'));
	},

	setup_buttons_for_donation: function(frm) {
		let label;

		if (frm.doc.donation_webhook_secret) {
			label = __('Regenerate Webhook Secret');

			frm.add_custom_button(__('Copy Webhook URL'), () => {
				frappe.utils.copy_to_clipboard(`https://${frappe.boot.sitename}/api/method/verenigingen.verenigingen.doctype.donation.donation.capture_razorpay_donations`);
			}, __('Donations'));

			frm.add_custom_button(__('Revoke Key'), () => {
				frm.call('revoke_key', {
					key: 'donation_webhook_secret'
				}).then(() => {
					frm.refresh();
				});
			}, __('Donations'));

		} else {
			label = __('Generate Webhook Secret');
		}

		frm.add_custom_button(label, () => {
			frm.call('generate_webhook_secret', {
				field: 'donation_webhook_secret'
			}).then(() => {
				frm.refresh();
			});
		}, __('Donations'));
	},

	setup_member_portal_buttons: function(frm) {
		// Add member portal management buttons
		frm.add_custom_button(__('View Portal Stats'), () => {
			frappe.call({
				method: 'verenigingen.utils.member_portal_utils.get_member_portal_stats',
				callback: function(r) {
					if (r.message) {
						const stats = r.message;
						let message = `
							<h4>Member Portal Statistics</h4>
							<table class="table table-bordered">
								<tr><td><strong>Total Member Users:</strong></td><td>${stats.total_member_users}</td></tr>
								<tr><td><strong>Members with Portal Home:</strong></td><td>${stats.members_with_portal_home}</td></tr>
								<tr><td><strong>Members with Linked Records:</strong></td><td>${stats.members_with_linked_records}</td></tr>
								<tr><td><strong>Portal Adoption Rate:</strong></td><td>${stats.portal_adoption_rate}%</td></tr>
							</table>
						`;

						frappe.msgprint({
							title: __('Member Portal Statistics'),
							message: message,
							wide: true
						});
					}
				}
			});
		}, __('Member Portal'));

		frm.add_custom_button(__('Setup Portal Home Pages'), () => {
			frappe.confirm(
				__('Set /member_portal as home page for all users with Member role?'),
				function() {
					frappe.call({
						method: 'verenigingen.utils.member_portal_utils.set_all_members_home_page',
						args: {
							home_page: '/member_portal'
						},
						callback: function(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({
									message: __('Updated {0} member users with portal home page', [r.message.updated_count]),
									indicator: 'green'
								}, 5);
							} else {
								frappe.msgprint({
									title: __('Error'),
									message: r.message.message || 'Failed to update member home pages',
									indicator: 'red'
								});
							}
						}
					});
				}
			);
		}, __('Member Portal'));

		frm.add_custom_button(__('Test Portal Redirect'), () => {
			frappe.call({
				method: 'verenigingen.utils.member_portal_utils.get_user_appropriate_home_page',
				callback: function(r) {
					if (r.message) {
						frappe.show_alert({
							message: __('Your appropriate home page: {0}', [r.message]),
							indicator: 'blue'
						}, 5);

						// Optionally navigate to it
						setTimeout(() => {
							if (confirm('Navigate to your home page now?')) {
								window.location.href = r.message;
							}
						}, 2000);
					}
				}
			});
		}, __('Member Portal'));
	}
});
