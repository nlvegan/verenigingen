// Mollie Bulk Run — form-level Cancel/Resume buttons + live progress.
//
// New runs auto-enqueue via the controller's after_insert hook, so users
// creating a run from the desk don't need a separate "Start" action — save
// the form and the worker picks it up.

frappe.ui.form.on("Mollie Bulk Run", {
    refresh(frm) {
        if (frm.is_new()) {
            return;
        }

        _renderStatusIndicator(frm);
        _addActionButtons(frm);
        _subscribeToProgress(frm);
    },

    onload(frm) {
        if (frm.is_new() && !frm.doc.batch_strategy) {
            frm.set_value("batch_strategy", "Month");
        }
    },
});

function _renderStatusIndicator(frm) {
    const status = frm.doc.status;
    const colorMap = {
        "Completed": "green",
        "Processing": "blue",
        "Fetching": "blue",
        "Queued": "blue",
        "Failed": "red",
        "Timed Out": "red",
        "Cancelled": "grey",
    };
    frm.page.set_indicator(status, colorMap[status] || "grey");
}

function _addActionButtons(frm) {
    const status = frm.doc.status;
    const active = ["Queued", "Fetching", "Processing"].includes(status);
    const resumable = ["Failed", "Timed Out", "Cancelled"].includes(status);

    if (active) {
        frm.add_custom_button(__("Cancel run"), () => _cancelRun(frm), __("Actions"));
    }

    if (resumable) {
        frm.add_custom_button(__("Resume run"), () => _resumeRun(frm), __("Actions"));
    }

    if (active || resumable) {
        frm.page.set_inner_btn_group_as_primary(__("Actions"));
    }
}

function _cancelRun(frm) {
    frappe.confirm(
        __("Request cancellation for {0}? The worker stops at the next checkpoint (every 10 payments).", [frm.doc.name]),
        () => {
            frappe.call({
                method: "verenigingen.api.mollie_bulk_run_api.request_cancel",
                args: { run_name: frm.doc.name },
                callback: () => {
                    frappe.show_alert({ message: __("Cancel requested"), indicator: "orange" });
                    frm.reload_doc();
                },
            });
        }
    );
}

function _resumeRun(frm) {
    frappe.call({
        method: "verenigingen.api.mollie_bulk_run_api.resume_bulk_run",
        args: { run_name: frm.doc.name },
        callback: (r) => {
            if (r.message && r.message.job_id) {
                frappe.show_alert({
                    message: __("Resumed — job {0}", [r.message.job_id]),
                    indicator: "green",
                });
                frm.reload_doc();
            }
        },
    });
}

function _subscribeToProgress(frm) {
    if (!frappe.realtime || !frappe.realtime.on) {
        return;
    }
    // Reload the form when the worker reports progress or finalizes the run.
    frappe.realtime.on("mollie_bulk_run_progress", (data) => {
        if (data && data.run_name === frm.doc.name) {
            frm.reload_doc();
        }
    });
}
