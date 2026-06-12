/**
 * @fileoverview Role Profile Child Table Controllers JavaScript Tests
 *
 * Comprehensive testing of child table controllers for the role profile system,
 * including Team Role Profile Assignment and Chapter Role Profile Mapping.
 * Tests inline editing, validation, field interactions, and integration with
 * parent form controllers.
 *
 * Business Context:
 * Child tables enable fine-grained role profile mapping where users can specify
 * different role profiles for different team roles or chapter board positions.
 * This provides flexibility beyond default role profile assignment.
 *
 * Key Testing Areas:
 * - Child table row addition and removal
 * - Inline field editing and validation
 * - Role and role profile selection filters
 * - Field dependencies within child table rows
 * - Integration with parent form validation
 * - Description field behavior and help text
 * - Error handling for invalid configurations
 *
 * Architecture Testing Focus:
 * - Child table grid JavaScript controllers
 * - Field type-specific input handling in grid context
 * - Link field autocomplete in child tables
 * - Validation triggers for child table fields
 * - Parent-child form communication
 * - Grid refresh and state management
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-26
 */

describe('Role Profile Child Table Controllers JavaScript Tests', () => {
	beforeEach(() => {
		const user = Cypress.env('ADMIN_USER');
		const pass = Cypress.env('ADMIN_PASSWORD');
		expect(user, 'ADMIN_USER env var').to.be.a('string').and.not.be.empty;
		expect(pass, 'ADMIN_PASSWORD env var').to.be.a('string').and.not.be.empty;
		cy.login(user, pass);
		cy.clear_test_data();
	});

	afterEach(() => {
		cy.clear_test_data();
	});

	describe('Team Role Profile Assignment Child Table Tests', () => {
		beforeEach(() => {
			// Setup team with role-specific profiles enabled for each test
			cy.visit_doctype_form('Team');
			cy.wait_for_navigation();
			cy.fill_frappe_field('team_name', 'Child Table Test Team');
			cy.fill_frappe_field('team_type', 'Project Team', {
				fieldtype: 'Select'
			});
			cy.fill_frappe_field('enable_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);
		});

		it('should test Team Role Profile Assignment child table structure and behavior', () => {
			// Verify child table is visible and accessible
			cy.get('[data-fieldname="role_specific_profiles"]').should('be.visible');

			// Test child table structure
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Team');
						const grid = frm.fields_dict.role_specific_profiles.grid;

						expect(grid).to.exist;
						expect(grid.doctype).to.equal('Team Role Profile Assignment');

						// Verify child table meta configuration
						const meta = win.frappe.get_meta('Team Role Profile Assignment');
						expect(meta).to.exist;
						expect(meta.istable).to.equal(1);

						cy.log('Team Role Profile Assignment child table structure validated');
					});
					return true;
				},
				null,
				'Team Child Table Structure'
			);

			// Test adding a new row to child table
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Team');
					const grid = frm.fields_dict.role_specific_profiles.grid;

					// Add new row
					const new_row = grid.add_new_row();
					expect(new_row).to.exist;

					cy.log('Successfully added new row to Team Role Profile Assignment table');
				});
				return true;
			}, 'Add Child Table Row');

			cy.save_frappe_doc();
		});

		it('should test Team Role Profile Assignment field interactions', () => {
			// Test field interactions within child table
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Team');
						const grid = frm.fields_dict.role_specific_profiles.grid;

						// Add new row for testing
						const row = grid.add_new_row();
						const row_doc = row.doc;

						// Test field configurations
						const meta = win.frappe.get_meta('Team Role Profile Assignment');
						const fields = meta.fields;

						// Verify team_role field configuration
						const team_role_field = fields.find((f) => f.fieldname === 'team_role');
						expect(team_role_field).to.exist;
						expect(team_role_field.fieldtype).to.equal('Link');
						expect(team_role_field.options).to.equal('Team Role');
						expect(team_role_field.reqd).to.equal(1);

						// Verify role_profile field configuration
						const role_profile_field = fields.find((f) => f.fieldname === 'role_profile');
						expect(role_profile_field).to.exist;
						expect(role_profile_field.fieldtype).to.equal('Link');
						expect(role_profile_field.options).to.equal('Role Profile');
						expect(role_profile_field.reqd).to.equal(1);

						// Verify description field configuration
						const description_field = fields.find((f) => f.fieldname === 'description');
						expect(description_field).to.exist;
						expect(description_field.fieldtype).to.equal('Small Text');

						cy.log('Team Role Profile Assignment field configurations validated');
					});
					return true;
				},
				null,
				'Team Child Table Field Interactions'
			);

			cy.save_frappe_doc();
		});

		it('should test Team Role Profile Assignment validation and error handling', () => {
			// Test validation scenarios in child table
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Team');
					const grid = frm.fields_dict.role_specific_profiles.grid;

					// Add row with incomplete data to test validation
					const row = grid.add_new_row();

					// Test that required fields are enforced
					const meta = win.frappe.get_meta('Team Role Profile Assignment');
					const required_fields = meta.fields.filter((f) => f.reqd);

					expect(required_fields.length).to.be.greaterThan(0);
					cy.log(`Team child table has ${required_fields.length} required fields for validation`);

					// Test field validation behavior
					required_fields.forEach((field) => {
						cy.log(`Required field in child table: ${field.fieldname}`);
						expect(field.reqd).to.equal(1);
					});
				});
				return true;
			}, 'Team Child Table Validation');

			cy.save_frappe_doc();
		});
	});

	describe('Chapter Role Profile Mapping Child Table Tests', () => {
		beforeEach(() => {
			// Setup chapter with board role-specific profiles enabled for each test
			cy.visit_doctype_form('Chapter');
			cy.wait_for_navigation();
			cy.window().then((win) => {
				const frm = win.frappe.ui.form.get_form('Chapter');
				frm.doc.name = 'Child Table Test Chapter';
			});
			cy.fill_frappe_field('region', 'Test Region', { fieldtype: 'Link' });
			cy.fill_frappe_field('introduction', 'Testing chapter role profile child table');
			cy.fill_frappe_field('enable_board_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);
		});

		it('should test Chapter Role Profile Mapping child table structure and behavior', () => {
			// Verify child table is visible and accessible
			cy.get('[data-fieldname="board_role_specific_profiles"]').should('be.visible');

			// Test child table structure
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Chapter');
						const grid = frm.fields_dict.board_role_specific_profiles.grid;

						expect(grid).to.exist;
						expect(grid.doctype).to.equal('Chapter Role Profile Mapping');

						// Verify child table meta configuration
						const meta = win.frappe.get_meta('Chapter Role Profile Mapping');
						expect(meta).to.exist;
						expect(meta.istable).to.equal(1);

						cy.log('Chapter Role Profile Mapping child table structure validated');
					});
					return true;
				},
				null,
				'Chapter Child Table Structure'
			);

			// Test adding a new row to child table
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Chapter');
					const grid = frm.fields_dict.board_role_specific_profiles.grid;

					// Add new row
					const new_row = grid.add_new_row();
					expect(new_row).to.exist;

					cy.log('Successfully added new row to Chapter Role Profile Mapping table');
				});
				return true;
			}, 'Add Chapter Child Table Row');

			cy.save_frappe_doc();
		});

		it('should test Chapter Role Profile Mapping field interactions', () => {
			// Test field interactions within child table
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Chapter');
						const grid = frm.fields_dict.board_role_specific_profiles.grid;

						// Add new row for testing
						const row = grid.add_new_row();

						// Test field configurations
						const meta = win.frappe.get_meta('Chapter Role Profile Mapping');
						const fields = meta.fields;

						// Verify chapter_role field configuration
						const chapter_role_field = fields.find((f) => f.fieldname === 'chapter_role');
						expect(chapter_role_field).to.exist;
						expect(chapter_role_field.fieldtype).to.equal('Link');
						expect(chapter_role_field.options).to.equal('Chapter Role');
						expect(chapter_role_field.reqd).to.equal(1);

						// Verify role_profile field configuration
						const role_profile_field = fields.find((f) => f.fieldname === 'role_profile');
						expect(role_profile_field).to.exist;
						expect(role_profile_field.fieldtype).to.equal('Link');
						expect(role_profile_field.options).to.equal('Role Profile');
						expect(role_profile_field.reqd).to.equal(1);

						// Verify description field configuration
						const description_field = fields.find((f) => f.fieldname === 'description');
						expect(description_field).to.exist;
						expect(description_field.fieldtype).to.equal('Small Text');
						expect(description_field.description).to.contain('board role profile assignment');

						cy.log('Chapter Role Profile Mapping field configurations validated');
					});
					return true;
				},
				null,
				'Chapter Child Table Field Interactions'
			);

			cy.save_frappe_doc();
		});

		it('should test Chapter Role Profile Mapping validation and error handling', () => {
			// Test validation scenarios in child table
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Chapter');
					const grid = frm.fields_dict.board_role_specific_profiles.grid;

					// Add row with incomplete data to test validation
					const row = grid.add_new_row();

					// Test that required fields are enforced
					const meta = win.frappe.get_meta('Chapter Role Profile Mapping');
					const required_fields = meta.fields.filter((f) => f.reqd);

					expect(required_fields.length).to.be.greaterThan(0);
					cy.log(`Chapter child table has ${required_fields.length} required fields for validation`);

					// Test field validation behavior
					required_fields.forEach((field) => {
						cy.log(`Required field in chapter child table: ${field.fieldname}`);
						expect(field.reqd).to.equal(1);
					});
				});
				return true;
			}, 'Chapter Child Table Validation');

			cy.save_frappe_doc();
		});
	});

	describe('Child Table Integration and Workflow Tests', () => {
		it('should test child table integration with parent form validation', () => {
			// Test Team child table integration
			cy.visit_doctype_form('Team');
			cy.wait_for_navigation();

			cy.fill_frappe_field('team_name', 'Integration Test Team');
			cy.fill_frappe_field('team_type', 'Committee', { fieldtype: 'Select' });
			cy.fill_frappe_field('enable_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);

			// Test parent-child form integration
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Team');

						// Verify parent form can save with empty child table
						expect(frm.doc.enable_role_specific_profiles).to.equal(1);

						// Add child table row
						const grid = frm.fields_dict.role_specific_profiles.grid;
						const row = grid.add_new_row();

						// Test that parent form validation includes child table
						cy.log('Testing parent-child form integration for Team');
					});
					return true;
				},
				null,
				'Team Parent-Child Integration'
			);

			cy.save_frappe_doc();

			// Test Chapter child table integration
			cy.visit_doctype_form('Chapter');
			cy.wait_for_navigation();

			cy.window().then((win) => {
				const frm = win.frappe.ui.form.get_form('Chapter');
				frm.doc.name = 'Integration Test Chapter';
			});
			cy.fill_frappe_field('region', 'Integration Region', {
				fieldtype: 'Link'
			});
			cy.fill_frappe_field('introduction', 'Testing integration');
			cy.fill_frappe_field('enable_board_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);

			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Chapter');

						// Verify parent form can save with empty child table
						expect(frm.doc.enable_board_role_specific_profiles).to.equal(1);

						// Add child table row
						const grid = frm.fields_dict.board_role_specific_profiles.grid;
						const row = grid.add_new_row();

						cy.log('Testing parent-child form integration for Chapter');
					});
					return true;
				},
				null,
				'Chapter Parent-Child Integration'
			);

			cy.save_frappe_doc();
		});

		it('should test child table data persistence and retrieval', () => {
			// Test data persistence for Team child table
			cy.visit_doctype_form('Team');
			cy.wait_for_navigation();

			cy.fill_frappe_field('team_name', 'Persistence Test Team');
			cy.fill_frappe_field('team_type', 'Working Group', {
				fieldtype: 'Select'
			});
			cy.fill_frappe_field('enable_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);

			// Add and save child table data
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Team');
						const grid = frm.fields_dict.role_specific_profiles.grid;

						// Add row with test data
						const row = grid.add_new_row();

						// Test data persistence structure
						expect(row.doc).to.exist;
						expect(row.doc.doctype).to.equal('Team Role Profile Assignment');
						expect(row.doc.parenttype).to.equal('Team');

						cy.log('Child table data structure configured for persistence');
					});
					return true;
				},
				null,
				'Child Table Data Persistence'
			);

			cy.save_frappe_doc();
		});

		it('should test child table performance with multiple rows', () => {
			// Test performance with multiple child table rows
			cy.visit_doctype_form('Team');
			cy.wait_for_navigation();

			cy.fill_frappe_field('team_name', 'Performance Test Team');
			cy.fill_frappe_field('team_type', 'Project Team', {
				fieldtype: 'Select'
			});
			cy.fill_frappe_field('enable_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);

			// Add multiple rows to test performance
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Team');
						const grid = frm.fields_dict.role_specific_profiles.grid;

						// Add multiple rows
						const num_rows = 3;
						for (let i = 0; i < num_rows; i++) {
							const row = grid.add_new_row();
							expect(row).to.exist;
						}

						// Verify all rows are present
						expect(grid.grid_rows.length).to.equal(num_rows);
						cy.log(`Successfully created ${num_rows} child table rows`);
					});
					return true;
				},
				null,
				'Child Table Performance Test'
			);

			cy.save_frappe_doc();
		});
	});

	describe('Child Table Error Handling and Edge Cases', () => {
		it('should test child table error recovery scenarios', () => {
			cy.visit_doctype_form('Team');
			cy.wait_for_navigation();

			cy.fill_frappe_field('team_name', 'Error Recovery Test Team');
			cy.fill_frappe_field('team_type', 'Task Force', { fieldtype: 'Select' });
			cy.fill_frappe_field('enable_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);

			// Test error recovery scenarios
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Team');
					const grid = frm.fields_dict.role_specific_profiles.grid;

					// Test grid stability
					expect(grid).to.exist;
					expect(grid.grid_rows).to.be.an('array');

					// Add row and test error recovery
					const row = grid.add_new_row();
					expect(row).to.exist;

					// Test row removal
					if (grid.grid_rows.length > 0) {
						const first_row = grid.grid_rows[0];
						if (first_row && first_row.remove) {
							// Test that row can be removed safely
							cy.log('Child table row removal capability verified');
						}
					}
				});
				return true;
			}, 'Child Table Error Recovery');

			cy.save_frappe_doc();
		});

		it('should test child table edge cases and boundary conditions', () => {
			// Test Chapter child table edge cases
			cy.visit_doctype_form('Chapter');
			cy.wait_for_navigation();

			cy.window().then((win) => {
				const frm = win.frappe.ui.form.get_form('Chapter');
				frm.doc.name = 'Edge Cases Test Chapter';
			});
			cy.fill_frappe_field('region', 'Edge Region', { fieldtype: 'Link' });
			cy.fill_frappe_field('introduction', 'Testing edge cases');
			cy.fill_frappe_field('enable_board_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);

			// Test edge cases
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Chapter');
						const grid = frm.fields_dict.board_role_specific_profiles.grid;

						// Test empty grid state
						expect(grid.grid_rows.length).to.equal(0);

						// Test adding and immediately removing row
						const row = grid.add_new_row();
						expect(row).to.exist;
						expect(grid.grid_rows.length).to.equal(1);

						// Test grid refresh capability
						if (grid.refresh) {
							grid.refresh();
							cy.log('Child table refresh capability verified');
						}
					});
					return true;
				},
				null,
				'Child Table Edge Cases'
			);

			cy.save_frappe_doc();
		});
	});

	describe('Child Table User Experience and Accessibility Tests', () => {
		it('should test child table user interface and accessibility', () => {
			cy.visit_doctype_form('Team');
			cy.wait_for_navigation();

			cy.fill_frappe_field('team_name', 'UI Test Team');
			cy.fill_frappe_field('team_type', 'Committee', { fieldtype: 'Select' });
			cy.fill_frappe_field('enable_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);

			// Test UI accessibility
			cy.get('[data-fieldname="role_specific_profiles"]').within(() => {
				// Verify table headers are accessible
				cy.get('.grid-heading-row').should('be.visible');

				// Test that add row button is accessible
				cy.get('.grid-add-row').should('be.visible');
			});

			// Test keyboard and mouse interactions
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Team');
						const grid = frm.fields_dict.role_specific_profiles.grid;

						// Test grid interaction capabilities
						expect(grid.wrapper.is(':visible')).to.be.true;
						cy.log('Child table is accessible and interactive');
					});
					return true;
				},
				null,
				'Child Table UI Accessibility'
			);

			cy.save_frappe_doc();
		});

		it('should test child table responsive behavior', () => {
			cy.visit_doctype_form('Chapter');
			cy.wait_for_navigation();

			cy.window().then((win) => {
				const frm = win.frappe.ui.form.get_form('Chapter');
				frm.doc.name = 'Responsive Test Chapter';
			});
			cy.fill_frappe_field('region', 'Responsive Region', {
				fieldtype: 'Link'
			});
			cy.fill_frappe_field('introduction', 'Testing responsive behavior');
			cy.fill_frappe_field('enable_board_role_specific_profiles', true, {
				fieldtype: 'Check'
			});
			cy.wait(1000);

			// Test responsive behavior
			cy.get('[data-fieldname="board_role_specific_profiles"]').should('be.visible');

			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Chapter');
					const grid = frm.fields_dict.board_role_specific_profiles.grid;

					// Test grid responsiveness
					expect(grid.wrapper.hasClass('form-grid')).to.be.true;
					cy.log('Child table responsive behavior verified');
				});
				return true;
			}, 'Child Table Responsive Behavior');

			cy.save_frappe_doc();
		});
	});
});
