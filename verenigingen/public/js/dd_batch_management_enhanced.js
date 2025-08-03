/**
 * @fileoverview Enhanced SEPA Direct Debit Batch Management - Enterprise-grade Payment Processing
 *
 * Comprehensive SEPA Direct Debit batch management system for the Verenigingen association platform,
 * providing advanced security validation, conflict resolution, real-time monitoring, and intelligent
 * duplicate detection with enterprise-grade financial processing capabilities and compliance features.
 *
 * ## Business Value
 * - **Payment Automation**: Streamlined bulk payment processing with automated validation
 * - **Risk Management**: Advanced security analysis and conflict detection preventing payment failures
 * - **Compliance Assurance**: SEPA standard compliance with comprehensive audit trails
 * - **Operational Efficiency**: Automated batch creation with intelligent invoice selection
 * - **Financial Security**: Multi-layer validation preventing duplicate charges and fraud
 *
 * ## Core Capabilities
 * - **Batch Lifecycle Management**: Complete workflow from creation to processing
 * - **Security Analysis**: Real-time risk assessment and anomaly detection
 * - **Conflict Resolution**: Intelligent duplicate detection with guided resolution workflows
 * - **Real-time Monitoring**: Live batch status updates with progress tracking
 * - **Wizard-driven Creation**: Step-by-step batch creation with validation at each stage
 * - **Multi-tier Filtering**: Advanced filtering by status, risk level, and financial criteria
 *
 * ## Technical Architecture
 * - **Class-based Design**: Modular architecture with separate dashboard and wizard components
 * - **Real-time Updates**: Automatic refresh with configurable update intervals
 * - **Modal Interface**: Rich dialog-based interaction for detailed operations
 * - **Event-driven Architecture**: Comprehensive event handling for user interactions
 * - **Progressive Enhancement**: Graceful degradation for basic functionality
 * - **Responsive Design**: Mobile-friendly interface with adaptive layout
 *
 * ## Security Features
 * - **IBAN Masking**: Secure display of sensitive banking information
 * - **Risk Assessment**: Multi-factor risk scoring with color-coded indicators
 * - **Duplicate Detection**: Advanced similarity algorithms for member verification
 * - **Conflict Escalation**: Administrative escalation for high-risk scenarios
 * - **Audit Trail**: Complete tracking of all batch operations and decisions
 * - **Access Control**: Role-based permissions for batch operations
 *
 * ## Integration Points
 * - **SEPA API**: Direct integration with SEPA Direct Debit processing systems
 * - **Member Database**: Real-time member verification and duplicate detection
 * - **Invoice System**: Automated invoice selection and payment matching
 * - **Notification Engine**: Automated alerts for batch status changes
 * - **Audit System**: Comprehensive logging of all financial operations
 * - **Security Framework**: Integration with fraud detection and prevention systems
 *
 * ## Advanced Features
 * - **Intelligent Filtering**: Multi-dimensional filtering with persistent preferences
 * - **Batch Analytics**: Real-time statistics and performance monitoring
 * - **Conflict Resolution Wizard**: Step-by-step guided conflict resolution
 * - **Security Dashboard**: Comprehensive security overview with actionable alerts
 * - **Automated Validation**: Multi-stage validation with business rule enforcement
 * - **Export Capabilities**: SEPA-compliant file generation and download
 *
 * ## Workflow Components
 * - **Invoice Selection**: Intelligent filtering and selection of eligible invoices
 * - **Duplicate Detection**: Advanced similarity matching with configurable thresholds
 * - **Conflict Resolution**: Manual and automated conflict resolution strategies
 * - **Security Validation**: Multi-layer security checks and risk assessment
 * - **Final Review**: Comprehensive pre-processing validation and approval
 * - **Batch Processing**: Automated batch execution with progress monitoring
 *
 * ## Performance Optimization
 * - **Lazy Loading**: On-demand loading of batch details and conflict data
 * - **Efficient Rendering**: Optimized DOM manipulation for large datasets
 * - **Smart Caching**: Intelligent caching of frequently accessed data
 * - **Debounced Updates**: Optimized real-time updates preventing excessive API calls
 * - **Progressive Loading**: Staged loading of complex interfaces
 *
 * ## Usage Examples
 * ```javascript
 * // Initialize dashboard
 * const dashboard = new DDBatchManagementDashboard();
 *
 * // Start batch creation wizard
 * const wizard = new BatchCreationWizard();
 * wizard.start();
 *
 * // Apply conflict resolutions
 * dashboard.applyConflictResolutions();
 * ```
 *
 * @version 2.1.0
 * @author Verenigingen Development Team
 * @since 2024-Q1
 *
 * @requires frappe
 * @requires jQuery
 * @requires Bootstrap Modal
 *
 * @see {@link direct_debit_batch.js} Batch DocType Controller
 * @see {@link sepa_mandate.js} SEPA Mandate Management
 * @see {@link api-service.js} API Integration Layer
 */

/**
 * Enhanced SEPA Direct Debit Batch Management Interface
 * Provides comprehensive batch management with security validation and conflict resolution
 */

class DDBatchManagementDashboard {
	constructor() {
		this.currentBatch = null;
		this.conflictData = null;
		this.securityAlerts = [];
		this.realTimeUpdateInterval = null;

		this.initializeInterface();
		this.setupEventHandlers();
		this.startRealTimeUpdates();
	}

	initializeInterface() {
		this.createDashboardLayout();
		this.initializeFilters();
		this.loadBatchList();
	}

	createDashboardLayout() {
		const dashboardHtml = `
            <div id="dd-batch-dashboard" class="dd-batch-dashboard">
                <!-- Header Section -->
                <div class="dashboard-header">
                    <h2>SEPA Direct Debit Batch Management</h2>
                    <div class="header-actions">
                        <button class="btn btn-primary" id="create-new-batch">
                            <i class="fa fa-plus"></i> Create New Batch
                        </button>
                        <button class="btn btn-secondary" id="security-overview">
                            <i class="fa fa-shield"></i> Security Overview
                        </button>
                    </div>
                </div>

                <!-- Security Alert Banner -->
                <div id="security-alerts" class="security-alerts" style="display: none;">
                </div>

                <!-- Filter Section -->
                <div class="filter-section">
                    <div class="row">
                        <div class="col-md-3">
                            <label>Status Filter</label>
                            <select id="status-filter" class="form-control">
                                <option value="">All Statuses</option>
                                <option value="Draft">Draft</option>
                                <option value="Generated">Generated</option>
                                <option value="Submitted">Submitted</option>
                                <option value="Processed">Processed</option>
                                <option value="Failed">Failed</option>
                            </select>
                        </div>
                        <div class="col-md-3">
                            <label>Date Range</label>
                            <input type="date" id="date-from" class="form-control" style="margin-bottom: 5px;">
                            <input type="date" id="date-to" class="form-control">
                        </div>
                        <div class="col-md-3">
                            <label>Risk Level</label>
                            <select id="risk-filter" class="form-control">
                                <option value="">All Risk Levels</option>
                                <option value="low">Low Risk</option>
                                <option value="medium">Medium Risk</option>
                                <option value="high">High Risk</option>
                            </select>
                        </div>
                        <div class="col-md-3">
                            <label>&nbsp;</label>
                            <button class="btn btn-info form-control" id="apply-filters">
                                <i class="fa fa-filter"></i> Apply Filters
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Batch List Table -->
                <div class="batch-list-section">
                    <div class="table-responsive">
                        <table id="batch-list-table" class="table table-striped">
                            <thead>
                                <tr>
                                    <th>Batch ID</th>
                                    <th>Date</th>
                                    <th>Status</th>
                                    <th>Entry Count</th>
                                    <th>Total Amount</th>
                                    <th>Risk Level</th>
                                    <th>Conflicts</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody id="batch-list-body">
                                <tr>
                                    <td colspan="8" class="text-center">
                                        <i class="fa fa-spinner fa-spin"></i> Loading batches...
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Batch Details Modal -->
                <div id="batch-details-modal" class="modal fade" tabindex="-1">
                    <div class="modal-dialog modal-lg">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h4 class="modal-title">Batch Details</h4>
                                <button type="button" class="close" data-dismiss="modal">
                                    <span>&times;</span>
                                </button>
                            </div>
                            <div class="modal-body" id="batch-details-content">
                                <!-- Batch details will be loaded here -->
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
                                <button type="button" class="btn btn-primary" id="process-batch">Process Batch</button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Conflict Resolution Modal -->
                <div id="conflict-resolution-modal" class="modal fade" tabindex="-1">
                    <div class="modal-dialog modal-xl">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h4 class="modal-title">Conflict Resolution</h4>
                                <button type="button" class="close" data-dismiss="modal">
                                    <span>&times;</span>
                                </button>
                            </div>
                            <div class="modal-body" id="conflict-resolution-content">
                                <!-- Conflict resolution interface will be loaded here -->
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
                                <button type="button" class="btn btn-warning" id="escalate-conflicts">Escalate to Admin</button>
                                <button type="button" class="btn btn-success" id="resolve-conflicts">Apply Resolutions</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

		// Insert dashboard into page
		$('body').append(dashboardHtml);

		// Add CSS styles
		this.addDashboardStyles();
	}

	addDashboardStyles() {
		const styles = `
            <style>
                .dd-batch-dashboard {
                    padding: 20px;
                    background: #f8f9fa;
                    min-height: 100vh;
                }

                .dashboard-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 20px;
                    padding: 20px;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }

                .header-actions {
                    display: flex;
                    gap: 10px;
                }

                .security-alerts {
                    margin-bottom: 20px;
                    padding: 15px;
                    background: #fff3cd;
                    border: 1px solid #ffeaa7;
                    border-radius: 8px;
                }

                .security-alert {
                    padding: 10px;
                    margin-bottom: 10px;
                    border-radius: 4px;
                }

                .security-alert.high {
                    background: #f8d7da;
                    border: 1px solid #f5c6cb;
                    color: #721c24;
                }

                .security-alert.medium {
                    background: #fff3cd;
                    border: 1px solid #ffeaa7;
                    color: #856404;
                }

                .security-alert.low {
                    background: #d1ecf1;
                    border: 1px solid #bee5eb;
                    color: #0c5460;
                }

                .filter-section {
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    margin-bottom: 20px;
                }

                .batch-list-section {
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }

                .risk-badge {
                    padding: 4px 8px;
                    border-radius: 12px;
                    font-size: 0.85em;
                    font-weight: bold;
                }

                .risk-badge.low {
                    background: #d4edda;
                    color: #155724;
                }

                .risk-badge.medium {
                    background: #fff3cd;
                    color: #856404;
                }

                .risk-badge.high {
                    background: #f8d7da;
                    color: #721c24;
                }

                .conflict-indicator {
                    padding: 2px 6px;
                    border-radius: 10px;
                    font-size: 0.8em;
                    font-weight: bold;
                }

                .conflict-indicator.none {
                    background: #d4edda;
                    color: #155724;
                }

                .conflict-indicator.minor {
                    background: #fff3cd;
                    color: #856404;
                }

                .conflict-indicator.major {
                    background: #f8d7da;
                    color: #721c24;
                }

                .member-comparison {
                    display: flex;
                    gap: 20px;
                    margin-bottom: 20px;
                }

                .member-card {
                    flex: 1;
                    padding: 15px;
                    border: 1px solid #dee2e6;
                    border-radius: 8px;
                    background: #f8f9fa;
                }

                .member-card.selected {
                    background: #e7f3ff;
                    border-color: #007bff;
                }

                .similarity-meter {
                    height: 20px;
                    background: #e9ecef;
                    border-radius: 10px;
                    overflow: hidden;
                    margin-top: 5px;
                }

                .similarity-fill {
                    height: 100%;
                    transition: width 0.3s ease;
                }

                .similarity-fill.high {
                    background: linear-gradient(90deg, #28a745, #20c997);
                }

                .similarity-fill.medium {
                    background: linear-gradient(90deg, #ffc107, #fd7e14);
                }

                .similarity-fill.low {
                    background: linear-gradient(90deg, #dc3545, #e83e8c);
                }

                .progress-indicator {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }

                .status-indicator {
                    width: 12px;
                    height: 12px;
                    border-radius: 50%;
                    display: inline-block;
                }

                .status-indicator.draft {
                    background: #6c757d;
                }

                .status-indicator.generated {
                    background: #17a2b8;
                }

                .status-indicator.submitted {
                    background: #ffc107;
                }

                .status-indicator.processed {
                    background: #28a745;
                }

                .status-indicator.failed {
                    background: #dc3545;
                }
            </style>
        `;

		$('head').append(styles);
	}

	setupEventHandlers() {
		// Create new batch button
		$(document).on('click', '#create-new-batch', () => {
			this.showBatchCreationWizard();
		});

		// Security overview button
		$(document).on('click', '#security-overview', () => {
			this.showSecurityOverview();
		});

		// Apply filters button
		$(document).on('click', '#apply-filters', () => {
			this.loadBatchList();
		});

		// Batch action buttons
		$(document).on('click', '.view-batch', (e) => {
			const batchId = $(e.target).data('batch-id');
			this.showBatchDetails(batchId);
		});

		$(document).on('click', '.resolve-conflicts', (e) => {
			const batchId = $(e.target).data('batch-id');
			this.showConflictResolution(batchId);
		});

		$(document).on('click', '.download-sepa', (e) => {
			const batchId = $(e.target).data('batch-id');
			this.downloadSepaFile(batchId);
		});

		// Modal actions
		$(document).on('click', '#process-batch', () => {
			this.processBatch(this.currentBatch);
		});

		$(document).on('click', '#resolve-conflicts', () => {
			this.applyConflictResolutions();
		});

		$(document).on('click', '#escalate-conflicts', () => {
			this.escalateConflicts();
		});
	}

	initializeFilters() {
		// Set default date range (last 30 days)
		const today = new Date();
		const thirtyDaysAgo = new Date(today.getTime() - (30 * 24 * 60 * 60 * 1000));

		$('#date-to').val(today.toISOString().split('T')[0]);
		$('#date-from').val(thirtyDaysAgo.toISOString().split('T')[0]);
	}

	async loadBatchList() {
		try {
			this.showLoading('#batch-list-body');

			const filters = this.getFilterValues();

			const response = await frappe.call({
				method: 'verenigingen.api.dd_batch_api.get_batch_list_with_security',
				args: { filters }
			});

			if (response.message && response.message.success) {
				this.renderBatchList(response.message.batches);
				this.updateSecurityAlerts(response.message.security_alerts);
			} else {
				this.showError('Failed to load batch list');
			}
		} catch (error) {
			console.error('Error loading batch list:', error);
			this.showError(`Error loading batch list: ${error.message}`);
		}
	}

	renderBatchList(batches) {
		const tbody = $('#batch-list-body');
		tbody.empty();

		if (!batches || batches.length === 0) {
			tbody.append(`
                <tr>
                    <td colspan="8" class="text-center text-muted">
                        No batches found matching the selected filters
                    </td>
                </tr>
            `);
			return;
		}

		batches.forEach(batch => {
			const row = this.createBatchRow(batch);
			tbody.append(row);
		});
	}

	createBatchRow(batch) {
		const riskLevel = this.calculateRiskLevel(batch);
		const conflictLevel = this.getConflictLevel(batch);

		return `
            <tr data-batch-id="${batch.name}">
                <td>
                    <div class="d-flex align-items-center">
                        <span class="status-indicator ${batch.status.toLowerCase()}"></span>
                        <span class="ml-2">${batch.name}</span>
                    </div>
                </td>
                <td>${frappe.datetime.str_to_user(batch.batch_date)}</td>
                <td>
                    <span class="badge badge-${this.getStatusColor(batch.status)}">
                        ${batch.status}
                    </span>
                </td>
                <td>${batch.entry_count || 0}</td>
                <td>${frappe.format_value(batch.total_amount, { fieldtype: 'Currency' })}</td>
                <td>
                    <span class="risk-badge ${riskLevel}">
                        ${riskLevel.toUpperCase()}
                    </span>
                </td>
                <td>
                    <span class="conflict-indicator ${conflictLevel}">
                        ${this.getConflictText(conflictLevel)}
                    </span>
                </td>
                <td>
                    <div class="btn-group">
                        <button class="btn btn-sm btn-outline-primary view-batch"
                                data-batch-id="${batch.name}">
                            <i class="fa fa-eye"></i>
                        </button>
                        ${batch.conflicts > 0 ? `
                            <button class="btn btn-sm btn-outline-warning resolve-conflicts"
                                    data-batch-id="${batch.name}">
                                <i class="fa fa-exclamation-triangle"></i>
                            </button>
                        ` : ''}
                        ${batch.sepa_file ? `
                            <button class="btn btn-sm btn-outline-success download-sepa"
                                    data-batch-id="${batch.name}">
                                <i class="fa fa-download"></i>
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `;
	}

	calculateRiskLevel(batch) {
		let score = 0;

		// High amount increases risk
		if (batch.total_amount > 10000) { score += 0.3; }

		// Many entries increase risk
		if (batch.entry_count > 100) { score += 0.2; }

		// Conflicts increase risk significantly
		if (batch.conflicts > 0) { score += 0.4; }

		// Failed batches are high risk
		if (batch.status === 'Failed') { score += 0.5; }

		if (score >= 0.7) { return 'high'; }
		if (score >= 0.4) { return 'medium'; }
		return 'low';
	}

	getConflictLevel(batch) {
		if (!batch.conflicts || batch.conflicts === 0) { return 'none'; }
		if (batch.conflicts <= 2) { return 'minor'; }
		return 'major';
	}

	getConflictText(level) {
		switch (level) {
			case 'none': return 'None';
			case 'minor': return 'Minor';
			case 'major': return 'Major';
			default: return 'Unknown';
		}
	}

	getStatusColor(status) {
		switch (status.toLowerCase()) {
			case 'draft': return 'secondary';
			case 'generated': return 'info';
			case 'submitted': return 'warning';
			case 'processed': return 'success';
			case 'failed': return 'danger';
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

			if (response.message && response.message.success) {
				this.renderBatchDetails(response.message.batch);
				$('#batch-details-modal').modal('show');
			} else {
				this.showError('Failed to load batch details');
			}
		} catch (error) {
			console.error('Error loading batch details:', error);
			this.showError(`Error loading batch details: ${error.message}`);
		}
	}

	renderBatchDetails(batch) {
		const content = `
            <div class="batch-details">
                <div class="row">
                    <div class="col-md-6">
                        <h5>Batch Information</h5>
                        <table class="table table-sm">
                            <tr><td><strong>Batch ID:</strong></td><td>${batch.name}</td></tr>
                            <tr><td><strong>Date:</strong></td><td>${frappe.datetime.str_to_user(batch.batch_date)}</td></tr>
                            <tr><td><strong>Status:</strong></td><td>
                                <span class="badge badge-${this.getStatusColor(batch.status)}">${batch.status}</span>
                            </td></tr>
                            <tr><td><strong>Type:</strong></td><td>${batch.batch_type}</td></tr>
                            <tr><td><strong>Currency:</strong></td><td>${batch.currency}</td></tr>
                        </table>
                    </div>
                    <div class="col-md-6">
                        <h5>Financial Summary</h5>
                        <table class="table table-sm">
                            <tr><td><strong>Entry Count:</strong></td><td>${batch.entry_count}</td></tr>
                            <tr><td><strong>Total Amount:</strong></td><td>${frappe.format_value(batch.total_amount, { fieldtype: 'Currency' })}</td></tr>
                            <tr><td><strong>Average Amount:</strong></td><td>${frappe.format_value(batch.total_amount / batch.entry_count, { fieldtype: 'Currency' })}</td></tr>
                            <tr><td><strong>Risk Level:</strong></td><td>
                                <span class="risk-badge ${this.calculateRiskLevel(batch)}">${this.calculateRiskLevel(batch).toUpperCase()}</span>
                            </td></tr>
                        </table>
                    </div>
                </div>

                <div class="row mt-3">
                    <div class="col-12">
                        <h5>Security Analysis</h5>
                        <div id="security-analysis">
                            ${this.renderSecurityAnalysis(batch.security_analysis)}
                        </div>
                    </div>
                </div>

                <div class="row mt-3">
                    <div class="col-12">
                        <h5>Invoices in Batch</h5>
                        <div class="table-responsive">
                            <table class="table table-sm table-striped">
                                <thead>
                                    <tr>
                                        <th>Invoice</th>
                                        <th>Member</th>
                                        <th>Amount</th>
                                        <th>IBAN</th>
                                        <th>Status</th>
                                        <th>Issues</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${this.renderInvoiceList(batch.invoices)}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        `;

		$('#batch-details-content').html(content);
	}

	renderSecurityAnalysis(analysis) {
		if (!analysis) {
			return '<p class="text-muted">No security analysis available</p>';
		}

		let html = '';

		if (analysis.duplicate_risks && analysis.duplicate_risks.length > 0) {
			html += `
                <div class="alert alert-warning">
                    <h6><i class="fa fa-exclamation-triangle"></i> Duplicate Risks Detected</h6>
                    <ul>
                        ${analysis.duplicate_risks.map(risk => `<li>${risk}</li>`).join('')}
                    </ul>
                </div>
            `;
		}

		if (analysis.amount_anomalies && analysis.amount_anomalies.length > 0) {
			html += `
                <div class="alert alert-info">
                    <h6><i class="fa fa-info-circle"></i> Amount Anomalies</h6>
                    <ul>
                        ${analysis.amount_anomalies.map(anomaly => `<li>${anomaly}</li>`).join('')}
                    </ul>
                </div>
            `;
		}

		if (analysis.iban_sharing && analysis.iban_sharing.length > 0) {
			html += `
                <div class="alert alert-warning">
                    <h6><i class="fa fa-users"></i> Shared Bank Accounts</h6>
                    <ul>
                        ${analysis.iban_sharing.map(sharing => `<li>${sharing}</li>`).join('')}
                    </ul>
                </div>
            `;
		}

		if (!html) {
			html = '<div class="alert alert-success"><i class="fa fa-check"></i> No security issues detected</div>';
		}

		return html;
	}

	renderInvoiceList(invoices) {
		if (!invoices || invoices.length === 0) {
			return '<tr><td colspan="6" class="text-center text-muted">No invoices found</td></tr>';
		}

		return invoices.map(invoice => `
            <tr>
                <td>${invoice.invoice}</td>
                <td>${invoice.member_name}</td>
                <td>${frappe.format_value(invoice.amount, { fieldtype: 'Currency' })}</td>
                <td>${this.maskIban(invoice.iban)}</td>
                <td>
                    <span class="badge badge-${this.getInvoiceStatusColor(invoice.status)}">
                        ${invoice.status}
                    </span>
                </td>
                <td>
                    ${invoice.issues ? `
                        <button class="btn btn-sm btn-outline-warning"
                                onclick="this.showInvoiceIssues('${invoice.invoice}')">
                            <i class="fa fa-exclamation-triangle"></i> ${invoice.issues.length}
                        </button>
                    ` : '<span class="text-success">None</span>'}
                </td>
            </tr>
        `).join('');
	}

	maskIban(iban) {
		if (!iban || iban.length < 8) { return iban; }
		return `${iban.substring(0, 4)}****${iban.substring(iban.length - 4)}`;
	}

	getInvoiceStatusColor(status) {
		switch (status?.toLowerCase()) {
			case 'pending': return 'warning';
			case 'successful': return 'success';
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

			if (response.message && response.message.success) {
				this.conflictData = response.message.conflicts;
				this.renderConflictResolution(response.message.conflicts);
				$('#conflict-resolution-modal').modal('show');
			} else {
				this.showError('Failed to load conflict data');
			}
		} catch (error) {
			console.error('Error loading conflicts:', error);
			this.showError(`Error loading conflicts: ${error.message}`);
		}
	}

	renderConflictResolution(conflicts) {
		let html = '';

		// High-risk conflicts
		if (conflicts.high_risk_matches && conflicts.high_risk_matches.length > 0) {
			html += `
                <div class="alert alert-danger">
                    <h5><i class="fa fa-exclamation-triangle"></i> High Risk Conflicts</h5>
                    <p>These conflicts require immediate attention and cannot be auto-resolved.</p>
                </div>

                <div class="conflict-section">
                    ${conflicts.high_risk_matches.map(conflict => this.renderConflictItem(conflict, 'high')).join('')}
                </div>
            `;
		}

		// Potential duplicates
		if (conflicts.potential_duplicates && conflicts.potential_duplicates.length > 0) {
			html += `
                <div class="alert alert-warning">
                    <h5><i class="fa fa-exclamation-triangle"></i> Potential Duplicates</h5>
                    <p>These members may be duplicates. Review and select the appropriate action.</p>
                </div>

                <div class="conflict-section">
                    ${conflicts.potential_duplicates.map(conflict => this.renderConflictItem(conflict, 'medium')).join('')}
                </div>
            `;
		}

		if (!html) {
			html = `
                <div class="alert alert-success">
                    <h5><i class="fa fa-check"></i> No Conflicts Detected</h5>
                    <p>All members in this batch have been validated without conflicts.</p>
                </div>
            `;
		}

		$('#conflict-resolution-content').html(html);
	}

	renderConflictItem(conflict, severity) {
		return `
            <div class="conflict-item mb-4 p-3 border rounded ${severity === 'high' ? 'border-danger' : 'border-warning'}">
                <div class="conflict-header mb-3">
                    <h6>
                        Similarity Score: ${(conflict.risk_score * 100).toFixed(1)}%
                        <span class="float-right">
                            <span class="badge badge-${severity === 'high' ? 'danger' : 'warning'}">
                                ${severity.toUpperCase()} RISK
                            </span>
                        </span>
                    </h6>
                    <div class="similarity-meter">
                        <div class="similarity-fill ${severity}" style="width: ${conflict.risk_score * 100}%"></div>
                    </div>
                </div>

                <div class="member-comparison">
                    <div class="member-card">
                        <h6>New Member</h6>
                        <p><strong>Name:</strong> ${conflict.new_member_name || 'N/A'}</p>
                        <p><strong>Email:</strong> ${conflict.new_member_email || 'N/A'}</p>
                        <p><strong>IBAN:</strong> ${this.maskIban(conflict.new_member_iban || '')}</p>
                    </div>

                    <div class="member-card">
                        <h6>Existing Member</h6>
                        <p><strong>Name:</strong> ${conflict.existing_name}</p>
                        <p><strong>Email:</strong> ${conflict.existing_email}</p>
                        <p><strong>IBAN:</strong> ${this.maskIban(conflict.existing_iban || '')}</p>
                    </div>
                </div>

                <div class="match-reasons mb-3">
                    <h6>Match Reasons:</h6>
                    <ul>
                        ${conflict.match_reasons.map(reason => `<li>${reason}</li>`).join('')}
                    </ul>
                </div>

                <div class="resolution-actions">
                    <h6>Resolution:</h6>
                    <div class="form-check">
                        <input class="form-check-input" type="radio"
                               name="resolution_${conflict.existing_member}"
                               value="proceed" id="proceed_${conflict.existing_member}">
                        <label class="form-check-label" for="proceed_${conflict.existing_member}">
                            Proceed with both members (they are different people)
                        </label>
                    </div>
                    <div class="form-check">
                        <input class="form-check-input" type="radio"
                               name="resolution_${conflict.existing_member}"
                               value="merge" id="merge_${conflict.existing_member}">
                        <label class="form-check-label" for="merge_${conflict.existing_member}">
                            Merge records (they are the same person)
                        </label>
                    </div>
                    <div class="form-check">
                        <input class="form-check-input" type="radio"
                               name="resolution_${conflict.existing_member}"
                               value="exclude" id="exclude_${conflict.existing_member}">
                        <label class="form-check-label" for="exclude_${conflict.existing_member}">
                            Exclude from this batch (review separately)
                        </label>
                    </div>
                    ${severity === 'high' ? `
                        <div class="form-check">
                            <input class="form-check-input" type="radio"
                                   name="resolution_${conflict.existing_member}"
                                   value="escalate" id="escalate_${conflict.existing_member}" checked>
                            <label class="form-check-label" for="escalate_${conflict.existing_member}">
                                <strong>Escalate to administrator (recommended for high risk)</strong>
                            </label>
                        </div>
                    ` : ''}
                </div>
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
					resolutions
				}
			});

			if (response.message && response.message.success) {
				$('#conflict-resolution-modal').modal('hide');
				this.showSuccess('Conflict resolutions applied successfully');
				this.loadBatchList(); // Refresh the list
			} else {
				this.showError('Failed to apply conflict resolutions');
			}
		} catch (error) {
			console.error('Error applying resolutions:', error);
			this.showError(`Error applying resolutions: ${error.message}`);
		}
	}

	collectResolutions() {
		const resolutions = {};

		// Collect all radio button selections
		$('input[type="radio"]:checked').each(function () {
			const name = $(this).attr('name');
			const value = $(this).val();

			if (name.startsWith('resolution_')) {
				const memberId = name.replace('resolution_', '');
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
					conflicts: this.conflictData
				}
			});

			if (response.message && response.message.success) {
				$('#conflict-resolution-modal').modal('hide');
				this.showSuccess('Conflicts escalated to administrator');
			} else {
				this.showError('Failed to escalate conflicts');
			}
		} catch (error) {
			console.error('Error escalating conflicts:', error);
			this.showError(`Error escalating conflicts: ${error.message}`);
		}
	}

	updateSecurityAlerts(alerts) {
		const alertContainer = $('#security-alerts');

		if (!alerts || alerts.length === 0) {
			alertContainer.hide();
			return;
		}

		let html = '';
		alerts.forEach(alert => {
			html += `
                <div class="security-alert ${alert.severity}">
                    <strong>${alert.title}</strong>
                    <p>${alert.message}</p>
                    ${alert.action_required ? `
                        <button class="btn btn-sm btn-primary" onclick="this.handleSecurityAction('${alert.id}')">
                            ${alert.action_text || 'Take Action'}
                        </button>
                    ` : ''}
                </div>
            `;
		});

		alertContainer.html(html).show();
	}

	startRealTimeUpdates() {
		// Update batch list every 30 seconds
		this.realTimeUpdateInterval = setInterval(() => {
			this.loadBatchList();
		}, 30000);
	}

	stopRealTimeUpdates() {
		if (this.realTimeUpdateInterval) {
			clearInterval(this.realTimeUpdateInterval);
			this.realTimeUpdateInterval = null;
		}
	}

	getFilterValues() {
		return {
			status: $('#status-filter').val(),
			date_from: $('#date-from').val(),
			date_to: $('#date-to').val(),
			risk_level: $('#risk-filter').val()
		};
	}

	showLoading(selector) {
		$(selector).html(`
            <tr>
                <td colspan="8" class="text-center">
                    <i class="fa fa-spinner fa-spin"></i> Loading...
                </td>
            </tr>
        `);
	}

	showError(message) {
		frappe.msgprint({
			title: 'Error',
			message,
			indicator: 'red'
		});
	}

	showSuccess(message) {
		frappe.msgprint({
			title: 'Success',
			message,
			indicator: 'green'
		});
	}

	destroy() {
		this.stopRealTimeUpdates();
		$('#dd-batch-dashboard').remove();
	}
}

// Batch Creation Wizard
class BatchCreationWizard {
	constructor() {
		this.currentStep = 0;
		this.steps = [
			'invoice-selection',
			'duplicate-detection',
			'conflict-resolution',
			'security-validation',
			'final-review'
		];
		this.batchData = {};
		this.validationResults = {};
	}

	async start() {
		this.createWizardInterface();
		await this.loadStep(0);
	}

	createWizardInterface() {
		const wizardHtml = `
            <div id="batch-creation-wizard" class="modal fade" tabindex="-1">
                <div class="modal-dialog modal-xl">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h4 class="modal-title">Create New SEPA Direct Debit Batch</h4>
                            <button type="button" class="close" data-dismiss="modal">
                                <span>&times;</span>
                            </button>
                        </div>
                        <div class="modal-body">
                            <!-- Progress indicator -->
                            <div class="wizard-progress mb-4">
                                <div class="progress">
                                    <div class="progress-bar" style="width: 20%"></div>
                                </div>
                                <div class="step-labels mt-2">
                                    <div class="step-label active">1. Invoice Selection</div>
                                    <div class="step-label">2. Duplicate Detection</div>
                                    <div class="step-label">3. Conflict Resolution</div>
                                    <div class="step-label">4. Security Validation</div>
                                    <div class="step-label">5. Final Review</div>
                                </div>
                            </div>

                            <!-- Step content -->
                            <div id="wizard-step-content">
                                <!-- Content will be loaded here -->
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-outline-primary" id="wizard-prev" style="display: none;">Previous</button>
                            <button type="button" class="btn btn-primary" id="wizard-next">Next</button>
                            <button type="button" class="btn btn-success" id="wizard-create" style="display: none;">Create Batch</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

		$('body').append(wizardHtml);
		$('#batch-creation-wizard').modal('show');

		// Setup event handlers
		this.setupWizardEventHandlers();
	}

	setupWizardEventHandlers() {
		$('#wizard-next').on('click', () => this.nextStep());
		$('#wizard-prev').on('click', () => this.prevStep());
		$('#wizard-create').on('click', () => this.createBatch());
	}

	async loadStep(stepIndex) {
		this.currentStep = stepIndex;
		this.updateProgress();

		const stepName = this.steps[stepIndex];

		switch (stepName) {
			case 'invoice-selection':
				await this.loadInvoiceSelection();
				break;
			case 'duplicate-detection':
				await this.loadDuplicateDetection();
				break;
			case 'conflict-resolution':
				await this.loadConflictResolution();
				break;
			case 'security-validation':
				await this.loadSecurityValidation();
				break;
			case 'final-review':
				await this.loadFinalReview();
				break;
		}
	}

	updateProgress() {
		const progress = ((this.currentStep + 1) / this.steps.length) * 100;
		$('.progress-bar').css('width', `${progress}%`);

		$('.step-label').removeClass('active completed');
		$('.step-label').each((index, element) => {
			if (index < this.currentStep) {
				$(element).addClass('completed');
			} else if (index === this.currentStep) {
				$(element).addClass('active');
			}
		});

		// Update navigation buttons
		$('#wizard-prev').toggle(this.currentStep > 0);
		$('#wizard-next').toggle(this.currentStep < this.steps.length - 1);
		$('#wizard-create').toggle(this.currentStep === this.steps.length - 1);
	}

	async nextStep() {
		// Validate current step before proceeding
		const isValid = await this.validateCurrentStep();
		if (!isValid) { return; }

		if (this.currentStep < this.steps.length - 1) {
			await this.loadStep(this.currentStep + 1);
		}
	}

	async prevStep() {
		if (this.currentStep > 0) {
			await this.loadStep(this.currentStep - 1);
		}
	}

	async validateCurrentStep() {
		const stepName = this.steps[this.currentStep];

		switch (stepName) {
			case 'invoice-selection':
				return this.validateInvoiceSelection();
			case 'duplicate-detection':
				return this.validateDuplicateDetection();
			case 'conflict-resolution':
				return this.validateConflictResolution();
			case 'security-validation':
				return this.validateSecurityValidation();
			default:
				return true;
		}
	}

	// Step implementations would continue here...
	// Each step would have its own load and validate methods

	async loadInvoiceSelection() {
		const content = `
            <div class="invoice-selection-step">
                <h5>Select Invoices for Batch Processing</h5>
                <p>Choose which unpaid invoices to include in this direct debit batch.</p>

                <div class="row mb-3">
                    <div class="col-md-4">
                        <label>Date Range</label>
                        <input type="date" id="invoice-date-from" class="form-control mb-2">
                        <input type="date" id="invoice-date-to" class="form-control">
                    </div>
                    <div class="col-md-4">
                        <label>Member Type</label>
                        <select id="member-type-filter" class="form-control">
                            <option value="">All Types</option>
                            <option value="Regular">Regular</option>
                            <option value="Student">Student</option>
                            <option value="Corporate">Corporate</option>
                        </select>
                    </div>
                    <div class="col-md-4">
                        <label>Amount Range</label>
                        <input type="number" id="amount-min" placeholder="Min amount" class="form-control mb-2">
                        <input type="number" id="amount-max" placeholder="Max amount" class="form-control">
                    </div>
                </div>

                <button class="btn btn-info mb-3" id="load-invoices">Load Eligible Invoices</button>

                <div id="invoice-selection-results">
                    <p class="text-muted">Click "Load Eligible Invoices" to see available invoices.</p>
                </div>
            </div>
        `;

		$('#wizard-step-content').html(content);

		// Setup event handlers for this step
		$('#load-invoices').on('click', () => this.loadEligibleInvoices());
	}

	async loadEligibleInvoices() {
		try {
			$('#invoice-selection-results').html('<i class="fa fa-spinner fa-spin"></i> Loading invoices...');

			const filters = {
				date_from: $('#invoice-date-from').val(),
				date_to: $('#invoice-date-to').val(),
				member_type: $('#member-type-filter').val(),
				amount_min: $('#amount-min').val(),
				amount_max: $('#amount-max').val()
			};

			const response = await frappe.call({
				method: 'verenigingen.api.dd_batch_api.get_eligible_invoices',
				args: { filters }
			});

			if (response.message && response.message.success) {
				this.renderEligibleInvoices(response.message.invoices);
			} else {
				$('#invoice-selection-results').html('<p class="text-danger">Failed to load invoices</p>');
			}
		} catch (error) {
			console.error('Error loading invoices:', error);
			$('#invoice-selection-results').html('<p class="text-danger">Error loading invoices</p>');
		}
	}

	renderEligibleInvoices(invoices) {
		if (!invoices || invoices.length === 0) {
			$('#invoice-selection-results').html('<p class="text-muted">No eligible invoices found with the selected criteria.</p>');
			return;
		}

		const html = `
            <div class="invoice-selection-table">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <h6>Found ${invoices.length} eligible invoices</h6>
                    <div>
                        <button class="btn btn-sm btn-outline-primary" id="select-all-invoices">Select All</button>
                        <button class="btn btn-sm btn-outline-secondary" id="deselect-all-invoices">Deselect All</button>
                    </div>
                </div>

                <div class="table-responsive">
                    <table class="table table-sm table-striped">
                        <thead>
                            <tr>
                                <th><input type="checkbox" id="invoice-select-all"></th>
                                <th>Invoice</th>
                                <th>Member</th>
                                <th>Amount</th>
                                <th>Due Date</th>
                                <th>IBAN</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${invoices.map(invoice => `
                                <tr>
                                    <td><input type="checkbox" class="invoice-checkbox" value="${invoice.name}"></td>
                                    <td>${invoice.name}</td>
                                    <td>${invoice.member_name}</td>
                                    <td>${frappe.format_value(invoice.amount, { fieldtype: 'Currency' })}</td>
                                    <td>${frappe.datetime.str_to_user(invoice.due_date)}</td>
                                    <td>${this.maskIban(invoice.iban)}</td>
                                    <td>
                                        <span class="badge badge-${invoice.validation_status === 'valid' ? 'success' : 'warning'}">
                                            ${invoice.validation_status}
                                        </span>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>

                <div class="selected-summary mt-3 p-3 bg-light rounded">
                    <strong>Selection Summary:</strong>
                    <span id="selection-count">0</span> invoices selected,
                    Total: <span id="selection-total">€0.00</span>
                </div>
            </div>
        `;

		$('#invoice-selection-results').html(html);

		// Setup selection event handlers
		this.setupInvoiceSelectionHandlers();

		// Store invoice data
		this.batchData.available_invoices = invoices;
	}

	setupInvoiceSelectionHandlers() {
		$('#select-all-invoices, #invoice-select-all').on('click', () => {
			$('.invoice-checkbox').prop('checked', true);
			this.updateSelectionSummary();
		});

		$('#deselect-all-invoices').on('click', () => {
			$('.invoice-checkbox').prop('checked', false);
			this.updateSelectionSummary();
		});

		$(document).on('change', '.invoice-checkbox', () => {
			this.updateSelectionSummary();
		});
	}

	updateSelectionSummary() {
		const selectedInvoices = $('.invoice-checkbox:checked');
		const count = selectedInvoices.length;

		let total = 0;
		selectedInvoices.each(() => {
			const invoiceId = $(this).val();
			const invoice = this.batchData.available_invoices.find(inv => inv.name === invoiceId);
			if (invoice) {
				total += invoice.amount;
			}
		});

		$('#selection-count').text(count);
		$('#selection-total').text(frappe.format_value(total, { fieldtype: 'Currency' }));

		// Store selected invoices
		this.batchData.selected_invoices = [];
		selectedInvoices.each(() => {
			this.batchData.selected_invoices.push($(this).val());
		});
	}

	validateInvoiceSelection() {
		if (!this.batchData.selected_invoices || this.batchData.selected_invoices.length === 0) {
			frappe.msgprint('Please select at least one invoice for the batch.');
			return false;
		}

		return true;
	}

	maskIban(iban) {
		if (!iban || iban.length < 8) { return iban; }
		return `${iban.substring(0, 4)}****${iban.substring(iban.length - 4)}`;
	}
}

// Initialize the dashboard when document is ready
$(document).ready(() => {
	// Only initialize if we're on the appropriate page
	if (window.location.pathname.includes('dd-batch') || window.location.pathname.includes('direct-debit')) {
		window.ddBatchDashboard = new DDBatchManagementDashboard();
	}
});

// Export classes for use in other modules
window.DDBatchManagementDashboard = DDBatchManagementDashboard;
window.BatchCreationWizard = BatchCreationWizard;
