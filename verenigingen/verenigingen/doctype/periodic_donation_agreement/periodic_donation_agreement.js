// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Periodic Donation Agreement', {
    refresh: function(frm) {
        // Add buttons based on status
        if (!frm.doc.__islocal) {
            if (frm.doc.status === 'Active') {
                frm.add_custom_button(__('Link Donation'), function() {
                    link_donation_dialog(frm);
                }, __('Actions'));

                frm.add_custom_button(__('Cancel Agreement'), function() {
                    cancel_agreement_dialog(frm);
                }, __('Actions'));

                frm.add_custom_button(__('Generate PDF'), function() {
                    generate_agreement_pdf(frm);
                }, __('Actions'));
            }

            if (frm.doc.status === 'Draft') {
                frm.add_custom_button(__('Activate Agreement'), function() {
                    activate_agreement(frm);
                }, __('Actions'));
            }

            // Add donation statistics
            add_donation_statistics(frm);
        }

        // Set agreement type options based on configuration
        set_agreement_type_options(frm);

        // Update payment amount on change
        frm.trigger('annual_amount');
        frm.trigger('payment_frequency');

        // Update ANBI eligibility display
        if (frm.doc.agreement_duration_years) {
            update_anbi_eligibility_message(frm);
        }
    },

    annual_amount: function(frm) {
        calculate_payment_amount(frm);
    },

    payment_frequency: function(frm) {
        calculate_payment_amount(frm);
    },

    agreement_duration_years: function(frm) {
        // Update ANBI eligibility message
        update_anbi_eligibility_message(frm);

        // Auto-update end date based on duration
        if (frm.doc.start_date && frm.doc.agreement_duration_years) {
            let duration = parseInt(frm.doc.agreement_duration_years.split(' ')[0]);
            if (duration) {
                let end_date = frappe.datetime.add_years(frm.doc.start_date, duration);
                frm.set_value('end_date', end_date);
            }
        }
    },

    start_date: function(frm) {
        // Auto-calculate end date based on selected duration
        if (frm.doc.start_date && frm.doc.agreement_duration_years) {
            let duration = parseInt(frm.doc.agreement_duration_years.split(' ')[0]);
            if (duration) {
                let end_date = frappe.datetime.add_years(frm.doc.start_date, duration);
                frm.set_value('end_date', end_date);
            }
        }
    },

    donor: function(frm) {
        // Check if donor has active ANBI consent
        if (frm.doc.donor) {
            frappe.call({
                method: 'verenigingen.api.anbi_operations.get_donor_anbi_data',
                args: {
                    donor: frm.doc.donor
                },
                callback: function(r) {
                    if (r.message && r.message.success) {
                        if (!r.message.anbi_consent) {
                            frappe.msgprint({
                                title: __('ANBI Consent Missing'),
                                message: __('This donor has not given ANBI consent. The agreement can still be created, but may not be valid for tax purposes.'),
                                indicator: 'orange'
                            });
                        }

                        if (!r.message.identification_verified) {
                            frappe.msgprint({
                                title: __('Identification Not Verified'),
                                message: __('This donor\'s identification has not been verified. Consider verifying before creating the agreement.'),
                                indicator: 'orange'
                            });
                        }
                    }
                }
            });
        }
    }
});

function calculate_payment_amount(frm) {
    if (frm.doc.annual_amount && frm.doc.payment_frequency) {
        let payment_amount = 0;

        if (frm.doc.payment_frequency === 'Monthly') {
            payment_amount = frm.doc.annual_amount / 12;
        } else if (frm.doc.payment_frequency === 'Quarterly') {
            payment_amount = frm.doc.annual_amount / 4;
        } else if (frm.doc.payment_frequency === 'Annually') {
            payment_amount = frm.doc.annual_amount;
        }

        frm.set_value('payment_amount', payment_amount);
    }
}

function link_donation_dialog(frm) {
    // Get unlinked donations for this donor
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'Donation',
            filters: {
                donor: frm.doc.donor,
                periodic_donation_agreement: ['is', 'not set'],
                docstatus: 1
            },
            fields: ['name', 'date', 'amount', 'payment_method'],
            limit_page_length: 100
        },
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                let fields = [
                    {
                        label: __('Select Donation'),
                        fieldname: 'donation',
                        fieldtype: 'Select',
                        options: r.message.map(d => ({
                            value: d.name,
                            label: `${d.name} - ${frappe.datetime.str_to_user(d.date)} - €${d.amount}`
                        })),
                        reqd: 1
                    }
                ];

                let d = new frappe.ui.Dialog({
                    title: __('Link Donation to Agreement'),
                    fields: fields,
                    primary_action_label: __('Link'),
                    primary_action: function(values) {
                        frappe.call({
                            method: 'link_donation',
                            doc: frm.doc,
                            args: {
                                donation_name: values.donation
                            },
                            callback: function(r) {
                                if (r.message) {
                                    frappe.show_alert({
                                        message: __('Donation linked successfully'),
                                        indicator: 'green'
                                    });
                                    frm.reload_doc();
                                }
                            }
                        });
                        d.hide();
                    }
                });

                d.show();
            } else {
                frappe.msgprint(__('No unlinked donations found for this donor'));
            }
        }
    });
}

function cancel_agreement_dialog(frm) {
    let d = new frappe.ui.Dialog({
        title: __('Cancel Periodic Donation Agreement'),
        fields: [
            {
                label: __('Cancellation Reason'),
                fieldname: 'reason',
                fieldtype: 'Small Text',
                reqd: 1
            }
        ],
        primary_action_label: __('Cancel Agreement'),
        primary_action: function(values) {
            frappe.confirm(
                __('Are you sure you want to cancel this agreement? This action cannot be undone.'),
                function() {
                    frappe.call({
                        method: 'cancel_agreement',
                        doc: frm.doc,
                        args: {
                            reason: values.reason
                        },
                        callback: function(r) {
                            if (r.message) {
                                frappe.show_alert({
                                    message: __('Agreement cancelled successfully'),
                                    indicator: 'green'
                                });
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
            d.hide();
        }
    });

    d.show();
}

function activate_agreement(frm) {
    // Check required fields
    let required_fields = ['donor', 'start_date', 'annual_amount', 'payment_frequency', 'payment_method'];
    let missing_fields = [];

    required_fields.forEach(field => {
        if (!frm.doc[field]) {
            missing_fields.push(frm.fields_dict[field].df.label);
        }
    });

    if (missing_fields.length > 0) {
        frappe.msgprint({
            title: __('Missing Required Fields'),
            message: __('Please fill the following fields before activating: {0}', [missing_fields.join(', ')]),
            indicator: 'red'
        });
        return;
    }

    frappe.confirm(
        __('Are you sure you want to activate this agreement?'),
        function() {
            frm.set_value('status', 'Active');
            frm.save();
        }
    );
}

function generate_agreement_pdf(frm) {
    // TODO: Implement PDF generation
    frappe.msgprint(__('PDF generation will be implemented in Phase 3'));
}

function add_donation_statistics(frm) {
    // Add donation statistics to the dashboard
    if (frm.doc.donations && frm.doc.donations.length > 0) {
        // Calculate actual duration in years
        let duration_years = 5; // default
        if (frm.doc.agreement_duration_years) {
            duration_years = parseInt(frm.doc.agreement_duration_years.split(' ')[0]) || 5;
        }

        let total_expected = frm.doc.annual_amount * duration_years;
        let progress_percentage = total_expected > 0 ? ((frm.doc.total_donated / total_expected) * 100).toFixed(1) : 0;

        // Determine agreement type for display
        let agreement_type = duration_years >= 5 ? __('ANBI Agreement') : __('Donation Pledge');

        let stats_html = `
            <div class="donation-statistics">
                <h5>${__('Donation Statistics')} - ${agreement_type}</h5>
                <div class="row">
                    <div class="col-sm-3">
                        <strong>${__('Total Expected')}:</strong><br>
                        €${total_expected.toFixed(2)}
                        <small class="text-muted">(${duration_years} ${__('years')})</small>
                    </div>
                    <div class="col-sm-3">
                        <strong>${__('Total Donated')}:</strong><br>
                        €${(frm.doc.total_donated || 0).toFixed(2)}
                    </div>
                    <div class="col-sm-3">
                        <strong>${__('Progress')}:</strong><br>
                        ${progress_percentage}%
                    </div>
                    <div class="col-sm-3">
                        <strong>${__('Next Expected')}:</strong><br>
                        ${frm.doc.next_expected_donation ? frappe.datetime.str_to_user(frm.doc.next_expected_donation) : __('Not set')}
                    </div>
                </div>
            </div>
        `;

        frm.dashboard.add_comment(stats_html, 'blue', true);
    }
}

function set_agreement_type_options(frm) {
    // Set agreement type options based on configuration
    // For now, we'll use the default options
    // This can be expanded to pull from system settings
}

// Child table events for donations tracking
frappe.ui.form.on('Periodic Donation Agreement Item', {
    donations_add: function(frm, cdt, cdn) {
        // Update tracking when donation is added
        frm.trigger('update_donation_tracking');
    },

    donations_remove: function(frm, cdt, cdn) {
        // Update tracking when donation is removed
        frm.trigger('update_donation_tracking');
    },

    status: function(frm, cdt, cdn) {
        // Update tracking when status changes
        frm.trigger('update_donation_tracking');
    }
});

frappe.ui.form.on('Periodic Donation Agreement', {
    update_donation_tracking: function(frm) {
        // This will be handled server-side in the validate method
        frm.dirty();
    }
});

function update_anbi_eligibility_message(frm) {
    // Update ANBI eligibility message based on selected duration
    if (frm.doc.agreement_duration_years) {
        let duration = parseInt(frm.doc.agreement_duration_years.split(' ')[0]);
        let message = '';
        let indicator = '';

        if (duration >= 5) {
            message = __('This agreement qualifies for ANBI periodic donation tax benefits (5+ year commitment).');
            indicator = 'green';
            frm.set_value('anbi_eligible', 1);

            // Show expected ANBI benefits
            let anbi_info = `
                <div style="margin-top: 10px; padding: 10px; background-color: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px;">
                    <strong>${__('ANBI Tax Benefits')}:</strong>
                    <ul style="margin-bottom: 0;">
                        <li>${__('Full tax deductibility for donor')}</li>
                        <li>${__('No maximum deduction limit')}</li>
                        <li>${__('Notarial deed not required for agreements up to €5,000/year')}</li>
                    </ul>
                </div>
            `;
            frm.set_df_property('agreement_duration_years', 'description',
                __('Duration of the commitment. Minimum 5 years required for ANBI periodic donation tax benefits.') + anbi_info);
        } else {
            message = __('This is a donation pledge without ANBI tax benefits (less than 5 years). The donor can still deduct donations but with standard limits.');
            indicator = 'orange';
            frm.set_value('anbi_eligible', 0);

            // Show pledge information
            let pledge_info = `
                <div style="margin-top: 10px; padding: 10px; background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 4px;">
                    <strong>${__('Donation Pledge (No Special ANBI Benefits)')}:</strong>
                    <ul style="margin-bottom: 0;">
                        <li>${__('Standard tax deduction rules apply')}</li>
                        <li>${__('Subject to annual deduction limits')}</li>
                        <li>${__('Consider extending to 5+ years for full ANBI benefits')}</li>
                    </ul>
                </div>
            `;
            frm.set_df_property('agreement_duration_years', 'description',
                __('Duration of the commitment. Minimum 5 years required for ANBI periodic donation tax benefits.') + pledge_info);
        }

        // Display message to user
        if (!frm.is_new()) {
            frappe.show_alert({
                message: message,
                indicator: indicator
            }, 5);
        }

        // Update commitment type field if it exists
        if (frm.fields_dict.commitment_type) {
            frm.refresh_field('commitment_type');
        }
    }
}
