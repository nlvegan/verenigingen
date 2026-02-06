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
