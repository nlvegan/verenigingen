frappe.ui.form.on("MijnRood Sync Settings", {
    onload(frm) {
        // Load dynamic document categories for folder mapping child table
        frappe.call({
            method: 'verenigingen.utils.document_categories.get_document_category_options',
            callback(r) {
                if (r.message) {
                    frm.fields_dict.document_folder_mappings?.grid?.update_docfield_property(
                        'document_type', 'options', '\n' + r.message
                    );
                }
            }
        });
    },

    refresh(frm) {
        // Render a small status indicator for the SSH credentials — the
        // underlying Password fields are hidden to prevent browser
        // password-manager prompts, so admins need a way to tell whether
        // a key/passphrase is currently configured.
        const status_wrapper = frm.get_field("ssh_credentials_status")?.$wrapper;
        if (status_wrapper) {
            const dot = (set) =>
                `<span style="color:${set ? "#28a745" : "#adb5bd"}">●</span>`;
            const key_set = !!frm.doc.ssh_private_key;
            const passphrase_set = !!frm.doc.ssh_password;
            status_wrapper.html(
                `<div class="text-muted" style="padding:6px 0">
                    ${dot(key_set)} ${__("Private key")}: <b>${key_set ? __("set") : __("not set")}</b>
                    &nbsp;·&nbsp;
                    ${dot(passphrase_set)} ${__("Passphrase")}: <b>${passphrase_set ? __("set") : __("not set")}</b>
                </div>`
            );
        }

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

        // Load Role Defaults — pre-populate role mapping table
        if (!frm.doc.role_mapping || !frm.doc.role_mapping.length) {
            frm.add_custom_button(__("Load Defaults"), function () {
                frappe.call({
                    method: "populate_default_role_mapping",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Loading default role mappings..."),
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
            }, __("MijnRood Rollen"));
        }

        // Set SSH Key — dialog with Code field for multi-line key paste
        frm.add_custom_button(__("Set SSH Key"), function () {
            const d = new frappe.ui.Dialog({
                title: __("Paste SSH Private Key"),
                fields: [
                    {
                        fieldname: "ssh_key_content",
                        fieldtype: "Code",
                        label: __("SSH Private Key"),
                        description: __("Paste the full private key including -----BEGIN ... KEY----- and -----END ... KEY----- lines"),
                        options: "Text",
                    },
                ],
                primary_action_label: __("Save Key"),
                primary_action(values) {
                    const key = (values.ssh_key_content || "").trim();
                    if (!key.startsWith("-----BEGIN ")) {
                        frappe.msgprint({
                            title: __("Invalid Key"),
                            indicator: "red",
                            message: __("Key must start with '-----BEGIN ... KEY-----'"),
                        });
                        return;
                    }
                    frm.set_value("ssh_private_key", key);
                    frm.dirty();
                    d.hide();
                    frappe.show_alert({
                        message: __("SSH key set. Save the document to store it encrypted."),
                        indicator: "green",
                    });
                },
            });
            d.show();
        }, __("SSH Tunnel"));

        // Set SSH Passphrase — dialog avoids exposing a password input on the
        // main form, which would otherwise trigger browser save-password prompts.
        frm.add_custom_button(__("Set SSH Passphrase"), function () {
            const d = new frappe.ui.Dialog({
                title: __("Set SSH Passphrase"),
                fields: [
                    {
                        fieldname: "ssh_passphrase",
                        fieldtype: "Password",
                        label: __("Passphrase"),
                        description: __("Passphrase for the encrypted SSH key, or the SSH account password. Leave blank to clear."),
                    },
                ],
                primary_action_label: __("Save"),
                primary_action(values) {
                    frm.set_value("ssh_password", values.ssh_passphrase || "");
                    frm.dirty();
                    d.hide();
                    frappe.show_alert({
                        message: __("Passphrase updated. Save the document to store it encrypted."),
                        indicator: "green",
                    });
                },
            });
            d.show();
        }, __("SSH Tunnel"));

        // Fetch Document Folders from MijnRood
        frm.add_custom_button(__("Fetch Folders"), function () {
            frappe.confirm(
                __("Fetch document folders from MijnRood? This will populate the folder mapping table with root-level folders."),
                function () {
                    frappe.call({
                        method: "fetch_document_folders",
                        doc: frm.doc,
                        freeze: true,
                        freeze_message: __("Connecting to MijnRood and fetching folders..."),
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
        }, __("Document Import"));

        // Auto-Classify folder mappings
        if (frm.doc.document_folder_mapping && frm.doc.document_folder_mapping.length) {
            frm.add_custom_button(__("Auto-Classify"), function () {
                frappe.confirm(
                    __("Auto-classify folder mappings? This will infer document types and chapters from folder names. Only blank rows will be updated — manual edits are preserved."),
                    function () {
                        frappe.call({
                            method: "auto_classify_folders",
                            doc: frm.doc,
                            freeze: true,
                            freeze_message: __("Classifying folders..."),
                            callback: function (r) {
                                if (r.message && r.message.success) {
                                    frappe.show_alert({
                                        message: r.message.message,
                                        indicator: "green",
                                    });
                                } else {
                                    frappe.msgprint({
                                        title: __("Classification Failed"),
                                        indicator: "red",
                                        message: r.message ? r.message.message : __("Unknown error"),
                                    });
                                }
                                frm.reload_doc();
                            },
                        });
                    }
                );
            }, __("Document Import"));
        }

        // Import Documents from MijnRood
        frm.add_custom_button(__("Import Documents"), function () {
            frappe.confirm(
                __("Start importing documents from MijnRood? Files will be downloaded via SFTP and Organization Document records created. This runs as a background job."),
                function () {
                    frappe.call({
                        method: "import_documents",
                        doc: frm.doc,
                        freeze: true,
                        freeze_message: __("Enqueuing document import job..."),
                        callback: function (r) {
                            if (r.message && r.message.success) {
                                frappe.show_alert({
                                    message: r.message.message,
                                    indicator: "green",
                                });
                            } else {
                                frappe.msgprint({
                                    title: __("Import Failed"),
                                    indicator: "red",
                                    message: r.message ? r.message.message : __("Unknown error"),
                                });
                            }
                            frm.reload_doc();
                        },
                    });
                }
            );
        }, __("Document Import"));

        // Listen for realtime import progress (register once, not on every refresh)
        if (!frm._import_progress_bound) {
            frm._import_progress_bound = true;
            frappe.realtime.on("document_import_progress", function (data) {
                frappe.show_progress(
                    __("Importing Documents"),
                    data.current,
                    data.total,
                    __("Imported: {0}, Skipped: {1}", [data.imported, data.skipped])
                );
                if (data.current === data.total) {
                    frm.reload_doc();
                }
            });
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
