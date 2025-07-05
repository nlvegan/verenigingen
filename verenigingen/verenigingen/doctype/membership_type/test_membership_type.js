/* eslint-disable */
// rename this file from _test_[name] to test_[name] to activate
// and remove above this line

QUnit.test("test: Membership Type", function (assert) {
	let done = assert.async();

	// number of asserts
	assert.expect(5);

	frappe.run_serially([
		// insert a new Membership Type
		() => frappe.tests.make('Membership Type', [
			// values to be set
			{membership_type_name: 'Test Gold'},
			{subscription_period: 'Annual'},
			{amount: 120},
			{currency: 'EUR'}
		]),
		() => {
			assert.equal(cur_frm.doc.membership_type_name, 'Test Gold');
			assert.equal(cur_frm.doc.subscription_period, 'Annual');
			assert.equal(cur_frm.doc.amount, 120);
		},

		// Test subscription period change
		() => frappe.tests.set_form_values(cur_frm, [
			{subscription_period: 'Custom'}
		]),
		() => frappe.timeout(1),
		() => {
			// Check if subscription_period_in_months field is visible and required
			let periodMonthsField = cur_frm.get_field('subscription_period_in_months');
			assert.ok($(periodMonthsField.wrapper).is(':visible'), "Months field should be visible for Custom period");
			assert.ok(periodMonthsField.df.reqd, "Months field should be required for Custom period");
		},
		() => done()
	]);
});

// Test for default membership handling
QUnit.test("test: Membership Type - Default Setting", function (assert) {
	let done = assert.async();

	// Create first membership type as default
	frappe.tests.make('Membership Type', [
		{membership_type_name: 'Default Type 1'},
		{subscription_period: 'Annual'},
		{amount: 100},
		{currency: 'EUR'},
		{default_for_new_members: 1}
	]);

	// number of asserts
	assert.expect(3);

	frappe.run_serially([
		// insert a second membership type as default
		() => frappe.tests.make('Membership Type', [
			{membership_type_name: 'Default Type 2'},
			{subscription_period: 'Annual'},
			{amount: 120},
			{currency: 'EUR'},
			{default_for_new_members: 1}
		]),
		() => frappe.timeout(1),
		() => {
			assert.equal(cur_frm.doc.membership_type_name, 'Default Type 2');
			assert.equal(cur_frm.doc.default_for_new_members, 1, "Second type should be set as default");
		},

		// Verify first type is no longer default by loading it
		() => frappe.set_route('Form', 'Membership Type', 'Default Type 1'),
		() => frappe.timeout(1),
		() => {
			assert.equal(cur_frm.doc.default_for_new_members, 0, "First type should no longer be default");
		},
		() => done()
	]);
});

// Test for subscription plan creation
QUnit.test("test: Membership Type - Subscription Plan", function (assert) {
	let done = assert.async();

	// number of asserts
	assert.expect(2);

	frappe.run_serially([
		// insert a new Membership Type
		() => frappe.tests.make('Membership Type', [
			{membership_type_name: 'Plan Test Type'},
			{subscription_period: 'Annual'},
			{amount: 150},
			{currency: 'EUR'}
		]),
		() => frappe.timeout(1),
		() => {
			// Check if Create Subscription Plan button exists
			let planButton = cur_frm.page.inner_toolbar.find('button:contains("Create Subscription Plan")');
			assert.ok(planButton.length, "Create Subscription Plan button should exist");

			// Initially subscription_plan should be empty
			assert.ok(!cur_frm.doc.subscription_plan, "Subscription Plan field should be empty");
		},
		() => done()
	]);
});
