// Custom button for Bank Transaction List to add MT940 import functionality

frappe.listview_settings['Bank Transaction'] = frappe.listview_settings['Bank Transaction'] || {};

// Add custom button to Bank Transaction list
frappe.listview_settings['Bank Transaction'].onload = function(listview) {

    // Add MT940 Import button
    listview.page.add_menu_item(__('Import MT940 File'), function() {
        // Open the MT940 import page
        window.open('/mt940_import', '_blank');
    }, true);

    // Alternative: Add as primary action button
    listview.page.add_primary_action(__('Import MT940'), function() {
        // Open MT940 import page in same tab
        frappe.set_route('/mt940_import');
    }, 'fa fa-upload');

    console.log('MT940 import buttons added to Bank Transaction list');
};
