// SEPA mandate utility functions for Member doctype

function generateMandateReference(memberDoc) {
    // Format: M-[MemberID]-[YYYYMMDD]-[Random3Digits]
    const today = new Date();
    const dateStr = today.getFullYear().toString() +
                   (today.getMonth() + 1).toString().padStart(2, '0') +
                   today.getDate().toString().padStart(2, '0');

    const randomSuffix = Math.floor(Math.random() * 900) + 100; // 3-digit random number

    let memberId = memberDoc.member_id || memberDoc.name.replace('Assoc-Member-', '').replace(/-/g, '');

    return `M-${memberId}-${dateStr}-${randomSuffix}`;
}

function create_sepa_mandate_with_dialog(frm, message = null) {
    // Prevent multiple mandate creation dialogs from being opened simultaneously
    if (frm._sepa_mandate_dialog_open) {
        console.log('SEPA mandate dialog already open, skipping');
        return;
    }

    const suggestedReference = generateMandateReference(frm.doc);

    const confirmMessage = message || __('Would you like to create a new SEPA mandate for this bank account?');

    frappe.confirm(
        confirmMessage,
        function() {
            frm._sepa_mandate_dialog_open = true;
            const d = new frappe.ui.Dialog({
                title: __('Create SEPA Mandate'),
                size: 'large',
                onhide: function() {
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
                primary_action: function(values) {
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
            d.fields_dict.iban.df.onchange = function() {
                const iban = d.get_value('iban');
                if (!iban) return;

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
                        args: { iban: iban },
                        callback: function(r) {
                            if (r.message && r.message.bic) {
                                d.set_value('bic', r.message.bic);
                            }
                        }
                    });
                }
            };
        },
        function() {
            console.log('User declined mandate creation');
            frappe.show_alert(__('No new SEPA mandate created. The existing mandate will remain active.'), 5);
        }
    );
}

function create_mandate_with_values(frm, values, dialog) {
    let additionalArgs = {};

    // Get server-side validation data
    frappe.call({
        method: 'verenigingen.verenigingen.doctype.member.member.validate_mandate_creation',
        args: {
            member: frm.doc.name,
            iban: values.iban,
            mandate_id: values.mandate_id
        },
        callback: function(validation_response) {
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
                callback: function(r) {
                    console.log('Mandate creation response:', r);
                    if (r.message) {
                        let alertMessage = __('SEPA Mandate {0} created successfully', [values.mandate_id]);
                        if (serverData && serverData.existing_mandate) {
                            alertMessage += '. ' + __('Previous mandate has been marked as replaced.');
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
                error: function(r) {
                    // Reset flag on error too
                    frm._sepa_mandate_dialog_open = false;
                    console.error('Error creating mandate:', r);
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
    if (frm._sepa_check_key === check_key) return;
    frm._sepa_check_key = check_key;

    // Clear existing SEPA UI elements before checking
    clear_sepa_ui_elements(frm);

    // Force a small delay to ensure cleanup is complete
    setTimeout(function() {
        let currentMandate = null;

    frappe.call({
        method: 'verenigingen.verenigingen.doctype.member.member.get_active_sepa_mandate',
        args: {
            member: frm.doc.name,
            iban: frm.doc.iban
        },
        callback: function(r) {
            // Only process if the response is for the current IBAN/payment method combination
            const current_check_key = `${frm.doc.iban}-${frm.doc.payment_method || 'none'}`;
            if (frm._sepa_check_key !== current_check_key) {
                return; // Ignore stale responses
            }

            if (r.message) {
                currentMandate = r.message;

                // Add mandate indicator
                const status_colors = {
                    'Active': 'green',
                    'Pending': 'orange',
                    'Draft': 'orange'
                };
                const color = status_colors[currentMandate.status] || 'red';
                const indicator_text = currentMandate.status === 'Active'
                    ? __("SEPA Mandate: {0}", [currentMandate.mandate_id])
                    : __("SEPA Mandate: {0} ({1})", [currentMandate.mandate_id, currentMandate.status]);

                frm.dashboard.add_indicator(indicator_text, color);

                // Add view mandate button
                frm.add_custom_button(__('View SEPA Mandate'), function() {
                    frappe.set_route('Form', 'SEPA Mandate', currentMandate.name);
                }, __('SEPA'));

            } else {
                // No active mandate found
                if (frm.doc.iban && frm.doc.payment_method === 'SEPA Direct Debit') {
                    frm.dashboard.add_indicator(__("No SEPA Mandate"), "red");

                    frm.add_custom_button(__('Create SEPA Mandate'), function() {
                        create_sepa_mandate_with_dialog(frm, __('No active SEPA mandate found for this IBAN. Would you like to create one?'));
                    }, __('SEPA'));
                }
            }
        },
        error: function(r) {
            console.error('Error checking SEPA mandate status:', r);
            // Don't show error to user, just fail silently
        }
    });
    }, 100); // Small delay to ensure UI cleanup
}

function clear_sepa_ui_elements(frm) {
    // Remove SEPA-related dashboard indicators
    if (frm.dashboard && frm.dashboard.stats_area_row) {
        $(frm.dashboard.stats_area_row).find('.indicator').filter(function() {
            const text = $(this).text().toLowerCase();
            return text.includes('sepa') || text.includes('mandate');
        }).remove();
    }

    // Remove SEPA-related custom buttons more thoroughly
    if (frm.custom_buttons) {
        // Remove the SEPA button group
        if (frm.custom_buttons['SEPA']) {
            Object.keys(frm.custom_buttons['SEPA']).forEach(function(button_name) {
                frm.remove_custom_button(button_name, 'SEPA');
            });
            delete frm.custom_buttons['SEPA'];
        }

        // Also remove any stray SEPA buttons
        $('.btn-custom').filter(function() {
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
