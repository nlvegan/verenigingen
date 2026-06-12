// Copyright (c) 2025, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on('Event Contact Campaign', {
	refresh(frm) {
		// Add action buttons
		if (!frm.is_new()) {
			frm.add_custom_button(
				__('Import Contactable Members'),
				() => {
					frm.trigger('import_members');
				},
				__('Actions')
			);

			// Add distribution buttons if we have members
			if (frm.doc.contact_list && frm.doc.contact_list.length > 0) {
				frm.add_custom_button(
					__('Distribute Members'),
					() => {
						frm.trigger('distribute_members');
					},
					__('Actions')
				);

				frm.add_custom_button(
					__('Clear Assignments'),
					() => {
						frm.trigger('clear_assignments');
					},
					__('Actions')
				);
			}
		}

		// Refresh progress dashboard
		frm.trigger('update_progress_dashboard');

		// Set up assigned_to filter for child table
		frm.trigger('setup_assigned_to_filter');

		// Add status indicator colors
		if (frm.doc.status === 'Active') {
			frm.page.set_indicator(__('Active'), 'blue');
		} else if (frm.doc.status === 'Completed') {
			frm.page.set_indicator(__('Completed'), 'green');
		} else if (frm.doc.status === 'Cancelled') {
			frm.page.set_indicator(__('Cancelled'), 'red');
		}
	},

	owner_type(frm) {
		// Clear owner_reference when owner_type changes
		frm.set_value('owner_reference', null);

		// Update assigned_to filter
		frm.trigger('setup_assigned_to_filter');
	},

	owner_reference(frm) {
		// Update assigned_to filter when owner changes
		frm.trigger('setup_assigned_to_filter');
	},

	chapter(frm) {
		// Clear contact list when chapter changes (only if there are members)
		if (frm.doc.contact_list && frm.doc.contact_list.length > 0) {
			frappe.confirm(
				__(
					'Changing the chapter will clear the existing contact list. Continue?'
				),
				() => {
					frm.clear_table('contact_list');
					frm.refresh_field('contact_list');
					frm.trigger('update_progress_dashboard');
				},
				() => {
					// Revert to previous chapter
					frm.reload_doc();
				}
			);
		}

		// Auto-set owner_reference if owner_type is Chapter
		if (frm.doc.owner_type === 'Chapter' && frm.doc.chapter) {
			frm.set_value('owner_reference', frm.doc.chapter);
		}
	},

	setup_assigned_to_filter(frm) {
		// Set up filter for assigned_to field in child table
		// This restricts volunteer selection to team/chapter members

		if (frm.is_new()) { return; }

		frappe.call({
			method: 'verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.get_available_volunteers',
			args: {
				docname: frm.doc.name
			},
			callback(r) {
				if (r.message && r.message.length > 0) {
					const volunteer_ids = r.message.map((v) => v.name);

					frm.fields_dict.contact_list.grid.get_field(
						'assigned_to'
					).get_query = function () {
						return {
							filters: {
								name: ['in', volunteer_ids]
							}
						};
					};

					// Store for later use
					frm.available_volunteers = r.message;
				} else {
					// No filter if no volunteers available
					frm.fields_dict.contact_list.grid.get_field(
						'assigned_to'
					).get_query = function () {
						return {};
					};
					frm.available_volunteers = [];
				}
			}
		});
	},

	import_members(frm) {
		if (!frm.doc.chapter) {
			frappe.msgprint(__('Please select a chapter first'));
			return;
		}

		// First, get a count of available members
		frappe.call({
			method: 'verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.get_contactable_members',
			args: {
				chapter: frm.doc.chapter
			},
			callback(r) {
				if (r.message) {
					const members = r.message;
					const new_count = members.filter(
						(m) =>
							!frm.doc.contact_list
                            || !frm.doc.contact_list.find(
                            	(row) => row.member === m.member
                            )
					).length;

					if (new_count === 0) {
						if (members.length === 0) {
							frappe.msgprint(
								__(
									'No contactable members found for this chapter. Members must be active and have accepted optional communications.'
								)
							);
						} else {
							frappe.msgprint(
								__(
									'All {0} contactable members are already in the list.',
									[members.length]
								)
							);
						}
						return;
					}

					frappe.confirm(
						__(
							'Found {0} new contactable members. Add them to the campaign?',
							[new_count]
						),
						() => {
							frappe.call({
								method: 'verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.import_contactable_members',
								args: {
									docname: frm.doc.name
								},
								freeze: true,
								freeze_message: __('Importing members...'),
								callback(resp) {
									if (resp.message) {
										const result = resp.message;
										if (result.status === 'success') {
											frappe.show_alert(
												{
													message: result.message,
													indicator: 'green'
												},
												5
											);
										} else if (result.status === 'info') {
											frappe.show_alert(
												{
													message: result.message,
													indicator: 'blue'
												},
												5
											);
										} else {
											frappe.show_alert(
												{
													message: result.message,
													indicator: 'orange'
												},
												5
											);
										}
										frm.reload_doc();
									}
								}
							});
						}
					);
				}
			}
		});
	},

	distribute_members(frm) {
		// Check if we have volunteers available
		frappe.call({
			method: 'verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.get_available_volunteers',
			args: {
				docname: frm.doc.name
			},
			callback(r) {
				if (!r.message || r.message.length === 0) {
					frappe.msgprint(
						__(
							'No volunteers available. Please select a Team or Chapter as campaign owner first.'
						)
					);
					return;
				}

				const volunteers = r.message;

				// Show dialog to select which volunteers to include
				const fields = [
					{
						fieldtype: 'HTML',
						options: `<p>${__(
							'Select volunteers to distribute members among:'
						)}</p>`
					}
				];

				// Add checkbox for each volunteer
				volunteers.forEach((v, idx) => {
					fields.push({
						fieldtype: 'Check',
						fieldname: `vol_${idx}`,
						label: v.volunteer_name || v.name,
						default: 1
					});
				});

				const d = new frappe.ui.Dialog({
					title: __('Distribute Members'),
					fields,
					primary_action_label: __('Distribute'),
					primary_action() {
						const selected = [];
						volunteers.forEach((v, idx) => {
							if (d.get_value(`vol_${idx}`)) {
								selected.push(v.name);
							}
						});

						if (selected.length === 0) {
							frappe.msgprint(
								__('Please select at least one volunteer')
							);
							return;
						}

						d.hide();

						frappe.call({
							method: 'verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.distribute_members',
							args: {
								docname: frm.doc.name,
								volunteer_ids: JSON.stringify(selected)
							},
							freeze: true,
							freeze_message: __('Distributing members...'),
							callback(resp) {
								if (resp.message) {
									const result = resp.message;
									const indicator
                                        = result.status === 'success'
                                        	? 'green'
                                        	: result.status === 'info'
                                        		? 'blue'
                                        		: 'orange';

									frappe.show_alert(
										{
											message: result.message,
											indicator
										},
										5
									);

									if (result.distribution) {
										frappe.msgprint({
											title: __('Distribution Summary'),
											message: result.distribution,
											indicator: 'green'
										});
									}

									frm.reload_doc();
								}
							}
						});
					}
				});

				d.show();
			}
		});
	},

	clear_assignments(frm) {
		frappe.confirm(
			__('Are you sure you want to clear all volunteer assignments?'),
			() => {
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.clear_assignments',
					args: {
						docname: frm.doc.name
					},
					freeze: true,
					freeze_message: __('Clearing assignments...'),
					callback(r) {
						if (r.message) {
							frappe.show_alert(
								{
									message: r.message.message,
									indicator:
                                        r.message.status === 'success'
                                        	? 'green'
                                        	: 'blue'
								},
								5
							);
							frm.reload_doc();
						}
					}
				});
			}
		);
	},

	update_progress_dashboard(frm) {
		if (frm.is_new()) {
			// Show empty state for new documents
			frm.set_df_property(
				'progress_dashboard',
				'options',
				`<div class="progress-dashboard" style="padding: 15px; background: #f8f9fa; border-radius: 8px; margin-bottom: 15px;">
                    <p style="color: #6c757d; margin: 0;">
                        <strong>Save the document and import members to see progress.</strong>
                    </p>
                </div>`
			);
			return;
		}

		frappe.call({
			method: 'verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.get_progress_dashboard',
			args: {
				docname: frm.doc.name
			},
			callback(r) {
				if (r.message) {
					frm.set_df_property('progress_dashboard', 'options', r.message);
				}
			}
		});
	},

	contact_list_on_form_rendered(frm) {
		// Refresh dashboard when contact list changes
		frm.trigger('update_progress_dashboard');
	}
});

// Child table events
frappe.ui.form.on('Event Contact Campaign Member', {
	contacted(frm, cdt, cdn) {
		const row = locals[cdt][cdn];

		if (row.contacted) {
			// Auto-fill contacted date and user if not set
			if (!row.contacted_date) {
				frappe.model.set_value(
					cdt,
					cdn,
					'contacted_date',
					frappe.datetime.now_datetime()
				);
			}
			if (!row.contacted_by) {
				frappe.model.set_value(
					cdt,
					cdn,
					'contacted_by',
					frappe.session.user
				);
			}
			// Set contact method to "Other" if still "Not Contacted"
			if (row.contact_method === 'Not Contacted') {
				frappe.model.set_value(cdt, cdn, 'contact_method', 'Other');
			}
		} else {
			// Clear contact fields when unchecked
			frappe.model.set_value(cdt, cdn, 'contact_method', 'Not Contacted');
		}

		// Trigger save to update progress
		frm.dirty();
	},

	response(frm, cdt, cdn) {
		const row = locals[cdt][cdn];

		// Auto-fill response date when response is set
		if (
			row.response
            && row.response !== 'No Response'
            && !row.response_date
		) {
			frappe.model.set_value(
				cdt,
				cdn,
				'response_date',
				frappe.datetime.get_today()
			);
		}

		// Trigger save to update progress
		frm.dirty();
	},

	contact_list_remove(frm) {
		// Update dashboard when a row is removed
		frm.dirty();
	}
});
