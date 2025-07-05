describe('Volunteer Expense Management', () => {
	let volunteerId;

	before(() => {
		// Create test volunteer
		cy.window().then((win) => {
			return win.frappe.call({
				method: 'verenigingen.tests.create_test_volunteer',
				args: {
					email: `volunteer${Date.now()}@example.com`
				}
			}).then((r) => {
				volunteerId = r.message.volunteer_id;
			});
		});
	});

	beforeEach(() => {
		cy.login();
	});

	it('should create expense claim from volunteer portal', () => {
		// Visit volunteer portal
		cy.visit(`/volunteer/expenses?volunteer=${volunteerId}`);

		// Click new expense
		cy.get('#new_expense_btn').click();

		// Fill expense details
		cy.get('#expense_date').type(new Date().toISOString().split('T')[0]);
		cy.get('#expense_type').select('Travel');
		cy.get('#amount').type('25.50');
		cy.get('#description').type('Train ticket to Amsterdam chapter meeting');

		// Add receipt (mock file upload)
		const fileName = 'receipt.pdf';
		cy.fixture(fileName, 'base64').then(fileContent => {
			cy.get('#receipt_upload').upload({
				fileContent,
				fileName,
				mimeType: 'application/pdf'
			});
		});

		// Submit expense
		cy.get('#submit_expense').click();

		// Verify success
		cy.get('.alert-success').should('contain', 'Expense submitted successfully');

		// Verify expense appears in list
		cy.get('.expense-list-item').should('contain', 'Travel');
		cy.get('.expense-list-item').should('contain', '€25.50');
		cy.get('.expense-status').should('contain', 'Pending');
	});

	it('should approve expense as coordinator', () => {
		// Login as chapter coordinator
		cy.login('coordinator@example.com', 'password');

		// Navigate to expense approvals
		cy.visit('/app/volunteer-expense');
		cy.get('.list-row').contains('Travel').click();

		// Review expense details
		cy.verify_field('expense_type', 'Travel');
		cy.verify_field('amount', '25.50');
		cy.verify_field('status', 'Pending');

		// Approve expense
		cy.get('.btn').contains('Approve').click();
		cy.get('#approval_notes').type('Approved for chapter meeting attendance');
		cy.get('.modal-footer .btn-primary').click();

		// Verify status change
		cy.verify_field('status', 'Approved');

		// Verify GL entries created
		cy.get('.btn').contains('View GL Entries').click();
		cy.get('.list-row').should('have.length', 2); // Debit and credit entries
	});

	it('should handle expense validation', () => {
		cy.visit(`/volunteer/expenses?volunteer=${volunteerId}`);
		cy.get('#new_expense_btn').click();

		// Test amount validation
		cy.get('#amount').type('0');
		cy.get('#submit_expense').click();
		cy.get('.help-block').should('contain', 'Amount must be greater than 0');

		// Test future date validation
		const futureDate = new Date();
		futureDate.setDate(futureDate.getDate() + 1);
		cy.get('#expense_date').type(futureDate.toISOString().split('T')[0]);
		cy.get('#submit_expense').click();
		cy.get('.help-block').should('contain', 'Expense date cannot be in the future');

		// Test maximum amount validation
		cy.get('#amount').clear().type('10000');
		cy.get('#submit_expense').click();
		cy.get('.help-block').should('contain', 'Amount exceeds maximum allowed');
	});

	it('should filter and search expenses', () => {
		cy.visit(`/volunteer/expenses?volunteer=${volunteerId}`);

		// Filter by status
		cy.get('#filter_status').select('Approved');
		cy.get('.expense-list-item').each(($el) => {
			cy.wrap($el).find('.expense-status').should('contain', 'Approved');
		});

		// Filter by date range
		cy.get('#filter_from_date').type('2024-01-01');
		cy.get('#filter_to_date').type('2024-12-31');
		cy.get('#apply_filters').click();

		// Search by description
		cy.get('#search_expenses').type('Train');
		cy.get('.expense-list-item').should('contain', 'Train ticket');

		// Clear filters
		cy.get('#clear_filters').click();
		cy.get('.expense-list-item').should('have.length.greaterThan', 0);
	});
});
