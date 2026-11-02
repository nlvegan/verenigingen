/**
 * @fileoverview /word-lid must not submit a Regular application whose delivery questions are unanswered (#1968).
 * The selects start on a blank placeholder, so an applicant who never chose has no answer to post.
 */

global.frappe = { ready: jest.fn() };
global.__ = (s) => s;

require('../../public/js/short_application.js');

const { problems, refreshDeliveryOptions } = window.ShortApplication;

function render(magazine, starterGuide) {
	document.body.innerHTML = `
		<form id="f">
			<select name="magazine_delivery" class="delivery-select">
				<option value="">Choose</option><option value="Digitaal">Digital</option>
			</select>
			<select name="starter_guide_delivery" class="delivery-select">
				<option value="">Choose</option><option value="Geen">None</option>
			</select>
		</form>`;
	const form = document.getElementById('f');
	form.elements.magazine_delivery.value = magazine;
	form.elements.starter_guide_delivery.value = starterGuide;
	return form;
}

function data(form) {
	return {
		first_name: 'A',
		last_name: 'B',
		email: 'a@example.org',
		postal_code: '1234AB',
		house_number: '1',
		address_line1: 'Straat',
		city: 'Utrecht',
		frequency: 'Annual',
		amount: '10',
		consent: 1,
		join_reasons: [],
		magazine_delivery: form.elements.magazine_delivery.value,
		starter_guide_delivery: form.elements.starter_guide_delivery.value
	};
}

const DELIVERY = 'Please choose how you want to receive the magazine and the starter guide.';

describe('short application delivery questions', () => {
	test('answered questions raise no problem', () => {
		const form = render('Digitaal', 'Geen');
		expect(problems({ form, isRegular: true, minimums: {} }, data(form))).toEqual([]);
	});

	test.each([
		['', 'Geen'],
		['Digitaal', '']
	])('an unanswered question is a problem (magazine=%p, guide=%p)', (magazine, guide) => {
		const form = render(magazine, guide);
		expect(problems({ form, isRegular: true, minimums: {} }, data(form))).toContain(DELIVERY);
	});

	test('a hidden question is not required', () => {
		const form = render('Digitaal', 'Geen');
		const posted = data(form);
		form.elements.starter_guide_delivery.remove();
		delete posted.starter_guide_delivery;
		expect(problems({ form, isRegular: true, minimums: {} }, posted)).toEqual([]);
	});

	test('an address abroad leaves an unanswered question unanswered', () => {
		document.body.innerHTML = `
			<form id="f">
				<input name="country" value="Belgium">
				<select name="magazine_delivery" class="delivery-select">
					<option value="" selected>Choose</option>
					<option value="Digitaal">Digital</option><option value="Papier">Paper</option>
				</select>
				<select name="starter_guide_delivery" class="delivery-select">
					<option value="">Choose</option>
					<option value="Digitaal">Digital</option><option value="Papier" selected>Paper</option>
				</select>
			</form>`;
		const form = document.getElementById('f');
		// Abroad, a selected paper option is replaced by Digitaal. The placeholder must not be.
		refreshDeliveryOptions(form);
		expect(form.elements.magazine_delivery.value).toBe('');
		expect(form.elements.starter_guide_delivery.value).toBe('Digitaal'); // control: paper is still undone
	});
});
