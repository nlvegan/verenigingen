// Copyright (c) 2025, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on("Event Contact Campaign", {
    refresh: function (frm) {
        // Add Import Members button
        if (frm.doc.chapter && !frm.is_new()) {
            frm.add_custom_button(
                __("Import Contactable Members"),
                function () {
                    frm.trigger("import_members");
                },
                __("Actions")
            );
        }

        // Refresh progress dashboard
        frm.trigger("update_progress_dashboard");

        // Add status indicator colors
        if (frm.doc.status === "Active") {
            frm.page.set_indicator(__("Active"), "blue");
        } else if (frm.doc.status === "Completed") {
            frm.page.set_indicator(__("Completed"), "green");
        } else if (frm.doc.status === "Cancelled") {
            frm.page.set_indicator(__("Cancelled"), "red");
        }
    },

    chapter: function (frm) {
        // Clear contact list when chapter changes (only if there are members)
        if (frm.doc.contact_list && frm.doc.contact_list.length > 0) {
            frappe.confirm(
                __(
                    "Changing the chapter will clear the existing contact list. Continue?"
                ),
                function () {
                    frm.clear_table("contact_list");
                    frm.refresh_field("contact_list");
                    frm.trigger("update_progress_dashboard");
                },
                function () {
                    // Revert to previous chapter
                    frm.reload_doc();
                }
            );
        }
    },

    import_members: function (frm) {
        if (!frm.doc.chapter) {
            frappe.msgprint(__("Please select a chapter first"));
            return;
        }

        // First, get a count of available members
        frappe.call({
            method: "verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.get_contactable_members",
            args: {
                chapter: frm.doc.chapter,
            },
            callback: function (r) {
                if (r.message) {
                    let members = r.message;
                    let existing_count = frm.doc.contact_list
                        ? frm.doc.contact_list.length
                        : 0;
                    let new_count = members.filter(
                        (m) =>
                            !frm.doc.contact_list ||
                            !frm.doc.contact_list.find(
                                (row) => row.member === m.member
                            )
                    ).length;

                    if (new_count === 0) {
                        if (members.length === 0) {
                            frappe.msgprint(
                                __(
                                    "No contactable members found for this chapter. Members must be active and have accepted optional communications."
                                )
                            );
                        } else {
                            frappe.msgprint(
                                __(
                                    "All {0} contactable members are already in the list.",
                                    [members.length]
                                )
                            );
                        }
                        return;
                    }

                    frappe.confirm(
                        __(
                            "Found {0} new contactable members. Add them to the campaign?",
                            [new_count]
                        ),
                        function () {
                            frappe.call({
                                method: "verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.import_contactable_members",
                                args: {
                                    docname: frm.doc.name,
                                },
                                freeze: true,
                                freeze_message: __("Importing members..."),
                                callback: function (r) {
                                    if (r.message) {
                                        let result = r.message;
                                        if (result.status === "success") {
                                            frappe.show_alert(
                                                {
                                                    message: result.message,
                                                    indicator: "green",
                                                },
                                                5
                                            );
                                        } else if (result.status === "info") {
                                            frappe.show_alert(
                                                {
                                                    message: result.message,
                                                    indicator: "blue",
                                                },
                                                5
                                            );
                                        } else {
                                            frappe.show_alert(
                                                {
                                                    message: result.message,
                                                    indicator: "orange",
                                                },
                                                5
                                            );
                                        }
                                        frm.reload_doc();
                                    }
                                },
                            });
                        }
                    );
                }
            },
        });
    },

    update_progress_dashboard: function (frm) {
        if (frm.is_new()) {
            // Show empty state for new documents
            frm.set_df_property(
                "progress_dashboard",
                "options",
                `<div class="progress-dashboard" style="padding: 15px; background: #f8f9fa; border-radius: 8px; margin-bottom: 15px;">
                    <p style="color: #6c757d; margin: 0;">
                        <strong>Save the document and import members to see progress.</strong>
                    </p>
                </div>`
            );
            return;
        }

        frappe.call({
            method: "verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.get_progress_dashboard",
            args: {
                docname: frm.doc.name,
            },
            callback: function (r) {
                if (r.message) {
                    frm.set_df_property("progress_dashboard", "options", r.message);
                }
            },
        });
    },

    contact_list_on_form_rendered: function (frm) {
        // Refresh dashboard when contact list changes
        frm.trigger("update_progress_dashboard");
    },
});

// Child table events
frappe.ui.form.on("Event Contact Campaign Member", {
    contacted: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        if (row.contacted) {
            // Auto-fill contacted date and user if not set
            if (!row.contacted_date) {
                frappe.model.set_value(cdt, cdn, "contacted_date", frappe.datetime.now_datetime());
            }
            if (!row.contacted_by) {
                frappe.model.set_value(cdt, cdn, "contacted_by", frappe.session.user);
            }
            // Set contact method to "Other" if still "Not Contacted"
            if (row.contact_method === "Not Contacted") {
                frappe.model.set_value(cdt, cdn, "contact_method", "Other");
            }
        } else {
            // Clear contact fields when unchecked
            frappe.model.set_value(cdt, cdn, "contact_method", "Not Contacted");
        }

        // Trigger save to update progress
        frm.dirty();
    },

    response: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Auto-fill response date when response is set
        if (row.response && row.response !== "No Response" && !row.response_date) {
            frappe.model.set_value(cdt, cdn, "response_date", frappe.datetime.get_today());
        }

        // Trigger save to update progress
        frm.dirty();
    },

    contact_list_remove: function (frm) {
        // Update dashboard when a row is removed
        frm.dirty();
    },
});
