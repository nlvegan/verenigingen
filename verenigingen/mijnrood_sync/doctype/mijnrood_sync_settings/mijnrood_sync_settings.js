frappe.ui.form.on("MijnRood Sync Settings", {
    refresh(frm) {
        frm.add_custom_button(__("Test Connection"), function () {
            frappe.call({
                method: "test_connection",
                doc: frm.doc,
                freeze: true,
                freeze_message: __("Testing connection..."),
                callback: function (r) {
                    if (r.message && r.message.success) {
                        frappe.msgprint({
                            title: __("Connection Successful"),
                            indicator: "green",
                            message: __("Connected to MijnRood database. Found {0} rows in admin_member.", [r.message.row_count]),
                        });
                    } else {
                        frappe.msgprint({
                            title: __("Connection Failed"),
                            indicator: "red",
                            message: r.message ? r.message.message : __("Unknown error"),
                        });
                    }
                    frm.reload_doc();
                },
            });
        });

        // Fetch from MijnRood — primary button, always shown (merges, doesn't overwrite)
        frm.add_custom_button(__("Fetch from MijnRood"), function () {
            frappe.confirm(
                __("Fetch membership statuses from MijnRood? Existing admin configuration (Membership Type, Termination Type) will be preserved."),
                function () {
                    frappe.call({
                        method: "fetch_lidmaatschapstypes_from_mijnrood",
                        doc: frm.doc,
                        freeze: true,
                        freeze_message: __("Connecting to MijnRood and fetching statuses..."),
                        callback: function (r) {
                            if (r.message && r.message.success) {
                                frappe.show_alert({
                                    message: r.message.message,
                                    indicator: "green",
                                });
                            } else {
                                frappe.msgprint({
                                    title: __("Fetch Failed"),
                                    indicator: "red",
                                    message: r.message ? r.message.message : __("Unknown error"),
                                });
                            }
                            frm.reload_doc();
                        },
                    });
                }
            );
        }, __("Lidmaatschapstypes"));

        // Load Defaults — fallback when MijnRood is unreachable
        if (!frm.doc.status_mapping || !frm.doc.status_mapping.length) {
            frm.add_custom_button(__("Load Defaults"), function () {
                frappe.call({
                    method: "populate_default_status_mapping",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Loading default status mappings..."),
                    callback: function (r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: "green",
                            });
                        }
                        frm.reload_doc();
                    },
                });
            }, __("Lidmaatschapstypes"));
        }

        frm.add_custom_button(__("Sync Now"), function () {
            frappe.confirm(
                __("Start an immediate sync with MijnRood? This will run in the background."),
                function () {
                    frappe.call({
                        method: "trigger_sync_now",
                        doc: frm.doc,
                        freeze: true,
                        freeze_message: __("Enqueuing sync job..."),
                        callback: function (r) {
                            if (r.message && r.message.success) {
                                frappe.show_alert({
                                    message: __("Sync job enqueued. Check MijnRood Sync Log for progress."),
                                    indicator: "green",
                                });
                            }
                        },
                    });
                }
            );
        });
    },
});
