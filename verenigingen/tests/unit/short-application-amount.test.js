/**
 * @fileoverview /word-lid builds its amount controls from the selected plan's contribution mode (#2127).
 * Fixed is the template amount with no choice, Flexible is the suggested amount plus the door's presets
 * (and a free amount only when the template allows one), Income-Based is the calculator. Choosing
 * another plan rebuilds the controls, so an amount chosen for one plan is never posted for another.
 */

global.frappe = { ready: jest.fn() };
global.__ = (s) => s;

require('../../public/js/contribution_calculator.js');
require('../../public/js/short_application.js');

const { chosenAmount, selectPlan, amountChoices, minimumFor, problems } = window.ShortApplication;

const FIXED = {
	id: 'fixed',
	mode: 'Fixed',
	frequency: 'Quarterly',
	billing_display: 'per quarter',
	amount: 30,
	minimum: 0,
	postal_minimum: 0,
	suggested: 30,
	presets: [],
	allow_custom: false,
	calculator: null
};
const FLEXIBLE = {
	id: 'flex',
	mode: 'Flexible',
	frequency: 'Monthly',
	billing_display: 'per month',
	amount: 12,
	minimum: 4,
	postal_minimum: 9,
	suggested: 12,
	presets: [25, 12, 18],
	allow_custom: false,
	calculator: null
};
const FLEXIBLE_CUSTOM = { ...FLEXIBLE, id: 'flexc', allow_custom: true };
const INCOME = {
	id: 'income',
	mode: 'Income-Based',
	frequency: 'Annual',
	billing_display: 'per year',
	amount: 0,
	minimum: 20,
	postal_minimum: 0,
	suggested: 0,
	presets: [],
	allow_custom: false,
	calculator: { mode: 'Income-Based', calculation_type: 'Percentage', percentage: 1, description: '' }
};

function render() {
	document.body.innerHTML = `
		<form id="f">
			<input type="hidden" name="plan" id="wl-plan">
			<p id="wl-fixed-amount"></p>
			<div id="wl-amount-choices"></div>
			<label id="wl-custom-amount-row"><input type="radio" name="amount_choice" value="custom">
				<input id="wl-custom-amount" type="number"></label>
			<div id="income-calculator" style="display:none">
				<p id="calculator-description"></p>
				<input id="calc-monthly-income" type="number">
				<select id="calc-payment-interval">
					<option value="monthly"></option><option value="quarterly"></option>
					<option value="semiannually"></option><option value="annually"></option>
				</select>
				<div id="calc-result"></div><div id="progressive-calc-result"></div>
				<button id="apply-calculated-amount" type="button"></button><p id="calculator-hint"></p>
			</div>
			<p id="wl-calculated-row"><span id="wl-calculated-amount"></span></p>
		</form>`;
	return document.getElementById('f');
}

function stateFor(plans) {
	return { form: render(), plans, isRegular: true, plan: null };
}

const visible = (id) => document.getElementById(id).style.display !== 'none';

describe('amount controls follow the plan template', () => {
	test('Fixed shows the template amount and no choice, and posts exactly that amount', () => {
		const state = stateFor([FIXED]);
		selectPlan(state, 'fixed');
		expect(document.getElementById('wl-fixed-amount').textContent).toContain('30.00');
		expect(visible('wl-fixed-amount')).toBe(true);
		expect(document.querySelectorAll('input[name="amount_choice"]:not([value="custom"])').length).toBe(0);
		expect(visible('wl-custom-amount-row')).toBe(false);
		expect(chosenAmount(state.form, state.plan, state)).toBe('30');
	});

	test('Flexible offers the suggested amount and the presets, lowest first and without duplicates', () => {
		expect(amountChoices(FLEXIBLE)).toEqual([12, 18, 25]);
		const state = stateFor([FLEXIBLE]);
		selectPlan(state, 'flex');
		const values = Array.from(document.querySelectorAll('#wl-amount-choices input')).map((i) => i.value);
		expect(values).toEqual(['12', '18', '25']);
	});

	test('a custom amount is offered only when the template allows it', () => {
		const state = stateFor([FLEXIBLE, FLEXIBLE_CUSTOM]);
		selectPlan(state, 'flex');
		expect(visible('wl-custom-amount-row')).toBe(false);
		selectPlan(state, 'flexc');
		expect(visible('wl-custom-amount-row')).toBe(true);
		form_custom(state.form, '7.5');
		expect(chosenAmount(state.form, state.plan, state)).toBe('7.5');
	});

	test('Income-Based shows the calculator and posts nothing until an amount is applied', () => {
		const state = stateFor([INCOME]);
		selectPlan(state, 'income');
		expect(visible('income-calculator')).toBe(true);
		expect(document.getElementById('calc-payment-interval').value).toBe('annually');
		expect(chosenAmount(state.form, state.plan, state)).toBe('');
		state.calculated = '45.00';
		expect(chosenAmount(state.form, state.plan, state)).toBe('45.00');
	});

	test('choosing another plan clears an amount chosen for the first one', () => {
		const state = stateFor([FLEXIBLE_CUSTOM, FIXED]);
		selectPlan(state, 'flexc');
		state.form.querySelector('#wl-amount-choices input[value="25"]').checked = true;
		expect(chosenAmount(state.form, state.plan, state)).toBe('25'); // control: it counts for this plan
		selectPlan(state, 'flexc');
		expect(chosenAmount(state.form, state.plan, state)).toBe('');
		selectPlan(state, 'fixed');
		expect(chosenAmount(state.form, state.plan, state)).toBe('30');
		expect(document.getElementById('wl-plan').value).toBe('fixed');
	});

	test('the postal minimum raises the minimum only for paper delivery', () => {
		expect(minimumFor(FLEXIBLE, false)).toBe(4);
		expect(minimumFor(FLEXIBLE, true)).toBe(9);
		expect(minimumFor(null, true)).toBe(0);
	});

	test('submitting without a plan is a problem', () => {
		const state = { form: render(), isRegular: true, plan: null };
		const posted = {
			first_name: 'A',
			last_name: 'B',
			email: 'a@b.nl',
			postal_code: '1',
			house_number: '1',
			address_line1: 'S',
			city: 'U',
			join_reasons: [],
			amount: '10',
			consent: 1
		};
		expect(problems(state, posted)).toContain('Please choose a payment plan.');
	});
});

function form_custom(form, value) {
	form.querySelector('input[value="custom"]').checked = true;
	form.querySelector('#wl-custom-amount').value = value;
}
