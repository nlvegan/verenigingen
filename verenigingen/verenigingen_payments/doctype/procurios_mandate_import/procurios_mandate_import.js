// Copyright (c) 2026, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on("Procurios Mandate Import", {
    refresh(frm) {
        // Validate CSV button — only shown before submit, when a CSV is attached
        // and we haven't already produced a successful preview.
        if (
            !frm.is_new() &&
            frm.doc.docstatus === 0 &&
            frm.doc.csv_file &&
            frm.doc.import_status !== "Ready for Import"
        ) {
            frm.add_custom_button(__("Validate CSV"), () => {
                frappe.call({
                    method:
                        "verenigingen.verenigingen_payments.doctype.procurios_mandate_import." +
                        "procurios_mandate_import.validate_import_file",
                    args: { import_doc_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Validating CSV..."),
                    callback: (r) => {
                        if (r.message) {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: r.message.status === "success" ? "green" : "red",
                            });
                            frm.reload_doc();
                        }
                    },
                });
            });
        }

        // While the background job runs, poll for progress.
        if (["Queued", "In Progress"].includes(frm.doc.import_status)) {
            if (!frm._procurios_refresh_handle) {
                frm._procurios_refresh_handle = setInterval(() => {
                    frm.reload_doc();
                }, 5000);
            }
        } else if (frm._procurios_refresh_handle) {
            clearInterval(frm._procurios_refresh_handle);
            frm._procurios_refresh_handle = null;
        }
    },

    onload(frm) {
        // Surface a hint about what the tool does on first open.
        if (frm.is_new()) {
            frm.dashboard.set_headline(
                __(
                    "Imports SEPA mandates from the Procurios mandate-export CSV. " +
                    "Only mandates whose Debiteur ID matches an existing Member's procurios_id are imported."
                )
            );
        }
    },
});
