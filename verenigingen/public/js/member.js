// Member form utilities - review functionality integrated into main member.js

// Define minimal UIUtils to prevent errors
window.UIUtils = window.UIUtils || {
    add_custom_css: function() {
        if (!$('#member-custom-css').length) {
            $('head').append(`
                <style id="member-custom-css">
                    .volunteer-info-card {
                        border: 1px solid #dee2e6;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    }
                    .board-memberships {
                        background: #f8f9fa;
                        padding: 10px;
                        border-radius: 5px;
                        margin: 10px 0;
                    }
                </style>
            `);
        }
    },
    setup_payment_history_grid: function(frm) {
        // Basic implementation
        if (frm.fields_dict.payment_history) {
            $(frm.fields_dict.payment_history.grid.wrapper).addClass('payment-history-grid');
        }
    },
    setup_member_id_display: function(frm) {
        // Basic implementation - just set read-only, skip styling to avoid errors
        if (frm.doc.member_id) {
            try {
                frm.set_df_property('member_id', 'read_only', 1);
                console.debug('Member ID set to read-only');
            } catch (e) {
                console.debug('Failed to set member_id read-only:', e);
            }
        }
    },
    show_board_memberships: function(frm) {
        // Placeholder - can be enhanced later
        console.log('Board memberships functionality placeholder');
    },
    setup_contact_requests_section: function(frm) {
        // Add contact requests section to member form
        if (!frm.is_new() && frm.doc.name) {
            frm.add_custom_button(__('Contact Requests'), function() {
                frappe.route_options = {"member": frm.doc.name};
                frappe.set_route("List", "Member Contact Request");
            }, __("View"));

            // Load and display recent contact requests
            frappe.call({
                method: 'verenigingen.verenigingen.doctype.member_contact_request.member_contact_request.get_member_contact_requests',
                args: {
                    member: frm.doc.name,
                    limit: 5
                },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        UIUtils.render_contact_requests_summary(frm, r.message);
                    }
                }
            });
        }
    },
    render_contact_requests_summary: function(frm, requests) {
        // Create a summary of recent contact requests
        let html = `
            <div class="contact-requests-summary">
                <h5>${__("Recent Contact Requests")}</h5>
                <div class="requests-list">
        `;

        requests.forEach(function(request) {
            const status_color = {
                'Open': 'orange',
                'In Progress': 'blue',
                'Resolved': 'green',
                'Closed': 'gray'
            }[request.status] || 'gray';

            html += `
                <div class="request-item" style="padding: 8px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>${request.subject}</strong><br>
                        <small style="color: #666;">${request.request_type} • ${moment(request.request_date).format('MMM DD, YYYY')}</small>
                    </div>
                    <span class="indicator ${status_color}">${request.status}</span>
                </div>
            `;
        });

        html += `
                </div>
                <div style="margin-top: 10px;">
                    <button class="btn btn-xs btn-default" onclick="frappe.set_route('List', 'Member Contact Request', {'member': '${frm.doc.name}'})">
                        ${__("View All Contact Requests")}
                    </button>
                </div>
            </div>
        `;

        // Add to the form - we'll add this to the dashboard area
        if (!frm.contact_requests_wrapper) {
            frm.contact_requests_wrapper = $('<div>').appendTo(frm.layout.wrapper.find('.form-dashboard'));
        }
        frm.contact_requests_wrapper.html(html);
    },
    handle_payment_method_change: function(frm) {
        // Basic implementation
        const is_direct_debit = frm.doc.payment_method === 'SEPA Direct Debit';
        const show_bank_details = ['SEPA Direct Debit', 'Bank Transfer'].includes(frm.doc.payment_method);

        frm.toggle_reqd('iban', is_direct_debit);
        frm.toggle_display('iban', show_bank_details);
        frm.toggle_display('bic', show_bank_details);
        frm.toggle_display('bank_name', show_bank_details);
    },
    create_organization_user: function(frm) {
        frappe.msgprint('Organization user creation functionality will be available after full utilities load.');
    },
    show_debug_postal_code_info: function(frm) {
        console.log('Debug postal code info placeholder');
    }
};

// SepaUtils will be loaded from sepa-utils.js via frappe.require
// No need to define placeholders as they override the real functions

window.ChapterUtils = window.ChapterUtils || {
    suggest_chapter_from_address: function(frm) {
        console.log('Chapter suggestion placeholder');
    },
    suggest_chapter_for_member: function(frm) {
        console.log('Chapter suggestion placeholder');
    }
};

window.VolunteerUtils = window.VolunteerUtils || {
    show_volunteer_info: function(frm) {
        console.log('Volunteer info placeholder');
    },
    show_volunteer_activities: function(name) {
        console.log('Volunteer activities placeholder');
    },
    show_volunteer_assignments: function(name) {
        console.log('Volunteer assignments placeholder');
    },
    create_volunteer_from_member: function(frm) {
        // Original implementation: Get organization email domain and set route options
        frappe.call({
            method: 'frappe.client.get_value',
            args: {
                doctype: 'Verenigingen Settings',
                fieldname: 'organization_email_domain'
            },
            callback: function(r) {
                // Default domain if not set
                const domain = r.message && r.message.organization_email_domain
                    ? r.message.organization_email_domain
                    : 'example.org';

                // Generate organization email based on full name
                // Replace spaces with dots and convert to lowercase
                const nameForEmail = frm.doc.full_name
                    ? frm.doc.full_name.replace(/\s+/g, '.').toLowerCase()
                    : '';

                // Construct organization email
                const orgEmail = nameForEmail ? `${nameForEmail}@${domain}` : '';

                // Set route options for creating volunteer
                frappe.route_options = {
                    'volunteer_name': frm.doc.full_name,
                    'member': frm.doc.name,
                    'preferred_pronouns': frm.doc.pronouns,
                    'email': orgEmail,  // Organization email
                    'personal_email': frm.doc.email || ''  // Personal email from member
                };

                // Create new volunteer doc
                frappe.new_doc('Volunteer');
            }
        });
    }
};

window.PaymentUtils = window.PaymentUtils || {
    process_payment: function(frm) {
        frappe.msgprint('Payment processing will be available after full utilities load.');
    },
    mark_as_paid: function(frm) {
        frappe.msgprint('Mark as paid will be available after full utilities load.');
    },
    refresh_financial_history: function(frm) {
        console.log('Financial history refresh placeholder');
    }
};

window.TerminationUtils = window.TerminationUtils || {
    show_termination_dialog: function(member, name) {
        frappe.msgprint('Termination functionality will be available after full utilities load.');
    },
    show_termination_history: function(member) {
        console.log('Termination history placeholder');
    }
};

// Initialize verenigingen namespace
frappe.provide("verenigingen.member_form");

verenigingen.member_form = {
    initialize_member_form: function(frm) {
        console.log('Initializing member form with contact requests');

        // Set up basic UI
        if (window.UIUtils) {
            UIUtils.add_custom_css();
            UIUtils.setup_member_id_display(frm);
            UIUtils.setup_payment_history_grid(frm);
            UIUtils.setup_contact_requests_section(frm);
        }

        // Set up form buttons and actions
        if (!frm.is_new()) {
            this.setup_custom_buttons(frm);
        }
    },

    setup_custom_buttons: function(frm) {
        // Add buttons for member-specific actions
        if (frm.doc.name && !frm.is_new()) {
            // Contact request button is already added in UIUtils.setup_contact_requests_section

            // Add volunteer creation button if not already a volunteer
            frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'Volunteer',
                    filters: {'member': frm.doc.name},
                    fieldname: 'name'
                },
                callback: function(r) {
                    if (!r.message) {
                        frm.add_custom_button(__('Create Volunteer'), function() {
                            VolunteerUtils.create_volunteer_from_member(frm);
                        }, __("Actions"));
                    }
                }
            });
        }
    }
};

frappe.ui.form.on('Member', {

    // ==================== FORM LIFECYCLE EVENTS ====================

    refresh: function(frm) {
        console.log('Member form refresh - initializing');

        // Prevent multiple initializations
        if (frm._member_form_initialized) {
            console.log('Member form already initialized, skipping');
            return;
        }

        // Initialize member form (utilities loaded at top level)
        verenigingen.member_form.initialize_member_form(frm);
        frm._member_form_initialized = true;
    },

    onload: function(frm) {
        // Set up form behavior on load
        setup_form_behavior(frm);

        // Populate address members on form load if address exists
        if (frm.doc.primary_address) {
            console.log('Form loaded with address, updating address members...');
            update_other_members_at_address(frm);
        }
    },

    // ==================== FIELD EVENT HANDLERS ====================

    full_name: function(frm) {
        if (frm.doc.full_name) {
            let full_name = [frm.doc.first_name, frm.doc.middle_name, frm.doc.last_name]
                .filter(name => name && name.trim())
                .join(' ');

            if (frm.doc.full_name !== full_name && full_name) {
                frm.set_value('full_name', full_name);
            }
        }
    },

    payment_method: function(frm) {
        if (window.UIUtils) {
            UIUtils.handle_payment_method_change(frm);
        }
    },

    iban: function(frm) {
        // Validate IBAN using comprehensive validator
        if (frm.doc.iban && window.IBANValidator) {
            const validation = window.IBANValidator.validate(frm.doc.iban);

            if (!validation.valid) {
                frappe.msgprint({
                    title: __('Invalid IBAN'),
                    message: validation.error,
                    indicator: 'red'
                });
                frm.set_df_property('iban', 'description', `<span style="color: red;">${validation.error}</span>`);
            } else {
                // Format the IBAN
                frm.set_value('iban', validation.formatted);
                frm.set_df_property('iban', 'description', '');

                // Auto-derive BIC for Dutch IBANs
                const bic = window.IBANValidator.deriveBIC(frm.doc.iban);
                if (bic && !frm.doc.bic) {
                    frm.set_value('bic', bic);

                    // Show bank name if available
                    const bankName = window.IBANValidator.getBankName(frm.doc.iban);
                    if (bankName) {
                        frappe.show_alert({
                            message: __('Bank identified: {0}', [bankName]),
                            indicator: 'green'
                        }, 3);
                    }
                }
            }
        }

        // Check SEPA mandate status
        if (frm.doc.iban && frm.doc.payment_method === 'SEPA Direct Debit' && window.SepaUtils) {
            SepaUtils.check_sepa_mandate_status(frm);
        }
    },

    pincode: function(frm) {
        // Auto-suggest chapter when postal code changes
        if (frm.doc.pincode && window.ChapterUtils) {
            setTimeout(() => {
                ChapterUtils.suggest_chapter_from_address(frm);
            }, 1000);
        }
    },

    primary_address: function(frm) {
        // Update other members at address when primary address changes
        update_other_members_at_address(frm);
    }
});

// ==================== ADDRESS MEMBERS FUNCTIONALITY ====================

function update_other_members_at_address(frm) {
    console.log('=== UPDATE OTHER MEMBERS AT ADDRESS CALLED ===');
    console.log('Member:', frm.doc.name);
    console.log('Primary Address:', frm.doc.primary_address);

    // Skip for new records
    if (frm.is_new() || !frm.doc.name || frm.doc.name.startsWith('new-')) {
        console.log('New record, skipping address member lookup');
        frm.set_value('other_members_at_address', '<div class="text-muted">Save member to see other members at this address</div>');
        return;
    }

    if (!frm.doc.primary_address) {
        console.log('No address, clearing field');
        frm.set_value('other_members_at_address', '<div class="text-muted">No address selected</div>');
        return;
    }

    // Show loading state
    console.log('Setting loading state');
    frm.set_value('other_members_at_address',
        '<div class="text-muted"><i class="fa fa-spinner fa-spin"></i> Loading other members...</div>');

    // Call dedicated API method to get HTML content for address members
    console.log('Calling API method: verenigingen.api.member_management.get_address_members_html_api');
    frappe.call({
        method: 'verenigingen.api.member_management.get_address_members_html_api',
        args: {
            member_id: frm.doc.name
        },
        callback: function(r) {
            console.log('API callback received:', r);
            if (r.message && r.message.success && r.message.html) {
                console.log('Setting HTML content, length:', r.message.html.length);
                frm.set_value('other_members_at_address', r.message.html);

                // Add click handlers for view buttons after content is set
                setTimeout(() => {
                    $(frm.fields_dict.other_members_at_address.$wrapper).off('click', '.view-member-btn').on('click', '.view-member-btn', function(e) {
                        e.preventDefault();
                        const memberName = $(this).data('member');
                        if (memberName) {
                            console.log('Opening member:', memberName);
                            frappe.set_route('Form', 'Member', memberName);
                        }
                    });
                }, 100);

                console.log('Address members HTML updated successfully');
            } else {
                console.log('No HTML content received');
                frm.set_value('other_members_at_address',
                    '<div class="text-muted">No other members found at this address</div>');
            }
        },
        error: function(err) {
            console.error('API Error:', err);
            frm.set_value('other_members_at_address',
                '<div class="text-muted text-danger">Error loading member information</div>');
        }
    });
}

function display_other_members_at_address(frm, other_members) {
    if (!other_members || other_members.length === 0) {
        frm.set_value('other_members_at_address',
            '<div class="text-muted">No other members found at this address</div>');
        return;
    }

    let html = `
        <div class="other-members-container" style="background: #f8f9fa; padding: 15px; border-radius: 8px; border: 1px solid #dee2e6;">
            <div style="display: flex; align-items: center; margin-bottom: 12px;">
                <i class="fa fa-users" style="color: #6c757d; margin-right: 8px;"></i>
                <span style="font-weight: 600; color: #495057;">
                    ${other_members.length} other member${other_members.length !== 1 ? 's' : ''} at this address
                </span>
            </div>
            <div class="members-list">
    `;

    other_members.forEach(member => {
        const statusColor = getStatusColor(member.status);
        const memberSince = member.member_since ? frappe.datetime.str_to_user(member.member_since) : 'Unknown';

        html += `
            <div class="member-card" style="background: white; padding: 12px; margin-bottom: 8px; border-radius: 6px; border-left: 4px solid ${statusColor}; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                <div style="display: flex; justify-content: between; align-items: flex-start;">
                    <div style="flex-grow: 1;">
                        <div style="display: flex; align-items: center; margin-bottom: 4px;">
                            <strong style="color: #212529; margin-right: 8px;">${member.full_name}</strong>
                            <span class="badge" style="background-color: ${statusColor}; color: white; font-size: 11px; padding: 2px 6px; border-radius: 12px;">
                                ${member.status}
                            </span>
                        </div>
                        <div style="font-size: 13px; color: #6c757d; margin-bottom: 4px;">
                            <i class="fa fa-heart" style="margin-right: 4px;"></i>
                            ${member.relationship}
                            ${member.age_group ? ` • ${member.age_group}` : ''}
                        </div>
                        <div style="font-size: 12px; color: #868e96;">
                            <i class="fa fa-calendar" style="margin-right: 4px;"></i>
                            Member since: ${memberSince}
                        </div>
                    </div>
                    <div style="margin-left: 12px;">
                        <button type="button" class="btn btn-xs btn-default view-member-btn"
                                data-member="${member.name}"
                                style="font-size: 11px; padding: 4px 8px;">
                            <i class="fa fa-external-link" style="margin-right: 4px;"></i>View
                        </button>
                    </div>
                </div>
            </div>
        `;
    });

    html += `
            </div>
        </div>
    `;

    frm.set_value('other_members_at_address', html);

    // Bind click events for view buttons
    setTimeout(() => {
        $(frm.fields_dict.other_members_at_address.$wrapper).off('click', '.view-member-btn').on('click', '.view-member-btn', function(e) {
            e.preventDefault();
            const memberName = $(this).data('member');
            frappe.set_route('Form', 'Member', memberName);
        });
    }, 100);
}

function getStatusColor(status) {
    const statusColors = {
        'Active': '#28a745',
        'Pending': '#ffc107',
        'Suspended': '#fd7e14',
        'Deceased': '#6c757d',
        'Banned': '#dc3545',
        'Terminated': '#dc3545',
        'Expired': '#6c757d'
    };
    return statusColors[status] || '#6c757d';
}

// ==================== CHILD TABLE EVENT HANDLERS ====================

frappe.ui.form.on('Member Payment History', {
    payment_history_add: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.transaction_date) {
            frappe.model.set_value(cdt, cdn, 'transaction_date', frappe.datetime.get_today());
        }
    },

    amount: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.outstanding_amount) {
            frappe.model.set_value(cdt, cdn, 'outstanding_amount', row.amount || 0);
        }
    }
});

// ==================== BUTTON SETUP FUNCTIONS ====================

function add_payment_buttons(frm) {
    if (frm.doc.payment_status !== 'Paid' && window.PaymentUtils) {
        frm.add_custom_button(__('Process Payment'), function() {
            PaymentUtils.process_payment(frm);
        }, __('Actions'));

        frm.add_custom_button(__('Mark as Paid'), function() {
            PaymentUtils.mark_as_paid(frm);
        }, __('Actions'));
    }
}

function add_customer_buttons(frm) {
    if (!frm.doc.customer && !frm.custom_buttons[__('Create Customer')]) {
        frm.add_custom_button(__('Create Customer'), function() {
            frm.call({
                doc: frm.doc,
                method: 'create_customer',
                callback: function(r) {
                    if (r.message) {
                        frm.refresh();
                    }
                }
            });
        }, __('Actions'));
    }
}

function add_membership_buttons(frm) {
    // Add button to create a new membership (original implementation)
    if (!frm.custom_buttons[__('Create Membership')]) {
        frm.add_custom_button(__('Create Membership'), function() {
            frappe.new_doc('Membership', {
                'member': frm.doc.name,
                'member_name': frm.doc.full_name,
                'email': frm.doc.email,
                'mobile_no': frm.doc.mobile_no,
                'start_date': frappe.datetime.get_today()
            });
        }, __('Actions'));
    }

    // Add button to view memberships
    if (!frm.custom_buttons[__('View Memberships')]) {
        frm.add_custom_button(__('View Memberships'), function() {
            frappe.set_route('List', 'Membership', {'member': frm.doc.name});
        }, __('View'));
    }

    // Add button to view current membership
    if (frm.doc.current_membership_details && !frm.custom_buttons[__('Current Membership')]) {
        frm.add_custom_button(__('Current Membership'), function() {
            frappe.set_route('Form', 'Membership', frm.doc.current_membership_details);
        }, __('View'));
    }
}

function add_chapter_buttons(frm) {
    frappe.call({
        method: 'verenigingen.verenigingen.doctype.member.member.is_chapter_management_enabled',
        callback: function(r) {
            if (r.message) {
                // Get member's current chapters and add view button if they have any
                get_member_current_chapters(frm.doc.name).then((chapters) => {
                    if (chapters.length > 0) {
                        if (chapters.length === 1) {
                            frm.add_custom_button(__('View Chapter'), function() {
                                frappe.set_route('Form', 'Chapter', chapters[0]);
                            }, __('View'));
                        } else {
                            // Multiple chapters - add dropdown
                            const chapter_dropdown = frm.add_custom_button(__('View Chapters'), function() {}, __('View'));
                            chapters.forEach(chapter => {
                                frm.add_custom_button(chapter, function() {
                                    frappe.set_route('Form', 'Chapter', chapter);
                                }, __('View'), chapter_dropdown);
                            });
                        }
                    }
                });

                frm.add_custom_button(__('Change Chapter'), function() {
                    if (window.ChapterUtils) {
                        ChapterUtils.suggest_chapter_for_member(frm);
                    }
                }, __('Actions'));

                // Add chapter suggestion UI when no chapter is assigned
                add_chapter_suggestion_UI(frm);

                // Chapter indicator is handled in main member form JS

                // Debug postal code button removed as requested
            }
        },
        error: function(r) {
            // If API call fails, still add basic chapter button if chapter exists
            console.log('Error checking chapter management, adding basic chapter button');
            get_member_current_chapters(frm.doc.name).then((chapters) => {
                if (chapters.length > 0) {
                    frm.add_custom_button(__('View Chapter'), function() {
                        frappe.set_route('Form', 'Chapter', chapters[0]);
                    }, __('View'));
                }
            });
        }
    });
}

function add_view_buttons(frm) {
    if (frm.doc.customer) {
        frm.add_custom_button(__('Customer'), function() {
            frappe.set_route('Form', 'Customer', frm.doc.customer);
        }, __('View'));

        frm.add_custom_button(__('Refresh Financial History'), function() {
            if (window.PaymentUtils) {
                PaymentUtils.refresh_financial_history(frm);
            }
        }, __('Actions'));

        frm.add_custom_button(__('View Donations'), function() {
            frappe.call({
                method: "verenigingen.verenigingen.doctype.member.member.get_linked_donations",
                args: {
                    "member": frm.doc.name
                },
                callback: function(r) {
                    if (r.message && r.message.donor) {
                        frappe.route_options = {
                            "donor": r.message.donor
                        };
                        frappe.set_route("List", "Donation");
                    } else {
                        frappe.msgprint(__("No donor record linked to this member."));
                    }
                }
            });
        }, __('View'));
    }
}

function add_volunteer_buttons(frm) {
    // Add create volunteer button (always available)
    if (!frm.custom_buttons[__('Create Volunteer')]) {
        frm.add_custom_button(__('Create Volunteer'), function() {
            if (window.VolunteerUtils) {
                VolunteerUtils.create_volunteer_from_member(frm);
            }
        }, __('Actions'));
    }

}

function add_user_buttons(frm) {
    // Add button to create user (original implementation)
    if (!frm.doc.user && frm.doc.email && !frm.custom_buttons[__('Create User')]) {
        frm.add_custom_button(__('Create User'), function() {
            frm.call({
                doc: frm.doc,
                method: 'create_user',
                callback: function(r) {
                    if (r.message) {
                        frm.refresh();
                    }
                }
            });
        }, __('Actions'));
    }

    // Add button to view linked user
    if (frm.doc.user && !frm.custom_buttons[__('User')]) {
        frm.add_custom_button(__('User'), function() {
            frappe.set_route('Form', 'User', frm.doc.user);
        }, __('View'));
    }
}

function add_termination_buttons(frm) {
    // Check termination status and add appropriate buttons
    frappe.call({
        method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_member_termination_status',
        args: {
            member: frm.doc.name
        },
        callback: function(r) {
            if (r.message) {
                const status = r.message;

                // Add terminate button if no active termination
                if (!status.has_active_termination) {
                    let button_class = 'btn-danger';
                    let button_text = __('Terminate Membership');

                    let btn = frm.add_custom_button(button_text, function() {
                        if (window.TerminationUtils) {
                            TerminationUtils.show_termination_dialog(frm.doc.name, frm.doc.full_name);
                        }
                    }, __('Actions'));

                    if (btn && btn.addClass) {
                        btn.addClass(button_class + ' termination-button');
                    }
                }


            }
        },
        error: function(r) {
            // If API call fails, still add basic termination button
            console.log('Error checking termination status, adding basic termination button');
            let btn = frm.add_custom_button(__('Terminate Membership'), function() {
                if (window.TerminationUtils) {
                    TerminationUtils.show_termination_dialog(frm.doc.name, frm.doc.full_name);
                }
            }, __('Actions'));

            if (btn && btn.addClass) {
                btn.addClass('btn-danger termination-button');
            }
        }
    });
}

function add_chapter_suggestion_UI(frm) {
    // Banner removed as requested - chapter assignment is handled elsewhere
    // No longer showing "This member doesn't have a chapter assigned yet" message
}

// ==================== FORM SETUP FUNCTIONS ====================

function setup_form_behavior(frm) {
    // Set up member ID field behavior
    if (frm.doc.member_id) {
        frm.set_df_property('member_id', 'read_only', 1);
    }

    // Set up payment method dependent fields
    if (window.UIUtils) {
        UIUtils.handle_payment_method_change(frm);
    }

    // Set up organization user creation if enabled
    setup_organization_user_creation(frm);
}

function setup_organization_user_creation(frm) {
    frappe.call({
        method: 'verenigingen.verenigingen.doctype.verenigingen_settings.verenigingen_settings.get_organization_email_domain',
        callback: function(r) {
            if (r.message && r.message.organization_email_domain) {
                if (!frm.doc.user && frm.doc.docstatus === 1) {
                    frm.add_custom_button(__('Create Organization User'), function() {
                        if (window.UIUtils) {
                            UIUtils.create_organization_user(frm);
                        }
                    }, __('Actions'));
                }
            }
        }
    });
}


// Member form utilities namespace
frappe.provide("verenigingen.member_form");

verenigingen.member_form = {
    initialize_member_form: function(frm) {
        console.log('Initializing member form for:', frm.doc.name);

        // Initialize UI and custom CSS
        if (window.UIUtils) {
            UIUtils.add_custom_css();
            UIUtils.setup_payment_history_grid(frm);
            UIUtils.setup_member_id_display(frm);
        }

        // Update chapter display if member exists
        if (frm.doc.name && !frm.doc.__islocal) {
            console.log('Calling refresh_chapter_display for member:', frm.doc.name);
            this.refresh_chapter_display(frm);
        } else {
            console.log('Not calling refresh_chapter_display - doc name:', frm.doc.name, 'islocal:', frm.doc.__islocal);
        }

        // Application review is now handled in the main member.js file

        // Set up buttons immediately without clearing (to prevent disappearing)
        this.setup_all_buttons(frm);

        // Check SEPA mandate status
        if (frm.doc.payment_method === 'SEPA Direct Debit' && frm.doc.iban && window.SepaUtils) {
            SepaUtils.check_sepa_mandate_status(frm);
        }

        // Show volunteer info if exists
        if (window.VolunteerUtils) {
            VolunteerUtils.show_volunteer_info(frm);
        }

        // Show board memberships if any
        if (window.UIUtils) {
            UIUtils.show_board_memberships(frm);
        }
    },

    setup_all_buttons: function(frm) {
        console.log('Setting up all buttons for member form');

        // Add action buttons for submitted documents
        if (frm.doc.docstatus === 1) {
            add_payment_buttons(frm);
        }

        // Add customer creation button if not exists
        add_customer_buttons(frm);

        // Add user creation/view buttons
        add_user_buttons(frm);

        // Add membership creation/view buttons
        add_membership_buttons(frm);

        // Add chapter management buttons
        add_chapter_buttons(frm);

        // Add view buttons for related records
        add_view_buttons(frm);

        // Add volunteer-related buttons
        add_volunteer_buttons(frm);

        // Add termination buttons
        add_termination_buttons(frm);

        // Show Chapter Info debug button removed as requested

        console.log('All member form buttons setup complete');
    },

    refresh_chapter_display: function(frm) {
        // Refresh the chapter display information
        console.log('refresh_chapter_display called for:', frm.doc.name);
        if (!frm.doc.name || frm.doc.__islocal) {
            console.log('Skipping chapter display - no name or local doc');
            return;
        }

        frappe.call({
            method: 'verenigingen.verenigingen.doctype.member.member.get_member_chapter_display_html',
            args: {
                member_name: frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    console.log('Chapter display HTML received:', r.message);

                    // Try multiple insertion strategies
                    let chapter_html = `
                        <div class="member-chapter-info" style="margin: 15px 0; padding: 15px; background: #f8f9fa; border-radius: 6px; border: 1px solid #dee2e6;">
                            <h5 style="margin-bottom: 10px; color: #495057;">
                                <i class="fa fa-map-marker" style="margin-right: 8px;"></i>
                                Chapter Membership
                            </h5>
                            <div class="chapter-content">
                                ${r.message}
                            </div>
                        </div>
                    `;

                    // Remove existing display first
                    $('.member-chapter-info').remove();

                    // Strategy 1: Insert after chapter_assigned_date field
                    if (frm.fields_dict.chapter_assigned_date) {
                        $(frm.fields_dict.chapter_assigned_date.wrapper).after(chapter_html);
                        console.log('Inserted chapter info after chapter_assigned_date field');
                    }
                    // Strategy 2: Insert after chapter_assigned_by field
                    else if (frm.fields_dict.chapter_assigned_by) {
                        $(frm.fields_dict.chapter_assigned_by.wrapper).after(chapter_html);
                        console.log('Inserted chapter info after chapter_assigned_by field');
                    }
                    // Strategy 3: Insert after member details section
                    else if (frm.fields_dict.member_details_section) {
                        $(frm.fields_dict.member_details_section.wrapper).after(chapter_html);
                        console.log('Inserted chapter info after member_details_section');
                    }
                    // Strategy 4: Insert at the top of the form
                    else {
                        $(frm.wrapper).find('.form-layout').first().prepend(chapter_html);
                        console.log('Inserted chapter info at top of form');
                    }
                }
            },
            error: function(r) {
                console.log('Error refreshing chapter display:', r);
            }
        });
    },


    initialize_member_form_basic: function(frm) {
        // Basic initialization without utilities
        console.log('Loading member form with basic functionality (utilities not available)');

        // Add action buttons for submitted documents
        if (frm.doc.docstatus === 1) {
            add_payment_buttons(frm);
        }

        // Add customer creation button if not exists
        add_customer_buttons(frm);

        // Add user creation/view buttons
        add_user_buttons(frm);

        // Add membership creation/view buttons
        add_membership_buttons(frm);

        // Add chapter management buttons
        add_chapter_buttons(frm);

        // Add view buttons for related records
        add_view_buttons(frm);

        // Add volunteer-related buttons
        add_volunteer_buttons(frm);

        // Add termination buttons
        add_termination_buttons(frm);
    }
};

// ==================== HELPER FUNCTIONS ====================

function get_member_current_chapters(member_name) {
    // Get list of chapters a member belongs to using safe server method
    return new Promise((resolve, reject) => {
        if (!member_name) {
            resolve([]);
            return;
        }

        frappe.call({
            method: 'verenigingen.verenigingen.doctype.member.member.get_member_current_chapters',
            args: {
                member_name: member_name
            },
            callback: function(r) {
                if (r.message) {
                    // Extract chapter names from the returned chapter objects
                    const chapters = r.message.map(ch => ch.chapter || ch.parent).filter(ch => ch);
                    resolve(chapters);
                } else {
                    resolve([]);
                }
            },
            error: function(r) {
                console.error('Error getting member chapters:', r);
                resolve([]);
            }
        });
    });
}

// (Duplicate function removed - using the one defined earlier)

function display_other_members_at_address(frm, members) {
    if (!members || members.length === 0) {
        frm.set_df_property('other_members_at_address', 'options',
            '<div class="text-muted">No other members found at this address</div>');
        frm.refresh_field('other_members_at_address');
        return;
    }

    // Create styled HTML display
    let html = `
        <div class="address-members-container" style="padding: 10px; background: #f8f9fa; border-radius: 5px; border: 1px solid #dee2e6;">
            <h6 style="margin-bottom: 15px; color: #495057; font-weight: 600;">
                <i class="fa fa-home" style="margin-right: 8px;"></i>
                Other Members at This Address (${members.length})
            </h6>
            <div class="row">
    `;

    members.forEach(function(member) {
        // Determine status color
        const statusColors = {
            'Active': 'success',
            'Pending': 'warning',
            'Suspended': 'secondary',
            'Expired': 'info'
        };
        const statusColor = statusColors[member.status] || 'secondary';

        // Create member card
        html += `
            <div class="col-md-6 col-lg-4 mb-3">
                <div class="card h-100" style="border: 1px solid #dee2e6; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div class="card-body" style="padding: 15px;">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <h6 class="card-title mb-1" style="font-size: 14px; font-weight: 600; color: #495057;">
                                ${frappe.utils.escape_html(member.full_name)}
                            </h6>
                            <span class="badge badge-${statusColor}" style="font-size: 11px;">
                                ${member.status}
                            </span>
                        </div>

                        <div class="member-details" style="font-size: 12px; color: #6c757d;">
                            ${member.relationship ? `<div><strong>Relationship:</strong> ${member.relationship}</div>` : ''}
                            ${member.age_group ? `<div><strong>Age Group:</strong> ${member.age_group}</div>` : ''}
                            ${member.member_since ? `<div><strong>Member Since:</strong> ${frappe.datetime.str_to_user(member.member_since)}</div>` : ''}
                        </div>

                        <div class="mt-3">
                            <button class="btn btn-sm btn-outline-primary view-member-btn"
                                    data-member-name="${member.name}"
                                    style="font-size: 11px; padding: 4px 8px;">
                                <i class="fa fa-external-link" style="margin-right: 4px;"></i>
                                View Member
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });

    html += `
            </div>
        </div>
    `;

    // Set the HTML content
    frm.set_df_property('other_members_at_address', 'options', html);
    frm.refresh_field('other_members_at_address');

    // Add click handlers for view buttons using setTimeout to ensure DOM is ready
    setTimeout(function() {
        $(frm.fields_dict.other_members_at_address.wrapper).find('.view-member-btn').off('click').on('click', function(e) {
            e.preventDefault();
            const memberName = $(this).data('member-name');
            if (memberName) {
                frappe.set_route('Form', 'Member', memberName);
            }
        });
    }, 100);
}

// ==================== FORM EVENT HANDLERS ====================

// Note: Main form handlers are in verenigingen/doctype/member/member.js
// Address members functionality is integrated into the main refresh handler

console.log("Member form scripts and review functionality loaded");
