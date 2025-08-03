/**
 * @fileoverview Customer-Member Integration Enhancement
 * @description Links ERPNext Customer records with Association Member profiles
 *
 * Business Context:
 * Bridges ERPNext's financial customer management with association membership
 * systems, enabling seamless navigation and data consistency between financial
 * transactions and membership operations.
 *
 * Key Features:
 * - Bidirectional navigation between Customer and Member records
 * - Real-time membership status indicators on customer forms
 * - Integrated dashboard connections for relationship visibility
 * - Automated status synchronization between systems
 *
 * Architecture:
 * - Form enhancement using Frappe's client-side form events
 * - API integration for real-time member data retrieval
 * - Dashboard widgets for relationship visualization
 * - Cross-reference navigation with route management
 *
 * Integration Points:
 * - ERPNext Customer DocType enhancement
 * - Association Member management system
 * - Financial transaction tracking
 * - Membership status workflows
 *
 * Business Value:
 * - Reduces data entry duplication between systems
 * - Improves customer service with membership context
 * - Enhances financial reporting with member categorization
 * - Streamlines administrative workflows
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module CustomerMemberLink
 * @requires frappe.ui.form, frappe.call
 */
frappe.ui.form.on('Customer', {
	refresh(frm) {
		if (!frm.is_new()) {
			// Add Member navigation button
			frappe.call({
				method: 'verenigingen.api.customer_member_link.get_member_from_customer',
				args: {
					customer: frm.doc.name
				},
				callback(r) {
					if (r.message) {
						// Add button to navigate to Member
						frm.add_custom_button(__('View Member'), () => {
							frappe.set_route('Form', 'Member', r.message.name);
						}, __('Links'));

						// Show member info in dashboard
						const status_color = r.message.status === 'Active' ? 'green'
							: r.message.status === 'Terminated' ? 'red' : 'orange';

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
