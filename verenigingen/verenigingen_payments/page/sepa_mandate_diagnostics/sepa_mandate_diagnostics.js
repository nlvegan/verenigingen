frappe.pages['sepa_mandate_diagnostics'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('SEPA Mandate Diagnostics'),
		single_column: true
	});

	// Add refresh button
	page.add_inner_button(__('Refresh'), function() {
		load_diagnostics(page);
	});

	// Initial load
	load_diagnostics(page);
};

function load_diagnostics(page) {
	// Show loading indicator
	$(page.body).html('<div class="text-center margin-top"><p class="text-muted">' + __('Loading diagnostics...') + '</p></div>');

	// Fetch diagnostic data
	frappe.call({
		method: 'verenigingen.verenigingen_payments.page.sepa_mandate_diagnostics.sepa_mandate_diagnostics.get_mandate_issues',
		callback: function(r) {
			if (r.message) {
				render_diagnostics(page, r.message);
			}
		}
	});
}

function render_diagnostics(page, data) {
	const { issues, summary } = data;

	// Build summary card
	let html = `
		<div class="frappe-card margin-bottom">
			<div class="frappe-card-head">
				<strong>${__('Summary')}</strong>
			</div>
			<div class="frappe-card-body">
				<div class="row">
					<div class="col-md-4">
						<div class="text-center">
							<h2 class="${summary.total_issues > 0 ? 'text-danger' : 'text-success'}">${summary.total_issues}</h2>
							<p class="text-muted">${__('Total Issues')}</p>
						</div>
					</div>
					<div class="col-md-4">
						<div class="text-center">
							<h2>${summary.unique_members}</h2>
							<p class="text-muted">${__('Affected Members')}</p>
						</div>
					</div>
					<div class="col-md-4">
						<div class="text-center">
							<p class="text-muted">${__('Last Checked')}</p>
							<p><small>${frappe.datetime.str_to_user(summary.last_checked)}</small></p>
						</div>
					</div>
				</div>
			</div>
		</div>
	`;

	// Build issue cards
	Object.keys(issues).forEach(issue_key => {
		const issue = issues[issue_key];
		const severity_class = issue.severity === 'critical' ? 'danger' :
		                       issue.severity === 'high' ? 'orange' :
		                       issue.severity === 'medium' ? 'warning' : 'info';

		html += `
			<div class="frappe-card margin-bottom">
				<div class="frappe-card-head" data-toggle="collapse" data-target="#${issue_key}" style="cursor: pointer;">
					<span class="indicator ${severity_class}">${issue.title}</span>
					<span class="badge badge-${severity_class} pull-right">${issue.count}</span>
				</div>
				<div class="frappe-card-body">
					<p class="text-muted">${issue.description}</p>
					${issue.count > 0 && issue_key !== 'sepa_selected_no_mandate' ? `
						<button class="btn btn-sm btn-primary" onclick="fix_all_for_issue('${issue_key}')">${__('Fix All')}</button>
					` : ''}
					${issue_key === 'sepa_selected_no_mandate' && issue.count > 0 ? `
						<div class="alert alert-warning">
							<strong>${__('Manual Action Required')}</strong><br>
							${__('These members need SEPA mandates created. Auto-fix is not available. Please review each member and create mandates as needed.')}
						</div>
					` : ''}
				</div>
				<div id="${issue_key}" class="collapse ${issue.count > 0 && issue.count <= 20 ? 'in' : ''}">
					<div class="frappe-card-body" style="max-height: 400px; overflow-y: auto;">
						${render_issue_members(issue_key, issue.members)}
					</div>
				</div>
			</div>
		`;
	});

	$(page.body).html(html);
}

function render_issue_members(issue_type, members) {
	if (members.length === 0) {
		return '<p class="text-muted text-center">' + __('No issues found') + '</p>';
	}

	let html = '<table class="table table-bordered table-hover"><thead><tr>';

	// Dynamic headers based on issue type
	if (issue_type === 'sepa_selected_no_mandate') {
		html += '<th>' + __('Member') + '</th><th>' + __('Payment Method') + '</th><th>' + __('Total Mandates') + '</th><th>' + __('Active Mandates') + '</th><th>' + __('Actions') + '</th>';
	} else if (issue_type === 'missing_child_table_entries') {
		html += '<th>' + __('Member') + '</th><th>' + __('Mandate Count') + '</th><th>' + __('Mandate IDs') + '</th><th>' + __('Actions') + '</th>';
	} else if (issue_type === 'orphaned_child_table_entries') {
		html += '<th>' + __('Member') + '</th><th>' + __('Orphaned Mandate') + '</th><th>' + __('Reference') + '</th><th>' + __('Actions') + '</th>';
	} else if (issue_type === 'outdated_child_table_data') {
		html += '<th>' + __('Member') + '</th><th>' + __('Mandate') + '</th><th>' + __('Current Status') + '</th><th>' + __('Child Table Status') + '</th><th>' + __('Actions') + '</th>';
	} else if (issue_type === 'multiple_current_mandates') {
		html += '<th>' + __('Member') + '</th><th>' + __('Current Count') + '</th><th>' + __('Mandate IDs') + '</th><th>' + __('Actions') + '</th>';
	}

	html += '</tr></thead><tbody>';

	members.forEach(member => {
		html += '<tr>';

		if (issue_type === 'sepa_selected_no_mandate') {
			html += `
				<td><a href="/app/member/${member.member_id}">${member.full_name}</a></td>
				<td><span class="label label-info">${member.payment_method}</span></td>
				<td>${member.total_mandates}</td>
				<td><span class="label label-danger">${member.active_mandates}</span></td>
			`;
		} else if (issue_type === 'missing_child_table_entries') {
			html += `
				<td><a href="/app/member/${member.member_id}">${member.full_name}</a></td>
				<td>${member.mandate_count}</td>
				<td><small>${member.mandate_ids}</small></td>
			`;
		} else if (issue_type === 'orphaned_child_table_entries') {
			html += `
				<td><a href="/app/member/${member.member_id}">${member.full_name}</a></td>
				<td>${member.mandate_name}</td>
				<td>${member.mandate_reference}</td>
			`;
		} else if (issue_type === 'outdated_child_table_data') {
			html += `
				<td><a href="/app/member/${member.member_id}">${member.full_name}</a></td>
				<td>${member.mandate_id}</td>
				<td><span class="label label-info">${member.current_status}</span></td>
				<td><span class="label label-warning">${member.child_table_status}</span></td>
			`;
		} else if (issue_type === 'multiple_current_mandates') {
			html += `
				<td><a href="/app/member/${member.member_id}">${member.full_name}</a></td>
				<td>${member.current_count}</td>
				<td><small>${member.mandate_ids}</small></td>
			`;
		}

		html += `
			<td>
				<button class="btn btn-xs btn-success" onclick="fix_single_member('${member.member_id}')">${__('Fix')}</button>
			</td>
		</tr>`;
	});

	html += '</tbody></table>';

	return html;
}

function fix_single_member(member_id) {
	frappe.show_progress(__('Fixing...'), 0, 1, __('Fixing mandate issues for member'));

	frappe.call({
		method: 'verenigingen.verenigingen_payments.page.sepa_mandate_diagnostics.sepa_mandate_diagnostics.fix_member_mandate_issues',
		args: { member_id: member_id },
		callback: function(r) {
			frappe.hide_progress();

			if (r.message && r.message.success) {
				frappe.show_alert({
					message: __('Successfully fixed issues for {0}', [r.message.member_name]),
					indicator: 'green'
				});

				// Reload diagnostics
				load_diagnostics(cur_page.page);
			} else {
				frappe.show_alert({
					message: __('Failed to fix issues: {0}', [r.message.error]),
					indicator: 'red'
				});
			}
		}
	});
}

function fix_all_for_issue(issue_type) {
	frappe.confirm(
		__('This will fix all members with this issue type. Continue?'),
		function() {
			frappe.show_progress(__('Bulk Fix...'), 0, 1, __('Fixing mandate issues in batch'));

			frappe.call({
				method: 'verenigingen.verenigingen_payments.page.sepa_mandate_diagnostics.sepa_mandate_diagnostics.bulk_fix_mandate_issues',
				args: { issue_type: issue_type },
				callback: function(r) {
					frappe.hide_progress();

					if (r.message) {
						const msg = __('Fixed {0} of {1} members. {2} failures.', [
							r.message.success,
							r.message.total,
							r.message.failed
						]);

						frappe.show_alert({
							message: msg,
							indicator: r.message.failed > 0 ? 'orange' : 'green'
						});

						// Reload diagnostics
						load_diagnostics(cur_page.page);
					}
				}
			});
		}
	);
}
