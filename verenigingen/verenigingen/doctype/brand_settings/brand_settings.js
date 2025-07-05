// Copyright (c) 2025, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on('Brand Settings', {
	refresh(frm) {
		// Add Owl Theme integration buttons
		if (frm.doc.is_active) {
			frm.add_custom_button(__('Sync to Owl Theme'), function() {
				sync_to_owl_theme(frm);
			}, __('Owl Theme'));

			frm.add_custom_button(__('Check Owl Theme Status'), function() {
				check_owl_theme_status(frm);
			}, __('Owl Theme'));

			frm.add_custom_button(__('Force Rebuild CSS'), function() {
				force_rebuild_css(frm);
			}, __('Debug'));
		}

		// Add color preview
		if (frm.doc.name) {
			add_color_preview(frm);
		}
	},

	is_active(frm) {
		// Refresh form when active status changes to show/hide buttons
		if (frm.doc.is_active) {
			frm.refresh();
		}
	},

	// Auto-preview color changes
	primary_color(frm) { update_color_preview(frm); },
	secondary_color(frm) { update_color_preview(frm); },
	accent_color(frm) { update_color_preview(frm); },
	background_primary_color(frm) { update_color_preview(frm); },
	background_secondary_color(frm) { update_color_preview(frm); }
});

function sync_to_owl_theme(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.brand_settings.brand_settings.sync_brand_settings_to_owl_theme',
		callback: function(r) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: __('Success'),
					message: r.message.message,
					indicator: 'green'
				});
			} else {
				frappe.msgprint({
					title: __('Error'),
					message: r.message ? r.message.message : 'Unknown error occurred',
					indicator: 'red'
				});
			}
		}
	});
}

function check_owl_theme_status(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.brand_settings.brand_settings.check_owl_theme_integration',
		callback: function(r) {
			if (r.message) {
				let status = r.message;
				let message = `
					<div style="font-size: 14px;">
						<p><strong>Owl Theme Installed:</strong> ${status.installed ? 'Yes' : 'No'}</p>
						${status.installed ? `
							<p><strong>Settings Exist:</strong> ${status.owl_settings_exists ? 'Yes' : 'No'}</p>
							<p><strong>Active Brand Settings:</strong> ${status.active_brand_settings ? status.active_brand_settings.settings_name : 'None'}</p>
						` : ''}
						<p><strong>Status:</strong> ${status.message}</p>
						${status.error ? `<p style="color: red;"><strong>Error:</strong> ${status.error}</p>` : ''}
					</div>
				`;

				frappe.msgprint({
					title: __('Owl Theme Integration Status'),
					message: message,
					indicator: status.installed ? 'blue' : 'orange'
				});
			}
		}
	});
}

function add_color_preview(frm) {
	// Add a color preview section
	if (!frm.fields_dict.color_preview) {
		let preview_html = `
			<div id="brand-color-preview" style="margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
				<h4>Color Preview</h4>
				<div style="display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px;">
					<div class="color-sample" data-field="primary_color">
						<div class="color-box" style="width: 60px; height: 40px; border-radius: 4px; border: 1px solid #ccc;"></div>
						<small style="display: block; text-align: center; margin-top: 5px;">Primary</small>
					</div>
					<div class="color-sample" data-field="secondary_color">
						<div class="color-box" style="width: 60px; height: 40px; border-radius: 4px; border: 1px solid #ccc;"></div>
						<small style="display: block; text-align: center; margin-top: 5px;">Secondary</small>
					</div>
					<div class="color-sample" data-field="accent_color">
						<div class="color-box" style="width: 60px; height: 40px; border-radius: 4px; border: 1px solid #ccc;"></div>
						<small style="display: block; text-align: center; margin-top: 5px;">Accent</small>
					</div>
				</div>
			</div>
		`;

		$(frm.layout.wrapper).find('.form-layout').append(preview_html);
		update_color_preview(frm);
	}
}

function update_color_preview(frm) {
	// Update color preview boxes
	setTimeout(() => {
		$('#brand-color-preview .color-sample').each(function() {
			let field = $(this).data('field');
			let color = frm.doc[field];
			if (color) {
				$(this).find('.color-box').css('background-color', color);
			}
		});
	}, 100);
}

function force_rebuild_css(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.brand_settings.brand_settings.force_rebuild_css',
		callback: function(r) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: __('Success'),
					message: r.message.message + `<br><small>CSS length: ${r.message.css_length} characters</small>`,
					indicator: 'green'
				});
			} else {
				frappe.msgprint({
					title: __('Error'),
					message: r.message ? r.message.message : 'Unknown error occurred',
					indicator: 'red'
				});
			}
		}
	});
}
