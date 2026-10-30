/**
 * @fileoverview The amount posted by /word-lid must belong to the chosen frequency.
 * A tier ticked under Monthly and then hidden by switching to yearly must not be posted as the yearly amount.
 */

global.frappe = { ready: jest.fn() };
global.__ = (s) => s;

require('../../public/js/short_application.js');

const { chosenAmount, resetAmountOnFrequencyChange } = window.ShortApplication;

function render(frequency) {
	document.body.innerHTML = `
		<form id="f">
			<input type="hidden" name="frequency" value="${frequency}">
			<label data-frequency="Monthly"><input type="radio" name="amount_choice" value="5"></label>
			<label data-frequency="Annual"><input type="radio" name="amount_choice" value="50"></label>
			<label><input type="radio" name="amount_choice" value="custom"><input id="wl-custom-amount" type="number"></label>
		</form>`;
	return document.getElementById('f');
}

function switchTo(form, frequency) {
	form.elements.frequency.value = frequency;
	resetAmountOnFrequencyChange(form);
}

describe('short application amount', () => {
	test('a Monthly tier is not posted after switching to Annual', () => {
		const form = render('Monthly');
		form.querySelector('input[value="5"]').checked = true;
		expect(chosenAmount(form)).toBe('5'); // control: it counts under Monthly
		switchTo(form, 'Annual');
		expect(chosenAmount(form)).toBe('');
	});

	test('an Annual tier chosen after switching is posted', () => {
		const form = render('Monthly');
		form.querySelector('input[value="5"]').checked = true;
		switchTo(form, 'Annual');
		form.querySelector('input[value="50"]').checked = true;
		expect(chosenAmount(form)).toBe('50');
	});

	test('a custom amount typed for one frequency is cleared on switching', () => {
		const form = render('Monthly');
		form.querySelector('input[value="custom"]').checked = true;
		form.querySelector('#wl-custom-amount').value = '7';
		expect(chosenAmount(form)).toBe('7'); // control
		switchTo(form, 'Annual');
		expect(chosenAmount(form)).toBe('');
	});
});
