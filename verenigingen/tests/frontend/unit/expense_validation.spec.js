const {
	validateExpenseAmount,
	validateExpenseDate,
	calculateExpenseTotals
} = require('../../verenigingen/public/js/expense_validation');

describe('Expense Validation', () => {
	let mockFrappe;

	beforeEach(() => {
		// Mock frappe object
		mockFrappe = {
			_: jest.fn((str) => str),
			__: jest.fn((str) => str),
			throw: jest.fn(),
			msgprint: jest.fn(),
			call: jest.fn(),
			model: {
				get_value: jest.fn(),
				set_value: jest.fn()
			},
			datetime: {
				str_to_obj: jest.fn((str) => new Date(str)),
				nowdate: jest.fn(() => '2024-01-15')
			}
		};
		global.frappe = mockFrappe;
	});

	describe('validateExpenseAmount', () => {
		it('should throw error for zero amount', () => {
			const expense = { amount: 0 };

			expect(() => {
				validateExpenseAmount(expense);
			}).toThrow('Amount must be greater than zero');
		});

		it('should throw error for negative amount', () => {
			const expense = { amount: -10 };

			expect(() => {
				validateExpenseAmount(expense);
			}).toThrow('Amount must be greater than zero');
		});

		it('should allow valid positive amounts', () => {
			const expense = { amount: 25.50 };

			expect(() => {
				validateExpenseAmount(expense);
			}).not.toThrow();
		});

		it('should enforce maximum amount limit', () => {
			const expense = { amount: 10000 };

			expect(() => {
				validateExpenseAmount(expense);
			}).toThrow('Amount exceeds maximum allowed limit');
		});
	});

	describe('validateExpenseDate', () => {
		it('should not allow future dates', () => {
			const tomorrow = new Date();
			tomorrow.setDate(tomorrow.getDate() + 1);
			const expense = { expense_date: tomorrow.toISOString().split('T')[0] };

			expect(() => {
				validateExpenseDate(expense);
			}).toThrow('Expense date cannot be in the future');
		});

		it('should allow today\'s date', () => {
			const today = new Date().toISOString().split('T')[0];
			const expense = { expense_date: today };

			expect(() => {
				validateExpenseDate(expense);
			}).not.toThrow();
		});

		it('should allow past dates within limit', () => {
			const pastDate = new Date();
			pastDate.setDate(pastDate.getDate() - 30);
			const expense = { expense_date: pastDate.toISOString().split('T')[0] };

			expect(() => {
				validateExpenseDate(expense);
			}).not.toThrow();
		});

		it('should not allow dates too far in the past', () => {
			const oldDate = new Date();
			oldDate.setFullYear(oldDate.getFullYear() - 2);
			const expense = { expense_date: oldDate.toISOString().split('T')[0] };

			expect(() => {
				validateExpenseDate(expense);
			}).toThrow('Expense date is too old');
		});
	});

	describe('calculateExpenseTotals', () => {
		it('should calculate totals correctly', () => {
			const expenses = [
				{ amount: 25.50, status: 'Approved' },
				{ amount: 30.00, status: 'Approved' },
				{ amount: 15.00, status: 'Pending' },
				{ amount: 20.00, status: 'Rejected' }
			];

			const totals = calculateExpenseTotals(expenses);

			expect(totals.approved).toBe(55.50);
			expect(totals.pending).toBe(15.00);
			expect(totals.rejected).toBe(20.00);
			expect(totals.total).toBe(90.50);
		});

		it('should handle empty expense list', () => {
			const expenses = [];
			const totals = calculateExpenseTotals(expenses);

			expect(totals.approved).toBe(0);
			expect(totals.pending).toBe(0);
			expect(totals.rejected).toBe(0);
			expect(totals.total).toBe(0);
		});
	});
});
