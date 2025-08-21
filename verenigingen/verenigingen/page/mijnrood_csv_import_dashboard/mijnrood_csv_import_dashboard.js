/**
 * @fileoverview Mijnrood CSV Import Dashboard Page for Verenigingen Association Management
 *
 * This page provides a user-friendly interface for importing member data from CSV files
 * with preview, validation, and guided import workflow.
 *
 * @author Verenigingen Development Team
 * @version 2025-08-14
 * @since 1.0.0
 */

frappe.pages['mijnrood-csv-import-dashboard'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Mijnrood CSV Import',
		single_column: true
	});

	const member_import = new MijnroodCSVImportPage(page);
	member_import.make();
};

class MijnroodCSVImportPage {
	constructor(page) {
		this.page = page;
		this.wrapper = this.page.main;
	}

	make() {
		this.make_header();
		this.make_import_section();
		this.make_recent_imports();
		this.setup_actions();
	}

	make_header() {
		const header_html = `
            <div class="member-import-header mb-4">
                <div class="row">
                    <div class="col-md-8">
                        <h3>Mijnrood CSV Import</h3>
                        <p class="text-muted">
                            Import member data from CSV files with validation and preview.
                            Use test mode to validate your data before creating records.
                        </p>
                    </div>
                    <div class="col-md-4 text-right">
                        <button class="btn btn-primary btn-sm" id="new-import-btn">
                            <i class="fa fa-plus"></i> New Import
                        </button>
                        <button class="btn btn-default btn-sm" id="download-template-btn">
                            <i class="fa fa-download"></i> Download Template
                        </button>
                    </div>
                </div>
            </div>
        `;
		$(this.wrapper).append(header_html);
	}

	make_import_section() {
		const import_html = `
            <div class="member-import-section">
                <div class="row">
                    <div class="col-md-12">
                        <div class="card">
                            <div class="card-header">
                                <h5>Quick Import Guide</h5>
                            </div>
                            <div class="card-body">
                                <div class="row">
                                    <div class="col-md-6">
                                        <h6>Expected CSV Format:</h6>
                                        <p class="small text-muted">Your CSV should contain these columns (Dutch headers are automatically mapped):</p>
                                        <div class="field-mapping-list">
                                            <small>
                                                <strong>Lidnr.</strong> → Member ID<br>
                                                <strong>Voornaam</strong> → First Name (required)<br>
                                                <strong>Achternaam</strong> → Last Name (required)<br>
                                                <strong>Geboortedatum</strong> → Birth Date<br>
                                                <strong>E-mailadres</strong> → Email<br>
                                                <strong>Telefoonnr.</strong> → Phone Number<br>
                                                <strong>Adres</strong> → Address<br>
                                                <strong>IBAN</strong> → Bank Account<br>
                                                <strong>Contributiebedrag</strong> → Membership Fee<br>
                                                <strong>Mollie CID/SID</strong> → Mollie Customer/Subscription ID
                                            </small>
                                        </div>
                                    </div>
                                    <div class="col-md-6">
                                        <h6>Import Process:</h6>
                                        <ol class="small">
                                            <li>Download the CSV template or prepare your file</li>
                                            <li>Click "New Import" to create an import record</li>
                                            <li>Upload your CSV file</li>
                                            <li>Review the validation results and preview</li>
                                            <li>Enable/disable test mode as needed</li>
                                            <li>Process the import to create member records</li>
                                        </ol>

                                        <div class="alert alert-info mt-3">
                                            <strong>Tip:</strong> Always run in test mode first to validate your data
                                            without creating actual records.
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
		$(this.wrapper).append(import_html);
	}

	make_recent_imports() {
		const recent_html = `
            <div class="recent-imports-section mt-4">
                <div class="card">
                    <div class="card-header">
                        <h5>Recent Imports</h5>
                    </div>
                    <div class="card-body">
                        <div id="recent-imports-list">
                            Loading recent imports...
                        </div>
                    </div>
                </div>
            </div>
        `;
		$(this.wrapper).append(recent_html);

		this.load_recent_imports();
	}

	load_recent_imports() {
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Mijnrood CSV Import',
				fields: ['name', 'descriptive_name', 'import_status', 'import_date', 'members_created', 'members_updated', 'members_skipped'],
				order_by: 'creation desc',
				limit: 10
			},
			callback: (r) => {
				if (r.message && r.message.length > 0) {
					this.render_recent_imports(r.message);
				} else {
					$('#recent-imports-list').html('<p class="text-muted">No recent imports found.</p>');
				}
			}
		});
	}

	render_recent_imports(imports) {
		let html = '<div class="table-responsive"><table class="table table-striped">';
		html += '<thead><tr><th>Import Name</th><th>Date</th><th>Status</th><th>Results</th><th>Actions</th></tr></thead><tbody>';

		imports.forEach(imp => {
			const status_class = this.get_status_class(imp.import_status);
			const results = imp.import_status === 'Completed'
				? `Created: ${imp.members_created || 0}, Updated: ${imp.members_updated || 0}, Skipped: ${imp.members_skipped || 0}`
				: '-';

			html += `
                <tr>
                    <td>${imp.descriptive_name || imp.name}</td>
                    <td>${frappe.datetime.str_to_user(imp.import_date)}</td>
                    <td><span class="badge ${status_class}">${imp.import_status || 'Pending'}</span></td>
                    <td>${results}</td>
                    <td>
                        <button class="btn btn-sm btn-default" onclick="frappe.set_route('Form', 'Mijnrood CSV Import', '${imp.name}')">
                            <i class="fa fa-eye"></i> View
                        </button>
                    </td>
                </tr>
            `;
		});

		html += '</tbody></table></div>';
		$('#recent-imports-list').html(html);
	}

	get_status_class(status) {
		const status_classes = {
			Pending: 'badge-secondary',
			Validating: 'badge-info',
			'Ready for Import': 'badge-success',
			'In Progress': 'badge-warning',
			Completed: 'badge-success',
			Failed: 'badge-danger'
		};
		return status_classes[status] || 'badge-secondary';
	}

	setup_actions() {
		// New Import button
		$(this.wrapper).on('click', '#new-import-btn', () => {
			frappe.new_doc('Mijnrood CSV Import');
		});

		// Download Template button
		$(this.wrapper).on('click', '#download-template-btn', () => {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import.get_import_template',
				callback: (r) => {
					if (r.message) {
						this.download_file(r.message.content, r.message.filename);
					}
				}
			});
		});
	}

	download_file(content, filename) {
		const blob = new Blob([content], { type: 'text/csv' });
		const url = window.URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = filename;
		document.body.appendChild(a);
		a.click();
		window.URL.revokeObjectURL(url);
		document.body.removeChild(a);
	}
}

// Add custom CSS
frappe.provide('frappe.pages["mijnrood-csv-import-dashboard"]');
frappe.pages['mijnrood-csv-import-dashboard'].on_page_show = function () {
	if (!document.querySelector('#member-import-page-styles')) {
		const style = document.createElement('style');
		style.id = 'member-import-page-styles';
		style.textContent = `
            .member-import-header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 20px;
            }
            .member-import-header h3 {
                color: white;
                margin-bottom: 5px;
            }
            .field-mapping-list {
                background: #f8f9fa;
                padding: 10px;
                border-radius: 4px;
                border-left: 4px solid #007bff;
            }
            .card {
                border: none;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .card-header {
                background: #f8f9fa;
                border-bottom: 1px solid #dee2e6;
                font-weight: 600;
            }
            .badge-secondary { background-color: #6c757d; }
            .badge-info { background-color: #17a2b8; }
            .badge-success { background-color: #28a745; }
            .badge-warning { background-color: #ffc107; color: #212529; }
            .badge-danger { background-color: #dc3545; }
        `;
		document.head.appendChild(style);
	}
};
