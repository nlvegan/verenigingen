// Cypress E2E Test: Membership Termination Request Controller
// Tests the complete termination workflow including approval and execution

describe('Membership Termination Request Controller', () => {
	let testMember;
	let terminationRequest;

	before(() => {
		cy.login('Administrator');

		// Create a test member for termination testing
		cy.task('createTestMember', {
			first_name: 'Termination',
			last_name: 'Test',
			email: 'termination.test@verenigingen.test',
			status: 'Active'
		}).then((member) => {
			testMember = member;
			cy.log(`Created test member: ${member.name}`);
		});
	});

	after(() => {
		// Cleanup test data
		if (testMember) {
			cy.task('deleteDocument', {
				doctype: 'Member',
				name: testMember.name
			});
		}
	});

	beforeEach(() => {
		cy.login('Administrator');
	});

	context('Voluntary Termination Workflow', () => {
		it('should create a voluntary termination request', () => {
			cy.visit('/app/membership-termination-request/new');

			// Fill in basic details
			cy.findByLabelText('Member').type(testMember.name).wait(500);
			cy.get('.awesomplete li').first().click();

			cy.findByLabelText('Termination Type').select('Voluntary');
			cy.findByLabelText('Member Request Date').type('2025-11-01');
			cy.findByLabelText('Termination Reason').type('Member relocating to another country');

			// Save the document
			cy.findByRole('button', { name: /save/i }).click();
			cy.wait(1000);

			// Verify it was created in Draft status
			cy.get('[data-fieldname="status"]').should('contain', 'Draft');

			// Store the termination request name for later use
			cy.get('[data-doctype="Membership Termination Request"]')
				.invoke('attr', 'data-name')
				.then((name) => {
					terminationRequest = name;
					cy.log(`Created termination request: ${name}`);
				});
		});

		it('should submit for approval and auto-approve voluntary request', () => {
			cy.visit(`/app/membership-termination-request/${terminationRequest}`);

			// Click submit for approval button
			cy.contains('button', 'Submit for Approval').click();
			cy.wait(1000);

			// Voluntary terminations should go straight to Approved
			cy.get('[data-fieldname="status"]').should('contain', 'Approved');
			cy.get('[data-fieldname="approved_by"]').should('not.be.empty');
			cy.get('[data-fieldname="termination_date"]').should('not.be.empty');
		});

		it('should execute the termination', () => {
			cy.visit(`/app/membership-termination-request/${terminationRequest}`);

			// Click execute termination button
			cy.contains('button', 'Execute Termination').click();
			cy.wait(2000); // Execution takes time

			// Should now be in Executed status
			cy.get('[data-fieldname="status"]').should('contain', 'Executed');
			cy.get('[data-fieldname="executed_by"]').should('not.be.empty');
			cy.get('[data-fieldname="execution_date"]').should('not.be.empty');

			// Verify system update counters are visible
			cy.get('[data-fieldname="system_updates_section"]').should('be.visible');
		});

		it('should show audit trail of all actions', () => {
			cy.visit(`/app/membership-termination-request/${terminationRequest}`);

			// Expand audit section
			cy.get('[data-fieldname="audit_trail"]').scrollIntoView();

			// Should have entries for: Created, Submitted, Approved, Executed
			cy.get('[data-fieldname="audit_trail"] table tbody tr').should('have.length.at.least', 4);

			// Check for key actions
			cy.get('[data-fieldname="audit_trail"]').should('contain', 'Request Created');
			cy.get('[data-fieldname="audit_trail"]').should('contain', 'Submitted for Approval');
			cy.get('[data-fieldname="audit_trail"]').should('contain', 'Request Approved');
			cy.get('[data-fieldname="audit_trail"]').should('contain', 'Termination Executed');
		});

		it('should prevent double execution (idempotency)', () => {
			cy.visit(`/app/membership-termination-request/${terminationRequest}`);

			// Try to execute again
			cy.contains('button', 'Execute Termination').click();
			cy.wait(1000);

			// Should show message that it was already executed
			cy.get('.msgprint').should('contain', 'already executed');
		});
	});

	context('Disciplinary Termination Workflow', () => {
		let disciplinaryRequest;
		let secondaryApprover = 'Administrator'; // Use admin as approver

		it('should require secondary approval for disciplinary termination', () => {
			// Create a new member for disciplinary termination
			cy.task('createTestMember', {
				first_name: 'Disciplinary',
				last_name: 'Test',
				email: 'disciplinary.test@verenigingen.test',
				status: 'Active'
			}).then((member) => {
				cy.visit('/app/membership-termination-request/new');

				// Fill in disciplinary termination
				cy.findByLabelText('Member').type(member.name).wait(500);
				cy.get('.awesomplete li').first().click();

				cy.findByLabelText('Termination Type').select('Disciplinary Action');
				cy.findByLabelText('Termination Reason').type('Violation of membership code of conduct');
				cy.findByLabelText('Disciplinary Documentation').type('See attached incident report #123');

				// Save
				cy.findByRole('button', { name: /save/i }).click();
				cy.wait(1000);

				// Store name
				cy.get('[data-doctype="Membership Termination Request"]')
					.invoke('attr', 'data-name')
					.then((name) => {
						disciplinaryRequest = name;
					});
			});
		});

		it('should show requires_secondary_approval checkbox', () => {
			cy.visit(`/app/membership-termination-request/${disciplinaryRequest}`);

			// For disciplinary types, secondary approval should be required
			cy.get('[data-fieldname="requires_secondary_approval"]').find('input').should('be.checked');
		});

		it('should require secondary approver before submission', () => {
			cy.visit(`/app/membership-termination-request/${disciplinaryRequest}`);

			// Try to submit without secondary approver
			cy.contains('button', 'Submit for Approval').click();
			cy.wait(500);

			// Should show error
			cy.get('.msgprint').should('contain', 'Secondary approver is required');
		});

		it('should submit to pending status with secondary approver', () => {
			cy.visit(`/app/membership-termination-request/${disciplinaryRequest}`);

			// Set secondary approver
			cy.get('[data-fieldname="secondary_approver"] input').type('Admin');
			cy.wait(500);
			cy.get('.awesomplete li').first().click();

			// Save
			cy.findByRole('button', { name: /save/i }).click();
			cy.wait(500);

			// Now submit
			cy.contains('button', 'Submit for Approval').click();
			cy.wait(1000);

			// Should be in Pending status (not auto-approved)
			cy.get('[data-fieldname="status"]').should('contain', 'Pending');
		});

		it('should allow secondary approver to approve', () => {
			cy.visit(`/app/membership-termination-request/${disciplinaryRequest}`);

			// Click approve button
			cy.contains('button', 'Approve Request').click();
			cy.wait(500);

			// Fill in approval dialog if it appears
			cy.get('body').then(($body) => {
				if ($body.find('[data-fieldname="notes"]').length) {
					cy.get('[data-fieldname="notes"]').type('Approved after review');
					cy.contains('button', 'Submit').click();
				}
			});

			cy.wait(1000);

			// Should now be Approved
			cy.get('[data-fieldname="status"]').should('contain', 'Approved');
			cy.get('[data-fieldname="approved_by"]').should('not.be.empty');
		});

		it('should create expulsion report entry for disciplinary termination', () => {
			// Execute the disciplinary termination
			cy.visit(`/app/membership-termination-request/${disciplinaryRequest}`);
			cy.contains('button', 'Execute Termination').click();
			cy.wait(2000);

			// Check that an expulsion report entry was created
			cy.task('checkDocumentExists', {
				doctype: 'Expulsion Report Entry',
				filters: {
					member_id: testMember.name
				}
			}).then((exists) => {
				expect(exists).to.be.true;
			});
		});
	});

	context('Field Validation and Business Rules', () => {
		it('should calculate grace period for termination date', () => {
			cy.visit('/app/membership-termination-request/new');

			// Fill in basic details
			cy.findByLabelText('Member').type(testMember.name).wait(500);
			cy.get('.awesomplete li').first().click();

			cy.findByLabelText('Termination Type').select('Voluntary');
			cy.findByLabelText('Member Request Date').type('2025-11-01');

			// Check the apply grace period checkbox
			cy.get('[data-fieldname="apply_grace_period"] input').check();

			// Save to trigger calculation
			cy.findByRole('button', { name: /save/i }).click();
			cy.wait(1000);

			// Termination date should be 30 days after member request date
			cy.get('[data-fieldname="termination_date"] input').invoke('val').should('include', '2025-12'); // Should be in December
		});

		it('should validate that termination date is not before member request date', () => {
			cy.visit('/app/membership-termination-request/new');

			cy.findByLabelText('Member').type(testMember.name).wait(500);
			cy.get('.awesomplete li').first().click();

			cy.findByLabelText('Termination Type').select('Voluntary');
			cy.findByLabelText('Member Request Date').type('2025-11-15');

			// Manually set termination date before member request date
			cy.get('[data-fieldname="termination_date"] input').clear().type('2025-11-01'); // Before member request date

			// Try to save
			cy.findByRole('button', { name: /save/i }).click();
			cy.wait(500);

			// Should show validation error
			cy.get('.msgprint').should('contain', 'cannot be before member request date');
		});

		it('should require documentation for disciplinary terminations', () => {
			cy.visit('/app/membership-termination-request/new');

			cy.findByLabelText('Member').type(testMember.name).wait(500);
			cy.get('.awesomplete li').first().click();

			cy.findByLabelText('Termination Type').select('Policy Violation');
			cy.findByLabelText('Termination Reason').type('Test reason');

			// Don't fill in disciplinary_documentation

			// Save
			cy.findByRole('button', { name: /save/i }).click();
			cy.wait(500);

			// Set secondary approver
			cy.get('[data-fieldname="secondary_approver"] input').type('Admin');
			cy.wait(500);
			cy.get('.awesomplete li').first().click();
			cy.findByRole('button', { name: /save/i }).click();
			cy.wait(500);

			// Try to submit
			cy.contains('button', 'Submit for Approval').click();
			cy.wait(500);

			// Should require documentation
			cy.get('.msgprint').should('contain', 'Documentation is required');
		});
	});

	context('Permission Model', () => {
		it('should show termination preview API', () => {
			cy.visit(`/app/membership-termination-request/${terminationRequest}`);

			// Call the termination preview API
			cy.window().then((win) => {
				return win.frappe
					.call({
						method: `frappe.client.get_doc`,
						args: {
							doctype: 'Membership Termination Request',
							name: terminationRequest
						}
					})
					.then((r) => {
						// Call get_termination_preview method
						return win.frappe.call({
							method: `${r.message.doctype}.${r.message.name}.get_termination_preview`,
							args: {}
						});
					})
					.then((preview) => {
						cy.log('Termination preview:', preview);
						// Preview should contain impact data
						expect(preview).to.have.property('message');
					});
			});
		});
	});

	context('Error Handling and Rollback', () => {
		it('should rollback status if execution fails', () => {
			// This test would require creating conditions for execution failure
			// Left as a placeholder for manual testing scenarios
			cy.log('Manual test: Verify status rollback on execution failure');
		});
	});

	context('System Updates Tracking', () => {
		it('should show counters after execution', () => {
			cy.visit(`/app/membership-termination-request/${terminationRequest}`);

			// Scroll to system updates section
			cy.get('[data-fieldname="system_updates_section"]').scrollIntoView();

			// Check that counters are visible
			cy.get('[data-fieldname="sepa_mandates_cancelled"]').should('be.visible');
			cy.get('[data-fieldname="positions_ended"]').should('be.visible');
			cy.get('[data-fieldname="newsletters_updated"]').should('be.visible');
			cy.get('[data-fieldname="outstanding_invoices_cancelled"]').should('be.visible');
		});
	});
});
