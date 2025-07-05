// Copyright (c) 2025, Your Organization and contributors
// For license information, please see license.txt

frappe.ui.form.on('Chapter', {
    onload: function(frm) {
        // Initialize chapter form functionality
        if (!frm._chapter_initialized) {
            setup_chapter_form(frm);
            frm._chapter_initialized = true;
        }
    },

    refresh: function(frm) {
        setup_chapter_buttons(frm);
        update_chapter_ui(frm);
        setup_board_grid(frm);
    },

    validate: function(frm) {
        return validate_chapter_form(frm);
    },

    before_save: function(frm) {
        return prepare_chapter_save(frm);
    },

    after_save: function(frm) {
        handle_chapter_after_save(frm);
    },

    // Field-specific handlers
    postal_codes: function(frm) {
        validate_postal_codes(frm);
    },

    chapter_head: function(frm) {
        validate_chapter_head(frm);
    },

    region: function(frm) {
        handle_region_change(frm);
    },

    published: function(frm) {
        handle_published_change(frm);
    }
});

// Child table events - Chapter Board Member
frappe.ui.form.on('Chapter Board Member', {
    board_members_add: function(frm, cdt, cdn) {
        handle_board_member_add(frm, cdt, cdn);
    },

    board_members_remove: function(frm, cdt, cdn) {
        handle_board_member_remove(frm, cdt, cdn);
    },

    volunteer: function(frm, cdt, cdn) {
        handle_volunteer_change(frm, cdt, cdn);
    },

    chapter_role: function(frm, cdt, cdn) {
        handle_role_change(frm, cdt, cdn);
    },

    from_date: function(frm, cdt, cdn) {
        handle_date_change(frm, cdt, cdn, 'from_date');
    },

    to_date: function(frm, cdt, cdn) {
        handle_date_change(frm, cdt, cdn, 'to_date');
    },

    is_active: function(frm, cdt, cdn) {
        handle_active_change(frm, cdt, cdn);
    }
});

// Child table events - Chapter Member
frappe.ui.form.on('Chapter Member', {
    members_add: function(frm, cdt, cdn) {
        handle_member_add(frm, cdt, cdn);
    },

    members_remove: function(frm, cdt, cdn) {
        handle_member_remove(frm, cdt, cdn);
    },

    member: function(frm, cdt, cdn) {
        handle_member_change(frm, cdt, cdn);
    },

    enabled: function(frm, cdt, cdn) {
        handle_enabled_change(frm, cdt, cdn);
    }
});

// Helper Functions
function setup_chapter_form(frm) {
    // Set up form-level functionality
    setup_postal_code_validation(frm);
    setup_member_filters(frm);
}

function setup_chapter_buttons(frm) {
    // Clear existing custom buttons
    frm.clear_custom_buttons();

    if (!frm.doc.__islocal) {
        // Add navigation buttons
        frm.add_custom_button(__('View Members'), function() {
            view_chapter_members(frm);
        }, __('View'));

        if (frm.doc.current_sepa_mandate) {
            frm.add_custom_button(__('Current SEPA Mandate'), function() {
                frappe.set_route('Form', 'SEPA Mandate', frm.doc.current_sepa_mandate);
            }, __('View'));
        }

        // Add board management buttons
        frm.add_custom_button(__('Manage Board Members'), function() {
            show_board_management_dialog(frm);
        }, __('Board'));

        frm.add_custom_button(__('View Board History'), function() {
            show_board_history(frm);
        }, __('Board'));

        frm.add_custom_button(__('Sync with Volunteer System'), function() {
            sync_board_with_volunteers(frm);
        }, __('Board'));
    }
}

function update_chapter_ui(frm) {
    // Update UI elements based on current state
    update_members_summary(frm);
    update_postal_code_preview(frm);
}

function setup_board_grid(frm) {
    // Set up board members grid
    if (frm.fields_dict.board_members && frm.fields_dict.board_members.grid) {
        frm.fields_dict.board_members.grid.get_field('volunteer').get_query = function() {
            return {
                filters: {
                    'status': ['in', ['Active', 'New']]
                }
            };
        };

        frm.fields_dict.board_members.grid.get_field('chapter_role').get_query = function() {
            return {
                filters: {
                    'is_active': 1
                }
            };
        };
    }
}

function validate_chapter_form(frm) {
    // Form validation
    if (!frm.doc.name || !frm.doc.region) {
        frappe.msgprint(__('Name and Region are required'));
        return false;
    }

    // Validate postal codes
    if (frm.doc.postal_codes && !validate_postal_codes(frm)) {
        return false;
    }

    return true;
}

function prepare_chapter_save(frm) {
    // Prepare data before save
    if (!frm.doc.route && frm.doc.name) {
        frm.doc.route = 'chapters/' + frappe.scrub(frm.doc.name);
    }

    return true;
}

function handle_chapter_after_save(frm) {
    frappe.show_alert({
        message: __('Chapter saved successfully'),
        indicator: 'green'
    }, 3);
}

function validate_postal_codes(frm) {
    if (!frm.doc.postal_codes) return true;

    try {
        frappe.call({
            method: 'validate_postal_codes',
            doc: frm.doc,
            callback: function(r) {
                if (!r.message) {
                    frappe.msgprint({
                        title: __('Invalid Postal Codes'),
                        indicator: 'red',
                        message: __('Please check your postal code patterns')
                    });
                }
            },
            error: function(r) {
                frappe.msgprint(__('Error validating postal codes: {0}', [r.message]));
            }
        });
    } catch (error) {
        console.error('Error validating postal codes:', error);
    }

    return true;
}

function validate_chapter_head(frm) {
    if (frm.doc.chapter_head) {
        frappe.db.get_value('Member', frm.doc.chapter_head, 'status', function(r) {
            if (r && r.status !== 'Active') {
                frappe.msgprint(__('Warning: Selected chapter head is not an active member'));
            }
        });
    }
}

function handle_region_change(frm) {
    if (frm.doc.region) {
        suggest_postal_codes_for_region(frm);
    }
}

function handle_published_change(frm) {
    if (frm.doc.published) {
        frappe.show_alert({
            message: __('Chapter is now public and visible to members'),
            indicator: 'green'
        }, 5);
    } else {
        frappe.show_alert({
            message: __('Chapter is now private and hidden from members'),
            indicator: 'orange'
        }, 5);
    }
}

function suggest_postal_codes_for_region(frm) {
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'Chapter',
            filters: {
                region: frm.doc.region,
                name: ['!=', frm.doc.name]
            },
            fields: ['postal_codes'],
            limit_page_length: 5
        },
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                const all_codes = new Set();
                r.message.forEach(chapter => {
                    if (chapter.postal_codes) {
                        chapter.postal_codes.split(',').forEach(code => {
                            all_codes.add(code.trim());
                        });
                    }
                });

                if (all_codes.size > 0) {
                    frappe.show_alert({
                        message: __('Other chapters in {0} use postal codes: {1}',
                            [frm.doc.region, Array.from(all_codes).join(', ')]),
                        indicator: 'blue'
                    }, 10);
                }
            }
        },
        error: function(r) {
            console.error('Error suggesting postal codes:', r);
        }
    });
}

// Board member handlers
function handle_board_member_add(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.from_date) {
        frappe.model.set_value(cdt, cdn, 'from_date', frappe.datetime.get_today());
    }
    row.is_active = 1;
}

function handle_board_member_remove(frm, cdt, cdn) {
    // Board member removed
}

function handle_volunteer_change(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (row.volunteer) {
        frappe.db.get_value('Volunteer', row.volunteer, ['volunteer_name', 'email'], function(r) {
            if (r) {
                frappe.model.set_value(cdt, cdn, 'volunteer_name', r.volunteer_name);
                frappe.model.set_value(cdt, cdn, 'email', r.email);
            }
        });
    }
}

function handle_role_change(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    // Handle role-specific logic
}

function handle_date_change(frm, cdt, cdn, field) {
    const row = locals[cdt][cdn];
    if (field === 'to_date' && row.to_date && row.from_date) {
        if (frappe.datetime.get_diff(row.to_date, row.from_date) < 0) {
            frappe.msgprint(__('End date cannot be before start date'));
            frappe.model.set_value(cdt, cdn, 'to_date', '');
        }
    }
}

function handle_active_change(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.is_active && !row.to_date) {
        frappe.model.set_value(cdt, cdn, 'to_date', frappe.datetime.get_today());
    }
}

// Member handlers
function handle_member_add(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    row.enabled = 1;
    if (!row.chapter_join_date) {
        frappe.model.set_value(cdt, cdn, 'chapter_join_date', frappe.datetime.get_today());
    }
}

function handle_member_remove(frm, cdt, cdn) {
    // Member removed
}

function handle_member_change(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (row.member && !row.chapter_join_date) {
        frappe.model.set_value(cdt, cdn, 'chapter_join_date', frappe.datetime.get_today());
    }
}

function handle_enabled_change(frm, cdt, cdn) {
    // Handle member enabled/disabled change
}

// UI Helper Functions
function update_members_summary(frm) {
    if (frm.doc.members) {
        const active_count = frm.doc.members.filter(m => m.enabled).length;
        const total_count = frm.doc.members.length;

        if (frm.dashboard && frm.dashboard.set_headline) {
            frm.dashboard.set_headline(__('Members: {0} active of {1} total', [active_count, total_count]));
        }
    }
}

function update_postal_code_preview(frm) {
    if (frm.doc.postal_codes) {
        // Could add a preview of postal code patterns
    }
}

function setup_postal_code_validation(frm) {
    // Set up real-time postal code validation
}

function setup_member_filters(frm) {
    // Set up member field filters
    frm.set_query('chapter_head', function() {
        return {
            filters: {
                'status': 'Active'
            }
        };
    });
}

// Dialog Functions
function view_chapter_members(frm) {
    // Navigate to members list - members will be filtered by chapter roster
    frappe.msgprint({
        title: __('Chapter Members'),
        message: __('Viewing members for this chapter. Use the chapter roster below to see all members.'),
        indicator: 'blue'
    });
    frappe.set_route('List', 'Member');
}

function show_board_management_dialog(frm) {
    const d = new frappe.ui.Dialog({
        title: __('Add Board Member'),
        fields: [
            {
                label: __('Volunteer'),
                fieldname: 'volunteer',
                fieldtype: 'Link',
                options: 'Volunteer',
                reqd: 1,
                get_query: function() {
                    return {
                        filters: {
                            'status': ['in', ['Active', 'New']]
                        }
                    };
                }
            },
            {
                label: __('Board Role'),
                fieldname: 'role',
                fieldtype: 'Link',
                options: 'Chapter Role',
                reqd: 1,
                get_query: function() {
                    return {
                        filters: {
                            'is_active': 1
                        }
                    };
                }
            },
            {
                label: __('From Date'),
                fieldname: 'from_date',
                fieldtype: 'Date',
                default: frappe.datetime.get_today(),
                reqd: 1
            },
            {
                label: __('To Date'),
                fieldname: 'to_date',
                fieldtype: 'Date'
            }
        ],
        primary_action_label: __('Add Board Member'),
        primary_action: function() {
            const values = d.get_values();
            if (!values) return;

            frappe.call({
                method: 'add_board_member',
                doc: frm.doc,
                args: {
                    volunteer: values.volunteer,
                    role: values.role,
                    from_date: values.from_date,
                    to_date: values.to_date
                },
                freeze: true,
                freeze_message: __('Adding board member...'),
                callback: function(r) {
                    if (r.message && r.message.success) {
                        frappe.show_alert({
                            message: __('Board member added successfully'),
                            indicator: 'green'
                        }, 3);
                        frm.reload_doc();
                        d.hide();
                    }
                },
                error: function(r) {
                    frappe.msgprint(__('Error adding board member: {0}', [r.message]));
                }
            });
        }
    });

    d.show();
}

function show_board_history(frm) {
    frappe.call({
        method: 'get_board_members',
        doc: frm.doc,
        args: {
            include_inactive: true
        },
        callback: function(r) {
            if (r.message) {
                show_board_history_dialog(r.message);
            }
        },
        error: function(r) {
            frappe.msgprint(__('Error loading board history: {0}', [r.message]));
        }
    });
}

function show_board_history_dialog(board_history) {
    const d = new frappe.ui.Dialog({
        title: __('Board History'),
        fields: [{
            fieldtype: 'HTML',
            options: render_board_history_html(board_history)
        }],
        primary_action_label: __('Close'),
        primary_action: function() {
            d.hide();
        }
    });

    d.show();
}

function render_board_history_html(board_history) {
    let html = '<div class="board-history">';
    html += '<table class="table table-bordered">';
    html += '<thead><tr>';
    html += '<th>' + __('Volunteer') + '</th>';
    html += '<th>' + __('Role') + '</th>';
    html += '<th>' + __('From') + '</th>';
    html += '<th>' + __('To') + '</th>';
    html += '<th>' + __('Status') + '</th>';
    html += '</tr></thead><tbody>';

    board_history.forEach(member => {
        html += '<tr>';
        html += '<td>' + (member.volunteer_name || '') + '</td>';
        html += '<td>' + (member.chapter_role || '') + '</td>';
        html += '<td>' + (member.from_date ? frappe.datetime.str_to_user(member.from_date) : '') + '</td>';
        html += '<td>' + (member.to_date ? frappe.datetime.str_to_user(member.to_date) : __('Present')) + '</td>';
        html += '<td><span class="indicator ' + (member.is_active ? 'green' : 'red') + '">' +
               (member.is_active ? __('Active') : __('Inactive')) + '</span></td>';
        html += '</tr>';
    });

    html += '</tbody></table></div>';
    return html;
}

function sync_board_with_volunteers(frm) {
    frappe.call({
        method: 'sync_board_members',
        doc: frm.doc,
        freeze: true,
        freeze_message: __('Syncing with volunteer system...'),
        callback: function(r) {
            if (r.message) {
                frappe.show_alert({
                    message: __('Board members synced successfully'),
                    indicator: 'green'
                }, 3);
                frm.refresh();
            }
        },
        error: function(r) {
            frappe.msgprint(__('Error syncing board members: {0}', [r.message]));
        }
    });
}
