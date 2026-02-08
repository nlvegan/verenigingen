// MijnRood Sync Event — rich diff rendering and review actions

// Field labels for display (mirrors Python MIJNROOD_FIELD_LABELS)
const FIELD_LABELS = {
    id: "MijnRood ID",
    first_name: "First Name",
    middle_name: "Middle Name",
    last_name: "Last Name",
    email: "Email",
    phone: "Phone",
    iban: "IBAN",
    address: "Address",
    city: "City",
    post_code: "Postal Code",
    country: "Country",
    date_of_birth: "Date of Birth",
    division_id: "Chapter",
    registration_time: "Registration Date",
    current_membership_status_id: "Membership Status",
    contribution_per_period_in_cents: "Contribution (cents/period)",
    mollie_customer_id: "Mollie Customer ID",
    mollie_subscription_id: "Mollie Subscription ID",
    roles: "Roles",
    accept_use_personal_information: "Privacy Consent",
    comments: "Comments",
    original_id: "Original Member ID",
    original_registration_time: "Original Registration Date",
    name: "Division Name",
    email_id: "Division Email",
    facebook: "Facebook",
    instagram: "Instagram",
    twitter: "Twitter",
    can_be_selected_on_application: "Selectable on Application",
    preferred_division_id: "Preferred Chapter",
    paid: "Paid",
    has_sent_initial_email: "Initial Email Sent",
};

// Key fields to show prominently in New record summary cards
const MEMBER_SUMMARY_FIELDS = [
    "first_name", "middle_name", "last_name", "email", "phone",
    "address", "city", "post_code", "country",
    "division_id", "current_membership_status_id",
    "contribution_per_period_in_cents", "date_of_birth",
    "iban", "registration_time",
];

const DIVISION_SUMMARY_FIELDS = [
    "name", "city", "email_id", "phone",
    "address", "post_code",
    "facebook", "instagram", "twitter",
    "can_be_selected_on_application",
];

// MijnRood status ID → human-readable label (mirrors Python STATUS_ID_LABELS)
const STATUS_LABELS = {
    1: "Active (lid)",
    2: "Aspirant",
    3: "Resigned (opgezegd)",
    4: "Expelled (geroyeerd)",
    5: "Deceased (overleden)",
    6: "Suspended (geschorst)",
};

function get_label(field) {
    return FIELD_LABELS[field] || field;
}

/**
 * Resolve raw DB values to display values for known special fields.
 * Used in the New record card where we only have raw new_data.
 */
function resolve_display_value(field, val) {
    if (val === null || val === undefined || val === "") return "";
    if (field === "current_membership_status_id") {
        var int_val = parseInt(val, 10);
        return STATUS_LABELS[int_val] || String(val);
    }
    return String(val);
}

function esc(val) {
    if (val === null || val === undefined || val === "") return "";
    var s = String(val);
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(s));
    return div.innerHTML;
}

function truncate(val, max_len) {
    if (!val) return "";
    var s = String(val);
    if (s.length > max_len) return s.substring(0, max_len) + "\u2026";
    return s;
}

/**
 * Build a color-coded diff table for Changed events.
 */
function render_changed_table(changed_fields) {
    if (!changed_fields || !changed_fields.length) {
        return '<p class="text-muted">No field changes detected.</p>';
    }

    var html = '<table class="table table-bordered table-sm" style="margin-top:10px">';
    html += "<thead><tr>"
        + '<th style="width:25%">Field</th>'
        + '<th style="width:37%">Old Value</th>'
        + '<th style="width:37%">New Value</th>'
        + "</tr></thead><tbody>";

    for (var i = 0; i < changed_fields.length; i++) {
        var c = changed_fields[i];
        var label = c.label || get_label(c.field);
        var old_val = c.old_display || c.old;
        var new_val = c.new_display || c.new;

        html += "<tr>"
            + "<td><strong>" + esc(label) + "</strong></td>"
            + '<td style="background-color:#fff0f0; color:#a94442">'
            + esc(truncate(old_val, 120)) + "</td>"
            + '<td style="background-color:#f0fff0; color:#3c763d">'
            + esc(truncate(new_val, 120)) + "</td>"
            + "</tr>";
    }

    html += "</tbody></table>";
    return html;
}

/**
 * Build a summary card for New record events.
 */
function render_new_card(table, new_data) {
    if (!new_data) {
        return '<p class="text-muted">No data available.</p>';
    }

    var fields = MEMBER_SUMMARY_FIELDS;
    if (table === "admin_division") {
        fields = DIVISION_SUMMARY_FIELDS;
    }

    // Build name header
    var name_parts = [];
    if (new_data.first_name) name_parts.push(new_data.first_name);
    if (new_data.middle_name) name_parts.push(new_data.middle_name);
    if (new_data.last_name) name_parts.push(new_data.last_name);
    if (table === "admin_division" && new_data.name) {
        name_parts = [new_data.name];
    }
    var display_name = name_parts.join(" ") || "Unknown";

    var html = '<div style="border:1px solid #d1d8dd; border-radius:4px; padding:15px; margin-top:10px; background:#fafbfc">';
    html += '<h5 style="margin-top:0">' + esc(display_name) + "</h5>";
    html += '<table class="table table-sm" style="margin-bottom:0">';

    for (var i = 0; i < fields.length; i++) {
        var field = fields[i];
        var val = new_data[field];
        if (val === null || val === undefined || val === "") continue;

        // Skip name fields already shown in header
        if (table !== "admin_division" && (field === "first_name" || field === "middle_name" || field === "last_name")) continue;
        if (table === "admin_division" && field === "name") continue;

        var display_val = resolve_display_value(field, val);

        html += "<tr>"
            + "<td style='width:35%; color:#6c757d'><strong>" + esc(get_label(field)) + "</strong></td>"
            + "<td>" + esc(truncate(display_val, 120)) + "</td>"
            + "</tr>";
    }

    html += "</table></div>";
    return html;
}

/**
 * Build a three-column comparison table: Field | Current Frappe | Proposed MijnRood | Status
 */
function render_comparison_table(changed_fields, frappe_data) {
    if (!changed_fields || !changed_fields.length) return "";

    var html = '<h6 style="margin-top:15px">Comparison with Current Frappe Data</h6>';
    html += '<table class="table table-bordered table-sm">';
    html += "<thead><tr>"
        + '<th style="width:20%">Field</th>'
        + '<th style="width:25%">Current (Frappe)</th>'
        + '<th style="width:25%">Proposed (MijnRood)</th>'
        + '<th style="width:15%">Status</th>'
        + "</tr></thead><tbody>";

    for (var i = 0; i < changed_fields.length; i++) {
        var c = changed_fields[i];
        var label = c.label || get_label(c.field);
        var proposed = c.new_display || c.new;
        var current = frappe_data[c.field] || "";

        // Determine if already applied
        var proposed_str = String(proposed || "");
        var current_str = String(current || "");
        var already_applied = proposed_str === current_str;

        var status_html;
        if (already_applied) {
            status_html = '<span class="indicator-pill green">Already applied</span>';
        } else {
            status_html = '<span class="indicator-pill orange">Needs update</span>';
        }

        html += "<tr>"
            + "<td><strong>" + esc(label) + "</strong></td>"
            + "<td>" + esc(truncate(current, 80)) + "</td>"
            + "<td>" + esc(truncate(proposed, 80)) + "</td>"
            + "<td>" + status_html + "</td>"
            + "</tr>";
    }

    html += "</tbody></table>";
    return html;
}

/**
 * Render a summary for Deleted events.
 */
function render_deleted_card(table, old_data) {
    if (!old_data) {
        return '<p class="text-muted">No data available for deleted record.</p>';
    }

    var name_parts = [];
    if (old_data.first_name) name_parts.push(old_data.first_name);
    if (old_data.middle_name) name_parts.push(old_data.middle_name);
    if (old_data.last_name) name_parts.push(old_data.last_name);
    if (table === "admin_division" && old_data.name) {
        name_parts = [old_data.name];
    }
    var display_name = name_parts.join(" ") || "Unknown";

    var html = '<div style="border:1px solid #f5c6cb; border-radius:4px; padding:15px; margin-top:10px; background:#fff5f5">';
    html += '<h5 style="margin-top:0; color:#a94442">Deleted: ' + esc(display_name) + "</h5>";

    var details = [];
    if (old_data.email) details.push("Email: " + old_data.email);
    if (old_data.city) details.push("City: " + old_data.city);
    if (old_data.id) details.push("MijnRood ID: " + old_data.id);

    if (details.length) {
        html += '<p class="text-muted" style="margin-bottom:0">' + esc(details.join(" | ")) + "</p>";
    }

    html += "</div>";
    return html;
}

function safe_parse_json(val) {
    if (!val) return null;
    if (typeof val === "object") return val;
    try {
        return JSON.parse(val);
    } catch (e) {
        return null;
    }
}


// ─── Frappe form event handlers ──────────────────────────────────

frappe.ui.form.on("MijnRood Sync Event", {
    refresh(frm) {
        // Action buttons for Pending events
        if (frm.doc.status === "Pending") {
            frm.add_custom_button(__("Approve"), function () {
                frappe.call({
                    method: "approve",
                    doc: frm.doc,
                    callback: function () {
                        frm.reload_doc();
                    },
                });
            }, __("Actions"));

            frm.add_custom_button(__("Reject"), function () {
                frappe.call({
                    method: "reject",
                    doc: frm.doc,
                    callback: function () {
                        frm.reload_doc();
                    },
                });
            }, __("Actions"));

            frm.add_custom_button(__("Ignore"), function () {
                frappe.call({
                    method: "ignore_event",
                    doc: frm.doc,
                    callback: function () {
                        frm.reload_doc();
                    },
                });
            }, __("Actions"));
        }

        // Apply button for Approved events
        if (frm.doc.status === "Approved") {
            frm.add_custom_button(__("Apply"), function () {
                frappe.confirm(
                    __("Apply this change to Verenigingen? This will modify member data."),
                    function () {
                        frappe.call({
                            method: "apply_event",
                            doc: frm.doc,
                            freeze: true,
                            freeze_message: __("Applying changes..."),
                            callback: function (r) {
                                if (r.message && r.message.success) {
                                    frappe.show_alert({
                                        message: __("Changes applied successfully"),
                                        indicator: "green",
                                    });
                                } else {
                                    frappe.msgprint({
                                        title: __("Application Failed"),
                                        indicator: "red",
                                        message: r.message ? r.message.message : __("Unknown error"),
                                    });
                                }
                                frm.reload_doc();
                            },
                        });
                    }
                );
            }).addClass("btn-primary");
        }

        // Color-code the status indicator
        var status_colors = {
            Pending: "orange",
            Approved: "blue",
            Applied: "green",
            Rejected: "red",
            Ignored: "grey",
        };
        if (status_colors[frm.doc.status]) {
            frm.page.set_indicator(__(frm.doc.status), status_colors[frm.doc.status]);
        }

        // Render rich change details
        render_change_details(frm);
    },
});

function render_change_details(frm) {
    var wrapper = frm.fields_dict.change_detail_html;
    if (!wrapper) return;

    var event_type = frm.doc.event_type;
    var table = frm.doc.mijnrood_table;
    var changed_fields = safe_parse_json(frm.doc.changed_fields);
    var new_data = safe_parse_json(frm.doc.new_data);
    var old_data = safe_parse_json(frm.doc.old_data);

    var html = "";

    if (event_type === "Changed") {
        html += render_changed_table(changed_fields);

        // If there's a linked member, fetch comparison data
        if (frm.doc.linked_member && changed_fields && changed_fields.length) {
            html += '<div class="member-comparison-container">'
                + '<p class="text-muted">Loading Frappe comparison data...</p>'
                + "</div>";
            wrapper.$wrapper.html(html);

            frappe.call({
                method: "get_member_comparison_data",
                doc: frm.doc,
                callback: function (r) {
                    if (r.message) {
                        var comparison_html = render_comparison_table(changed_fields, r.message);
                        wrapper.$wrapper.find(".member-comparison-container").html(comparison_html);
                    } else {
                        wrapper.$wrapper.find(".member-comparison-container").html("");
                    }
                },
                error: function () {
                    wrapper.$wrapper.find(".member-comparison-container").html(
                        '<p class="text-muted">Could not load comparison data.</p>'
                    );
                },
            });
            return;
        }
    } else if (event_type === "New") {
        html += render_new_card(table, new_data);
    } else if (event_type === "Deleted") {
        html += render_deleted_card(table, old_data);
    }

    wrapper.$wrapper.html(html);
}


// ─── List view settings ──────────────────────────────────────────

frappe.listview_settings["MijnRood Sync Event"] = {
    get_indicator(doc) {
        const status_map = {
            "Pending": [__("Pending"), "orange", "status,=,Pending"],
            "Approved": [__("Approved"), "blue", "status,=,Approved"],
            "Applied": [__("Applied"), "green", "status,=,Applied"],
            "Rejected": [__("Rejected"), "red", "status,=,Rejected"],
            "Ignored": [__("Ignored"), "grey", "status,=,Ignored"],
        };
        return status_map[doc.status] || [doc.status, "grey", "status,=," + doc.status];
    },

    onload(listview) {
        // Default filter to Pending events
        if (!listview.filter_area.filter_list.length) {
            listview.filter_area.add([[listview.doctype, "status", "=", "Pending"]]);
        }

        // Batch actions
        listview.page.add_action_item(__("Approve Selected"), function () {
            const selected = listview.get_checked_items();
            if (!selected.length) {
                frappe.throw(__("Please select at least one event"));
            }
            const names = selected.map(function (d) { return d.name; });
            frappe.call({
                method: "verenigingen.mijnrood_sync.services.event_application_service.batch_approve",
                args: { event_names: names },
                freeze: true,
                freeze_message: __("Approving events..."),
                callback: function () {
                    listview.refresh();
                },
            });
        });

        listview.page.add_action_item(__("Apply Selected"), function () {
            const selected = listview.get_checked_items();
            if (!selected.length) {
                frappe.throw(__("Please select at least one event"));
            }
            const names = selected.map(function (d) { return d.name; });
            frappe.confirm(
                __("Apply {0} selected events? This will modify member data.", [names.length]),
                function () {
                    frappe.call({
                        method: "verenigingen.mijnrood_sync.services.event_application_service.batch_apply",
                        args: { event_names: names },
                        freeze: true,
                        freeze_message: __("Applying events..."),
                        callback: function () {
                            listview.refresh();
                        },
                    });
                }
            );
        });
    },
};
