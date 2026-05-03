/**
 * @fileoverview Organization Document form behavior.
 *
 * - Loads document_type Select options from Verenigingen Settings.
 * - Snaps applies_on to match applies_on_precision (Day/Month/Year) so
 *   the form mirrors the server-side normalization in
 *   OrganizationDocument._normalize_applies_on_precision.
 * - When source_folder_id is set, exposes an Actions menu button that
 *   reclassifies the doc against the current MijnRood folder mapping
 *   via document_reclassify_service.reclassify_documents (dry-run →
 *   confirm preview → apply).
 *
 * Public interface for sibling scripts (e.g. organization_document_list.js):
 *   window.verenigingen.run_reclassify_flow(names, onApplied)
 *     - names: string[] of Organization Document names
 *     - onApplied: () => void, called after successful apply
 */

// Copyright (c) 2025, Veganisme.org and contributors
// For license information, please see license.txt

frappe.ui.form.on('Organization Document', {
	setup(frm) {
		// Load document categories from Settings (single source of truth)
		frappe.call({
			method: 'verenigingen.utils.document_categories.get_document_category_options',
			callback(r) {
				if (r.message) {
					frm.set_df_property('document_type', 'options', r.message);
				}
			}
		});
	},

	refresh(frm) {
		if (frm.is_new() || !frm.doc.source_folder_id) {
			return;
		}
		frm.add_custom_button(__('Reclassify from MijnRood folder'), () => {
			run_reclassify_flow([frm.doc.name], () => frm.reload_doc());
		}, __('Actions'));
	},

	applies_on_precision(frm) {
		if (!frm.doc.applies_on) return;
		const d = frappe.datetime.str_to_obj(frm.doc.applies_on);
		if (!d || isNaN(d)) return;

		if (frm.doc.applies_on_precision === 'Month' && d.getDate() !== 1) {
			d.setDate(1);
			frm.set_value('applies_on', frappe.datetime.obj_to_str(d));
		} else if (frm.doc.applies_on_precision === 'Year' && (d.getMonth() !== 0 || d.getDate() !== 1)) {
			d.setMonth(0);
			d.setDate(1);
			frm.set_value('applies_on', frappe.datetime.obj_to_str(d));
		}
	},

	applies_on(frm) {
		if (!frm.doc.applies_on) return;
		const d = frappe.datetime.str_to_obj(frm.doc.applies_on);
		if (!d || isNaN(d)) return;

		// If the user picked a non-1 day, force precision to Day. Don't touch
		// precision when day is 1 — could be a real Jan 1 or month-precision.
		if (d.getDate() !== 1 && frm.doc.applies_on_precision !== 'Day') {
			frm.set_value('applies_on_precision', 'Day');
		}
	}
});

// Shared dry-run → confirm → apply flow used by both the form button
// (single doc) and the list-view bulk action.
window.verenigingen = window.verenigingen || {};
window.verenigingen.run_reclassify_flow = run_reclassify_flow;

function run_reclassify_flow(names, onApplied) {
	frappe.call({
		method: 'verenigingen.mijnrood_sync.services.document_reclassify_service.reclassify_documents',
		args: { names: names, dry_run: true },
		freeze: true,
		freeze_message: __('Computing reclassification preview…'),
		callback(r) {
			if (!r.message) return;
			show_reclassify_preview(r.message, () => {
				frappe.call({
					method: 'verenigingen.mijnrood_sync.services.document_reclassify_service.reclassify_documents',
					args: { names: names, dry_run: false },
					freeze: true,
					freeze_message: __('Applying reclassification…'),
					callback(r2) {
						if (!r2.message) return;
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
						if (onApplied) onApplied();
					}
				});
			});
		}
	});
}

function show_reclassify_preview(result, onConfirm) {
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
