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
            const passphrase_set = !!frm.doc.ssh_key_passphrase;
            const password_set = !!frm.doc.ssh_password;
            status_wrapper.html(
                `<div class="text-muted" style="padding:6px 0">
                    ${dot(key_set)} ${__("Private key")}: <b>${key_set ? __("set") : __("not set")}</b>
                    &nbsp;·&nbsp;
                    ${dot(passphrase_set)} ${__("Key passphrase")}: <b>${passphrase_set ? __("set") : __("not set")}</b>
                    &nbsp;·&nbsp;
                    ${dot(password_set)} ${__("SSH password")}: <b>${password_set ? __("set") : __("not set")}</b>
                </div>`
            );
        }

        // First-time setup — single entry point for fresh installs.
        // Visible only when at least one defaults table is still empty.
        const needs_first_time_setup =
            !frm.doc.status_mapping?.length || !frm.doc.role_mapping?.length;
        if (needs_first_time_setup) {
            frm.add_custom_button(__("First-time setup"), function () {
                frappe.confirm(
                    __("This creates the default teams (Landelijk Beheer + Secretariaat) and populates any empty status/role mapping tables with recommended defaults. Existing data is preserved. Continue?"),
                    function () {
                        frappe.call({
                            method: "first_time_setup",
                            doc: frm.doc,
                            freeze: true,
                            freeze_message: __("Running first-time setup..."),
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
                    }
                );
            }).addClass("btn-primary");
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

        // Dialog-based secret entry — kept off the main form to suppress
        // browser save-password prompts. Used for both key passphrase and
        // login password since the UX is identical.
        const open_secret_dialog = (title, label, description, target_field, alert_text) => {
            const d = new frappe.ui.Dialog({
                title: __(title),
                fields: [
                    {
                        fieldname: "secret",
                        fieldtype: "Password",
                        label: __(label),
                        description: __(description),
                    },
                ],
                primary_action_label: __("Save"),
                primary_action(values) {
                    frm.set_value(target_field, values.secret || "");
                    frm.dirty();
                    d.hide();
                    frappe.show_alert({
                        message: __(alert_text),
                        indicator: "green",
                    });
                },
            });
            d.show();

            // Suppress browser autofill (Chrome ignores autocomplete="off" on
            // password fields but DOES respect autocomplete="new-password"). We
            // also randomise `name` so the browser can't pattern-match saved
            // credentials. data-lpignore / data-form-type cover LastPass and 1P.
            const $input = d.fields_dict.secret.$input;
            if ($input) {
                const random_name = "secret_" + Math.random().toString(36).slice(2);
                $input.attr({
                    autocomplete: "new-password",
                    name: random_name,
                    "data-lpignore": "true",
                    "data-form-type": "other",
                    "data-1p-ignore": "true",
                });
                $input.val("");
                setTimeout(() => {
                    if (!$input.is(":focus")) $input.val("");
                }, 100);
            }
        };

        frm.add_custom_button(__("Set SSH Key Passphrase"), function () {
            open_secret_dialog(
                "Set SSH Key Passphrase",
                "Passphrase",
                "Passphrase for the encrypted SSH key. Leave blank for unencrypted keys.",
                "ssh_key_passphrase",
                "Passphrase updated. Save the document to store it encrypted."
            );
        }, __("SSH Tunnel"));

        frm.add_custom_button(__("Set SSH Password"), function () {
            open_secret_dialog(
                "Set SSH Password",
                "Password",
                "SSH login password (only when not using key auth). Leave blank to clear.",
                "ssh_password",
                "Password updated. Save the document to store it encrypted."
            );
        }, __("SSH Tunnel"));

        // Diagnose which auth path will fire and what key (if any) parses.
        // Returns only non-sensitive metadata (key type, fingerprint, paths).
        // Optionally also attempts a real handshake and captures paramiko's
        // DEBUG log — useful for debugging legacy SSH server failures.
        frm.add_custom_button(__("Diagnose SSH Auth"), function () {
            const prompt = new frappe.ui.Dialog({
                title: __("SSH Auth Diagnostic"),
                fields: [
                    {
                        fieldtype: "Check",
                        fieldname: "attempt_handshake",
                        label: __("Attempt real SSH handshake (captures paramiko DEBUG log)"),
                        description: __(
                            "Opens an SSH connection to the configured host using the saved credentials. " +
                            "Useful for debugging connection failures against legacy SSH servers. " +
                            "Closes the connection immediately and returns the log."
                        ),
                    },
                ],
                primary_action_label: __("Run Diagnostic"),
                primary_action(values) {
                    prompt.hide();
                    frappe.call({
                        method: "diagnose_ssh_auth",
                        doc: frm.doc,
                        args: { attempt_handshake: !!values.attempt_handshake },
                        freeze: true,
                        freeze_message: values.attempt_handshake
                            ? __("Attempting SSH handshake...")
                            : __("Inspecting SSH configuration..."),
                        callback: function (r) {
                            if (!r.message) return;
                            const data = r.message;
                            // Pull the paramiko log out for a separate viewer
                            // — JSON pretty-printing mangles multi-line text.
                            const log = data.handshake && data.handshake.paramiko_log;
                            const summary = { ...data };
                            if (summary.handshake) {
                                summary.handshake = { ...summary.handshake };
                                delete summary.handshake.paramiko_log;
                            }
                            const fields = [
                                {
                                    fieldtype: "Code",
                                    fieldname: "report",
                                    label: __("Report"),
                                    options: "JSON",
                                    read_only: 1,
                                    default: JSON.stringify(summary, null, 2),
                                },
                            ];
                            if (log) {
                                fields.push({
                                    fieldtype: "Code",
                                    fieldname: "log",
                                    label: __("Paramiko DEBUG Log"),
                                    options: "Text",
                                    read_only: 1,
                                    default: log,
                                });
                            }
                            const d = new frappe.ui.Dialog({
                                title: __("SSH Auth Diagnostic"),
                                size: "large",
                                fields: fields,
                                primary_action_label: __("Close"),
                                primary_action() { d.hide(); },
                            });
                            d.show();
                        },
                    });
                },
            });
            prompt.show();
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
