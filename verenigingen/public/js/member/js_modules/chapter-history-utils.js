// Chapter Membership History utility functions for Member doctype

function setup_chapter_history_display(frm) {
	if (!frm.doc.name || frm.doc.__islocal) return;

	// Enhance the chapter membership history table display
	enhance_chapter_history_table(frm);
}


function enhance_chapter_history_table(frm) {
	if (!frm.fields_dict.chapter_membership_history) return;

	// Add custom styling and functionality to the chapter membership history table
	frm.fields_dict.chapter_membership_history.grid.get_field('status').get_query = function() {
		return {
			filters: [
				['name', 'in', ['Active', 'Completed', 'Terminated']]
			]
		};
	};

	// Color code status in the grid
	setTimeout(() => {
		const grid_wrapper = frm.fields_dict.chapter_membership_history.$wrapper;
		grid_wrapper.find('.grid-body .rows .grid-row').each(function() {
			const row = $(this);
			const status_cell = row.find('[data-fieldname="status"]');
			const status = status_cell.text().trim();

			if (status === 'Active') {
				status_cell.addClass('text-success font-weight-bold');
			} else if (status === 'Completed') {
				status_cell.addClass('text-primary');
			} else if (status === 'Terminated') {
				status_cell.addClass('text-danger');
			}
		});
	}, 1000);
}

function add_chapter_history_insights(frm) {
	if (!frm.doc.chapter_membership_history || frm.doc.chapter_membership_history.length === 0) {
		return;
	}

	// Count active vs completed memberships
	const active_count = frm.doc.chapter_membership_history.filter(h => h.status === 'Active').length;
	const completed_count = frm.doc.chapter_membership_history.filter(h => h.status === 'Completed').length;
	const terminated_count = frm.doc.chapter_membership_history.filter(h => h.status === 'Terminated').length;

	// Get unique chapters
	const chapters = [...new Set(frm.doc.chapter_membership_history.map(h => h.chapter_name))];

	// Add insights HTML after the chapter membership history section
	const insights_html = `
        <div class="chapter-history-insights" style="margin-top: 15px; padding: 10px; background-color: #f8f9fa; border-radius: 5px;">
            <h6><i class="fa fa-chart-bar"></i> ${__('Chapter History Insights')}</h6>
            <div class="row">
                <div class="col-md-4">
                    <span class="text-success font-weight-bold">${active_count}</span> ${__('Active')}
                </div>
                <div class="col-md-4">
                    <span class="text-primary font-weight-bold">${completed_count}</span> ${__('Completed')}
                </div>
                <div class="col-md-4">
                    <span class="text-danger font-weight-bold">${terminated_count}</span> ${__('Terminated')}
                </div>
            </div>
            <div style="margin-top: 10px;">
                <strong>${__('Associated Chapters')} (${chapters.length}):</strong> ${chapters.join(', ')}
            </div>
        </div>
    `;

	// Find the chapter membership history section and add insights
	const section = frm.fields_dict.chapter_membership_history_section;
	if (section && section.$wrapper) {
		// Remove existing insights
		section.$wrapper.find('.chapter-history-insights').remove();
		// Add new insights
		section.$wrapper.append(insights_html);
	}
}

// Export functions for use in member.js
window.ChapterHistoryUtils = {
	setup_chapter_history_display,
	enhance_chapter_history_table,
	add_chapter_history_insights
};
