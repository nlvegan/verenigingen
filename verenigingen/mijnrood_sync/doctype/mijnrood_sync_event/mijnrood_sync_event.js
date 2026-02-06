frappe.ui.form.on("MijnRood Sync Event", {
    refresh(frm) {
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
        if (frm.doc.status === "Pending") {
            frm.page.set_indicator(__("Pending"), "orange");
        } else if (frm.doc.status === "Approved") {
            frm.page.set_indicator(__("Approved"), "blue");
        } else if (frm.doc.status === "Applied") {
            frm.page.set_indicator(__("Applied"), "green");
        } else if (frm.doc.status === "Rejected") {
            frm.page.set_indicator(__("Rejected"), "red");
        } else if (frm.doc.status === "Ignored") {
            frm.page.set_indicator(__("Ignored"), "grey");
        }
    },
});

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
