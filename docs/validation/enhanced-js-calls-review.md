# Enhanced JavaScript Calls Review - Refined Analysis

## Executive Summary
- **Total JavaScript files analyzed**: 96
- **Total unique method calls found**: 188
- **Framework methods (excluded)**: 100
- **App-specific methods analyzed**: 162
- **Missing methods requiring implementation**: 66
- **Existing methods (verified)**: 96

## Missing Methods by Component

### E-Boekhouden Integration (17 methods)

#### `verenigingen.e_boekhouden.api.get_migration_config_status`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:22`
- **Purpose**: Status Check - Retrieves current status information
- **Implementation Complexity**: Easy
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
teners();
		updateStepVisibility();
	}

	// Load initial configuration status
	async function loadInitialStatus() {
		try {
			const response = await frappe.call({
				method: 'verenigingen.e_boekhouden.api.get_migration_config_status',
				freeze: true,
				freeze_message: __('Loading configuration...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.utils_category_mapping_fixed.analyze_accounts_with_proper_categories`

- **File**: `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration_original.js:338`
- **Purpose**: Account Mapping - Manages account mappings for E-Boekhouden
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/utils_category_mapping_fixed
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
tion_label: 'Use Category-based (Recommended)',
						primary_action: function() {
							d.hide();
							// Use fixed category-based mapping
							frappe.call({
								method: 'verenigingen.e_boekhouden.utils_category_mapping_fixed.analyze_accounts_with_proper_categories',
								callback: func...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.apply_suggested_mappings`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:785`
- **Purpose**: Application - Applies changes or configurations
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
e: __('Please select suggestions to apply'),
								indicator: 'orange'
							});
							return;
						}

						try {
							const response = await frappe.call({
								method: 'verenigingen.e_boekhouden.api.apply_suggested_mappings',
								args: { suggestions: selected }
							});

							if ...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.get_staged_data_summary`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:188`
- **Purpose**: Data Aggregation - Fetches summarized or aggregated data
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
iv>
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
...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.export_migration_config`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:475`
- **Purpose**: Data Transfer - Handles data import/export operations
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
Error('Failed to start migration', error);
		}
	}

	// Export configuration
	async function exportConfiguration() {
		try {
			const response = await frappe.call({
				method: 'verenigingen.e_boekhouden.api.export_migration_config'
			});

			const config = response.message;
			const blob = new Blob...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.import_migration_config`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:514`
- **Purpose**: Data Transfer - Handles data import/export operations
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
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

			if (response.message.success) {...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.remove_account_mapping`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:356`
- **Purpose**: Delete Operation - Removes records or entities
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
(!confirm(__('Are you sure you want to remove this mapping?'))) return;

		try {
			const mapping = state.mappings[index];
			const response = await frappe.call({
				method: 'verenigingen.e_boekhouden.api.remove_account_mapping',
				args: { mapping_id: mapping.id }
			});

			if (response.message....
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.clear_all_mappings`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:538`
- **Purpose**: Delete Operation - Removes records or entities
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
AllMappings() {
		if (!confirm(__('Are you sure you want to clear all mappings? This cannot be undone.'))) return;

		try {
			const response = await frappe.call({
				method: 'verenigingen.e_boekhouden.api.clear_all_mappings'
			});

			if (response.message.success) {
				state.mappings = [];
				d...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.utils_group_analysis_improved.analyze_account_categories_improved`

- **File**: `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration_original.js:357`
- **Purpose**: E-Boekhouden Integration - Integrates with E-Boekhouden accounting system
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/utils_group_analysis_improved
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
secondary_action_label: 'Use Group-based',
						secondary_action: function() {
							d.hide();
							// Use original group-based mapping
							frappe.call({
								method: 'verenigingen.e_boekhouden.utils_group_analysis_improved.analyze_account_categories_improved',
								args: {
									use...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.utils_full_migration.migrate_all_eboekhouden_data`

- **File**: `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration_original.js:207`
- **Purpose**: Migration - Handles data migration operations
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/utils_full_migration
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
'</div>'
								}]
							});
							progress_dialog.show();
							progress_dialog.get_close_btn().hide();

							// Start full migration
							frappe.call({
								method: 'verenigingen.e_boekhouden.utils_full_migration.migrate_all_eboekhouden_data',
								callback: function(r) {
									pr...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.preview_migration_impact`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:377`
- **Purpose**: Preview - Provides preview of operations before execution
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
owError('Failed to remove mapping', error);
		}
	};

	// Preview migration impact
	async function previewImpact() {
		try {
			const response = await frappe.call({
				method: 'verenigingen.e_boekhouden.api.preview_migration_impact',
				freeze: true,
				freeze_message: __('Calculating migration im...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.stage_eboekhouden_data`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:143`
- **Purpose**: Staging - Stages data for processing
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
E-Boekhouden
	async function stageData() {
		const dateRange = await promptDateRange();
		if (!dateRange) return;

		try {
			const response = await frappe.call({
				method: 'verenigingen.e_boekhouden.api.stage_eboekhouden_data',
				args: {
					from_date: dateRange.from_date,
					to_date: dateRa...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.start_configured_migration`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:447`
- **Purpose**: Workflow Control - Initiates processes or workflows
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
Migration() {
		if (!confirm(__('Are you ready to start the migration with your current configuration?'))) return;

		try {
			const response = await frappe.call({
				method: 'verenigingen.e_boekhouden.api.start_configured_migration',
				args: {
					use_staged_data: true,
					apply_mappings: tru...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.add_account_mapping`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:267`
- **Purpose**: Create Operation - Creates new records or entities
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
w_alert({
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
					account_type: accountT...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.suggest_account_mappings`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:752`
- **Purpose**: Search/Suggestion - Searches for records or provides suggestions
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
Auto-suggest mappings
	document.getElementById('suggest-mappings-btn').addEventListener('click', async function() {
		try {
			const response = await frappe.call({
				method: 'verenigingen.e_boekhouden.api.suggest_account_mappings',
				freeze: true,
				freeze_message: __('Analyzing accounts and s...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.update_account_mapping`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:649`
- **Purpose**: Update Operation - Modifies existing records
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
|| mapping.notes
				}
			],
			primary_action_label: __('Update'),
			primary_action: async function(values) {
				try {
					const response = await frappe.call({
						method: 'verenigingen.e_boekhouden.api.update_account_mapping',
						args: {
							mapping_id: mapping.name || mapping.id,
					...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

#### `verenigingen.e_boekhouden.api.bulk_update_mappings`

- **File**: `verenigingen/public/js/eboekhouden_migration_config.js:728`
- **Purpose**: Update Operation - Modifies existing records
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: e_boekhouden/api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
unt_type || mapping.target_account_type,
								priority: values.priority || mapping.priority
							});
						}
					}

					const response = await frappe.call({
						method: 'verenigingen.e_boekhouden.api.bulk_update_mappings',
						args: { updates: updates }
					});

					if (response.message...
```

**Implementation Notes:**
- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures

---

### Direct Debit Batching (6 methods)

#### `verenigingen.api.dd_batch_api.get_batch_details_with_security`

- **File**: `verenigingen/public/js/dd_batch_management_enhanced.js:562`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: No suitable file found for method path: api/dd_batch_api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
anger';
			default: return 'secondary';
		}
	}

	async showBatchDetails(batchId) {
		try {
			this.currentBatch = batchId;

			const response = await frappe.call({
				method: 'verenigingen.api.dd_batch_api.get_batch_details_with_security',
				args: { batch_id: batchId }
			});

			if (response.mes...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `verenigingen.api.dd_batch_api.get_batch_conflicts`

- **File**: `verenigingen/public/js/dd_batch_management_enhanced.js:737`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: No suitable file found for method path: api/dd_batch_api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
case 'failed': return 'danger';
			default: return 'secondary';
		}
	}

	async showConflictResolution(batchId) {
		try {
			const response = await frappe.call({
				method: 'verenigingen.api.dd_batch_api.get_batch_conflicts',
				args: { batch_id: batchId }
			});

			if (response.message && respons...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `verenigingen.api.dd_batch_api.get_eligible_invoices`

- **File**: `verenigingen/public/js/dd_batch_management_enhanced.js:1236`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: No suitable file found for method path: api/dd_batch_api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
type: $('#member-type-filter').val(),
				amount_min: $('#amount-min').val(),
				amount_max: $('#amount-max').val()
			};

			const response = await frappe.call({
				method: 'verenigingen.api.dd_batch_api.get_eligible_invoices',
				args: { filters: filters }
			});

			if (response.message && res...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `verenigingen.api.dd_batch_api.apply_conflict_resolutions`

- **File**: `verenigingen/public/js/dd_batch_management_enhanced.js:884`
- **Purpose**: Application - Applies changes or configurations
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: api/dd_batch_api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
</div>
        `;
	}

	async applyConflictResolutions() {
		try {
			const resolutions = this.collectResolutions();

			const response = await frappe.call({
				method: 'verenigingen.api.dd_batch_api.apply_conflict_resolutions',
				args: {
					batch_id: this.currentBatch,
					resolutions: resolut...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `verenigingen.api.dd_batch_api.get_batch_list_with_security`

- **File**: `verenigingen/public/js/dd_batch_management_enhanced.js:419`
- **Purpose**: Data Aggregation - Fetches summarized or aggregated data
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: api/dd_batch_api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
}

	async loadBatchList() {
		try {
			this.showLoading('#batch-list-body');

			const filters = this.getFilterValues();

			const response = await frappe.call({
				method: 'verenigingen.api.dd_batch_api.get_batch_list_with_security',
				args: { filters: filters }
			});

			if (response.message &...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `verenigingen.api.dd_batch_api.escalate_conflicts`

- **File**: `verenigingen/public/js/dd_batch_management_enhanced.js:925`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: api/dd_batch_api
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ution_', '');
				resolutions[memberId] = value;
			}
		});

		return resolutions;
	}

	async escalateConflicts() {
		try {
			const response = await frappe.call({
				method: 'verenigingen.api.dd_batch_api.escalate_conflicts',
				args: {
					batch_id: this.currentBatch,
					conflicts: this.confl...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

### Member Management (1 methods)

#### `verenigingen.api.member_management.get_chapter_member_emails`

- **File**: `verenigingen/public/js/chapter_dashboard.js:387`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Method 'get_chapter_member_emails' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/member_management.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
an_approve_members) {
		frappe.msgprint(__('You do not have permission to email all members.'));
		return;
	}

	// Get member emails for the chapter
	frappe.call({
		method: 'verenigingen.api.member_management.get_chapter_member_emails',
		args: {
			chapter_name: selectedChapter
		},
		callback: fu...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

### Membership Applications (1 methods)

#### `verenigingen.api.membership_application.suggest_chapters_for_postal_code`

- **File**: `verenigingen/public/js/membership_application.js:931`
- **Purpose**: Search/Suggestion - Searches for records or provides suggestions
- **Implementation Complexity**: Medium
- **Status**: Method 'suggest_chapters_for_postal_code' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/membership_application.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
talCode = $('#postal_code').val();

		if (!postalCode || postalCode.length < 4) return;

		// Call API to validate postal code and suggest chapters
		frappe.call({
			method: 'verenigingen.api.membership_application.suggest_chapters_for_postal_code',
			args: { postal_code: postalCode },
			callback...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

### Termination Workflow (5 methods)

#### `verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_termination_statistics`

- **File**: `verenigingen/public/js/termination_dashboard.js:19`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Method 'get_termination_statistics' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
[]);

  const fetchDashboardData = async () => {
    try {
      // Simulate API calls that would be made to Frappe
      const statsResponse = await frappe.call({
        method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_termination_statist...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_eligible_approvers`

- **File**: `verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.js:454`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Method 'get_eligible_approvers' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ship_termination_request.membership_termination_request');

frappe.query_reports['Get Eligible Approvers'] = {
	execute: function(filters) {
		return frappe.call({
			method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_eligible_approvers',
			...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.generate_expulsion_report`

- **File**: `verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request_list.js:71`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Method 'generate_expulsion_report' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ription: __('Filter by specific chapter (optional)')
			}
		],
		primary_action_label: __('Generate Report'),
		primary_action: function(values) {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.generate_expulsion_report',...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `execute_termination`

- **File**: `verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.js:280`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
'• ' + __('End all board/committee positions') + '<br>' +
        '• ' + __('Update membership status'),
		function() {
			// User confirmed
			frappe.call({
				method: 'execute_termination',
				doc: frm.doc,
				freeze: true,
				freeze_message: __('Executing termination...'),
				callback: funct...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.initiate_disciplinary_termination`

- **File**: `verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.js:405`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Method 'initiate_disciplinary_termination' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
n'];
			const is_disciplinary = disciplinary_types.includes(values.termination_type);

			if (is_disciplinary) {
				// Use disciplinary workflow
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.initiate_disciplinary_term...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

### Chapter Management (1 methods)

#### `verenigingen.verenigingen.doctype.chapter.chapter.debug_postal_code_matching`

- **File**: `verenigingen/public/js/member/js_modules/ui-utils.js:94`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Method 'debug_postal_code_matching' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/chapter/chapter.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
r-radius: 0 5px 5px 0;
                }
            </style>
        `);
	}
}

function show_debug_postal_code_info(frm) {
	if (frm.doc.pincode) {
		frappe.call({
			method: 'verenigingen.verenigingen.doctype.chapter.chapter.debug_postal_code_matching',
			args: {
				pincode: frm.doc.pincode
			},...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

### Volunteer Management (2 methods)

#### `get_volunteer_history`

- **File**: `verenigingen/verenigingen/doctype/volunteer/volunteer.js:425`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
.show();
}

// Function to show volunteer timeline
function show_volunteer_timeline(frm) {
	// Display a timeline visualization of volunteer history
	frappe.call({
		method: 'get_volunteer_history',
		doc: frm.doc,
		freeze: true,
		freeze_message: __('Loading volunteer history...'),
		callback: fun...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `verenigingen.verenigingen.doctype.volunteer.volunteer.create_from_member`

- **File**: `verenigingen/public/js/member/js_modules/volunteer-utils.js:102`
- **Purpose**: Create Operation - Creates new records or entities
- **Implementation Complexity**: Medium
- **Status**: Method 'create_from_member' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/volunteer/volunteer.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
unction create_volunteer_from_member(frm) {
	frappe.confirm(
		__('Would you like to create a volunteer profile for this member?'),
		function() {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.volunteer.volunteer.create_from_member',
				args: {
					member: frm.doc.name
				},
			...
```

**Implementation Notes:**
- Data creation operation
- Validate input parameters
- Use `frappe.get_doc()` and `doc.insert()`
- Handle validation errors gracefully

---

### General/Other (33 methods)

#### `verenigingen.utils.payment_utils.get_donation_payment_entry`

- **File**: `verenigingen/verenigingen/doctype/donation/donation.js:14`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: No suitable file found for method path: utils/payment_utils
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
button(__('Create Payment Entry'), function() {
				frm.events.make_payment_entry(frm);
			});
		}
	},

	make_payment_entry: function(frm) {
		return frappe.call({
			method: 'verenigingen.utils.payment_utils.get_donation_payment_entry',
			args: {
				'dt': frm.doc.doctype,
				'dn': frm.doc.name
	...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `get_board_members`

- **File**: `verenigingen/verenigingen/doctype/chapter/chapter.js:487`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
) {
					frappe.msgprint(__('Error adding board member: {0}', [r.message]));
				}
			});
		}
	});

	d.show();
}

function show_board_history(frm) {
	frappe.call({
		method: 'get_board_members',
		doc: frm.doc,
		args: {
			include_inactive: true
		},
		callback: function(r) {
			if (r.message) {
		...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `get_billing_amount`

- **File**: `verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.js:115`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
tails
				frm.set_value('member', membership.member);

				// Subscription system removed - using dues schedule system

				// Set current amount
				frappe.call({
					method: 'get_billing_amount',
					doc: membership,
					callback: function(amount_result) {
						if (amount_result.message) {
			...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `get_impact_preview`

- **File**: `verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.js:136`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
using dues schedule system

function load_impact_preview(frm) {
	if (!frm.doc.membership || frm.doc.amendment_type !== 'Fee Change') {
		return;
	}

	frappe.call({
		method: 'get_impact_preview',
		doc: frm.doc,
		callback: function(r) {
			if (r.message && r.message.html) {
				frm.fields_dict.impa...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `get_current_membership_fee`

- **File**: `verenigingen/verenigingen/doctype/member/member.js:1072`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ee_override_by"]').show();
		}, 100);
	} else {
		frm.toggle_display('fee_management_section', false);
	}
}

function show_fee_details_dialog(frm) {
	frappe.call({
		method: 'get_current_membership_fee',
		doc: frm.doc,
		callback: function(r) {
			if (r.message) {
				const fee_info = r.message;
		...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `get_aggregated_assignments`

- **File**: `verenigingen/verenigingen/doctype/volunteer/volunteer.js:160`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ssignments-header"><h4>' + __('Current Assignments') + '</h4></div>').appendTo(assignments_container);

	// Get assignments data with error handling
	frappe.call({
		method: 'get_aggregated_assignments',
		doc: frm.doc,
		freeze: true,
		freeze_message: __('Loading assignments...'),
		callback: func...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `get_skills_by_category`

- **File**: `verenigingen/verenigingen/doctype/volunteer/volunteer.js:630`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
Use Promise.all to fetch data concurrently
		const [skillsResult, assignmentsResult] = await Promise.all([
			new Promise((resolve, reject) => {
				frappe.call({
					method: 'get_skills_by_category',
					doc: frm.doc,
					callback: function(r) {
						if (r.message !== undefined) {
							resolv...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `verenigingen.api.eboekhouden_migration_redesign.get_migration_statistics`

- **File**: `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.js:634`
- **Purpose**: Data Retrieval - Fetches data from database
- **Implementation Complexity**: Easy
- **Status**: No suitable file found for method path: api/eboekhouden_migration_redesign
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
,
					message: r.message ? r.message.error : 'Unknown error',
					indicator: 'red'
				});
			}
		}
	});
}

function show_migration_statistics() {
	frappe.call({
		method: 'verenigingen.api.eboekhouden_migration_redesign.get_migration_statistics',
		callback: function(r) {
			if (r.message) {
				...
```

**Implementation Notes:**
- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format

---

#### `verenigingen.verenigingen.doctype.member.member.process_payment`

- **File**: `verenigingen/public/js/member/js_modules/payment-utils.js:10`
- **Purpose**: Processing - Processes data or handles workflow
- **Implementation Complexity**: Hard
- **Status**: Method 'process_payment' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/member.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
Schedule system.

function process_payment(frm) {
	if (!frm.doc.name) {
		frappe.msgprint(__('Please save the member record first.'));
		return;
	}

	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.process_payment',
		args: {
			member: frm.doc.name
		},
		callback: function...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `process_batch`

- **File**: `verenigingen/verenigingen/doctype/direct_debit_batch/direct_debit_batch.js:543`
- **Purpose**: Processing - Processes data or handles workflow
- **Implementation Complexity**: Hard
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
_bank_dialog(frm) {
	frappe.confirm(
		__('Are you sure you want to submit this batch to the bank? This action cannot be undone.'),
		function() {
			frappe.call({
				method: 'process_batch',
				doc: frm.doc,
				callback: function(r) {
					if (!r.exc) {
						frm.reload_doc();
						frappe.show_...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `verenigingen.utils.test_rest_migration.test_rest_mutation_fetch`

- **File**: `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.js:1743`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Hard
- **Status**: No suitable file found for method path: utils/test_rest_migration
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
let start_id = values.start_id;
							let end_id = values.test_mode ? Math.min(values.start_id + 100, values.end_id) : values.end_id;

							frappe.call({
								method: 'verenigingen.utils.test_rest_migration.test_rest_mutation_fetch',
								args: {
									start_id: start_id,
									end_id...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `apply_amendment`

- **File**: `verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.js:200`
- **Purpose**: Application - Applies changes or configurations
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ction apply_amendment(frm) {
	frappe.confirm(
		__('Are you sure you want to apply this amendment? This action cannot be undone.'),
		function() {
			frappe.call({
				method: 'apply_amendment',
				doc: frm.doc,
				callback: function(r) {
					if (!r.exc && r.message) {
						const response = r.me...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `verenigingen.utils.fix_receivable_payable_entries.apply_account_type_fixes`

- **File**: `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration_original.js:422`
- **Purpose**: Application - Applies changes or configurations
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: utils/fix_receivable_payable_entries
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ction_label: 'Apply Fixes',
												primary_action: function() {
													preview_dialog.hide();
													// Apply the fixes
													frappe.call({
														method: 'verenigingen.utils.fix_receivable_payable_entries.apply_account_type_fixes',
														args: {
														...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `verenigingen.verenigingen.doctype.member.member.create_organization_user`

- **File**: `verenigingen/public/js/member/js_modules/ui-utils.js:226`
- **Purpose**: Create Operation - Creates new records or entities
- **Implementation Complexity**: Medium
- **Status**: Method 'create_organization_user' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/member.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
el: __('Send Welcome Email'),
						default: 1
					}
				],
				primary_action_label: __('Create User'),
				primary_action: function(values) {
					frappe.call({
						method: 'verenigingen.verenigingen.doctype.member.member.create_organization_user',
						args: {
							member: frm.doc.name,
			...
```

**Implementation Notes:**
- Data creation operation
- Validate input parameters
- Use `frappe.get_doc()` and `doc.insert()`
- Handle validation errors gracefully

---

#### `add_board_member`

- **File**: `verenigingen/verenigingen/doctype/chapter/chapter.js:455`
- **Purpose**: Create Operation - Creates new records or entities
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
}
		],
		primary_action_label: __('Add Board Member'),
		primary_action: function() {
			const values = d.get_values();
			if (!values) return;

			frappe.call({
				method: 'add_board_member',
				doc: frm.doc,
				args: {
					volunteer: values.volunteer,
					role: values.role,
					from_date: va...
```

**Implementation Notes:**
- Data creation operation
- Validate input parameters
- Use `frappe.get_doc()` and `doc.insert()`
- Handle validation errors gracefully

---

#### `add_activity`

- **File**: `verenigingen/verenigingen/doctype/volunteer/volunteer.js:328`
- **Purpose**: Create Operation - Creates new records or entities
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
Small Text',
				label: __('Notes')
			}
		],
		primary_action_label: __('Add'),
		primary_action: function() {
			const values = d.get_values();

			frappe.call({
				method: 'add_activity',
				doc: frm.doc,
				freeze: true,
				freeze_message: __('Adding activity...'),
				args: {
					activity_...
```

**Implementation Notes:**
- Data creation operation
- Validate input parameters
- Use `frappe.get_doc()` and `doc.insert()`
- Handle validation errors gracefully

---

#### `verenigingen.verenigingen.doctype.member.member.migrate_member_id_counter`

- **File**: `verenigingen/public/js/member_counter.js:241`
- **Purpose**: Migration - Handles data migration operations
- **Implementation Complexity**: Medium
- **Status**: Method 'migrate_member_id_counter' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/member.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
unction() {
			frappe.confirm(
				__('Run member ID counter migration? This should only be done once during system upgrade.'),
				function() {
					frappe.call({
						method: 'verenigingen.verenigingen.doctype.member.member.migrate_member_id_counter',
						freeze: true,
						freeze_message: __(...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `verenigingen.verenigingen.doctype.member.member.mark_as_paid`

- **File**: `verenigingen/public/js/member/js_modules/payment-utils.js:32`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Method 'mark_as_paid' not found in /home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/member.py
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ry again.'));
		}
	});
}

function mark_as_paid(frm) {
	frappe.confirm(
		__('Are you sure you want to mark this member as paid?'),
		function() {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member.mark_as_paid',
				args: {
					member: frm.doc.name
				},
				callback: f...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `refresh_financial_history`

- **File**: `verenigingen/public/js/member/js_modules/payment-utils.js:73`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
}
}

function refresh_membership_dues_info(frm) {
	frappe.show_alert({
		message: __('Refreshing financial history...'),
		indicator: 'blue'
	});

	frappe.call({
		method: 'refresh_financial_history',
		doc: frm.doc,
		callback: function(r) {
			frm.refresh_field('payment_history');

			// Updated t...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `submit_for_approval`

- **File**: `verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.js:182`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
for disciplinary terminations'));
		}
	}
}

function submit_for_approval(frm) {
	// Validate required fields first
	validate_required_fields(frm);

	frappe.call({
		method: 'submit_for_approval',
		doc: frm.doc,
		callback: function(r) {
			if (r.message) {
				frm.refresh();
				frappe.show_alert({...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `approve_request`

- **File**: `verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.js:235`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ision}" === "approved"`
			}
		],
		primary_action_label: __(decision === 'approved' ? 'Approve' : 'Reject'),
		primary_action: function(values) {
			frappe.call({
				method: 'approve_request',
				doc: frm.doc,
				args: {
					decision: decision,
					notes: values.notes || ''
				},
				callback...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `sync_board_members`

- **File**: `verenigingen/verenigingen/doctype/chapter/chapter.js:547`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
nactive')) + '</span></td>';
		html += '</tr>';
	});

	html += '</tbody></table></div>';
	return html;
}

function sync_board_with_volunteers(frm) {
	frappe.call({
		method: 'sync_board_members',
		doc: frm.doc,
		freeze: true,
		freeze_message: __('Syncing with volunteer system...'),
		callback: fu...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `reverse_expulsion`

- **File**: `verenigingen/verenigingen/doctype/expulsion_report_entry/expulsion_report_entry.js:111`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
{
					fieldname: 'reversal_reason',
					label: __('Reversal Reason'),
					fieldtype: 'Small Text',
					reqd: 1
				}
			], function(values) {
				frappe.call({
					method: 'reverse_expulsion',
					doc: frm.doc,
					args: {
						reversal_reason: values.reversal_reason
					},
					callback: f...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `approve_amendment`

- **File**: `verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.js:156`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
s'),
			fieldname: 'approval_notes',
			fieldtype: 'Small Text',
			description: __('Optional notes about the approval')
		}
	], function(values) {
		frappe.call({
			method: 'approve_amendment',
			doc: frm.doc,
			args: {
				approval_notes: values.approval_notes
			},
			callback: function(r) {
	...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `reject_amendment`

- **File**: `verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.js:181`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
'rejection_reason',
			fieldtype: 'Small Text',
			reqd: 1,
			description: __('Please provide a reason for rejection')
		}
	], function(values) {
		frappe.call({
			method: 'reject_amendment',
			doc: frm.doc,
			args: {
				rejection_reason: values.rejection_reason
			},
			callback: function(r) {...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `generate_sepa_xml`

- **File**: `verenigingen/verenigingen/doctype/direct_debit_batch/direct_debit_batch.js:519`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
ction use)')
			}
		],
		primary_action_label: __('Generate'),
		primary_action(values) {
			frm.set_value('batch_date', values.collection_date);

			frappe.call({
				method: 'generate_sepa_xml',
				doc: frm.doc,
				callback: function(r) {
					if (!r.exc) {
						frm.reload_doc();
						frappe.s...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `mark_invoices_as_paid`

- **File**: `verenigingen/verenigingen/doctype/direct_debit_batch/direct_debit_batch.js:629`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
: __('Process Payments'),
		primary_action(values) {
			if (!values.confirm) return;

			frappe.show_progress(__('Processing Payments'), 0, 100);

			frappe.call({
				method: 'mark_invoices_as_paid',
				doc: frm.doc,
				callback: function(r) {
					frappe.hide_progress();
					if (!r.exc && r.mes...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `link_donation`

- **File**: `verenigingen/verenigingen/doctype/periodic_donation_agreement/periodic_donation_agreement.js:160`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
title: __('Link Donation to Agreement'),
					fields: fields,
					primary_action_label: __('Link'),
					primary_action: function(values) {
						frappe.call({
							method: 'link_donation',
							doc: frm.doc,
							args: {
								donation_name: values.donation
							},
							callback: funct...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `cancel_agreement`

- **File**: `verenigingen/verenigingen/doctype/periodic_donation_agreement/periodic_donation_agreement.js:204`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
function(values) {
			frappe.confirm(
				__('Are you sure you want to cancel this agreement? This action cannot be undone.'),
				function() {
					frappe.call({
						method: 'cancel_agreement',
						doc: frm.doc,
						args: {
							reason: values.reason
						},
						callback: function(r) {
	...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `end_activity`

- **File**: `verenigingen/verenigingen/doctype/volunteer/volunteer.js:389`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
t',
				label: __('Notes')
			}
		],
		primary_action_label: __('End Activity'),
		primary_action: function() {
			const values = d.get_values();

			frappe.call({
				method: 'end_activity',
				doc: frm.doc,
				freeze: true,
				freeze_message: __('Ending activity...'),
				args: {
					activity_...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `verenigingen.api.test_eboekhouden_connection.test_eboekhouden_connection`

- **File**: `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.js:613`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: api/test_eboekhouden_connection
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
e ? r.message.error : 'Unknown error',
								indicator: 'red'
							});
						}
					}
				});
			});
		}
	);
}

function test_api_connection() {
	frappe.call({
		method: 'verenigingen.api.test_eboekhouden_connection.test_eboekhouden_connection',
		callback: function(r) {
			if (r.message && r.me...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `verenigingen.utils.fix_receivable_payable_entries.analyze_and_fix_entries`

- **File**: `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration_original.js:404`
- **Purpose**: Unknown - Purpose unclear from method name and context
- **Implementation Complexity**: Medium
- **Status**: No suitable file found for method path: utils/fix_receivable_payable_entries
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
yze Accounts',
						primary_action: function() {
							console.log('Analyze Accounts clicked, calling method...');
							fix_dialog.hide();
							frappe.call({
								method: 'verenigingen.utils.fix_receivable_payable_entries.analyze_and_fix_entries',
								callback: function(r) {
									co...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

#### `validate_postal_codes`

- **File**: `verenigingen/verenigingen/doctype/chapter/chapter.js:199`
- **Purpose**: Validation - Validates data or business rules
- **Implementation Complexity**: Medium
- **Status**: Invalid method path format
- **Recommended Action**: Add missing method

**Context Preview:**
```javascript
hapter saved successfully'),
		indicator: 'green'
	}, 3);
}

function validate_postal_codes(frm) {
	if (!frm.doc.postal_codes) return true;

	try {
		frappe.call({
			method: 'validate_postal_codes',
			doc: frm.doc,
			callback: function(r) {
				if (!r.message) {
					frappe.msgprint({
						title...
```

**Implementation Notes:**
- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases

---

## Implementation Priorities

### High Priority (Production Critical)
These methods are likely being called in production interfaces:

- `verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_termination_statistics` (Data Retrieval) - Easy complexity
- `verenigingen.api.member_management.get_chapter_member_emails` (Data Retrieval) - Easy complexity
- `verenigingen.verenigingen.doctype.member.member.migrate_member_id_counter` (Migration) - Medium complexity
- `verenigingen.api.membership_application.suggest_chapters_for_postal_code` (Search/Suggestion) - Medium complexity
- `verenigingen.api.dd_batch_api.get_batch_list_with_security` (Data Aggregation) - Medium complexity
- `verenigingen.api.dd_batch_api.get_batch_details_with_security` (Data Retrieval) - Easy complexity
- `verenigingen.api.dd_batch_api.get_batch_conflicts` (Data Retrieval) - Easy complexity
- `verenigingen.api.dd_batch_api.apply_conflict_resolutions` (Application) - Medium complexity
- `verenigingen.api.dd_batch_api.escalate_conflicts` (Unknown) - Medium complexity
- `verenigingen.api.dd_batch_api.get_eligible_invoices` (Data Retrieval) - Easy complexity

### Medium Priority (Feature Enhancements)
E-Boekhouden migration interface methods:

- `verenigingen.e_boekhouden.api.get_migration_config_status` (Status Check) - Easy complexity
- `verenigingen.e_boekhouden.api.stage_eboekhouden_data` (Staging) - Hard complexity
- `verenigingen.e_boekhouden.api.get_staged_data_summary` (Data Aggregation) - Hard complexity
- `verenigingen.e_boekhouden.api.add_account_mapping` (Create Operation) - Medium complexity
- `verenigingen.e_boekhouden.api.remove_account_mapping` (Delete Operation) - Hard complexity
- ... and 12 more e_boekhouden methods

### Low Priority (Optional Features)
Other missing methods that may be legacy or test functions.

## Next Steps

1. **Audit Production Usage**: Verify which missing methods are actually being called in production
2. **Prioritize by User Impact**: Focus on methods in user-facing interfaces first
3. **Create Implementation Plan**: Start with "Easy" complexity methods
4. **Add Testing**: Ensure all new methods have appropriate test coverage
5. **Update Documentation**: Document new API endpoints as they're implemented

## Files Generated
- **Detailed CSV**: `docs/validation/enhanced-js-calls-review.csv`
- **Implementation Tracker**: Use this markdown file to track progress
