frappe.ready(() => {
    // State management
    const state = {
        stagedData: null,
        mappings: [],
        currentStep: 1,
        migrationId: null
    };

    // Initialize page
    initializePage();

    function initializePage() {
        loadInitialStatus();
        attachEventListeners();
        updateStepVisibility();
    }

    // Load initial configuration status
    async function loadInitialStatus() {
        try {
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.get_migration_config_status',
                freeze: true,
                freeze_message: __('Loading configuration status...')
            });

            const data = response.message;
            updateStatusDisplay(data);

            if (data.staged_data_exists) {
                state.stagedData = data.staged_data;
                state.currentStep = Math.max(2, state.currentStep);
            }

            if (data.mappings && data.mappings.length > 0) {
                state.mappings = data.mappings;
                state.currentStep = Math.max(3, state.currentStep);
                displayMappings();
            }

            updateStepVisibility();
        } catch (error) {
            showError('Failed to load configuration status', error);
        }
    }

    // Update status display
    function updateStatusDisplay(data) {
        const statusContainer = document.getElementById('status-container');
        const html = `
            <div class="row">
                <div class="col-md-6">
                    <div class="info-item">
                        <label class="text-muted">${__('Staged Data')}</label>
                        <p class="mb-0">
                            ${data.staged_data_exists ?
                                `<span class="badge badge-success">${__('Available')}</span> - ${data.staged_count || 0} ${__('transactions')}` :
                                `<span class="badge badge-secondary">${__('Not staged')}</span>`
                            }
                        </p>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="info-item">
                        <label class="text-muted">${__('Account Mappings')}</label>
                        <p class="mb-0">
                            ${data.mappings_count || 0} ${__('configured')}
                        </p>
                    </div>
                </div>
            </div>
            ${data.last_staging_date ?
                `<div class="mt-2">
                    <small class="text-muted">${__('Last staged')}: ${frappe.datetime.str_to_user(data.last_staging_date)}</small>
                </div>` : ''
            }
        `;
        statusContainer.innerHTML = html;
    }

    // Attach event listeners
    function attachEventListeners() {
        // Stage data button
        document.getElementById('stage-data-btn').addEventListener('click', stageData);

        // Review data button
        document.getElementById('review-data-btn').addEventListener('click', reviewStagedData);

        // Add mapping button
        document.getElementById('add-mapping-btn').addEventListener('click', addMapping);

        // Preview impact button
        document.getElementById('preview-impact-btn').addEventListener('click', previewImpact);

        // Start migration button
        document.getElementById('start-migration-btn').addEventListener('click', startMigration);

        // Export/Import buttons
        document.getElementById('export-config-btn').addEventListener('click', exportConfiguration);
        document.getElementById('import-config-btn').addEventListener('click', importConfiguration);

        // Quick actions
        document.getElementById('review-account-types-btn').addEventListener('click', openAccountTypeReview);
        document.getElementById('refresh-status-btn').addEventListener('click', loadInitialStatus);
        document.getElementById('clear-mappings-btn').addEventListener('click', clearAllMappings);

        // Enter key on mapping inputs
        ['account-code', 'account-type', 'mapping-notes'].forEach(id => {
            document.getElementById(id).addEventListener('keypress', (e) => {
                if (e.key === 'Enter') addMapping();
            });
        });
    }

    // Update step visibility based on current progress
    function updateStepVisibility() {
        for (let i = 1; i <= 5; i++) {
            const card = document.getElementById(`step${i}-card`);
            if (!card) continue;

            if (i <= state.currentStep) {
                card.style.display = 'block';
                if (i < state.currentStep) {
                    card.classList.add('step-complete');
                    card.classList.remove('step-active');
                } else {
                    card.classList.add('step-active');
                    card.classList.remove('step-complete');
                }
            } else {
                card.style.display = 'none';
            }
        }
    }

    // Stage data from E-Boekhouden
    async function stageData() {
        const dateRange = await promptDateRange();
        if (!dateRange) return;

        try {
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.stage_eboekhouden_data',
                args: {
                    from_date: dateRange.from_date,
                    to_date: dateRange.to_date
                },
                freeze: true,
                freeze_message: __('Staging data from E-Boekhouden...')
            });

            if (response.message.success) {
                state.stagedData = response.message.data;
                state.currentStep = Math.max(2, state.currentStep);
                updateStepVisibility();

                showStagingResults(response.message);
                frappe.show_alert({
                    message: __('Data staged successfully'),
                    indicator: 'green'
                });
            }
        } catch (error) {
            showError('Failed to stage data', error);
        }
    }

    // Show staging results
    function showStagingResults(result) {
        const container = document.getElementById('staging-results');
        container.innerHTML = `
            <div class="alert alert-success mt-3">
                <h6>${__('Staging Complete')}</h6>
                <ul class="mb-0">
                    <li>${__('Transactions')}: ${result.transaction_count || 0}</li>
                    <li>${__('Unique Accounts')}: ${result.account_count || 0}</li>
                    <li>${__('Date Range')}: ${frappe.datetime.str_to_user(result.from_date)} - ${frappe.datetime.str_to_user(result.to_date)}</li>
                </ul>
            </div>
        `;
        container.style.display = 'block';
    }

    // Review staged data
    async function reviewStagedData() {
        try {
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.get_staged_data_summary',
                freeze: true,
                freeze_message: __('Loading staged data...')
            });

            displayDataReview(response.message);
            $('#dataReviewModal').modal('show');
        } catch (error) {
            showError('Failed to load staged data', error);
        }
    }

    // Display data review in modal
    function displayDataReview(data) {
        const content = document.getElementById('data-review-content');
        content.innerHTML = `
            <div class="data-review">
                <h6>${__('Account Summary')}</h6>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>${__('Account Code')}</th>
                                <th>${__('Account Name')}</th>
                                <th>${__('Transaction Count')}</th>
                                <th>${__('Total Amount')}</th>
                                <th>${__('Suggested Type')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.accounts.map(account => `
                                <tr>
                                    <td><code>${account.code}</code></td>
                                    <td>${account.name}</td>
                                    <td>${account.count}</td>
                                    <td>${frappe.format(account.total, {fieldtype: 'Currency'})}</td>
                                    <td>${account.suggested_type ?
                                        `<span class="badge badge-info">${account.suggested_type}</span>` :
                                        '<span class="text-muted">-</span>'
                                    }</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>

                <h6 class="mt-3">${__('Transaction Types')}</h6>
                <div class="row">
                    ${Object.entries(data.transaction_types || {}).map(([type, count]) => `
                        <div class="col-md-4">
                            <div class="card mb-2">
                                <div class="card-body p-2">
                                    <h6 class="mb-0">${count}</h6>
                                    <small class="text-muted">${type}</small>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // Add a new mapping
    async function addMapping() {
        const accountCode = document.getElementById('account-code').value.trim();
        const accountType = document.getElementById('account-type').value;
        const notes = document.getElementById('mapping-notes').value.trim();

        if (!accountCode || !accountType) {
            frappe.show_alert({
                message: __('Please provide both account code and type'),
                indicator: 'red'
            });
            return;
        }

        try {
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.add_account_mapping',
                args: {
                    account_code: accountCode,
                    account_type: accountType,
                    notes: notes
                }
            });

            if (response.message.success) {
                state.mappings.push(response.message.mapping);
                displayMappings();

                // Clear inputs
                document.getElementById('account-code').value = '';
                document.getElementById('account-type').value = '';
                document.getElementById('mapping-notes').value = '';

                frappe.show_alert({
                    message: __('Mapping added successfully'),
                    indicator: 'green'
                });

                state.currentStep = Math.max(3, state.currentStep);
                updateStepVisibility();
            }
        } catch (error) {
            showError('Failed to add mapping', error);
        }
    }

    // Display current mappings
    function displayMappings() {
        const container = document.getElementById('mappings-table');

        if (state.mappings.length === 0) {
            container.innerHTML = '<p class="text-muted">' + __('No mappings configured yet') + '</p>';
            document.getElementById('bulk-edit-btn').style.display = 'none';
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-sm">
                    <thead>
                        <tr>
                            <th>
                                <input type="checkbox" id="select-all-mappings" onchange="toggleAllMappings()">
                            </th>
                            <th>${__('Account Code')}</th>
                            <th>${__('Account Type')}</th>
                            <th>${__('Notes')}</th>
                            <th>${__('Actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${state.mappings.map((mapping, index) => `
                            <tr>
                                <td>
                                    <input type="checkbox" class="mapping-checkbox" value="${index}">
                                </td>
                                <td><code>${mapping.account_code}</code></td>
                                <td><span class="badge badge-primary">${mapping.target_account_type || mapping.account_type}</span></td>
                                <td>${mapping.description || mapping.notes || '-'}</td>
                                <td>
                                    <button class="btn btn-sm btn-info" onclick="editMapping(${index})">
                                        <i class="fa fa-edit"></i>
                                    </button>
                                    <button class="btn btn-sm btn-danger" onclick="removeMapping(${index})">
                                        <i class="fa fa-trash"></i>
                                    </button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        // Show bulk edit button if there are mappings
        document.getElementById('bulk-edit-btn').style.display = state.mappings.length > 0 ? 'inline-block' : 'none';
    }

    // Remove a mapping
    window.removeMapping = async function(index) {
        if (!confirm(__('Are you sure you want to remove this mapping?'))) return;

        try {
            const mapping = state.mappings[index];
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.remove_account_mapping',
                args: { mapping_id: mapping.id }
            });

            if (response.message.success) {
                state.mappings.splice(index, 1);
                displayMappings();
                frappe.show_alert({
                    message: __('Mapping removed'),
                    indicator: 'orange'
                });
            }
        } catch (error) {
            showError('Failed to remove mapping', error);
        }
    };

    // Preview migration impact
    async function previewImpact() {
        try {
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.preview_migration_impact',
                freeze: true,
                freeze_message: __('Calculating migration impact...')
            });

            displayPreview(response.message);
            $('#previewModal').modal('show');

            state.currentStep = Math.max(4, state.currentStep);
            updateStepVisibility();
        } catch (error) {
            showError('Failed to preview impact', error);
        }
    }

    // Display preview results
    function displayPreview(preview) {
        const content = document.getElementById('preview-content');
        content.innerHTML = `
            <div class="preview-results">
                <h6>${__('Migration Impact Summary')}</h6>
                <div class="row">
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-body">
                                <h5>${preview.journal_entries || 0}</h5>
                                <small class="text-muted">${__('Journal Entries')}</small>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-body">
                                <h5>${preview.purchase_invoices || 0}</h5>
                                <small class="text-muted">${__('Purchase Invoices')}</small>
                            </div>
                        </div>
                    </div>
                </div>

                ${preview.warnings && preview.warnings.length > 0 ? `
                    <div class="alert alert-warning mt-3">
                        <h6>${__('Warnings')}</h6>
                        <ul class="mb-0">
                            ${preview.warnings.map(w => `<li>${w}</li>`).join('')}
                        </ul>
                    </div>
                ` : ''}

                ${preview.unmapped_accounts && preview.unmapped_accounts.length > 0 ? `
                    <div class="mt-3">
                        <h6>${__('Unmapped Accounts')}</h6>
                        <p class="text-muted">${__('These accounts will use default mappings:')}</p>
                        <div class="unmapped-list">
                            ${preview.unmapped_accounts.map(a =>
                                `<span class="badge badge-secondary mr-1">${a.code} - ${a.name}</span>`
                            ).join('')}
                        </div>
                    </div>
                ` : ''}
            </div>
        `;
    }

    // Start the migration
    async function startMigration() {
        if (!confirm(__('Are you ready to start the migration with your current configuration?'))) return;

        try {
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.start_configured_migration',
                args: {
                    use_staged_data: true,
                    apply_mappings: true
                }
            });

            if (response.message.success) {
                state.migrationId = response.message.migration_id;
                frappe.show_alert({
                    message: __('Migration started successfully'),
                    indicator: 'green'
                });

                // Redirect to migration monitoring page
                setTimeout(() => {
                    window.location.href = `/app/e-boekhouden-migration/${state.migrationId}`;
                }, 2000);
            }
        } catch (error) {
            showError('Failed to start migration', error);
        }
    }

    // Export configuration
    async function exportConfiguration() {
        try {
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.export_migration_config'
            });

            const config = response.message;
            const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `eboekhouden_config_${frappe.datetime.now_datetime()}.json`;
            a.click();
            window.URL.revokeObjectURL(url);

            frappe.show_alert({
                message: __('Configuration exported successfully'),
                indicator: 'green'
            });
        } catch (error) {
            showError('Failed to export configuration', error);
        }
    }

    // Import configuration
    async function importConfiguration() {
        const fileInput = document.getElementById('import-config-file');
        const file = fileInput.files[0];

        if (!file) {
            frappe.show_alert({
                message: __('Please select a file to import'),
                indicator: 'red'
            });
            return;
        }

        try {
            const text = await file.text();
            const config = JSON.parse(text);

            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.import_migration_config',
                args: { config: config }
            });

            if (response.message.success) {
                frappe.show_alert({
                    message: __('Configuration imported successfully'),
                    indicator: 'green'
                });

                // Reload page to reflect changes
                setTimeout(() => location.reload(), 1000);
            }
        } catch (error) {
            showError('Failed to import configuration', error);
        }
    }

    // Clear all mappings
    async function clearAllMappings() {
        if (!confirm(__('Are you sure you want to clear all mappings? This cannot be undone.'))) return;

        try {
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.clear_all_mappings'
            });

            if (response.message.success) {
                state.mappings = [];
                displayMappings();
                frappe.show_alert({
                    message: __('All mappings cleared'),
                    indicator: 'orange'
                });
            }
        } catch (error) {
            showError('Failed to clear mappings', error);
        }
    }

    // Prompt for date range
    async function promptDateRange() {
        return new Promise((resolve) => {
            const d = new frappe.ui.Dialog({
                title: __('Select Date Range'),
                fields: [
                    {
                        label: __('From Date'),
                        fieldname: 'from_date',
                        fieldtype: 'Date',
                        default: frappe.datetime.add_months(frappe.datetime.now_date(), -3)
                    },
                    {
                        label: __('To Date'),
                        fieldname: 'to_date',
                        fieldtype: 'Date',
                        default: frappe.datetime.now_date()
                    }
                ],
                primary_action_label: __('Stage Data'),
                primary_action(values) {
                    resolve(values);
                    d.hide();
                },
                secondary_action_label: __('Cancel'),
                secondary_action() {
                    resolve(null);
                    d.hide();
                }
            });
            d.show();
        });
    }

    // Show error message
    function showError(message, error) {
        console.error(error);
        frappe.show_alert({
            message: __(message) + ': ' + (error.message || error),
            indicator: 'red'
        });
    }

    // Toggle all mappings selection
    window.toggleAllMappings = function() {
        const selectAll = document.getElementById('select-all-mappings');
        const checkboxes = document.querySelectorAll('.mapping-checkbox');
        checkboxes.forEach(cb => cb.checked = selectAll.checked);
        updateBulkEditButton();
    };

    // Update bulk edit button visibility
    function updateBulkEditButton() {
        const checkedBoxes = document.querySelectorAll('.mapping-checkbox:checked');
        const bulkEditBtn = document.getElementById('bulk-edit-btn');
        if (bulkEditBtn) {
            bulkEditBtn.style.display = checkedBoxes.length > 0 ? 'inline-block' : 'none';
        }
    }

    // Edit a single mapping
    window.editMapping = async function(index) {
        const mapping = state.mappings[index];

        const d = new frappe.ui.Dialog({
            title: __('Edit Account Mapping'),
            fields: [
                {
                    label: __('Account Code'),
                    fieldname: 'account_code',
                    fieldtype: 'Data',
                    default: mapping.account_code,
                    read_only: 1
                },
                {
                    label: __('Account Type'),
                    fieldname: 'account_type',
                    fieldtype: 'Select',
                    options: [
                        'Asset', 'Liability', 'Equity', 'Income', 'Expense',
                        'Bank', 'Cash', 'Receivable', 'Payable', 'Tax'
                    ],
                    default: mapping.target_account_type || mapping.account_type
                },
                {
                    label: __('Notes'),
                    fieldname: 'notes',
                    fieldtype: 'Small Text',
                    default: mapping.description || mapping.notes
                }
            ],
            primary_action_label: __('Update'),
            primary_action: async function(values) {
                try {
                    const response = await frappe.call({
                        method: 'verenigingen.e_boekhouden.api.update_account_mapping',
                        args: {
                            mapping_id: mapping.name || mapping.id,
                            account_type: values.account_type,
                            notes: values.notes
                        }
                    });

                    if (response.message.success) {
                        // Update local state
                        state.mappings[index] = {
                            ...mapping,
                            target_account_type: values.account_type,
                            description: values.notes
                        };
                        displayMappings();
                        frappe.show_alert({
                            message: __('Mapping updated successfully'),
                            indicator: 'green'
                        });
                        d.hide();
                    }
                } catch (error) {
                    showError('Failed to update mapping', error);
                }
            }
        });
        d.show();
    };

    // Bulk edit selected mappings
    document.getElementById('bulk-edit-btn').addEventListener('click', function() {
        const checkboxes = document.querySelectorAll('.mapping-checkbox:checked');
        const selectedIndices = Array.from(checkboxes).map(cb => parseInt(cb.value));

        if (selectedIndices.length === 0) {
            frappe.show_alert({
                message: __('Please select mappings to edit'),
                indicator: 'orange'
            });
            return;
        }

        const d = new frappe.ui.Dialog({
            title: __('Bulk Edit Account Mappings'),
            fields: [
                {
                    label: __('Account Type'),
                    fieldname: 'account_type',
                    fieldtype: 'Select',
                    options: [
                        '', 'Asset', 'Liability', 'Equity', 'Income', 'Expense',
                        'Bank', 'Cash', 'Receivable', 'Payable', 'Tax'
                    ],
                    description: __('Leave empty to keep existing values')
                },
                {
                    label: __('Priority'),
                    fieldname: 'priority',
                    fieldtype: 'Int',
                    description: __('Leave empty to keep existing values')
                }
            ],
            primary_action_label: __('Update Selected'),
            primary_action: async function(values) {
                try {
                    const updates = [];
                    for (const index of selectedIndices) {
                        const mapping = state.mappings[index];
                        if (values.account_type || values.priority) {
                            updates.push({
                                mapping_id: mapping.name || mapping.id,
                                account_type: values.account_type || mapping.target_account_type,
                                priority: values.priority || mapping.priority
                            });
                        }
                    }

                    const response = await frappe.call({
                        method: 'verenigingen.e_boekhouden.api.bulk_update_mappings',
                        args: { updates: updates }
                    });

                    if (response.message.success) {
                        frappe.show_alert({
                            message: __('Updated {0} mappings', [updates.length]),
                            indicator: 'green'
                        });
                        loadInitialStatus(); // Reload data
                        d.hide();
                    }
                } catch (error) {
                    showError('Failed to update mappings', error);
                }
            }
        });
        d.show();
    });

    // Auto-suggest mappings
    document.getElementById('suggest-mappings-btn').addEventListener('click', async function() {
        try {
            const response = await frappe.call({
                method: 'verenigingen.e_boekhouden.api.suggest_account_mappings',
                freeze: true,
                freeze_message: __('Analyzing accounts and suggesting mappings...')
            });

            if (response.message.success) {
                const suggestions = response.message.suggestions;

                const d = new frappe.ui.Dialog({
                    title: __('Suggested Account Mappings'),
                    fields: [
                        {
                            fieldtype: 'HTML',
                            fieldname: 'suggestions_html'
                        }
                    ],
                    primary_action_label: __('Apply Selected'),
                    primary_action: async function() {
                        const selected = [];
                        document.querySelectorAll('.suggestion-checkbox:checked').forEach(cb => {
                            selected.push(JSON.parse(cb.value));
                        });

                        if (selected.length === 0) {
                            frappe.show_alert({
                                message: __('Please select suggestions to apply'),
                                indicator: 'orange'
                            });
                            return;
                        }

                        try {
                            const response = await frappe.call({
                                method: 'verenigingen.e_boekhouden.api.apply_suggested_mappings',
                                args: { suggestions: selected }
                            });

                            if (response.message.success) {
                                frappe.show_alert({
                                    message: __('Applied {0} mappings', [selected.length]),
                                    indicator: 'green'
                                });
                                loadInitialStatus();
                                d.hide();
                            }
                        } catch (error) {
                            showError('Failed to apply suggestions', error);
                        }
                    }
                });

                // Build suggestions HTML
                let html = '<div class="suggestions-list">';
                html += '<div class="mb-2"><label><input type="checkbox" id="select-all-suggestions"> ' + __('Select All') + '</label></div>';
                html += '<table class="table table-sm"><thead><tr><th></th><th>' + __('Account') + '</th><th>' + __('Suggested Type') + '</th><th>' + __('Confidence') + '</th></tr></thead><tbody>';

                suggestions.forEach((sug, idx) => {
                    const confidence = sug.confidence || 'medium';
                    const badgeClass = confidence === 'high' ? 'success' : confidence === 'medium' ? 'warning' : 'secondary';
                    html += `<tr>
                        <td><input type="checkbox" class="suggestion-checkbox" value='${JSON.stringify(sug)}'></td>
                        <td><code>${sug.account_code}</code> - ${sug.account_name}</td>
                        <td><span class="badge badge-primary">${sug.suggested_type}</span></td>
                        <td><span class="badge badge-${badgeClass}">${confidence}</span></td>
                    </tr>`;
                });

                html += '</tbody></table></div>';

                d.fields_dict.suggestions_html.$wrapper.html(html);

                // Add select all functionality
                document.getElementById('select-all-suggestions').addEventListener('change', function() {
                    document.querySelectorAll('.suggestion-checkbox').forEach(cb => {
                        cb.checked = this.checked;
                    });
                });

                d.show();
            }
        } catch (error) {
            showError('Failed to get suggestions', error);
        }
    });

    // Add event delegation for checkbox changes
    document.addEventListener('change', function(e) {
        if (e.target.classList.contains('mapping-checkbox')) {
            updateBulkEditButton();
        }
    });

    // Open Account Type Review Page
    function openAccountTypeReview() {
        // Open the existing full-featured account type review page in same tab
        window.location.href = '/eboekhouden_mapping_review';
    }
});
