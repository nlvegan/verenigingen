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
                        callback: function (r) {
                            if (!r.message) return;
                            const batch_id = r.message.batch_id;
                            const total = r.message.total;
                            const dialog = new frappe.ui.Dialog({
                                title: __("Applying {0} events...", [total]),
                                fields: [
                                    { fieldtype: "HTML", fieldname: "progress_area" },
                                ],
                            });
                            dialog.fields_dict.progress_area.$wrapper.html(
                                '<div class="progress"><div class="progress-bar" style="width: 0%"></div></div>' +
                                '<p class="batch-status text-muted">' + __("Starting...") + "</p>"
                            );
                            dialog.show();
                            dialog.$wrapper.find(".modal-footer").hide();

                            function onProgress(data) {
                                if (data.batch_id !== batch_id) return;
                                const pct = Math.round((data.current / data.total) * 100);
                                dialog.fields_dict.progress_area.$wrapper
                                    .find(".progress-bar").css("width", pct + "%");
                                dialog.fields_dict.progress_area.$wrapper
                                    .find(".batch-status").text(
                                        __("{0}/{1} processed — {2} applied, {3} errors",
                                            [data.current, data.total, data.applied, data.errors])
                                    );
                            }

                            function onComplete(data) {
                                if (data.batch_id !== batch_id) return;
                                frappe.realtime.off("batch_apply_progress", onProgress);
                                frappe.realtime.off("batch_apply_complete", onComplete);
                                dialog.hide();
                                if (data.errors && data.errors.length) {
                                    frappe.msgprint({
                                        title: __("Batch Apply Results"),
                                        message: __("Applied {0}/{1}. Errors:<br>{2}",
                                            [data.applied, data.total, data.errors.join("<br>")]),
                                        indicator: "orange",
                                    });
                                } else {
                                    frappe.show_alert({
                                        message: __("{0} events applied successfully.", [data.applied]),
                                        indicator: "green",
                                    });
                                }
                                listview.refresh();
                            }

                            frappe.realtime.on("batch_apply_progress", onProgress);
                            frappe.realtime.on("batch_apply_complete", onComplete);

                            dialog.on_hide = function () {
                                frappe.realtime.off("batch_apply_progress", onProgress);
                                frappe.realtime.off("batch_apply_complete", onComplete);
                            };
                        },
                    });
                }
            );
        });
    },
};
