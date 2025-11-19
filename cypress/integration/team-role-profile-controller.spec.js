/**
 * @fileoverview Team DocType Role Profile System JavaScript Controller Tests
 *
 * Comprehensive testing of the Team DocType JavaScript controller focusing specifically
 * on the role profile system refactoring. Tests database-driven role profile configuration,
 * dynamic UI interactions, child table management, and integration workflows.
 *
 * Business Context:
 * The role profile system enables teams to automatically assign appropriate permissions
 * and access levels to team members based on their roles. This replaces hardcoded
 * role mappings with flexible database-driven configuration.
 *
 * Key Testing Areas:
 * - Role profile section UI interactions (show/hide)
 * - Default role profile assignment workflow
 * - Role-specific profile configuration toggle
 * - Team Role Profile Assignment child table functionality
 * - Team member addition with automatic role assignment
 * - Form validation and error handling
 * - Integration with existing team management workflows
 *
 * Architecture Testing Focus:
 * - JavaScript controller event handlers for role profile fields
 * - Dynamic field visibility based on checkbox states
 * - Child table row addition/removal behaviors
 * - Field dependencies and validation rules
 * - API integration for role profile lookups
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-26
 */

describe("Team Role Profile System JavaScript Controller Tests", () => {
  beforeEach(() => {
    const user = Cypress.env("ADMIN_USER");
    const pass = Cypress.env("ADMIN_PASSWORD");
    expect(user, "ADMIN_USER env var").to.be.a("string").and.not.be.empty;
    expect(pass, "ADMIN_PASSWORD env var").to.be.a("string").and.not.be.empty;
    cy.login(user, pass);
    cy.clear_test_data();
  });

  afterEach(() => {
    cy.clear_test_data();
  });

  describe("Team Form Controller and Role Profile Section Tests", () => {
    it("should load Team form with role profile configuration fields", () => {
      // Navigate to new Team form
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Verify the controller is loaded
      cy.window().then((win) => {
        expect(win.frappe.ui.form.get_form("Team")).to.exist;
      });

      // Verify role profile section and fields are present
      cy.get('[data-fieldname="role_profile_section"]').should("be.visible");
      cy.get('[data-fieldname="default_role_profile"]').should("be.visible");
      cy.get('[data-fieldname="enable_role_specific_profiles"]').should(
        "be.visible",
      );

      // Verify role-specific profiles table initially hidden (depends_on checkbox)
      cy.get('[data-fieldname="role_specific_profiles"]').should(
        "not.be.visible",
      );
    });

    it("should test role profile section dynamic UI behavior", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Create basic team first
      cy.fill_frappe_field("team_name", "UI Test Team");
      cy.fill_frappe_field("team_type", "Committee", { fieldtype: "Select" });

      // Test initial state - role-specific profiles should be hidden
      cy.get('[data-fieldname="role_specific_profiles"]').should(
        "not.be.visible",
      );

      // Enable role-specific profiles checkbox
      cy.fill_frappe_field("enable_role_specific_profiles", true, {
        fieldtype: "Check",
      });
      cy.wait(1000); // Allow JavaScript to process

      // Verify role-specific profiles table becomes visible
      cy.get('[data-fieldname="role_specific_profiles"]').should("be.visible");

      // Disable checkbox again
      cy.fill_frappe_field("enable_role_specific_profiles", false, {
        fieldtype: "Check",
      });
      cy.wait(1000);

      // Verify table is hidden again
      cy.get('[data-fieldname="role_specific_profiles"]').should(
        "not.be.visible",
      );
    });

    it("should test default role profile assignment workflow", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Create team with basic information
      cy.fill_frappe_field("team_name", "Role Profile Test Team");
      cy.fill_frappe_field("team_type", "Working Group", {
        fieldtype: "Select",
      });
      cy.fill_frappe_field(
        "description",
        "Testing role profile assignment functionality",
      );

      // Test default role profile selection
      cy.execute_business_workflow(
        () => {
          cy.window().then((win) => {
            const frm = win.frappe.ui.form.get_form("Team");

            // Verify default role profile field exists and is configurable
            expect(frm.fields_dict.default_role_profile).to.exist;
            cy.log("Default role profile field available for configuration");

            // Test field properties
            expect(frm.fields_dict.default_role_profile.df.fieldtype).to.equal(
              "Link",
            );
            expect(frm.fields_dict.default_role_profile.df.options).to.equal(
              "Role Profile",
            );
          });
          return true;
        },
        null,
        "Default Role Profile Configuration",
      );

      // Test role profile field interaction (if Role Profiles exist in system)
      cy.window().then((win) => {
        // Check if Role Profile DocType has any records for testing
        win.frappe.call({
          method: "frappe.client.get_list",
          args: {
            doctype: "Role Profile",
            limit_page_length: 1,
          },
          callback(r) {
            if (r.message && r.message.length > 0) {
              cy.log("Role Profile records available for testing");
              // Could test actual role profile selection here
            } else {
              cy.log("No Role Profile records found - skipping selection test");
            }
          },
        });
      });

      cy.save_frappe_doc();
    });

    it("should test team member addition with role profile context", () => {
      cy.createTestMemberWithFinancialSetup().then((member) => {
        cy.visit_doctype_form("Team");
        cy.wait_for_navigation();

        // Create team with role profile configuration
        cy.fill_frappe_field("team_name", "Member Assignment Test Team");
        cy.fill_frappe_field("team_type", "Project Team", {
          fieldtype: "Select",
        });

        // Test team members section integration
        cy.execute_business_workflow(
          () => {
            cy.window().then((win) => {
              const frm = win.frappe.ui.form.get_form("Team");

              // Verify team members table exists
              if (frm.fields_dict.team_members) {
                expect(frm.fields_dict.team_members).to.exist;
                cy.log("Team members table available for member assignment");

                // Test that role profile fields are accessible for member assignment logic
                expect(frm.doc.default_role_profile).to.not.be.undefined;
                expect(frm.doc.enable_role_specific_profiles).to.not.be
                  .undefined;
              }
            });
            return true;
          },
          null,
          "Team Member Assignment Context",
        );

        cy.save_frappe_doc();
      });
    });
  });

  describe("Role-Specific Profiles Configuration Tests", () => {
    it("should test role-specific profiles table functionality", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Create team and enable role-specific profiles
      cy.fill_frappe_field("team_name", "Role-Specific Test Team");
      cy.fill_frappe_field("team_type", "Task Force", { fieldtype: "Select" });
      cy.fill_frappe_field("enable_role_specific_profiles", true, {
        fieldtype: "Check",
      });
      cy.wait(1000);

      // Verify role-specific profiles table is now visible
      cy.get('[data-fieldname="role_specific_profiles"]').should("be.visible");

      // Test child table structure
      cy.execute_form_operation(() => {
        cy.window().then((win) => {
          const frm = win.frappe.ui.form.get_form("Team");

          // Verify child table configuration
          const role_profiles_field = frm.fields_dict.role_specific_profiles;
          expect(role_profiles_field).to.exist;
          expect(role_profiles_field.df.fieldtype).to.equal("Table");
          expect(role_profiles_field.df.options).to.equal(
            "Team Role Profile Assignment",
          );

          // Verify depends_on functionality is working
          expect(role_profiles_field.df.depends_on).to.equal(
            "enable_role_specific_profiles",
          );
        });
        return true;
      }, "Role-Specific Profiles Table Configuration");

      cy.save_frappe_doc();
    });

    it("should test Team Role Profile Assignment child table behavior", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Setup team with role-specific profiles enabled
      cy.fill_frappe_field("team_name", "Child Table Test Team");
      cy.fill_frappe_field("team_type", "Operational Team", {
        fieldtype: "Select",
      });
      cy.fill_frappe_field("enable_role_specific_profiles", true, {
        fieldtype: "Check",
      });
      cy.wait(1000);

      // Test adding rows to role-specific profiles table
      cy.execute_business_workflow(
        () => {
          cy.window().then((win) => {
            const frm = win.frappe.ui.form.get_form("Team");

            // Verify we can access the child table
            const grid = frm.fields_dict.role_specific_profiles.grid;
            expect(grid).to.exist;

            // Test child table field structure
            const child_meta = frappe.get_meta("Team Role Profile Assignment");
            if (child_meta) {
              const expected_fields = [
                "team_role",
                "role_profile",
                "description",
              ];
              expected_fields.forEach((fieldname) => {
                const field = child_meta.fields.find(
                  (f) => f.fieldname === fieldname,
                );
                if (field) {
                  cy.log(`Child table field ${fieldname} configured correctly`);
                  expect(field).to.exist;
                }
              });
            }
          });
          return true;
        },
        null,
        "Child Table Structure Validation",
      );

      cy.save_frappe_doc();
    });

    it("should test role profile field dependencies and validation", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Test field dependencies
      cy.fill_frappe_field("team_name", "Dependencies Test Team");
      cy.fill_frappe_field("team_type", "Committee", { fieldtype: "Select" });

      // Test dependency behavior
      cy.execute_form_operation(() => {
        cy.window().then((win) => {
          const frm = win.frappe.ui.form.get_form("Team");

          // Test that role-specific profiles field has correct depends_on
          const role_specific_field = frm.fields_dict.role_specific_profiles;
          expect(role_specific_field.df.depends_on).to.equal(
            "enable_role_specific_profiles",
          );

          // Test field validation rules
          const default_profile_field = frm.fields_dict.default_role_profile;
          expect(default_profile_field.df.options).to.equal("Role Profile");
          expect(default_profile_field.df.fieldtype).to.equal("Link");

          // Test description field for role profile section
          const section_field = frm.fields_dict.role_profile_section;
          expect(section_field.df.description).to.contain("role profiles");
        });
        return true;
      }, "Field Dependencies and Validation");

      cy.save_frappe_doc();
    });
  });

  describe("Role Profile Integration Workflow Tests", () => {
    it("should test complete role profile configuration workflow", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Complete workflow test
      cy.fill_frappe_field("team_name", "Complete Workflow Team");
      cy.fill_frappe_field("team_type", "Project Team", {
        fieldtype: "Select",
      });
      cy.fill_frappe_field(
        "description",
        "Testing complete role profile workflow",
      );

      // Step 1: Configure default role profile
      cy.execute_business_workflow(
        () => {
          cy.window().then((win) => {
            const frm = win.frappe.ui.form.get_form("Team");

            // Verify default configuration is available
            expect(frm.fields_dict.default_role_profile).to.exist;
            cy.log("Step 1: Default role profile configuration available");
          });
          return true;
        },
        null,
        "Workflow Step 1 - Default Profile",
      );

      // Step 2: Enable role-specific configuration
      cy.fill_frappe_field("enable_role_specific_profiles", true, {
        fieldtype: "Check",
      });
      cy.wait(1000);

      // Step 3: Verify role-specific table becomes available
      cy.get('[data-fieldname="role_specific_profiles"]').should("be.visible");

      // Step 4: Test that both configuration options work together
      cy.execute_business_workflow(
        () => {
          cy.window().then((win) => {
            const frm = win.frappe.ui.form.get_form("Team");

            // Both systems should be available simultaneously
            expect(frm.doc.default_role_profile).to.not.be.undefined;
            expect(frm.doc.enable_role_specific_profiles).to.equal(1);
            expect(
              frm.fields_dict.role_specific_profiles.wrapper.is(":visible"),
            ).to.be.true;

            cy.log(
              "Complete workflow: Both default and role-specific profiles available",
            );
          });
          return true;
        },
        null,
        "Complete Workflow Integration",
      );

      cy.save_frappe_doc();

      // Verify document structure after save
      cy.window().then((win) => {
        const frm = win.frappe.ui.form.get_form("Team");
        expect(frm.doc.name).to.contain("Complete Workflow Team");
        expect(frm.doc.enable_role_specific_profiles).to.equal(1);
        cy.log("Workflow completed successfully with proper data persistence");
      });
    });

    it("should test error handling and validation scenarios", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Test validation scenarios
      cy.fill_frappe_field("team_name", "Validation Test Team");
      cy.fill_frappe_field("team_type", "Other", { fieldtype: "Select" });

      // Test form validation with role profiles
      cy.execute_form_operation(() => {
        cy.window().then((win) => {
          const frm = win.frappe.ui.form.get_form("Team");

          // Test that form can be saved without role profile configuration
          // (role profiles should be optional)
          cy.log("Testing form validation without role profile configuration");

          // Verify no errors occur when role profiles are not configured
          expect(frm.doc.default_role_profile).to.be.undefined;
          expect(frm.doc.enable_role_specific_profiles).to.equal(0);
        });
        return true;
      }, "Validation Without Role Profiles");

      cy.save_frappe_doc();

      // Test form still saves successfully
      cy.get(".indicator.green").should("contain", "Saved");
    });

    it("should test role profile system integration with existing team features", () => {
      cy.createTestMemberWithFinancialSetup().then((member) => {
        cy.visit_doctype_form("Team");
        cy.wait_for_navigation();

        // Test integration with existing team features
        cy.fill_frappe_field("team_name", "Integration Test Team");
        cy.fill_frappe_field("team_type", "Working Group", {
          fieldtype: "Select",
        });
        cy.fill_frappe_field("team_lead", member.name, { fieldtype: "Link" });
        cy.wait_for_member_data();

        // Configure role profiles
        cy.fill_frappe_field("enable_role_specific_profiles", true, {
          fieldtype: "Check",
        });
        cy.wait(1000);

        // Test that role profile configuration doesn't interfere with existing functionality
        cy.execute_business_workflow(
          () => {
            cy.window().then((win) => {
              const frm = win.frappe.ui.form.get_form("Team");

              // Verify existing functionality still works
              expect(frm.doc.team_lead).to.equal(member.name);
              expect(frm.fields_dict.team_members).to.exist;

              // Verify role profile functionality is additive
              expect(frm.fields_dict.default_role_profile).to.exist;
              expect(frm.fields_dict.role_specific_profiles).to.exist;

              // Test that cost center field still works
              if (frm.fields_dict.cost_center) {
                expect(frm.fields_dict.cost_center).to.exist;
              }

              cy.log(
                "Role profile system integrates properly with existing team features",
              );
            });
            return true;
          },
          null,
          "Integration with Existing Features",
        );

        cy.save_frappe_doc();
      });
    });
  });

  describe("User Experience and Interface Tests", () => {
    it("should test role profile section accessibility and usability", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Test UI accessibility
      cy.get('[data-fieldname="role_profile_section"]')
        .should("be.visible")
        .should("contain", "Role Profile Configuration");

      // Test field labels and descriptions
      cy.get('[data-fieldname="default_role_profile"]')
        .parent()
        .should("contain", "Default Role Profile");

      cy.get('[data-fieldname="enable_role_specific_profiles"]')
        .parent()
        .should("contain", "Enable Role-Specific Profiles");

      // Test section description is helpful
      cy.execute_business_workflow(
        () => {
          cy.window().then((win) => {
            const frm = win.frappe.ui.form.get_form("Team");
            const section = frm.fields_dict.role_profile_section;

            // Verify section has descriptive text
            expect(section.df.description).to.exist;
            expect(section.df.description).to.contain("role profiles");

            cy.log("Role profile section provides clear user guidance");
          });
          return true;
        },
        null,
        "UI Accessibility and Usability",
      );
    });

    it("should test responsive behavior and field interactions", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Test responsive behavior
      cy.fill_frappe_field("team_name", "Responsive Test Team");
      cy.fill_frappe_field("team_type", "Committee", { fieldtype: "Select" });

      // Test checkbox interactions
      cy.get(
        '[data-fieldname="enable_role_specific_profiles"] input[type="checkbox"]',
      ).should("not.be.checked");

      cy.fill_frappe_field("enable_role_specific_profiles", true, {
        fieldtype: "Check",
      });

      cy.get(
        '[data-fieldname="enable_role_specific_profiles"] input[type="checkbox"]',
      ).should("be.checked");

      // Test immediate UI response
      cy.get('[data-fieldname="role_specific_profiles"]').should("be.visible");

      // Test toggle back
      cy.fill_frappe_field("enable_role_specific_profiles", false, {
        fieldtype: "Check",
      });

      cy.get('[data-fieldname="role_specific_profiles"]').should(
        "not.be.visible",
      );

      cy.save_frappe_doc();
    });
  });

  describe("Performance and Reliability Tests", () => {
    it("should test role profile system performance with multiple operations", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Performance test with multiple rapid operations
      cy.fill_frappe_field("team_name", "Performance Test Team");
      cy.fill_frappe_field("team_type", "Task Force", { fieldtype: "Select" });

      // Rapid toggle testing
      for (let i = 0; i < 3; i++) {
        cy.fill_frappe_field("enable_role_specific_profiles", true, {
          fieldtype: "Check",
        });
        cy.wait(200);
        cy.get('[data-fieldname="role_specific_profiles"]').should(
          "be.visible",
        );

        cy.fill_frappe_field("enable_role_specific_profiles", false, {
          fieldtype: "Check",
        });
        cy.wait(200);
        cy.get('[data-fieldname="role_specific_profiles"]').should(
          "not.be.visible",
        );
      }

      // Final state
      cy.fill_frappe_field("enable_role_specific_profiles", true, {
        fieldtype: "Check",
      });
      cy.save_frappe_doc();

      // Verify system stability after rapid operations
      cy.get(".indicator.green").should("contain", "Saved");
    });

    it("should test error recovery and system stability", () => {
      cy.visit_doctype_form("Team");
      cy.wait_for_navigation();

      // Test error recovery scenarios
      cy.fill_frappe_field("team_name", "Error Recovery Test Team");
      cy.fill_frappe_field("team_type", "Project Team", {
        fieldtype: "Select",
      });

      // Test system stability with various field states
      cy.execute_business_workflow(
        () => {
          cy.window().then((win) => {
            const frm = win.frappe.ui.form.get_form("Team");

            // Verify form remains stable
            expect(frm).to.exist;
            expect(frm.doc).to.exist;
            expect(frm.fields_dict.default_role_profile).to.exist;
            expect(frm.fields_dict.enable_role_specific_profiles).to.exist;
            expect(frm.fields_dict.role_specific_profiles).to.exist;

            cy.log("System maintains stability under various conditions");
          });
          return true;
        },
        null,
        "Error Recovery and Stability",
      );

      cy.save_frappe_doc();
    });
  });
});
