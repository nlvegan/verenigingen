// Expense validation functions

function validateExpenseAmount(expense) {
	if (!expense.amount || expense.amount <= 0) {
		throw new Error('Amount must be greater than zero');
	}
	if (expense.amount > 5000) {
		throw new Error('Amount exceeds maximum allowed limit');
	}
}

function validateExpenseDate(expense) {
	const expenseDate = new Date(expense.expense_date);
	expenseDate.setHours(0, 0, 0, 0);
	const today = new Date();
	today.setHours(0, 0, 0, 0);

	// Check if date is in the future
	if (expenseDate > today) {
		throw new Error('Expense date cannot be in the future');
	}

	// Check if date is too old (more than 1 year)
	const oneYearAgo = new Date();
	oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
	if (expenseDate < oneYearAgo) {
		throw new Error('Expense date is too old');
	}
}

function calculateExpenseTotals(expenses) {
	const totals = {
		approved: 0,
		pending: 0,
		rejected: 0,
		total: 0
	};

	expenses.forEach(expense => {
		totals.total += expense.amount;
		if (expense.status === 'Approved') {
			totals.approved += expense.amount;
		} else if (expense.status === 'Pending') {
			totals.pending += expense.amount;
		} else if (expense.status === 'Rejected') {
			totals.rejected += expense.amount;
		}
	});

	return totals;
}

// Export for testing
if (typeof module !== 'undefined' && module.exports) {
	module.exports = {
		validateExpenseAmount,
		validateExpenseDate,
		calculateExpenseTotals
	};
}
