/**
 * @fileoverview Membership Application Review Page - Streamlined Application Processing Interface
 *
 * This module provides a dedicated interface for reviewing and processing membership applications,
 * featuring bulk review capabilities, automated validation, and streamlined approval workflows.
 * Designed to optimize the membership onboarding process while ensuring data quality and compliance.
 *
 * Key Features:
 * - Centralized application review dashboard
 * - Bulk approval and rejection capabilities
 * - Automated eligibility validation
 * - Document verification interface
 * - Application status tracking
 * - Communication tools for applicant interaction
 * - Compliance reporting and audit trails
 *
 * Business Value:
 * - Accelerated membership onboarding process
 * - Reduced administrative overhead for application processing
 * - Improved applicant experience through faster turnaround
 * - Enhanced data quality through validation checks
 * - Compliance support for membership criteria verification
 * - Streamlined communication with prospective members
 *
 * Technical Architecture:
 * - Frappe framework page controller
 * - Integration with Member and Membership doctypes
 * - Real-time application status updates
 * - Document management integration
 * - Email notification system
 * - Audit logging for compliance tracking
 *
 * Security Features:
 * - Role-based access control for application reviewers
 * - Audit trail for all application decisions
 * - Data privacy protection for applicant information
 * - Secure document handling and verification
 *
 * @author Verenigingen Development Team
 * @version 1.5.0
 * @since 1.0.0
 *
 * @requires frappe
 * @requires verenigingen.verenigingen.doctype.member
 * @requires verenigingen.verenigingen.doctype.membership
 *
 * @example
 * // Access via: Workspace > Membership > Application Review
 *
 * @see {@link /app/membership-application} Page URL
 * @see {@link verenigingen.verenigingen.doctype.member} Member DocType
 * @see {@link verenigingen.verenigingen.doctype.membership} Membership DocType
 */

/**
 * The change table for an application: what approving it would change on the existing Member.
 * Self-contained; the approve dialog calls it with the rows of
 * verenigingen.api.membership_application_review.get_application_changes (#1765).
 * Every value is escaped, an empty list renders nothing (a new applicant changes no Member).
 *
 * @param {Array<{field: string, label: string, current: *, proposed: *}>} rows
 * @returns {string} HTML
 * Call as frappe.pages['membership-application-review'].render_application_changes(rows).
 */
frappe.pages['membership-application-review'].render_application_changes = function (rows) {
	if (!rows || !rows.length) {
		return '';
	}
	const cell = (value) => frappe.utils.escape_html(value === null || value === undefined ? '' : String(value));
	const body = rows
		.map((row) => `<tr><td>${cell(row.label)}</td><td>${cell(row.current)}</td><td>${cell(row.proposed)}</td></tr>`)
		.join('');
	return (
		'<table class="table table-bordered application-changes"><thead><tr>' +
		`<th>${cell(__('Field'))}</th><th>${cell(__('Current'))}</th><th>${cell(__('Proposed'))}</th>` +
		`</tr></thead><tbody>${body}</tbody></table>`
	);
};

/**
 * Frappe page loader for Membership Application Review
 *
 * Implements a comprehensive interface for reviewing and processing membership applications,
 * featuring bulk review capabilities, automated validation, and streamlined approval workflows.
 *
 * @param {Object} wrapper - Frappe page wrapper element
 * @since 1.0.0
 */
frappe.pages['membership-application-review'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Membership Application Review',
		single_column: true
	});

	// Initialize the application review interface
	frappe.membership_application_review = new MembershipApplicationReview(page);
	frappe.membership_application_review.make();
};

/**
 * Membership Application Review Interface
 * Provides comprehensive tools for reviewing and processing membership applications
 */
class MembershipApplicationReview {
	constructor(page) {
		this.page = page;
		this.filters = {
			chapter: null,
			days_overdue: null
		};
		this.applications = [];
		this.selected_applications = new Set();
		// The chapter dashboard links here with ?application=<name> to review that one application.
		const params = new URLSearchParams(window.location.search);
		this.focus_application =
			(frappe.route_options && frappe.route_options.application) || params.get('application') || null;
	}

	escapeHtml(str) {
		if (!str) {
			return '';
		}
		return String(str)
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#x27;');
	}

	make() {
		// Add HTML content directly
		const html = `
			<div class="membership-application-review-page">
				<div class="page-head">
					<div class="container">
						<div class="row">
							<div class="col-md-8">
								<h1 class="page-title">${__('Membership Application Review')}</h1>
								<p class="text-muted">Review and process pending membership applications</p>
							</div>
							<div class="col-md-4 text-right">
								<button class="btn btn-default btn-sm" id="btn-refresh">
									<i class="fa fa-refresh"></i> ${__('Refresh')}
								</button>
								<div class="btn-group" role="group">
									<button type="button" class="btn btn-default btn-sm dropdown-toggle" data-toggle="dropdown">
										<i class="fa fa-cog"></i> ${__('Actions')}
									</button>
									<ul class="dropdown-menu">
										<li><a href="#" id="btn-statistics">${__('View Statistics')}</a></li>
										<li><a href="#" id="btn-bulk-actions">${__('Bulk Actions')}</a></li>
										<li class="divider"></li>
										<li><a href="#" id="btn-email-templates">${__('Create Email Templates')}</a></li>
									</ul>
								</div>
							</div>
						</div>
					</div>
				</div>

				<div class="page-content">
					<div class="container">
						<!-- Filters Section -->
						<div class="row filter-section">
							<div class="col-md-4">
								<label>${__('Chapter')}</label>
								<select class="form-control" id="filter-chapter">
									<option value="">${__('All Chapters')}</option>
									<option value="Unassigned">${__('Unassigned')}</option>
								</select>
							</div>
							<div class="col-md-4">
								<label>${__('Days Overdue')}</label>
								<input type="number" class="form-control" id="filter-days-overdue" placeholder="e.g., 14">
							</div>
							<div class="col-md-4">
								<label>&nbsp;</label>
								<div>
									<button class="btn btn-primary btn-sm" id="btn-apply-filters">
										<i class="fa fa-filter"></i> ${__('Apply Filters')}
									</button>
									<button class="btn btn-link btn-sm" id="btn-clear-filters">
										${__('Clear')}
									</button>
								</div>
							</div>
						</div>

						<!-- Statistics Cards -->
						<div class="row stats-section">
							<div class="col-md-4">
								<div class="card stats-card">
									<div class="card-body text-center">
										<h3 class="card-title" id="total-pending">-</h3>
										<p class="card-text text-muted">${__('Total Pending')}</p>
									</div>
								</div>
							</div>
							<div class="col-md-4">
								<div class="card stats-card overdue-card">
									<div class="card-body text-center">
										<h3 class="card-title text-danger" id="overdue-count">-</h3>
										<p class="card-text text-muted">${__('Overdue (>14 days)')}</p>
									</div>
								</div>
							</div>
							<div class="col-md-4">
								<div class="card stats-card">
									<div class="card-body text-center">
										<h3 class="card-title text-success" id="avg-processing">-</h3>
										<p class="card-text text-muted">${__('Avg Processing (days)')}</p>
									</div>
								</div>
							</div>
						</div>

						<!-- Applications Section -->
						<div class="row">
							<div class="col-md-12">
								<div class="card applications-card">
									<div class="card-header d-flex justify-content-between align-items-center">
										<h5 class="mb-0">${__('Pending Applications')}</h5>
										<div class="bulk-actions" style="display: none;">
											<button class="btn btn-success btn-sm" id="btn-bulk-approve">
												<i class="fa fa-check"></i> ${__('Approve Selected')}
											</button>
											<button class="btn btn-danger btn-sm" id="btn-bulk-reject">
												<i class="fa fa-times"></i> ${__('Reject Selected')}
											</button>
											<span class="selected-count ml-2 text-muted">0 selected</span>
										</div>
									</div>
									<div class="card-body">
										<div class="applications-list">
											<div class="loading-state text-center p-4">
												<i class="fa fa-spinner fa-spin fa-2x text-muted"></i>
												<p class="text-muted mt-2">${__('Loading applications...')}</p>
											</div>
										</div>
									</div>
								</div>
							</div>
						</div>

						<!-- Last Updated -->
						<div class="row mt-4">
							<div class="col-md-12 text-center text-muted">
								<small>${__('Last updated')}: <span id="last-updated">-</span></small>
							</div>
						</div>
					</div>
				</div>

				<style>
				.membership-application-review-page {
					background-color: #f5f7fa;
					min-height: 100vh;
					padding-bottom: 30px;
				}
				.page-head {
					background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
					color: white;
					padding: 30px 0;
					margin-bottom: 30px;
				}
				.page-head .btn {
					margin-left: 5px;
				}
				.page-head .btn-default {
					background-color: rgba(255,255,255,0.2);
					border-color: rgba(255,255,255,0.3);
					color: white;
				}
				.page-head .btn-default:hover {
					background-color: rgba(255,255,255,0.3);
					border-color: rgba(255,255,255,0.4);
					color: white;
				}
				.filter-section {
					margin-bottom: 20px;
					padding: 20px;
					background: white;
					border-radius: 8px;
					box-shadow: 0 2px 4px rgba(0,0,0,0.1);
				}
				.stats-section {
					margin-bottom: 30px;
				}
				.stats-card {
					border: none;
					border-radius: 8px;
					box-shadow: 0 2px 4px rgba(0,0,0,0.1);
					transition: all 0.3s ease;
					margin-bottom: 15px;
				}
				.stats-card:hover {
					transform: translateY(-2px);
					box-shadow: 0 4px 8px rgba(0,0,0,0.15);
				}
				.overdue-card:hover {
					border-left: 4px solid #dc3545;
				}
				.applications-card {
					border: none;
					border-radius: 8px;
					box-shadow: 0 2px 4px rgba(0,0,0,0.1);
				}
				.applications-card .card-header {
					background-color: #f8f9fa;
					border-bottom: 2px solid #e9ecef;
					border-radius: 8px 8px 0 0;
				}
				.application-card {
					border: 1px solid #e9ecef;
					border-radius: 8px;
					margin-bottom: 15px;
					transition: all 0.2s ease;
				}
				.application-card:hover {
					box-shadow: 0 4px 8px rgba(0,0,0,0.1);
				}
				.application-card.border-danger {
					border-left: 4px solid #dc3545;
				}
				.application-card .card-header {
					background-color: #f8f9fa;
					border-bottom: 1px solid #e9ecef;
					padding: 15px 20px;
				}
				.application-card .card-body {
					padding: 15px 20px;
				}
				.badge {
					font-size: 0.75em;
					padding: 4px 8px;
				}
				.empty-state, .error-state, .loading-state {
					padding: 40px 20px;
					text-align: center;
				}
				.empty-state .fa {
					color: #6c757d;
				}
				.application-actions .btn {
					margin-left: 5px;
					border-radius: 4px;
				}
				.bulk-actions {
					display: flex;
					align-items: center;
					gap: 10px;
				}
				.selected-count {
					font-size: 0.9em;
					padding: 5px 10px;
					background-color: #e9ecef;
					border-radius: 12px;
				}
				.app-checkbox {
					transform: scale(1.2);
					margin-right: 10px;
				}
				.dropdown-menu > li > a {
					cursor: pointer;
					padding: 8px 16px;
				}
				.dropdown-menu > li > a:hover {
					background-color: #f8f9fa;
				}
				@keyframes spin {
					0% { transform: rotate(0deg); }
					100% { transform: rotate(360deg); }
				}
				.fa-spin {
					animation: spin 1s linear infinite;
				}
				@media (max-width: 768px) {
					.page-head .col-md-4 {
						margin-top: 20px;
						text-align: left !important;
					}
					.application-actions {
						margin-top: 10px;
					}
					.application-actions .btn {
						margin: 2px;
						font-size: 0.8em;
						padding: 5px 10px;
					}
					.bulk-actions {
						flex-direction: column;
						align-items: flex-start;
						gap: 5px;
					}
				}
				</style>
			</div>
		`;

		$(this.page.main).html(html);

		// Initialize components after DOM is ready
		this.wrapper = $(this.page.main);
		this.setup_event_handlers();
		this.check_permissions();
		this.load_data();
	}

	setup_event_handlers() {
		const $wrapper = $(this.wrapper);

		// Filter handlers
		$wrapper.on('change', '#filter-chapter', () => {
			this.filters.chapter = $('#filter-chapter').val();
			this.load_applications();
		});

		$wrapper.on('change', '#filter-days-overdue', () => {
			this.filters.days_overdue = $('#filter-days-overdue').val();
		});

		$wrapper.on('click', '.show-all-applications', (e) => {
			e.preventDefault();
			this.focus_application = null;
			this.load_applications();
		});

		$wrapper.on('click', '#btn-apply-filters', () => {
			this.load_applications();
		});

		$wrapper.on('click', '#btn-clear-filters', () => {
			$('#filter-chapter').val('');
			$('#filter-days-overdue').val('');
			this.filters = { chapter: null, days_overdue: null };
			this.load_applications();
		});

		// Action button handlers
		$wrapper.on('click', '#btn-refresh', () => {
			this.load_data();
		});

		$wrapper.on('click', '#btn-statistics', () => {
			this.show_statistics();
		});

		$wrapper.on('click', '#btn-bulk-actions', () => {
			this.show_bulk_actions();
		});

		// Security: Event delegation for action buttons (prevents XSS from inline onclick)
		$wrapper.on('click', '.action-approve', (e) => {
			const applicationName = $(e.currentTarget).data('application');
			if (applicationName) {
				this.approve_application(applicationName);
			}
		});

		$wrapper.on('click', '.action-reject', (e) => {
			const applicationName = $(e.currentTarget).data('application');
			if (applicationName) {
				this.reject_application(applicationName);
			}
		});

		$wrapper.on('click', '.action-details', (e) => {
			const applicationName = $(e.currentTarget).data('application');
			if (applicationName) {
				this.view_details(applicationName);
			}
		});

		$wrapper.on('click', '#btn-bulk-approve', () => {
			this.bulk_approve();
		});

		$wrapper.on('click', '#btn-bulk-reject', () => {
			this.bulk_reject();
		});

		// Checkbox change handler for bulk selection
		$wrapper.on('change', '.app-checkbox', () => {
			this.update_bulk_actions();
		});

		// Page head button handlers
		$(document).on('click', '#btn-refresh', () => {
			this.load_data();
		});

		$(document).on('click', '#btn-statistics', () => {
			this.show_statistics();
		});

		$(document).on('click', '#btn-bulk-actions', () => {
			this.show_bulk_actions();
		});

		$(document).on('click', '#btn-email-templates', () => {
			this.create_email_templates();
		});
	}

	update_bulk_actions() {
		const selected = $('.app-checkbox:checked').length;
		if (selected > 0) {
			$('.bulk-actions').show();
			$('.selected-count').text(`${selected} selected`);
		} else {
			$('.bulk-actions').hide();
		}
	}

	async check_permissions() {
		try {
			// Check user's chapter management permissions
			const permissions = await frappe.call({
				method: 'verenigingen.services.chapter.chapter_security.get_user_chapter_permissions'
			});

			this.user_permissions = permissions.message || {};

			// Hide bulk actions if user can't manage any applications
			if (!this.user_permissions.can_manage_applications) {
				$(this.wrapper).find('.bulk-actions').hide();
				$(this.wrapper).find('#btn-bulk-actions').parent().hide();
			}

			// Update UI based on permissions
			if (this.user_permissions.is_admin) {
				// Admins see everything
				$(this.wrapper).find('.admin-only').show();
			} else {
				// Chapter board members see limited view
				$(this.wrapper).find('.admin-only').hide();
			}
		} catch (error) {
			console.error('Error checking permissions:', error);
			// Fail securely - hide all action buttons if permission check fails
			$(this.wrapper).find('.bulk-actions').hide();
			$(this.wrapper).find('#btn-bulk-actions').parent().hide();
		}
	}

	async load_data() {
		await this.load_chapters();
		await this.load_statistics();
		await this.load_applications();
	}

	async load_chapters() {
		try {
			const chapters = await frappe.call({
				method: 'frappe.client.get_list',
				args: {
					doctype: 'Chapter',
					filters: { status: 'Active' },
					fields: ['name'],
					order_by: 'name'
				}
			});

			if (chapters.message) {
				const $select = $('#filter-chapter');
				// Keep existing options (All Chapters, Unassigned) and add chapters
				chapters.message.forEach((chapter) => {
					const chapterName = frappe.utils.escape_html(chapter.name);
					$select.append(`<option value="${chapterName}">${chapterName}</option>`);
				});
			}
		} catch (error) {
			console.error('Error loading chapters:', error);
		}
	}

	async load_statistics() {
		try {
			const response = await frappe.call({
				method: 'verenigingen.api.admin_membership_operations.get_application_stats'
			});

			if (response.message) {
				const stats = response.message;
				$('#total-pending').text(stats.by_status?.['Pending Review'] || 0);
				$('#overdue-count').text(stats.overdue_count || 0);
				$('#avg-processing').text(stats.avg_processing_days || 0);
			}
		} catch (error) {
			console.error('Error loading statistics:', error);
		}
	}

	async load_applications() {
		$('.applications-list').html(`
			<div class="loading-state text-center p-4">
				<i class="fa fa-spinner fa-spin"></i> Loading applications...
			</div>
		`);

		try {
			const response = await frappe.call({
				method: 'verenigingen.api.membership_application_review.get_pending_applications',
				args: {
					chapter: this.filters.chapter,
					days_overdue: this.filters.days_overdue
				}
			});

			this.applications = response.message || [];
			if (this.focus_application) {
				this.applications = this.applications.filter((app) => app.name === this.focus_application);
			}
			this.render_applications();
		} catch (error) {
			console.error('Error loading applications:', error);
			$('.applications-list').html(`
				<div class="error-state text-center p-4 text-danger">
					<i class="fa fa-exclamation-triangle"></i> Error loading applications: ${frappe.utils.escape_html(error.message)}
				</div>
			`);
		}
	}

	render_applications() {
		if (this.applications.length === 0) {
			$('.applications-list').html(`
				<div class="empty-state text-center p-5">
					<i class="fa fa-inbox fa-3x text-muted mb-3"></i>
					<h5 class="text-muted">No pending applications found</h5>
					<p class="text-muted">All applications have been processed or no applications match your filters.</p>
				</div>
			`);
			return;
		}

		const banner = this.focus_application
			? `<div class="alert alert-info focus-banner">${__('Showing one application.')} <a href="#" class="show-all-applications">${__('Show all pending applications')}</a></div>`
			: '';
		const html = this.applications.map((app) => this.render_application_card(app)).join('');
		$('.applications-list').html(banner + html);

		// Update statistics
		this.update_local_statistics();
	}

	render_application_card(app) {
		const overdue = app.days_pending > 14;
		const overdueClass = overdue ? 'border-danger' : '';

		// Security: applicant names and emails are guest input. Every value is escaped, and the
		// actions use data attributes with event delegation instead of inline onclick.
		const e = (str) => this.escapeHtml(str);
		return `
			<div class="card application-card mb-3 ${overdueClass}" data-application="${e(app.name)}">
				<div class="card-header d-flex justify-content-between align-items-center">
					<div class="d-flex align-items-center">
						<input type="checkbox" class="mr-2 app-checkbox" data-application="${e(app.name)}">
						<strong>${e(app.applicant_name)}</strong>
						${overdue ? '<span class="badge badge-danger ml-2">Overdue</span>' : ''}
					</div>
					<div class="application-actions">
						<button class="btn btn-success btn-sm action-approve" data-application="${e(app.name)}">
							<i class="fa fa-check"></i> Approve
						</button>
						<button class="btn btn-danger btn-sm action-reject" data-application="${e(app.name)}">
							<i class="fa fa-times"></i> Reject
						</button>
						<button class="btn btn-info btn-sm action-details" data-application="${e(app.name)}">
							<i class="fa fa-eye"></i> Details
						</button>
					</div>
				</div>
				<div class="card-body">
					<div class="row">
						<div class="col-md-6">
							<p class="mb-1"><strong>Email:</strong> ${e(app.email)}</p>
							<p class="mb-1"><strong>Application ID:</strong> ${e(app.application_id) || 'Not assigned'}</p>
						</div>
						<div class="col-md-6">
							<p class="mb-1"><strong>Application Date:</strong> ${e(frappe.datetime.str_to_user(app.application_date))}</p>
							<p class="mb-1"><strong>Days Pending:</strong> ${e(app.days_pending)}</p>
							<p class="mb-1"><strong>Chapter:</strong> ${e(app.chapter) || 'Unassigned'}</p>
							<p class="mb-1"><strong>Membership Type:</strong> ${e(app.membership_type) || 'Not selected'}</p>
						</div>
					</div>
				</div>
			</div>
		`;
	}

	update_local_statistics() {
		const total = this.applications.length;
		const overdue = this.applications.filter((app) => app.days_pending > 14).length;

		$('#total-pending').text(total);
		$('#overdue-count').text(overdue);
	}

	async approve_application(application_name) {
		const app = this.applications.find((a) => a.name === application_name);
		if (!app) {
			return;
		}

		const dialogFields = [];

		// Possible duplicates of this applicant (name, birth date, IBAN; the exact-email Member is the
		// applicant themselves and is not reported). Never blocks the approval if the check fails.
		const duplicateField = await this.duplicate_warning_field(application_name);
		if (duplicateField.fields.length) {
			dialogFields.push(...duplicateField.fields);
		}

		// What approving would change on an existing Member (nothing for a new applicant). A failed
		// preview must not look like "nothing to change", so the dialog says it could not be loaded.
		let changesHtml = '';
		try {
			const changes = await frappe.call({
				method: 'verenigingen.api.membership_application_review.get_application_changes',
				args: { application_name }
			});
			changesHtml = frappe.pages['membership-application-review'].render_application_changes(changes.message);
		} catch (error) {
			console.error('Error loading application changes:', error);
			changesHtml = `<div class="alert alert-danger application-changes-error">${__(
				'The changes this approval would make could not be loaded. Do not approve until you have reviewed the applicant and the existing member yourself, or reload the page and try again.'
			)}</div>`;
		}
		if (changesHtml) {
			dialogFields.push({
				fieldtype: 'HTML',
				fieldname: 'application_changes',
				options: `<h5>${__('Approving this application changes the existing member')}</h5>${changesHtml}`
			});
		}

		dialogFields.push(
			{
				fieldtype: 'Link',
				fieldname: 'membership_type',
				label: 'Membership Type',
				options: 'Membership Type',
				reqd: 1,
				default: app.membership_type,
				get_query: () => ({ filters: { is_active: 1 } })
			},
			{
				fieldtype: 'Link',
				fieldname: 'chapter',
				label: 'Chapter Assignment',
				options: 'Chapter',
				default: app.chapter || ''
			},
			{
				fieldtype: 'Small Text',
				fieldname: 'notes',
				label: 'Approval Notes'
			},
			{
				fieldtype: 'Check',
				fieldname: 'create_invoice',
				label: 'Create Invoice',
				default: 1
			},
			{
				fieldtype: 'Check',
				fieldname: 'activate_as_volunteer',
				label: __('Activate as Full Volunteer'),
				default: 0,
				description: __(
					'Grant full volunteer access with Employee record for expense claims. If unchecked, only a volunteer interest record will be created.'
				)
			}
		);

		const dialog = new frappe.ui.Dialog({
			title: __('Approve Application: {0}', [frappe.utils.escape_html(app.applicant_name)]),
			fields: dialogFields,
			primary_action_label: 'Approve',
			primary_action: async (values) => {
				try {
					const response = await frappe.call({
						method: 'verenigingen.api.membership_application_review.approve_application',
						args: {
							application_name,
							membership_type: values.membership_type,
							chapter: values.chapter,
							notes: values.notes,
							create_invoice: values.create_invoice,
							activate_as_volunteer: values.activate_as_volunteer || 0
						}
					});

					if (response.message?.success) {
						frappe.show_alert({
							message: __('Application approved for {0}', [frappe.utils.escape_html(app.applicant_name)]),
							indicator: 'green'
						});
						this.load_applications();
						this.load_statistics();
					}
					dialog.hide();
				} catch (error) {
					frappe.msgprint(`Error approving application: ${frappe.utils.escape_html(error.message)}`);
				}
			}
		});

		dialog.show();
	}

	/**
	 * The approve dialog's duplicate-warning fields for an application, from
	 * check_duplicate_for_application (#1870). Returns {fields, blocking}; a failed check yields no fields.
	 */
	async duplicate_warning_field(application_name) {
		let result;
		try {
			result = await frappe.call({
				method: 'verenigingen.services.member.validation.member_duplicate_detection_service.check_duplicate_for_application',
				args: { application_name }
			});
		} catch (error) {
			console.error('Error checking duplicates:', error);
			return { fields: [] };
		}
		const duplicates = result?.message;
		if (!duplicates?.has_duplicates) {
			return { fields: [] };
		}
		const summary = duplicates.summary;
		const e = (str) => this.escapeHtml(str);

		let warningHtml =
			'<div style="background: #fff3cd; border: 1px solid #ffc107; padding: 15px; border-radius: 5px; margin-bottom: 15px;">';
		warningHtml +=
			'<h5 style="margin-top: 0; color: #856404;"><i class="fa fa-exclamation-triangle"></i> Potential Duplicate Members Found</h5>';
		if (summary.high > 0) {
			warningHtml += `<p style="color: #721c24; font-weight: bold;">${summary.high} high-confidence match(es)</p>`;
		}
		if (summary.medium > 0) {
			warningHtml += `<p style="color: #856404;">${summary.medium} medium-confidence match(es)</p>`;
		}
		if (summary.low > 0) {
			warningHtml += `<p style="color: #666;">${summary.low} low-confidence match(es)</p>`;
		}
		const importantMatches = [...duplicates.high_confidence, ...duplicates.medium_confidence];
		if (importantMatches.length > 0) {
			warningHtml += '<div style="margin-top: 10px;"><strong>Matches:</strong><ul style="margin-bottom: 5px;">';
			importantMatches.forEach((match) => {
				const confidence = Math.round(match.confidence * 100);
				const details = match.details;
				// Escape all data: the applicant's own details and the matched member's are user input.
				warningHtml += `<li>
					<strong>${e(details.full_name)}</strong> (${confidence}% match)<br>
					<small style="color: #666;">
						${e(details.email) || 'No email'} |
						Status: ${e(details.status) || 'Unknown'} |
						Reason: ${e(details.reason)}
						<a href="#Form/Member/${e(match.member_name)}" target="_blank" style="margin-left: 10px;">View Record</a>
					</small>
				</li>`;
			});
			warningHtml += '</ul></div>';
		}
		warningHtml +=
			'<p style="margin-bottom: 0; margin-top: 10px;"><strong>Please review these matches before approving.</strong></p>';
		warningHtml += '</div>';

		const fields = [{ fieldtype: 'HTML', fieldname: 'duplicate_warning', options: warningHtml }];
		if (summary.high > 0) {
			fields.push({
				fieldtype: 'Check',
				fieldname: 'acknowledge_duplicates',
				label: 'I have reviewed the duplicate matches and want to proceed',
				reqd: 1,
				default: 0
			});
		}
		return { fields };
	}

	async reject_application(application_name) {
		const app = this.applications.find((a) => a.name === application_name);
		if (!app) {
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __('Reject Application: {0}', [frappe.utils.escape_html(app.applicant_name)]),
			fields: this.rejection_fields(),
			primary_action_label: 'Reject',
			primary_action: async (values) => {
				try {
					const response = await this.call_reject(application_name, values);

					if (response.message?.success) {
						frappe.show_alert({
							message: __('Application rejected for {0}', [frappe.utils.escape_html(app.applicant_name)]),
							indicator: 'orange'
						});
						this.load_applications();
						this.load_statistics();
					}
					dialog.hide();
				} catch (error) {
					frappe.msgprint(`Error rejecting application: ${frappe.utils.escape_html(error.message)}`);
				}
			}
		});

		dialog.show();
	}

	rejection_fields() {
		return [
			{
				fieldtype: 'Select',
				fieldname: 'rejection_category',
				label: 'Rejection Category',
				options: ['General', 'Incomplete Information', 'Ineligible', 'Duplicate Application'],
				reqd: 1
			},
			{
				fieldtype: 'Small Text',
				fieldname: 'reason',
				label: 'Rejection Reason',
				reqd: 1
			},
			{
				fieldtype: 'Link',
				fieldname: 'email_template',
				label: 'Email Template',
				options: 'Email Template',
				get_query: () => ({
					filters: {
						name: ['like', 'membership_rejection%']
					}
				})
			},
			{
				fieldtype: 'Small Text',
				fieldname: 'internal_notes',
				label: 'Internal Notes'
			}
		];
	}

	call_reject(application_name, values) {
		return frappe.call({
			method: 'verenigingen.api.membership_application_review.reject_application',
			args: {
				application_name,
				reason: values.reason,
				email_template: values.email_template,
				rejection_category: values.rejection_category,
				internal_notes: values.internal_notes
			}
		});
	}

	view_details(application_name) {
		frappe.set_route('Form', 'Membership Application Submission', application_name);
	}

	show_statistics() {
		frappe
			.call({
				method: 'verenigingen.api.admin_membership_operations.get_application_stats'
			})
			.then((response) => {
				if (response.message) {
					const stats = response.message;
					const dialog = new frappe.ui.Dialog({
						title: 'Application Statistics',
						size: 'large',
						fields: [
							{
								fieldtype: 'HTML',
								fieldname: 'stats_html',
								options: this.render_statistics_html(stats)
							}
						]
					});
					dialog.show();
				}
			});
	}

	render_statistics_html(stats) {
		const by_chapter = stats.by_chapter || [];
		const chapter_rows = by_chapter
			.map(
				(c) =>
					`<tr><td>${frappe.utils.escape_html(c.current_chapter_display || 'Unassigned')}</td><td>${frappe.utils.escape_html(c.count)}</td></tr>`
			)
			.join('');

		return `
			<div class="row">
				<div class="col-md-6">
					<h5>Applications by Status</h5>
					<table class="table table-bordered">
						<tr><th>Status</th><th>Count</th></tr>
						${Object.entries(stats.by_status || {})
							.map(
								([status, count]) =>
									`<tr><td>${frappe.utils.escape_html(status)}</td><td>${frappe.utils.escape_html(count)}</td></tr>`
							)
							.join('')}
					</table>
				</div>
				<div class="col-md-6">
					<h5>Applications by Chapter</h5>
					<table class="table table-bordered">
						<tr><th>Chapter</th><th>Count</th></tr>
						${chapter_rows}
					</table>
				</div>
			</div>
			<div class="row mt-3">
				<div class="col-md-12">
					<p><strong>Applications in last 30 days:</strong> ${stats.last_30_days || 0}</p>
					<p><strong>Average processing time:</strong> ${stats.avg_processing_days || 0} days</p>
				</div>
			</div>
		`;
	}

	show_bulk_actions() {
		const selected = $('.app-checkbox:checked').length;
		if (selected === 0) {
			frappe.msgprint('Please select applications to perform bulk actions.');
			return;
		}
		$('.bulk-actions').show();
		$('.selected-count').text(`${selected} selected`);
	}

	selected_application_names() {
		return $('.app-checkbox:checked')
			.map(function () {
				return $(this).data('application');
			})
			.get();
	}

	bulk_approve() {
		const selected = this.selected_application_names();

		if (selected.length === 0) {
			frappe.msgprint('Please select applications to approve.');
			return;
		}

		// One decision for the whole selection; each application keeps its own membership type
		// and chapter. They are approved one after the other, and every outcome is reported.
		frappe.confirm(`Are you sure you want to approve ${selected.length} applications?`, async () => {
			const results = { done: [], failed: [] };
			for (const application_name of selected) {
				const app = this.applications.find((a) => a.name === application_name);
				try {
					const response = await frappe.call({
						method: 'verenigingen.api.membership_application_review.approve_application',
						args: {
							application_name,
							membership_type: app && app.membership_type,
							chapter: app && app.chapter,
							create_invoice: 1
						}
					});
					(response.message?.success ? results.done : results.failed).push({
						application_name,
						error: response.message?.message
					});
				} catch (error) {
					results.failed.push({ application_name, error: error.message });
				}
			}
			this.report_bulk_result(__('Approved'), results);
		});
	}

	bulk_reject() {
		const selected = this.selected_application_names();

		if (selected.length === 0) {
			frappe.msgprint('Please select applications to reject.');
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __('Reject {0} applications', [selected.length]),
			fields: this.rejection_fields(),
			primary_action_label: 'Reject',
			primary_action: async (values) => {
				dialog.hide();
				const results = { done: [], failed: [] };
				for (const application_name of selected) {
					try {
						const response = await this.call_reject(application_name, values);
						(response.message?.success ? results.done : results.failed).push({
							application_name,
							error: response.message?.message
						});
					} catch (error) {
						results.failed.push({ application_name, error: error.message });
					}
				}
				this.report_bulk_result(__('Rejected'), results);
			}
		});

		dialog.show();
	}

	report_bulk_result(label, results) {
		const failures = results.failed
			.map(
				(f) =>
					`<li>${frappe.utils.escape_html(f.application_name)}: ${frappe.utils.escape_html(f.error || '')}</li>`
			)
			.join('');
		frappe.msgprint({
			title: __('Bulk result'),
			indicator: results.failed.length ? 'orange' : 'green',
			message: `<p>${frappe.utils.escape_html(label)}: ${results.done.length}</p>${
				failures ? `<p>${__('Failed')}: ${results.failed.length}</p><ul>${failures}</ul>` : ''
			}`
		});
		this.load_applications();
		this.load_statistics();
	}

	async create_email_templates() {
		try {
			const response = await frappe.call({
				method: 'verenigingen.api.membership_email_templates.create_default_email_templates'
			});

			if (response.message?.success) {
				frappe.show_alert({
					message: `Created ${response.message.templates.length} email templates`,
					indicator: 'green'
				});
			}
		} catch (error) {
			frappe.msgprint(`Error creating email templates: ${frappe.utils.escape_html(error.message)}`);
		}
	}

	update_last_updated() {
		$('#last-updated').text(frappe.datetime.now_datetime());
	}
}
