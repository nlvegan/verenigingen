describe('Member Application Flow', () => {
	const testEmail = `test${Date.now()}@example.com`;

	beforeEach(() => {
		cy.login();
	});

	it('should create a member application successfully', () => {
		// Visit the public application page
		cy.visit('/membership-application');

		// Fill personal information
		cy.get('#first_name').type('Test');
		cy.get('#last_name').type('User');
		cy.get('#email').type(testEmail);
		cy.get('#birth_date').type('1990-01-01');

		// Fill address
		cy.get('#address_line1').type('Test Street 123');
		cy.get('#city').type('Amsterdam');
		cy.get('#postal_code').type('1234AB');
		cy.get('#country').select('Netherlands');

		// Select membership type
		cy.get('#membership_type').select('Regular Member');

		// Check volunteer interest
		cy.get('#interested_in_volunteering').check();

		// Submit application
		cy.get('#submit_application').click();

		// Verify success message
		cy.get('.alert-success').should('contain', 'Application submitted successfully');
	});

	it('should review and approve application', () => {
		// Login as admin
		cy.login('Administrator', 'admin');

		// Navigate to pending applications
		cy.visit_list('Member');
		cy.get('.list-row').contains(testEmail).click();

		// Verify application details
		cy.verify_field('email', testEmail);
		cy.verify_field('application_status', 'Pending');

		// Approve application
		cy.get('.btn').contains('Approve Application').click();
		cy.get('.modal-footer .btn-primary').click();

		// Verify status change
		cy.verify_field('application_status', 'Approved');

		// Verify volunteer record created
		cy.get('.btn').contains('View Volunteer Record').should('exist');
	});

	it('should handle validation errors', () => {
		cy.visit('/membership-application');

		// Try to submit without required fields
		cy.get('#submit_application').click();

		// Verify error messages
		cy.get('.help-block').should('contain', 'First Name is required');
		cy.get('.help-block').should('contain', 'Last Name is required');
		cy.get('.help-block').should('contain', 'Email is required');

		// Test invalid email
		cy.get('#email').type('invalid-email');
		cy.get('#submit_application').click();
		cy.get('.help-block').should('contain', 'Please enter a valid email');

		// Test invalid postal code
		cy.get('#postal_code').type('123');
		cy.get('#submit_application').click();
		cy.get('.help-block').should('contain', 'Invalid postal code format');
	});
});
