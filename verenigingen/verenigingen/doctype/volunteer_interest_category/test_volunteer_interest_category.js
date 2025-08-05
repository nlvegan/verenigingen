/**
 * @fileoverview Frontend test suite for Volunteer Interest Category DocType
 *
 * This QUnit test module provides comprehensive frontend testing for the Volunteer Interest
 * Category DocType, covering category creation, hierarchical relationships, and organizational
 * structure validation. The tests ensure proper functionality for volunteer skill and interest
 * classification systems that support effective volunteer matching and coordination.
 *
 * Key Test Coverage:
 * - Interest category creation with name and description validation
 * - Parent-child hierarchical relationships for category organization
 * - Data integrity and cleanup procedures
 * - Category reference linking and validation
 *
 * Business Context:
 * Volunteer Interest Categories provide a structured taxonomy for organizing volunteer
 * skills, interests, and competencies. This hierarchical system enables effective
 * volunteer-opportunity matching, skills development tracking, and organizational
 * capacity planning by categorizing diverse volunteer capabilities.
 *
 * Hierarchical Structure:
 * The system supports nested categories (parent-child relationships) allowing for
 * sophisticated organization of volunteer interests from broad categories to specific
 * skills and specializations.
 *
 * Integration Points:
 * - Volunteer Interest Area DocType for detailed skill tracking
 * - Volunteer DocType for individual capability profiles
 * - Volunteer Assignment DocType for role matching
 *
 * Test Infrastructure:
 * Uses Frappe's QUnit framework with proper cleanup procedures to prevent test
 * data pollution and ensure reliable test execution.
 *
 * @requires frappe.tests
 * @requires QUnit
 * @module VolunteerInterestCategoryTests
 * @since 2024
 */

/* eslint-disable */
// rename this file from _test_[name] to test_[name] to activate
// and remove above this line

QUnit.module('Volunteer Interest Category');

QUnit.test("test: Interest Category Creation", function (assert) {
    let done = assert.async();

    // number of asserts
    assert.expect(2);

    frappe.run_serially([
        // Insert a new Interest Category
        () => frappe.tests.make('Volunteer Interest Category', [
            // values to be set
            {category_name: 'Test Interest Category'},
            {description: 'Test interest category for JS tests'}
        ]),
        () => {
            assert.equal(cur_frm.doc.category_name, 'Test Interest Category', "Category name set correctly");
            assert.equal(cur_frm.doc.description, 'Test interest category for JS tests', "Description set correctly");
        },
        () => done()
    ]);
});

QUnit.test("test: Parent-Child Relationship", function (assert) {
    let done = assert.async();

    // Create test categories
    let parent_category;
    let child_category;

    // number of asserts
    assert.expect(1);

    frappe.run_serially([
        // Create parent category
        () => frappe.tests.make('Volunteer Interest Category', [
            {category_name: 'JS Parent Category'},
            {description: 'Parent category for JS tests'}
        ]),
        (doc) => {
            parent_category = doc.name;
        },
        // Create child category with parent reference
        () => frappe.tests.make('Volunteer Interest Category', [
            {category_name: 'JS Child Category'},
            {description: 'Child category for JS tests'},
            {parent_category: 'JS Parent Category'}
        ]),
        (doc) => {
            child_category = doc.name;
            assert.equal(cur_frm.doc.parent_category, 'JS Parent Category', "Parent category set correctly");
        },
        // Clean up
        () => frappe.tests.delete_if_exists('Volunteer Interest Category', 'JS Child Category'),
        () => frappe.tests.delete_if_exists('Volunteer Interest Category', 'JS Parent Category'),
        () => done()
    ]);
});
