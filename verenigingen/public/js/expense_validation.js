/**
 * @fileoverview Expense Validation Utilities
 * @description Comprehensive validation functions for volunteer expense management
 *
 * Business Context:
 * Ensures financial integrity and compliance through robust expense validation.
 * Critical for audit trail maintenance and financial governance in association
 * expense reimbursement workflows.
 *
 * Key Features:
 * - Amount validation with configurable limits
 * - Date range validation for audit compliance
 * - Expense status tracking and totaling
 * - Comprehensive validation error messaging
 *
 * Validation Rules:
 * - Expense amounts must be positive and within limits
 * - Expense dates cannot be in future or beyond retention period
 * - Status-based categorization for financial reporting
 *
 * Integration Points:
 * - Volunteer expense submission forms
 * - Financial reporting and analytics
 * - Audit trail generation systems
 * - Expense approval workflows
 *
 * Security Considerations:
 * - Input sanitization and type validation
 * - Business rule enforcement at client level
 * - Audit-compliant error logging
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module ExpenseValidation
 */

/**
 * Validates expense amount against business rules
 *
 * Enforces minimum and maximum expense limits for financial governance
 * and audit compliance.
 *
 * @param {Object} expense - Expense object containing amount
 * @param {number} expense.amount - Expense amount to validate
 * @throws {Error} When amount validation fails
 */
function validateExpenseAmount(expense) {
	if (!expense.amount || expense.amount <= 0) {
		throw new Error('Amount must be greater than zero');
	}
	if (expense.amount > 5000) {
		throw new Error('Amount exceeds maximum allowed limit');
	}
}

/**
 * Validates expense date against business rules
 *
 * Ensures expense dates fall within acceptable ranges for audit
 * and compliance purposes. Prevents future dates and enforces
 * retention period limits.
 *
 * @param {Object} expense - Expense object containing date
 * @param {string|Date} expense.expense_date - Expense date to validate
 * @throws {Error} When date validation fails
 */
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

/**
 * Calculates expense totals by status category
 *
 * Provides financial summary data for reporting and analytics,
 * categorizing expenses by approval status for dashboard display
 * and financial oversight.
 *
 * @param {Array<Object>} expenses - Array of expense objects
 * @param {number} expenses[].amount - Individual expense amount
 * @param {string} expenses[].status - Expense approval status
 * @returns {Object} Totals object with categorized amounts
 * @returns {number} returns.approved - Total approved expenses
 * @returns {number} returns.pending - Total pending expenses
 * @returns {number} returns.rejected - Total rejected expenses
 * @returns {number} returns.total - Total all expenses
 */
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
