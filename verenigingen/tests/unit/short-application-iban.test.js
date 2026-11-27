/**
 * @fileoverview /word-lid asks for an IBAN when the plan is Monthly, or on every plan of a door that
 * requires one (#3451). The server is the authority; this only saves the applicant a round trip.
 */

global.frappe = { ready: jest.fn() };
global.__ = (s) => s;

require('../../public/js/short_application.js');

const { problems } = window.ShortApplication;

const IBAN_MESSAGE = 'An IBAN is required (direct debit).';
const MONTHLY_MESSAGE = 'A monthly contribution requires an IBAN (direct debit).';

function ibanProblems(frequency, requireIban, iban) {
	document.body.innerHTML = '<form id="f"></form>';
	const form = document.getElementById('f');
	const data = {
		first_name: 'A',
		last_name: 'B',
		email: 'a@example.org',
		postal_code: '1234AB',
		house_number: '1',
		address_line1: 'Straat',
		city: 'Utrecht',
		amount: '10',
		consent: 1,
		join_reasons: [],
		iban
	};
	const plan = { id: 'p', mode: 'Flexible', frequency, minimum: 0, postal_minimum: 0 };
	return problems({ form, isRegular: true, requireIban, plan }, data);
}

describe('short application IBAN', () => {
	test('an annual plan on a door that requires an IBAN needs one', () => {
		expect(ibanProblems('Annual', true, '')).toContain(IBAN_MESSAGE);
	});

	test('controls: an annual plan on an ordinary door needs none, and an IBAN satisfies the door', () => {
		expect(ibanProblems('Annual', false, '')).toEqual([]);
		expect(ibanProblems('Annual', true, 'NL91ABNA0417164300')).toEqual([]);
	});

	test('a monthly plan still needs one on an ordinary door', () => {
		expect(ibanProblems('Monthly', false, '')).toContain(MONTHLY_MESSAGE);
	});
});
