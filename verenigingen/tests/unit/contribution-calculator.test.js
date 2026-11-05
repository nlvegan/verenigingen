/**
 * @fileoverview The income calculator shared by the full application form and /word-lid. The figures are
 * the ones the full form's inline calculator produced before it was extracted (#2127).
 */

const calculator = require('../../public/js/contribution_calculator.js');

const PERCENTAGE = { calculation_type: 'Percentage', percentage: 0.75 };
const PROGRESSIVE = {
	calculation_type: 'Progressive',
	progressive: { reference_income: 3500, lower_threshold: 2200 }
};

describe('contribution calculator', () => {
	test('percentage mode scales a monthly figure to the billing interval', () => {
		const at = (interval) => calculator.compute(PERCENTAGE, 'Income-Based', 2000, interval).amount;
		expect(at('monthly')).toBeCloseTo(15);
		expect(at('quarterly')).toBeCloseTo(45);
		expect(at('semiannually')).toBeCloseTo(90);
		expect(at('annually')).toBeCloseTo(180);
	});

	test('progressive mode runs from 0.5% at the lower threshold to 1% at the reference income', () => {
		const pct = (income) => calculator.compute(PROGRESSIVE, 'Income-Based', income, 'monthly').percentage;
		expect(pct(2000)).toBeCloseTo(0.5);
		expect(pct(2850)).toBeCloseTo(0.75);
		expect(pct(5000)).toBeCloseTo(1.0);
		expect(calculator.compute(PROGRESSIVE, 'Income-Based', 2850, 'monthly').kind).toBe('progressive');
	});

	test('nothing is calculated without an income or for a mode without a calculator', () => {
		expect(calculator.compute(PERCENTAGE, 'Income-Based', 0, 'monthly')).toBeNull();
		expect(calculator.compute(PERCENTAGE, 'Fixed', 2000, 'monthly')).toBeNull();
		expect(calculator.compute(PERCENTAGE, 'Flexible', 2000, 'monthly')).toBeNull();
	});

	test('a billing frequency maps to its interval, an unknown one to the full form default', () => {
		expect(calculator.intervalFor('Quarterly')).toBe('quarterly');
		expect(calculator.intervalFor('Semi-Annual')).toBe('semiannually');
		expect(calculator.intervalFor('Annual')).toBe('annually');
		expect(calculator.intervalFor('Weekly')).toBe('quarterly');
	});

	test('render shows the matching result and hides the other', () => {
		document.body.innerHTML = `
			<div id="calc-result" style="display:none"><span id="calc-suggested-amount"></span>
				<span id="calc-payment-frequency"></span><span id="calc-income-percentage"></span></div>
			<div id="progressive-calc-result" style="display:none"></div>
			<button id="apply-calculated-amount" style="display:none"></button>`;
		calculator.render(calculator.compute(PERCENTAGE, 'Income-Based', 2000, 'quarterly'), 'per quarter');
		expect(document.getElementById('calc-suggested-amount').textContent).toBe('€45.00');
		expect(document.getElementById('calc-result').style.display).toBe('block');
		expect(document.getElementById('progressive-calc-result').style.display).toBe('none');
		expect(document.getElementById('apply-calculated-amount').style.display).toBe('block');
		calculator.render(null);
		expect(document.getElementById('apply-calculated-amount').style.display).toBe('none');
	});
});
