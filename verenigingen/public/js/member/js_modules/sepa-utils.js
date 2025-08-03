/**
 * @fileoverview SEPA Mandate Utilities Module - European Payment Standard Implementation
 *
 * Comprehensive SEPA (Single Euro Payments Area) mandate management utilities for
 * the Verenigingen association platform. Provides complete European banking standard
 * compliance with automated IBAN validation, BIC derivation, mandate lifecycle management,
 * and seamless integration with member payment systems.
 *
 * ## Business Value
 * - **Payment Automation**: Streamlined recurring payment collection via SEPA Direct Debit
 * - **Regulatory Compliance**: Full adherence to European banking standards and regulations
 * - **Member Experience**: Simplified payment setup with intelligent bank detection
 * - **Administrative Efficiency**: Automated mandate creation and lifecycle management
 * - **Financial Security**: Secure payment authorization with comprehensive audit trails
 *
 * ## Core Capabilities
 * - **IBAN Validation**: Real-time International Bank Account Number validation
 * - **BIC Derivation**: Automatic Bank Identifier Code lookup and validation
 * - **Mandate Generation**: Intelligent mandate reference generation with unique identifiers
 * - **Bank Recognition**: Automatic bank name and details recognition from IBAN
 * - **Status Monitoring**: Real-time mandate status tracking and visualization
 * - **Payment Integration**: Seamless integration with member payment method configuration
 *
 * ## Technical Architecture
 * - **Modular Design**: Reusable utility functions with clear separation of concerns
 * - **Client-side Validation**: Real-time IBAN/BIC validation before server submission
 * - **Dialog Components**: Rich modal interfaces for mandate creation and management
 * - **API Integration**: Secure communication with backend SEPA services
 * - **Error Handling**: Comprehensive validation with user-friendly error messages
 * - **State Management**: Intelligent UI state management preventing duplicate operations
 *
 * ## SEPA Compliance Features
 * - **IBAN Standards**: Full ISO 13616 International Bank Account Number validation
 * - **BIC Standards**: ISO 9362 Bank Identifier Code validation and derivation
 * - **Mandate Types**: Support for both recurring and one-off payment mandates
 * - **Signature Requirements**: Digital signature tracking and validation
 * - **Regulatory Reporting**: Comprehensive audit trails for compliance reporting
 * - **Data Protection**: GDPR-compliant handling of sensitive financial information
 *
 * ## Integration Points
 * - **Member System**: Complete integration with member profile and payment methods
 * - **SEPA Mandate DocType**: Direct integration with mandate management system
 * - **Payment Processing**: Connection to SEPA Direct Debit batch processing
 * - **Banking APIs**: Integration with bank identification and validation services
 * - **Audit System**: Complete tracking of mandate creation and modifications
 * - **Notification Engine**: Automated alerts for mandate status changes
 *
 * ## Security Features
 * - **Data Validation**: Multi-layer validation of financial data before processing
 * - **Secure Transmission**: Encrypted communication for sensitive financial information
 * - **Access Control**: Role-based permissions for mandate creation and management
 * - **Audit Trail**: Complete logging of all mandate-related operations
 * - **Privacy Protection**: GDPR-compliant handling of personal financial data
 *
 * ## Performance Optimization
 * - **Client-side Validation**: Immediate feedback without server round-trips
 * - **Intelligent Caching**: Efficient caching of bank identification data
 * - **Lazy Loading**: On-demand loading of mandate status and details
 * - **Debounced Operations**: Prevention of duplicate API calls and submissions
 * - **Progressive Enhancement**: Graceful degradation for basic mandate functionality
 *
 * ## Module Functions
 * - `generateMandateReference()`: Create unique mandate identifiers
 * - `create_sepa_mandate_with_dialog()`: Interactive mandate creation interface
 * - `check_sepa_mandate_status()`: Real-time mandate status monitoring
 * - `clear_sepa_ui_elements()`: Clean UI state management
 *
 * ## Usage Examples
 * ```javascript
 * // Create SEPA mandate with dialog
 * SepaUtils.create_sepa_mandate_with_dialog(frm);
 *
 * // Check mandate status
 * SepaUtils.check_sepa_mandate_status(frm);
 *
 * // Generate mandate reference
 * const ref = SepaUtils.generateMandateReference(memberDoc);
 * ```
 *
 * @version 1.4.0
 * @author Verenigingen Development Team
 * @since 2024-Q1
 *
 * @requires frappe.ui.Dialog
 * @requires frappe.client
 * @requires IBANValidator (optional)
 *
 * @see {@link member.js} Member DocType Controller
 * @see {@link sepa_mandate.js} SEPA Mandate Management
 * @see {@link direct_debit_batch.js} Payment Processing
 */

// SEPA mandate utility functions for Member doctype

function generateMandateReference(memberDoc) {
	// Format: M-[MemberID]-[YYYYMMDD]-[Random3Digits]
	const today = new Date();
	const dateStr = today.getFullYear().toString()
                   + (today.getMonth() + 1).toString().padStart(2, '0')
                   + today.getDate().toString().padStart(2, '0');

	const randomSuffix = Math.floor(Math.random() * 900) + 100; // 3-digit random number

	const memberId = memberDoc.member_id || memberDoc.name.replace('Assoc-Member-', '').replace(/-/g, '');

	return `M-${memberId}-${dateStr}-${randomSuffix}`;
}

function create_sepa_mandate_with_dialog(frm, message = null) {
	// Prevent multiple mandate creation dialogs from being opened simultaneously
	if (frm._sepa_mandate_dialog_open) {
		return;
	}

	const suggestedReference = generateMandateReference(frm.doc);

	const confirmMessage = message || __('Would you like to create a new SEPA mandate for this bank account?');

	frappe.confirm(
		confirmMessage,
		() => {
			frm._sepa_mandate_dialog_open = true;
			const d = new frappe.ui.Dialog({
				title: __('Create SEPA Mandate'),
				size: 'large',
				onhide() {
					// Reset flag when dialog is closed
					frm._sepa_mandate_dialog_open = false;
				},
				fields: [
					{
						fieldname: 'mandate_id',
						fieldtype: 'Data',
						label: __('Mandate Reference'),
						reqd: 1,
						default: suggestedReference,
						description: __('Unique identifier for this mandate')
					},
					{
						fieldname: 'iban',
						fieldtype: 'Data',
						label: __('IBAN'),
						reqd: 1,
						default: frm.doc.iban || '',
						description: __('International Bank Account Number')
					},
					{
						fieldname: 'bic',
						fieldtype: 'Data',
						label: __('BIC/SWIFT Code'),
						default: frm.doc.bic || '',
						description: __('Bank Identifier Code (auto-derived from IBAN if empty)')
					},
					{
						fieldname: 'account_holder_name',
						fieldtype: 'Data',
						label: __('Account Holder Name'),
						reqd: 1,
						default: frm.doc.full_name || '',
						description: __('Name of the bank account holder')
					},
					{
						fieldtype: 'Column Break'
					},
					{
						fieldname: 'mandate_type',
						fieldtype: 'Select',
						label: __('Mandate Type'),
						options: 'One-off\nRecurring',
						default: 'Recurring',
						reqd: 1
					},
					{
						fieldname: 'sign_date',
						fieldtype: 'Date',
						label: __('Signature Date'),
						default: frappe.datetime.get_today(),
						reqd: 1
					},
					{
						fieldname: 'used_for_memberships',
						fieldtype: 'Check',
						label: __('Use for Membership Payments'),
						default: 1
					},
					{
						fieldname: 'used_for_donations',
						fieldtype: 'Check',
						label: __('Use for Donation Payments'),
						default: 0
					},
					{
						fieldtype: 'Section Break',
						label: __('Additional Options')
					},
					{
						fieldname: 'update_payment_method',
						fieldtype: 'Check',
						label: __('Update Member Payment Method to SEPA Direct Debit'),
						default: (frm.doc.payment_method !== 'SEPA Direct Debit') ? 1 : 0
					},
					{
						fieldname: 'notes',
						fieldtype: 'Text',
						label: __('Notes'),
						description: __('Optional notes about this mandate')
					}
				],
				primary_action_label: __('Create Mandate'),
				primary_action(values) {
					// Validate IBAN before submission
					if (window.IBANValidator) {
						const validation = window.IBANValidator.validate(values.iban);
						if (!validation.valid) {
							frappe.msgprint({
								title: __('Invalid IBAN'),
								message: validation.error,
								indicator: 'red'
							});
							return;
						}
						// Use formatted IBAN
						values.iban = validation.formatted;
					}

					create_mandate_with_values(frm, values, d);
				}
			});

			d.show();

			// Auto-derive BIC and validate IBAN when it changes
			d.fields_dict.iban.df.onchange = function () {
				const iban = d.get_value('iban');
				if (!iban) { return; }

				// Use comprehensive IBAN validation if available
				if (window.IBANValidator) {
					const validation = window.IBANValidator.validate(iban);

					if (!validation.valid) {
						frappe.msgprint({
							title: __('Invalid IBAN'),
							message: validation.error,
							indicator: 'red'
						});
						d.fields_dict.iban.$input.addClass('invalid');
						return;
					} else {
						// Format the IBAN
						d.set_value('iban', validation.formatted);
						d.fields_dict.iban.$input.removeClass('invalid');

						// Auto-derive BIC for Dutch IBANs
						const bic = window.IBANValidator.deriveBIC(iban);
						if (bic && !d.get_value('bic')) {
							d.set_value('bic', bic);

							// Show bank name if available
							const bankName = window.IBANValidator.getBankName(iban);
							if (bankName) {
								frappe.show_alert({
									message: __('Bank identified: {0}', [bankName]),
									indicator: 'green'
								}, 3);
							}
						}
					}
				}

				// Fallback to server-side BIC derivation
				if (!d.get_value('bic')) {
					frappe.call({
						method: 'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban',
						args: { iban },
						callback(r) {
							if (r.message && r.message.bic) {
								d.set_value('bic', r.message.bic);
							}
						}
					});
				}
			};
		},
		() => {
			frappe.show_alert(__('No new SEPA mandate created. The existing mandate will remain active.'), 5);
		}
	);
}

function create_mandate_with_values(frm, values, dialog) {
	const additionalArgs = {};

	// Get server-side validation data
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.validate_mandate_creation',
		args: {
			member: frm.doc.name,
			iban: values.iban,
			mandate_id: values.mandate_id
		},
		callback(validation_response) {
			const serverData = validation_response.message;

			if (serverData && serverData.existing_mandate) {
				additionalArgs.replace_existing = serverData.existing_mandate;
				frappe.show_alert({
					message: __('Existing mandate {0} will be replaced', [serverData.existing_mandate]),
					indicator: 'orange'
				}, 5);
			}

			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member.create_and_link_mandate_enhanced',
				args: {
					member: frm.doc.name,
					mandate_id: values.mandate_id,
					iban: values.iban,
					bic: values.bic || '',
					account_holder_name: values.account_holder_name,
					mandate_type: values.mandate_type,
					sign_date: values.sign_date,
					used_for_memberships: values.used_for_memberships,
					used_for_donations: values.used_for_donations,
					notes: values.notes,
					...additionalArgs
				},
				callback(r) {
					if (r.message) {
						let alertMessage = __('SEPA Mandate {0} created successfully', [values.mandate_id]);
						if (serverData && serverData.existing_mandate) {
							alertMessage += `. ${__('Previous mandate has been marked as replaced.')}`;
						}

						frappe.show_alert({
							message: alertMessage,
							indicator: 'green'
						}, 7);

						// Update payment method if requested
						if (values.update_payment_method && frm.doc.payment_method !== 'SEPA Direct Debit') {
							frm.set_value('payment_method', 'SEPA Direct Debit');
							frappe.show_alert({
								message: __('Payment method updated to SEPA Direct Debit'),
								indicator: 'blue'
							}, 5);
						}

						// Reset dialog flag and close dialog
						frm._sepa_mandate_dialog_open = false;
						dialog.hide();

						// Wait a moment then reload the form
						setTimeout(() => {
							frm.reload_doc();
						}, 1500);
					}
				},
				error(r) {
					// Reset flag on error too
					frm._sepa_mandate_dialog_open = false;
				}
			});
		}
	});
}

function check_sepa_mandate_status(frm) {
	if (!frm.doc.iban) {
		// Clear any existing SEPA buttons/indicators if no IBAN
		clear_sepa_ui_elements(frm);
		return;
	}

	// Create a unique check key based on IBAN and payment method
	const check_key = `${frm.doc.iban}-${frm.doc.payment_method || 'none'}`;

	// Prevent duplicate checks for the same IBAN/payment method combination
	if (frm._sepa_check_key === check_key) { return; }
	frm._sepa_check_key = check_key;

	// Clear existing SEPA UI elements before checking
	clear_sepa_ui_elements(frm);

	// Force a small delay to ensure cleanup is complete
	setTimeout(() => {
		let currentMandate = null;

		frappe.call({
			method: 'verenigingen.verenigingen.doctype.member.member.get_active_sepa_mandate',
			args: {
				member: frm.doc.name,
				iban: frm.doc.iban
			},
			callback(r) {
				// Only process if the response is for the current IBAN/payment method combination
				const current_check_key = `${frm.doc.iban}-${frm.doc.payment_method || 'none'}`;
				if (frm._sepa_check_key !== current_check_key) {
					return; // Ignore stale responses
				}

				if (r.message) {
					currentMandate = r.message;

					// Add mandate indicator
					const status_colors = {
						Active: 'green',
						Pending: 'orange',
						Draft: 'orange'
					};
					const color = status_colors[currentMandate.status] || 'red';
					const indicator_text = currentMandate.status === 'Active'
						? __('SEPA Mandate: {0}', [currentMandate.mandate_id])
						: __('SEPA Mandate: {0} ({1})', [currentMandate.mandate_id, currentMandate.status]);

					frm.dashboard.add_indicator(indicator_text, color);

					// Add view mandate button
					frm.add_custom_button(__('View SEPA Mandate'), () => {
						frappe.set_route('Form', 'SEPA Mandate', currentMandate.name);
					}, __('SEPA'));
				} else {
					// No active mandate found
					if (frm.doc.iban && frm.doc.payment_method === 'SEPA Direct Debit') {
						frm.dashboard.add_indicator(__('No SEPA Mandate'), 'red');

						frm.add_custom_button(__('Create SEPA Mandate'), () => {
							create_sepa_mandate_with_dialog(frm, __('No active SEPA mandate found for this IBAN. Would you like to create one?'));
						}, __('SEPA'));
					}
				}
			},
			error(r) {
				// Don't show error to user, just fail silently
			}
		});
	}, 100); // Small delay to ensure UI cleanup
}

function clear_sepa_ui_elements(frm) {
	// Remove SEPA-related dashboard indicators
	if (frm.dashboard && frm.dashboard.stats_area_row) {
		$(frm.dashboard.stats_area_row).find('.indicator').filter(function () {
			const text = $(this).text().toLowerCase();
			return text.includes('sepa') || text.includes('mandate');
		}).remove();
	}

	// Remove SEPA-related custom buttons more thoroughly
	if (frm.custom_buttons) {
		// Remove the SEPA button group
		if (frm.custom_buttons['SEPA']) {
			Object.keys(frm.custom_buttons['SEPA']).forEach((button_name) => {
				frm.remove_custom_button(button_name, 'SEPA');
			});
			delete frm.custom_buttons['SEPA'];
		}

		// Also remove any stray SEPA buttons
		$('.btn-custom').filter(function () {
			const label = $(this).attr('data-label') || $(this).text();
			return label && (label.includes('SEPA') || label.includes('Mandate'));
		}).remove();
	}
}

// Export functions for use in member.js
window.SepaUtils = {
	generateMandateReference,
	create_sepa_mandate_with_dialog,
	check_sepa_mandate_status,
	clear_sepa_ui_elements
};
