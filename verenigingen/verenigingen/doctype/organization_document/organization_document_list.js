/**
 * @fileoverview Organization Document list view customization.
 *
 * Adds a "Reclassify from MijnRood folder" entry to the list-view Actions
 * menu, visible only to System Manager / Verenigingen Administrator. The
 * action takes the user's selected items and runs them through the same
 * dry-run → confirm preview → apply flow used by the form button (defined
 * in organization_document.js).
 *
 * Self-contained: this file does NOT depend on the form bundle being
 * loaded. It uses the same preview helper as the form, duplicated here.
 * If the form bundle IS loaded (user opened a doc form earlier), we
 * defer to its helper so behavior stays identical.
 */
// Copyright (c) 2025, Veganisme.org and contributors

frappe.listview_settings['Organization Document'] = {
	onload(listview) {
		const roles = frappe.user_roles || [];
		const allowed = roles.includes('System Manager') || roles.includes('Verenigingen Administrator');
		if (!allowed) { return; }

		listview.page.add_actions_menu_item(__('Reclassify from MijnRood folder'), () => {
			const items = listview.get_checked_items();
			if (!items.length) {
				frappe.msgprint(__('Select at least one document.'));
				return;
			}
			const names = items.map(i => i.name);

			// Defer to the form bundle's helper if loaded; both paths show the
			// same preview dialog, so this just avoids duplicate code paths in
			// the common case where a user has visited a doc form recently.
			const flow = (window.verenigingen && window.verenigingen.run_reclassify_flow)
				|| run_reclassify_flow_local;
			flow(names, () => listview.refresh());
		});
	}
};

// Local fallback copy of the dry-run → confirm → apply flow, used when
// organization_document.js (form bundle) hasn't loaded yet. Behavior matches
// the form bundle's window.verenigingen.run_reclassify_flow exactly.
function run_reclassify_flow_local(names, onApplied) {
	frappe.call({
		method: 'verenigingen.mijnrood_sync.services.document_reclassify_service.reclassify_documents',
		args: { names, dry_run: true },
		freeze: true,
		freeze_message: __('Computing reclassification preview…'),
		callback(r) {
			if (!r.message) { return; }
			show_reclassify_preview_local(r.message, () => {
				frappe.call({
					method: 'verenigingen.mijnrood_sync.services.document_reclassify_service.reclassify_documents',
					args: { names, dry_run: false },
					freeze: true,
					freeze_message: __('Applying reclassification…'),
					callback(r2) {
						if (!r2.message) { return; }
						const errorCount = (r2.message.changes || [])
							.reduce((n, c) => n + ((c.write_errors || []).length), 0);
						if (errorCount > 0) {
							frappe.show_alert({
								message: __('Reclassified {0} documents with {1} field write error(s) — check error log.',
									[r2.message.applied, errorCount]),
								indicator: 'orange'
							});
						} else {
							frappe.show_alert({
								message: __('Reclassified {0} documents.', [r2.message.applied]),
								indicator: 'green'
							});
						}
						if (onApplied) { onApplied(); }
					}
				});
			});
		}
	});
}

function show_reclassify_preview_local(result, onConfirm) {
	const changes = result.changes || [];
	const skipped = result.skipped || [];

	if (!changes.length) {
		frappe.msgprint({
			title: __('Nothing to reclassify'),
			message: __('All {0} documents are unchanged or skipped (skipped: {1}).',
				[result.total, skipped.length]),
			indicator: 'blue'
		});
		return;
	}

	const rows = changes.flatMap(c => c.diff_fields.map(f => `
		<tr>
			<td>${frappe.utils.escape_html(c.name)}</td>
			<td>${frappe.utils.escape_html(f)}</td>
			<td>${frappe.utils.escape_html(String(c.current[f] ?? ''))}</td>
			<td>${frappe.utils.escape_html(String(c.proposed[f] ?? ''))}</td>
		</tr>
	`)).join('');

	const html = `
		<div style="max-height: 400px; overflow-y: auto;">
			<table class="table table-bordered" style="font-size: 12px;">
				<thead><tr>
					<th>${__('Document')}</th><th>${__('Field')}</th>
					<th>${__('Current')}</th><th>${__('Proposed')}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
		<p>${__('{0} change(s), {1} skipped.', [changes.length, skipped.length])}</p>
	`;

	const dialog = new frappe.ui.Dialog({
		title: __('Reclassify preview'),
		size: 'large',
		primary_action_label: __('Apply'),
		primary_action() {
			dialog.hide();
			onConfirm();
		}
	});
	dialog.$body.html(html);
	dialog.show();
}
