/* eslint-disable */
// rename this file from _test_[name] to test_[name] to activate
// and remove above this line

QUnit.module('Volunteer Activity');

QUnit.test("test: Volunteer Activity Creation", function (assert) {
    let done = assert.async();

    // First we need a volunteer to associate with the activity
    let test_volunteer;

    // number of asserts
    assert.expect(4);

    frappe.run_serially([
        // Create a test volunteer first
        () => frappe.tests.make('Volunteer', [
            {volunteer_name: 'Activity Test Volunteer'},
            {email: 'activity.test@example.org'},
            {status: 'Active'}
        ]),
        (vol) => {
            test_volunteer = vol.name;
        },
        // Now create a volunteer activity
        () => frappe.tests.make('Volunteer Activity', [
            {volunteer: test_volunteer},
            {activity_type: 'Project'},
            {role: 'Project Coordinator'},
            {description: 'Test volunteer activity'},
            {status: 'Active'},
            {start_date: frappe.datetime.get_today()}
        ]),
        () => {
            assert.equal(cur_frm.doc.volunteer, test_volunteer, "Volunteer set correctly");
            assert.equal(cur_frm.doc.activity_type, 'Project', "Activity type set correctly");
            assert.equal(cur_frm.doc.role, 'Project Coordinator', "Role set correctly");
            assert.equal(cur_frm.doc.status, 'Active', "Status set correctly");
        },
        () => done()
    ]);
});

QUnit.test("test: Volunteer Activity Completion", function (assert) {
    let done = assert.async();

    // First we need a volunteer to associate with the activity
    let test_volunteer;
    let test_activity;

    // number of asserts
    assert.expect(3);

    frappe.run_serially([
        // Create a test volunteer first
        () => frappe.tests.make('Volunteer', [
            {volunteer_name: 'Completion Test Volunteer'},
            {email: 'completion.test@example.org'},
            {status: 'Active'}
        ]),
        (vol) => {
            test_volunteer = vol.name;
        },
        // Now create a volunteer activity
        () => frappe.tests.make('Volunteer Activity', [
            {volunteer: test_volunteer},
            {activity_type: 'Event'},
            {role: 'Event Organizer'},
            {description: 'Test completion activity'},
            {status: 'Active'},
            {start_date: frappe.datetime.get_today()}
        ]),
        (act) => {
            test_activity = act.name;

            // Update activity to completed
            cur_frm.doc.status = 'Completed';
            cur_frm.doc.end_date = frappe.datetime.get_today();
            cur_frm.doc.actual_hours = 5;

            // Save the form
            return cur_frm.save();
        },
        () => {
            assert.equal(cur_frm.doc.status, 'Completed', "Status changed to completed");
            assert.equal(cur_frm.doc.end_date, frappe.datetime.get_today(), "End date set correctly");
            assert.equal(cur_frm.doc.actual_hours, 5, "Actual hours set correctly");
        },
        () => done()
    ]);
});

QUnit.test("test: Volunteer Activity with Reference", function (assert) {
    let done = assert.async();

    // First we need a volunteer to associate with the activity
    let test_volunteer;

    // number of asserts
    assert.expect(2);

    frappe.run_serially([
        // Create a test volunteer first
        () => frappe.tests.make('Volunteer', [
            {volunteer_name: 'Reference Test Volunteer'},
            {email: 'reference.test@example.org'},
            {status: 'Active'}
        ]),
        (vol) => {
            test_volunteer = vol.name;
        },
        // Now create a volunteer activity with reference
        () => frappe.tests.make('Volunteer Activity', [
            {volunteer: test_volunteer},
            {activity_type: 'Event'},
            {role: 'Event Support'},
            {description: 'Test reference activity'},
            {status: 'Active'},
            {start_date: frappe.datetime.get_today()},
            {reference_doctype: 'Team'},
            {reference_name: 'Test Team'}  // Assumes a team with this name exists or will use a mock
        ]),
        () => {
            assert.equal(cur_frm.doc.reference_doctype, 'Team', "Reference doctype set correctly");
            assert.equal(cur_frm.doc.reference_name, 'Test Team', "Reference name set correctly");
        },
        () => done()
    ]);
});
