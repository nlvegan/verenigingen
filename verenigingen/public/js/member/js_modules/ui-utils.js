// UI utility functions for Member doctype - modernized for performance

function setup_payment_history_grid(frm) {
	if (!frm.fields_dict.payment_history) return;

	const gridWrapper = $(frm.fields_dict.payment_history.grid.wrapper);
	gridWrapper.addClass('payment-history-grid');

	// Remove 'No.' column from the payment history grid - optimized approach
	const hideGridColumns = () => {
		// Use more efficient CSS-based hiding instead of individual jQuery calls
		gridWrapper.addClass('no-idx-column');

		// Batch hide operations for better performance
		const elementsToHide = gridWrapper.find(
			'.grid-heading-row .grid-row-check, ' +
			'.grid-heading-row .row-index, ' +
			'.grid-body .data-row .row-index, ' +
			'.grid-body .data-row .grid-row-check'
		);
		elementsToHide.hide();
	};

	// Use requestAnimationFrame for better performance than setTimeout
	if (window.requestAnimationFrame) {
		requestAnimationFrame(hideGridColumns);
	} else {
		setTimeout(hideGridColumns, 100); // Reduced timeout for faster response
	}

	// Format existing rows with optimization
	const grid = frm.fields_dict.payment_history.grid;
	if (grid?.grid_rows?.length && window.PaymentUtils?.format_payment_history_row) {
		grid.grid_rows.forEach(row => {
			window.PaymentUtils.format_payment_history_row(row);
		});
	}
}

function add_custom_css() {
	if (!$('#member-custom-css').length) {
		$('head').append(`
            <style id="member-custom-css">
                .volunteer-info-card {
                    border: 1px solid #dee2e6;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }

                .payment-history-grid .no-idx-column .grid-heading-row .row-index,
                .payment-history-grid .no-idx-column .data-row .row-index,
                .payment-history-grid .no-idx-column .grid-heading-row .grid-row-check,
                .payment-history-grid .no-idx-column .data-row .grid-row-check {
                    display: none !important;
                }

                .chapter-suggestion-container {
                    border-left: 4px solid #007bff;
                }

                .termination-button {
                    margin-left: 10px;
                }

                .impact-assessment {
                    border: 1px solid #dee2e6;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                }

                .board-memberships {
                    background: #f8f9fa;
                    padding: 10px;
                    border-radius: 5px;
                    margin: 10px 0;
                }

                .board-memberships ul {
                    margin-bottom: 0;
                }

                .sepa-mandate-info {
                    background: #e7f3ff;
                    border-left: 4px solid #007bff;
                    padding: 10px;
                    margin: 10px 0;
                    border-radius: 0 5px 5px 0;
                }
            </style>
        `);
	}
}

function show_debug_postal_code_info(frm) {
	if (frm.doc.pincode) {
		frappe.call({
			method: 'verenigingen.verenigingen.doctype.chapter.chapter.debug_postal_code_matching',
			args: {
				pincode: frm.doc.pincode
			},
			callback: function(r) {
				if (r.message) {
					let message = `<div><strong>Postal Code Debug Results for ${r.message.pincode}</strong><br><br>`;

					if (r.message.chapters && r.message.chapters.length > 0) {
						message += '<strong>Matching Chapters:</strong><br>';
						r.message.chapters.forEach(chapter => {
							message += `• ${chapter.name} (Score: ${chapter.score}%, Distance: ${chapter.distance}km)<br>`;
						});
					} else {
						message += 'No matching chapters found.<br>';
					}

					if (r.message.debug_info) {
						message += '<br><strong>Debug Info:</strong><br>';
						Object.keys(r.message.debug_info).forEach(key => {
							message += `${key}: ${r.message.debug_info[key]}<br>`;
						});
					}

					message += '</div>';

					frappe.msgprint({
						title: __('Postal Code Debug'),
						message: message,
						indicator: 'blue'
					});
				}
			}
		});
	} else {
		frappe.msgprint(__('No postal code set for this member.'));
	}
}

function show_board_memberships(frm) {
	// First, always remove any existing board memberships display to prevent stale data
	$('.board-memberships').remove();

	// Only proceed if we have a valid member name
	if (!frm.doc.name) {
		return;
	}

	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.get_board_memberships',
		args: {
			member_name: frm.doc.name
		},
		callback: function(r) {

			// Only show board memberships if we actually have results
			if (r.message && Array.isArray(r.message) && r.message.length > 0) {
				var html = '<div class="board-memberships"><h4>Board Positions</h4><ul>';
				r.message.forEach(function(membership) {
					html += '<li><strong>' + membership.chapter + ':</strong> ' + membership.role +
                            ' (' + frappe.datetime.str_to_user(membership.start_date) + ' - ' +
                            (membership.end_date ? frappe.datetime.str_to_user(membership.end_date) : 'Current') + ')</li>';
				});
				html += '</ul></div>';

				// Insert after a suitable field, or create a dedicated section
				if (frm.fields_dict.current_chapter_display) {
					$(frm.fields_dict.current_chapter_display.wrapper).after(html);
				} else {
					// Fallback: add to end of form if no suitable field found
					$(frm.wrapper).find('.form-layout').append(html);
				}
			} else {
				// No board memberships found - ensure no stale HTML is displayed
			}
		},
		error: function(r) {
			// Remove any existing display on error
			$('.board-memberships').remove();
		}
	});
}

function create_organization_user(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.verenigingen_settings.verenigingen_settings.get_organization_email_domain',
		callback: function(r) {
			const domain = r.message && r.message.organization_email_domain
				? r.message.organization_email_domain
				: 'example.org';

			const nameForEmail = frm.doc.full_name
				? frm.doc.full_name.toLowerCase()
					.replace(/[^a-z0-9\s]/g, '')
					.replace(/\s+/g, '.')
				: '';

			const orgEmail = nameForEmail ? `${nameForEmail}@${domain}` : '';

			const d = new frappe.ui.Dialog({
				title: __('Create Organization User Account'),
				fields: [
					{
						fieldname: 'email',
						fieldtype: 'Data',
						label: __('Email Address'),
						reqd: 1,
						default: orgEmail
					},
					{
						fieldname: 'first_name',
						fieldtype: 'Data',
						label: __('First Name'),
						reqd: 1,
						default: frm.doc.first_name || ''
					},
					{
						fieldname: 'last_name',
						fieldtype: 'Data',
						label: __('Last Name'),
						default: frm.doc.last_name || ''
					},
					{
						fieldname: 'send_welcome_email',
						fieldtype: 'Check',
						label: __('Send Welcome Email'),
						default: 1
					}
				],
				primary_action_label: __('Create User'),
				primary_action: function(values) {
					frappe.call({
						method: 'verenigingen.verenigingen.doctype.member.member.create_organization_user',
						args: {
							member: frm.doc.name,
							email: values.email,
							first_name: values.first_name,
							last_name: values.last_name,
							send_welcome_email: values.send_welcome_email
						},
						callback: function(r) {
							if (r.message) {
								d.hide();
								frm.refresh();
								frappe.show_alert({
									message: __('User account created successfully'),
									indicator: 'green'
								}, 5);
							}
						}
					});
				}
			});

			d.show();
		}
	});
}

function setup_member_id_display(frm) {
	// Update member ID display - just set read-only, skip styling to avoid errors
	if (frm.doc.member_id) {
		try {
			frm.set_df_property('member_id', 'read_only', 1);
		} catch (e) {
			// Ignore styling errors for member ID field
		}
	}
}

function handle_payment_method_change(frm) {
	const is_direct_debit = frm.doc.payment_method === 'SEPA Direct Debit';
	const show_bank_details = ['SEPA Direct Debit', 'Bank Transfer'].includes(frm.doc.payment_method);

	// Show/hide bank details based on payment method
	frm.toggle_reqd('iban', is_direct_debit);
	frm.toggle_display('iban', show_bank_details);
	frm.toggle_display('bic', show_bank_details);
	frm.toggle_display('bank_name', show_bank_details);

	// Set up IBAN change handler for BIC derivation
	if (show_bank_details) {
		setup_iban_bic_derivation(frm);
	}

	if (is_direct_debit && frm.doc.iban) {
		if (window.SepaUtils && window.SepaUtils.check_sepa_mandate_status) {
			window.SepaUtils.check_sepa_mandate_status(frm);
		}
	}
}

function setup_iban_bic_derivation(frm) {
	// Set up IBAN field to auto-derive BIC
	// Check if IBAN field exists and is rendered before attaching handlers
	if (frm.fields_dict.iban && frm.fields_dict.iban.$input) {
		frm.fields_dict.iban.$input.off('change.bic_derivation').on('change.bic_derivation', function() {
			const iban = $(this).val();
			if (iban) {
				const derivedBic = get_bic_from_iban(iban);
				if (derivedBic && derivedBic !== frm.doc.bic) {
					frm.set_value('bic', derivedBic);
					frappe.show_alert({
						message: __('BIC automatically derived from IBAN: {0}', [derivedBic]),
						indicator: 'green'
					}, 3);
				}
			}
		});
	}
}

function get_bic_from_iban(iban) {
	/**
     * Derive BIC from IBAN using the same logic as the backend
     * This matches the get_bic_from_iban() function in direct_debit_batch.py
     */
	if (!iban || iban.length < 8) {
		return null;
	}

	try {
		// Remove spaces and convert to uppercase
		iban = iban.replace(/\s+/g, '').toUpperCase();

		// Dutch IBAN - extract bank code
		if (iban.startsWith('NL')) {
			const bankCode = iban.substring(4, 8);

			// Common Dutch bank codes (matching backend)
			const bankCodes = {
				'INGB': 'INGBNL2A',  // ING Bank
				'ABNA': 'ABNANL2A',  // ABN AMRO
				'RABO': 'RABONL2U',  // Rabobank
				'TRIO': 'TRIONL2U',  // Triodos Bank
				'SNSB': 'SNSBNL2A',  // SNS Bank
				'ASNB': 'ASNBNL21',  // ASN Bank
				'KNAB': 'KNABNL2H'   // Knab
			};

			return bankCodes[bankCode] || null;
		}

		// For other countries, we would need a more extensive mapping
		return null;
	} catch (error) {
		return null;
	}
}

// Export functions for use in member.js
window.UIUtils = {
	setup_payment_history_grid,
	add_custom_css,
	show_debug_postal_code_info,
	show_board_memberships,
	create_organization_user,
	setup_member_id_display,
	handle_payment_method_change,
	setup_iban_bic_derivation,
	get_bic_from_iban
};
