/**
 * @fileoverview Organization Document list view customization.
 *
 * Adds a "Reclassify from MijnRood folder" entry to the list-view Actions
 * menu, visible only to System Manager / Verenigingen Administrator. The
 * action takes the user's selected items and runs them through the same
 * dry-run → confirm preview → apply flow used by the form button (defined
 * in organization_document.js as window.verenigingen.run_reclassify_flow).
 *
 * If the form bundle is not loaded (user opens the list view first without
 * ever opening a form), falls back to a minimal direct apply flow without
 * the preview dialog.
 */
// Copyright (c) 2025, Veganisme.org and contributors

frappe.listview_settings['Organization Document'] = {
	onload(listview) {
		const roles = frappe.user_roles || [];
		const allowed = roles.includes('System Manager') || roles.includes('Verenigingen Administrator');
		if (!allowed) return;

		listview.page.add_actions_menu_item(__('Reclassify from MijnRood folder'), () => {
			const items = listview.get_checked_items();
			if (!items.length) {
				frappe.msgprint(__('Select at least one document.'));
				return;
			}
			const names = items.map(i => i.name);

			// Reuse the form's flow if loaded; otherwise call directly.
			if (window.verenigingen && window.verenigingen.run_reclassify_flow) {
				window.verenigingen.run_reclassify_flow(names, () => listview.refresh());
			} else {
				// The form bundle defines the helper; if a user opens the list
				// without ever opening a form, fall back to a minimal flow.
				frappe.call({
					method: 'verenigingen.mijnrood_sync.services.document_reclassify_service.reclassify_documents',
					args: { names: names, dry_run: false },
					freeze: true,
					callback(r) {
						if (!r.message) return;
						frappe.show_alert({
							message: __('Reclassified {0} documents.', [r.message.applied]),
							indicator: 'green'
						});
						listview.refresh();
					}
				});
			}
		});
	}
};
