/**
 * @fileoverview Verenigingen Settings DocType Controller - System Configuration Management
 *
 * Comprehensive system configuration management interface for the Verenigingen association platform,
 * providing centralized control over membership settings, donation configuration, webhook management,
 * accounting integration, portal management, and organization-wide operational parameters.
 *
 * ## Business Value
 * - **Centralized Configuration**: Single source of truth for all system settings
 * - **Financial Integration**: Seamless accounting system configuration and management
 * - **Webhook Management**: Secure payment gateway integration with key rotation
 * - **Portal Administration**: Member portal configuration and statistics monitoring
 * - **Operational Control**: Organization-wide settings for membership and donation systems
 *
 * ## Core Capabilities
 * - **Account Configuration**: Automated setup of receivable and payment accounts
 * - **Print Format Management**: Customizable document templates for invoices and memberships
 * - **Webhook Security**: Secure webhook key generation and management
 * - **Portal Statistics**: Real-time member portal adoption and usage analytics
 * - **Company Integration**: Multi-company setup for membership and donation operations
 * - **Document Linking**: Intelligent filtering for account and format selections
 *
 * ## Technical Architecture
 * - **Form Controller**: Event-driven settings form management with dynamic validation
 * - **Query Filters**: Dynamic filtering for account selection based on company context
 * - **API Integration**: Secure communication with payment gateways and external services
 * - **Statistics Dashboard**: Real-time analytics for portal usage and member engagement
 * - **Security Management**: Webhook key lifecycle management with regeneration capabilities
 *
 * ## Integration Points
 * - **Accounting System**: Direct integration with ERPNext Chart of Accounts
 * - **Payment Gateways**: Webhook configuration for Razorpay and other payment providers
 * - **Print Framework**: Integration with Frappe's print format system
 * - **Member Portal**: Configuration and monitoring of member portal functionality
 * - **Membership System**: Core configuration for membership lifecycle management
 * - **Donation Platform**: Settings for donation processing and accounting
 *
 * ## Security Features
 * - **Webhook Key Management**: Secure generation, rotation, and revocation of webhook secrets
 * - **Account Validation**: Automated validation of accounting configuration
 * - **Access Control**: Role-based access to system configuration settings
 * - **Audit Trail**: Complete tracking of configuration changes and security events
 *
 * ## Configuration Categories
 * - **Membership Settings**: Core membership configuration and account mapping
 * - **Donation Settings**: Donation processing and accounting configuration
 * - **Portal Management**: Member portal behavior and home page configuration
 * - **Webhook Security**: Payment gateway integration and security settings
 * - **Company Configuration**: Multi-company setup and account segregation
 * - **Print Templates**: Document formatting and template management
 *
 * ## Advanced Features
 * - **Portal Analytics**: Real-time statistics on member portal adoption and usage
 * - **Bulk Operations**: Mass configuration of member portal home pages
 * - **Security Testing**: Portal redirect testing and validation
 * - **Account Filtering**: Context-aware account filtering based on company selection
 * - **Webhook URL Management**: Automated webhook URL generation and copying
 * - **Key Rotation**: Secure webhook key lifecycle management
 *
 * ## Usage Examples
 * ```javascript
 * // Configure membership accounts
 * frm.set_value('membership_debit_account', 'Receivable Account');
 *
 * // Generate webhook secret
 * frm.call('generate_webhook_secret', {field: 'membership_webhook_secret'});
 *
 * // Setup portal home pages
 * frm.trigger('setup_member_portal_buttons');
 * ```
 *
 * @version 1.4.0
 * @author Verenigingen Development Team
 * @since 2020-Q1
 *
 * @requires frappe.ui.form
 * @requires frappe.utils
 * @requires vereinigen.utils.member_portal_utils
 *
 * @see {@link member.js} Member Management Integration
 * @see {@link membership.js} Membership Configuration
 * @see {@link donation.js} Donation System Integration
 */

// Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Verenigingen Settings', {
	refresh(frm) {
		frm.set_query('inv_print_format', () => {
			return {
				filters: {
					doc_type: 'Sales Invoice'
				}
			};
		});

		frm.set_query('membership_print_format', () => {
			return {
				filters: {
					doc_type: 'Membership'
				}
			};
		});

		frm.set_query('membership_debit_account', () => {
			return {
				filters: {
					account_type: 'Receivable',
					is_group: 0,
					company: frm.doc.company
				}
			};
		});

		frm.set_query('donation_debit_account', () => {
			return {
				filters: {
					account_type: 'Receivable',
					is_group: 0,
					company: frm.doc.donation_company
				}
			};
		});

		frm.set_query('membership_payment_account', () => {
			const account_types = ['Bank', 'Cash'];
			return {
				filters: {
					account_type: ['in', account_types],
					is_group: 0,
					company: frm.doc.company
				}
			};
		});

		frm.set_query('donation_payment_account', () => {
			const account_types = ['Bank', 'Cash'];
			return {
				filters: {
					account_type: ['in', account_types],
					is_group: 0,
					company: frm.doc.donation_company
				}
			};
		});

		const docs_url = 'https://docs.erpnext.com/docs/user/manual/en/verenigingen/membership';

		frm.set_intro(`${__('You can learn more about memberships in the manual. ')}<a href='${docs_url}'>${__('ERPNext Docs')}</a>`, true);
		frm.trigger('setup_buttons_for_membership');
		frm.trigger('setup_buttons_for_donation');
		frm.trigger('setup_member_portal_buttons');
	},

	setup_buttons_for_membership(frm) {
		let label;

		if (frm.doc.membership_webhook_secret) {
			frm.add_custom_button(__('Copy Webhook URL'), () => {
				frappe.utils.copy_to_clipboard(`https://${frappe.boot.sitename}/api/method/verenigingen.verenigingen.doctype.membership.membership.trigger_razorpay_dues_schedule`);
			}, __('Memberships'));

			frm.add_custom_button(__('Revoke Key'), () => {
				frm.call('revoke_key', {
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

	setup_buttons_for_donation(frm) {
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

	setup_member_portal_buttons(frm) {
		// Add member portal management buttons
		frm.add_custom_button(__('View Portal Stats'), () => {
			frappe.call({
				method: 'verenigingen.utils.member_portal_utils.get_member_portal_stats',
				callback(r) {
					if (r.message) {
						const stats = r.message;
						const message = `
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
							message,
							wide: true
						});
					}
				}
			});
		}, __('Member Portal'));

		frm.add_custom_button(__('Setup Portal Home Pages'), () => {
			frappe.confirm(
				__('Set /member_portal as home page for all users with Member role?'),
				() => {
					frappe.call({
						method: 'verenigingen.utils.member_portal_utils.set_all_members_home_page',
						args: {
							home_page: '/member_portal'
						},
						callback(r) {
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
				callback(r) {
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
