/**
 * @fileoverview Frontend test suite for Membership DocType
 *
 * This QUnit test module provides comprehensive frontend testing for the Membership DocType,
 * covering membership creation, payment method handling, dues schedule generation, and
 * cancellation workflows. The tests validate critical business logic for membership
 * lifecycle management, payment processing, and member engagement tracking.
 *
 * Key Test Coverage:
 * - Membership creation with member association and automatic field population
 * - Payment method selection with SEPA Direct Debit mandate requirements
 * - Dues schedule automatic generation and visibility controls
 * - Membership cancellation eligibility and button availability
 * - Status transitions (Draft → Active) through submission workflow
 *
 * Business Context:
 * Memberships are the core revenue-generating entity linking members to payment
 * obligations and organizational benefits. These tests ensure the frontend properly
 * handles membership registration, payment setup, dues scheduling, and lifecycle
 * management that supports sustainable organizational funding.
 *
 * Integration Points:
 * - Member DocType for membership holder association
 * - Membership Type DocType for fee structure
 * - SEPA Mandate DocType for payment authorization
 * - Dues Schedule DocType for payment tracking
 *
 * Critical Business Rules Tested:
 * - Renewal date calculation (1 year from start date)
 * - SEPA mandate requirement for direct debit payments
 * - Automatic dues schedule generation upon submission
 * - Cancellation button availability for long-term memberships
 *
 * Test Infrastructure:
 * Uses Frappe's QUnit framework with serial test execution and automatic cleanup.
 * Creates complete member and membership data chains for realistic testing scenarios.
 *
 * @requires frappe.tests
 * @requires QUnit
 * @module MembershipTests
 * @since 2024
 */

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

// Test for dues schedule and payment section
QUnit.test("test: Membership - Dues Schedule", function (assert) {
	let done = assert.async();

	// number of asserts
	assert.expect(3);

	frappe.run_serially([
		// Create test member first (needed for membership)
		() => frappe.tests.make('Member', [
			{first_name: 'Dues'},
			{last_name: 'Test'},
			{email: 'dues.test@example.com'}
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

			// Check if dues schedule was created
			let duesScheduleField = cur_frm.get_field('dues_schedule');
			assert.ok(cur_frm.doc.dues_schedule, "Dues schedule should be created automatically");

			// Check if View Dues Schedule button exists
			let viewButton = $(cur_frm.fields_dict.view_dues_schedule.input);
			assert.ok(viewButton.is(':visible'), "View Dues Schedule button should be visible");
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
