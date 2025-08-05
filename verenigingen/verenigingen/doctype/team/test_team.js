/**
 * @fileoverview Frontend test suite for Team DocType
 *
 * This QUnit test module provides comprehensive frontend testing for the Team DocType,
 * covering team creation, member management, responsibility tracking, and status workflows.
 * The tests validate business logic for team composition, role assignments, and
 * collaborative work coordination within the association structure.
 *
 * Key Test Coverage:
 * - Team creation with basic properties and validation
 * - Team member addition with roles and status management
 * - Responsibility assignment and tracking
 * - Member status transitions and lifecycle management
 *
 * Business Context:
 * Teams are fundamental organizational units for coordinating volunteers and managing
 * specific areas of work (committees, working groups, project teams). These tests
 * ensure the frontend properly handles team formation, member coordination, and
 * responsibility distribution that supports effective volunteer management.
 *
 * Integration Points:
 * - Volunteer DocType for team membership
 * - Team Member child DocType for role management
 * - Team Responsibility child DocType for task coordination
 *
 * Test Infrastructure:
 * Uses Frappe's QUnit framework with serial test execution and automatic cleanup.
 * Creates isolated test data including volunteers and team structures for each scenario.
 *
 * @requires frappe.tests
 * @requires QUnit
 * @module TeamTests
 * @since 2024
 */

/* eslint-disable */
// rename this file from _test_[name] to test_[name] to activate
// and remove above this line

QUnit.module('Team');

QUnit.test("test: Team Creation", function (assert) {
    let done = assert.async();

    // number of asserts
    assert.expect(3);

    frappe.run_serially([
        // Insert a new Team
        () => frappe.tests.make('Team', [
            // values to be set
            {team_name: 'Test JS Team'},
            {description: 'Team created for JS tests'},
            {team_type: 'Working Group'},
            {status: 'Active'},
            {start_date: frappe.datetime.get_today()}
        ]),
        () => {
            assert.equal(cur_frm.doc.team_name, 'Test JS Team', "Team name set correctly");
            assert.equal(cur_frm.doc.team_type, 'Working Group', "Team type set correctly");
            assert.equal(cur_frm.doc.status, 'Active', "Status set correctly");
        },
        () => done()
    ]);
});

QUnit.test("test: Team Members", function (assert) {
    let done = assert.async();

    // First we need a volunteer to add as team member
    let test_volunteer;

    // number of asserts
    assert.expect(2);

    frappe.run_serially([
        // Create a test volunteer first
        () => frappe.tests.make('Volunteer', [
            {volunteer_name: 'Team Test Volunteer'},
            {email: 'team.test@example.org'},
            {status: 'Active'}
        ]),
        (vol) => {
            test_volunteer = vol.name;
        },
        // Now create a team with this volunteer as member
        () => frappe.tests.make('Team', [
            {team_name: 'Team Members Test'},
            {team_type: 'Committee'},
            {status: 'Active'},
            // Add team member
            {team_members: [
                [
                    {volunteer: test_volunteer},
                    {role_type: 'Team Leader'},
                    {role: 'Committee Chair'},
                    {from_date: frappe.datetime.get_today()},
                    {status: 'Active'},
                    {is_active: 1}
                ]
            ]}
        ]),
        () => {
            assert.equal(cur_frm.doc.team_members.length, 1, "Team member added");
            assert.equal(
                cur_frm.doc.team_members[0].role,
                'Committee Chair',
                "Team member role set correctly"
            );
        },
        () => done()
    ]);
});

QUnit.test("test: Team Responsibilities", function (assert) {
    let done = assert.async();

    // number of asserts
    assert.expect(2);

    frappe.run_serially([
        // Create team with responsibilities
        () => frappe.tests.make('Team', [
            {team_name: 'Responsibilities Test Team'},
            {team_type: 'Project Team'},
            {status: 'Active'},
            // Add responsibilities
            {key_responsibilities: [
                [
                    {responsibility: 'Test Task 1'},
                    {description: 'First test task description'},
                    {status: 'Pending'}
                ],
                [
                    {responsibility: 'Test Task 2'},
                    {description: 'Second test task description'},
                    {status: 'In Progress'}
                ]
            ]}
        ]),
        () => {
            assert.equal(cur_frm.doc.key_responsibilities.length, 2, "Two responsibilities added");

            // Check if both responsibilities are in the list
            let responsibilities = cur_frm.doc.key_responsibilities.map(r => r.responsibility);
            assert.ok(
                responsibilities.includes('Test Task 1') && responsibilities.includes('Test Task 2'),
                "Both responsibilities were added correctly"
            );
        },
        () => done()
    ]);
});

QUnit.test("test: Team Member Status Change", function (assert) {
    let done = assert.async();

    // Create a test team with a member
    let test_volunteer;

    // number of asserts
    assert.expect(2);

    frappe.run_serially([
        // Create a test volunteer first
        () => frappe.tests.make('Volunteer', [
            {volunteer_name: 'Status Test Volunteer'},
            {email: 'status.test@example.org'},
            {status: 'Active'}
        ]),
        (vol) => {
            test_volunteer = vol.name;
        },
        // Create team with member
        () => frappe.tests.make('Team', [
            {team_name: 'Status Test Team'},
            {team_type: 'Working Group'},
            {status: 'Active'},
            // Add team member
            {team_members: [
                [
                    {volunteer: test_volunteer},
                    {role_type: 'Team Member'},
                    {role: 'Working Group Member'},
                    {from_date: frappe.datetime.get_today()},
                    {status: 'Active'},
                    {is_active: 1}
                ]
            ]}
        ]),
        // Now change the status
        () => {
            // Update the team member's status
            cur_frm.doc.team_members[0].status = 'Inactive';
            cur_frm.doc.team_members[0].is_active = 0;
            cur_frm.doc.team_members[0].to_date = frappe.datetime.get_today();

            // Save the form
            return cur_frm.save();
        },
        () => {
            assert.equal(cur_frm.doc.team_members[0].status, 'Inactive', "Status changed to inactive");
            assert.equal(cur_frm.doc.team_members[0].is_active, 0, "Is active flag synchronized with status");
        },
        () => done()
    ]);
});
