/**
 * @fileoverview The applicant's payment choice must reach the payload.
 *
 * Business context: choosing SEPA Direct Debit is what puts a member on the
 * mandate path. #420 — the form submitted "Bank Transfer" for everyone: the
 * collector read the radios correctly, then getAllFormData() overwrote the key
 * from `this.state`, which nothing on the page ever writes (the two writers bind
 * to `.payment-method-option` / `.payment-method-radio`, neither of which the
 * page renders) and which showPaymentMethodFallback() seeds to "Bank Transfer".
 *
 * The radio values are the wire values the server maps
 * (`map_payment_method`: bank_transfer -> "Bank Transfer"), so passing them
 * through unchanged is correct.
 */

require('../../public/js/membership_application.js');

const { getPaymentMethod } = window.MembershipApplication.prototype;

/** Render the payment radios the way apply_for_membership.html does. */
function renderPaymentRadios(checkedValue) {
	document.body.innerHTML = ['bank_transfer', 'sepa_direct_debit', 'mollie']
		.map(
			(value) =>
				`<label><input type="radio" name="payment_method" value="${value}"
				  class="form-input w-auto" ${value === checkedValue ? 'checked' : ''} required></label>`
		)
		.join('');
}

/** The state the live page actually has: seeded by the fallback, never updated. */
function pageState(seeded = 'Bank Transfer') {
	return { paymentMethod: '', state: { get: () => seeded } };
}

describe('getPaymentMethod', () => {
	afterEach(() => {
		document.body.innerHTML = '';
	});

	it('returns what the applicant checked, not the seeded default', () => {
		renderPaymentRadios('sepa_direct_debit');

		expect(getPaymentMethod.call(pageState())).toBe('sepa_direct_debit');
	});

	it('follows the applicant to a different choice', () => {
		renderPaymentRadios('mollie');

		expect(getPaymentMethod.call(pageState())).toBe('mollie');
	});

	it('falls back to state when the page renders no radios', () => {
		document.body.innerHTML = '';

		expect(getPaymentMethod.call(pageState('SEPA Direct Debit'))).toBe('SEPA Direct Debit');
	});

	it('prefers an explicitly set method when nothing is checked', () => {
		renderPaymentRadios(null);

		expect(getPaymentMethod.call({ paymentMethod: 'Mollie', state: { get: () => '' } })).toBe('Mollie');
	});
});
