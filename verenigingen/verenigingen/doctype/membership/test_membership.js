/* eslint-disable */
// rename this file from _test_[name] to test_[name] to activate
// and remove above this line

QUnit.test("test: Membership", function (assert) {
	let done = assert.async();

	// number of asserts
	assert.expect(5);

	frappe.run_serially([
		// Create test member first (needed for membership)
		() => frappe.tests.make('Member', [
			{first_name: 'Membership'},
			{last_name: 'Test Member'},
			{email: 'membership.test@example.com'}
		]),

		// Insert a new Membership
		() => frappe.tests.make('Membership', [
			{member: cur_frm.doc.name},  // Use member created above
			{membership_type: 'Test Type'},  // This membership type must exist
			{start_date: frappe.datetime.get_today()},
			{payment_method: 'Bank Transfer'}
		]),
		() => frappe.timeout(1),
		() => {
			assert.equal(cur_frm.doc.member_name, 'Membership Test Member', "Member name should be fetched automatically");
			assert.equal(cur_frm.doc.status, 'Draft', "Initial status should be Draft");

			// Check if renewal date was calculated (must be 1 year after start date)
			const startDate = frappe.datetime.str_to_obj(cur_frm.doc.start_date);
			const renewalDate = frappe.datetime.str_to_obj(cur_frm.doc.renewal_date);
			const yearDiff = renewalDate.getFullYear() - startDate.getFullYear();

			assert.equal(yearDiff, 1, "Renewal date should be 1 year after start date");
		},

		// Test payment method change
		() => frappe.tests.set_form_values(cur_frm, [
			{payment_method: 'SEPA Direct Debit'}
		]),
		() => frappe.timeout(1),
		() => {
			// Check if mandate section is visible
			let mandateField = cur_frm.get_field('sepa_mandate');
			assert.ok(mandateField.df.reqd, "SEPA Mandate should be required for SEPA Direct Debit");

			// Check if mandate section is visible
			let mandateSection = $(cur_frm.fields_dict.mandate_section.wrapper);
			assert.ok(mandateSection.is(':visible'), "Mandate section should be visible for SEPA Direct Debit");
		},
		() => done()
	]);
});

// Test for subscription and payment section
QUnit.test("test: Membership - Subscription", function (assert) {
	let done = assert.async();

	// number of asserts
	assert.expect(3);

	frappe.run_serially([
		// Create test member first (needed for membership)
		() => frappe.tests.make('Member', [
			{first_name: 'Subscription'},
			{last_name: 'Test'},
			{email: 'subscription.test@example.com'}
		]),

		// Insert and submit a membership
		() => frappe.tests.make('Membership', [
			{member: cur_frm.doc.name},  // Use member created above
			{membership_type: 'Test Type'},
			{start_date: frappe.datetime.get_today()},
			{payment_method: 'Bank Transfer'}
		]),
		() => cur_frm.savesubmit(),
		() => frappe.timeout(2),
		() => cur_frm.refresh(),
		() => frappe.timeout(1),
		() => {
			// After submission, status should be Active
			assert.equal(cur_frm.doc.status, 'Active', "Status should be Active after submission");

			// Check if subscription was created
			let subscriptionField = cur_frm.get_field('subscription');
			assert.ok(cur_frm.doc.subscription, "Subscription should be created automatically");

			// Check if View Subscription button exists
			let viewButton = $(cur_frm.fields_dict.view_subscription.input);
			assert.ok(viewButton.is(':visible'), "View Subscription button should be visible");
		},
		() => done()
	]);
});

// Test for cancellation dialog
QUnit.test("test: Membership - Cancellation", function (assert) {
	let done = assert.async();

	// number of asserts
	assert.expect(2);

	// Simulate a membership that's been active for over a year
	let oneYearAgo = frappe.datetime.add_months(frappe.datetime.get_today(), -13);

	frappe.run_serially([
		// Create test member first (needed for membership)
		() => frappe.tests.make('Member', [
			{first_name: 'Cancellation'},
			{last_name: 'Test'},
			{email: 'cancellation.test@example.com'}
		]),

		// Insert and submit a membership with start date over a year ago
		() => frappe.tests.make('Membership', [
			{member: cur_frm.doc.name},
			{membership_type: 'Test Type'},
			{start_date: oneYearAgo},
			{payment_method: 'Bank Transfer'}
		]),
		() => cur_frm.savesubmit(),
		() => frappe.timeout(2),
		() => cur_frm.refresh(),
		() => frappe.timeout(1),
		() => {
			// Check if Cancel Membership button exists and is not disabled
			let cancelButton = cur_frm.page.inner_toolbar.find('button:contains("Cancel Membership")');
			assert.ok(cancelButton.length, "Cancel Membership button should exist");
			assert.ok(!cancelButton.hasClass('btn-default'), "Cancel button should not be disabled");
		},
		() => done()
	]);
});
