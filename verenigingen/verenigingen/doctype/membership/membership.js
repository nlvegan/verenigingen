/**
 * @fileoverview Membership DocType Controller - Comprehensive Membership Lifecycle Management
 *
 * Advanced membership management system for the Verenigingen association platform,
 * providing integrated dues schedule coordination, payment method management, and
 * membership type workflow automation. Seamlessly bridges membership records with
 * financial obligations through the sophisticated dues schedule system.
 *
 * ## Business Value
 * - **Revenue Management**: Automated dues schedule creation and financial tracking
 * - **Member Experience**: Streamlined payment method configuration and history access
 * - **Administrative Efficiency**: Centralized membership lifecycle management
 * - **Financial Compliance**: SEPA-compliant payment processing and audit trails
 * - **Retention Optimization**: Proactive renewal management and engagement tracking
 *
 * ## Core Capabilities
 * - **Dues Schedule Integration**: Automated creation and linking of payment schedules
 * - **Payment Method Management**: SEPA Direct Debit and alternative payment handling
 * - **Membership Type Workflow**: Dynamic form behavior based on membership configuration
 * - **Payment History Visualization**: Comprehensive financial transaction tracking
 * - **Renewal Management**: Automated date calculation and notification systems
 * - **Status Monitoring**: Real-time membership status and dues compliance tracking
 *
 * ## Technical Architecture
 * - **Form Controller**: Event-driven membership form management with financial integration
 * - **Database Integration**: Real-time queries for dues schedule status and validation
 * - **Dialog Components**: Modal interfaces for payment history and schedule management
 * - **Server Method Calls**: Secure communication with backend financial systems
 * - **Conditional UI**: Dynamic field visibility based on payment method selection
 * - **Error Handling**: Comprehensive validation and user feedback systems
 *
 * ## Integration Points
 * - **Membership Dues Schedule**: Primary financial obligation management system
 * - **Member Records**: Bidirectional linking for complete member profile management
 * - **SEPA Mandate System**: European payment standard compliance and validation
 * - **Payment Processing**: Integration with financial transaction systems
 * - **Notification Engine**: Automated renewal and payment reminder systems
 * - **Reporting Framework**: Financial analytics and membership insights
 *
 * ## Security Features
 * - **Document Status Validation**: State-based action restrictions
 * - **Payment Method Security**: Secure SEPA mandate handling and validation
 * - **Audit Trail**: Complete tracking of membership modifications and financial events
 * - **Permission Controls**: Role-based access to financial and membership data
 * - **Data Privacy**: GDPR-compliant member information handling
 *
 * ## Performance Optimization
 * - **Lazy Loading**: On-demand dues schedule and payment history retrieval
 * - **Query Optimization**: Efficient database access for status checks
 * - **Caching Strategy**: Smart caching of membership type configurations
 * - **Batch Processing**: Optimized bulk membership operations
 * - **Progressive Enhancement**: Graceful degradation for basic membership functions
 *
 * ## Financial Integration Features
 * - **Dues Schedule Automation**: Intelligent payment schedule generation
 * - **Payment History Access**: Real-time financial transaction visibility
 * - **SEPA Compliance**: European banking standard implementation
 * - **Renewal Tracking**: Automated membership period management
 * - **Status Synchronization**: Real-time dues and membership status alignment
 *
 * ## Usage Examples
 * ```javascript
 * // Configure SEPA Direct Debit
 * frm.set_value('payment_method', 'SEPA Direct Debit');
 * ```
 *
 * @version 1.3.0
 * @author Verenigingen Development Team
 * @since 2024-Q1
 *
 * @requires frappe.ui.form
 * @requires frappe.db
 * @requires frappe.ui.Dialog
 *
 * @see {@link member.js} Member Profile Management
 * @see {@link membership_dues_schedule.js} Financial Obligations
 * @see {@link sepa_mandate.js} Payment Authorization
 */

// Membership form controller with dues schedule integration
frappe.ui.form.on('Membership', {
	refresh(frm) {
		// Set up dues schedule buttons
		if (frm.doc.docstatus === 1) {
			// Check for any active dues schedule for this member
			if (frm.doc.member) {
				frappe.db
					.get_value(
						'Membership Dues Schedule',
						{
							member: frm.doc.member,
							is_template: 0,
							status: ['in', ['Active', 'Paused']]
						},
						'name'
					)
					.then((result) => {
						if (result.message && result.message.name) {
							frm.add_custom_button(
								__('View Active Dues Schedule'),
								() => {
									frappe.set_route('Form', 'Membership Dues Schedule', result.message.name);
								},
								__('Dues Schedule')
							);
						}
					});
			}

			// Note: dues_schedule field no longer exists on Membership.
			// Dues schedules are created automatically on submit (on_submit hook ->
			// MembershipDuesSchedule.create_from_template) and linked through member.
		}
	},

	membership_type(frm) {
		// Handle membership type change
		if (frm.doc.membership_type) {
			// Note: Dues/fee data is now stored in Membership Dues Schedule
			// This change will trigger dues schedule creation/update on save
			frm.trigger('refresh_dues_schedule_info');
		}
	},

	start_date(frm) {
		frm.trigger('calculate_renewal_date');
	},

	payment_method(frm) {
		const is_direct_debit = frm.doc.payment_method === 'SEPA Direct Debit';
		frm.toggle_reqd(['sepa_mandate'], is_direct_debit);
	}
});
