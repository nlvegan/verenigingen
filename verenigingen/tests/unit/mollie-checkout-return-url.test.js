/**
 * @fileoverview The success redirect of the Mollie checkout page (#1996).
 *
 * redirectToSuccess runs after the checkout's own status poll saw "Completed". It must send
 * the payer to this app's /payment_success (not the payments app's hyphenated route, which
 * reports success for any outcome) and carry BOTH proofs the page accepts: the Mollie
 * payment id and the return token make_payment minted after its ownership check. Sales
 * Invoice has no payment_id field, so for it the token is the only proof that works.
 *
 * The real script is executed, with a fake `window` so the assigned location can be read.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = fs.readFileSync(
	path.join(__dirname, '../../verenigingen_payments/templates/includes/mollie_checkout.js'),
	'utf8'
);

/** Run mollie_checkout.js against a page whose make_payment answers `payment`; return the redirect. */
function followCompletedCheckout(payment, pageConfig) {
	jest.useFakeTimers();
	document.body.innerHTML = `
		<script type="application/json" id="page-config">${JSON.stringify(pageConfig)}</script>
		<script type="application/json" id="payment-data">${JSON.stringify({ amount: '10' })}</script>
		<form id="payment-form"></form>`;
	const fakeWindow = { location: { href: '' }, addEventListener: () => {} };
	const fakeJquery = () => ({ ready: (callback) => callback() });
	const fakeFrappe = { call: (options) => options.callback({ message: payment }) };

	// eslint-disable-next-line no-new-func -- runs the real script against a fake window
	new Function('window', 'document', '$', 'frappe', '__', SOURCE)(
		fakeWindow,
		document,
		fakeJquery,
		fakeFrappe,
		(text) => ({ format: () => text, toString: () => text })
	);
	document.getElementById('payment-form').dispatchEvent(new Event('submit', { cancelable: true }));
	jest.advanceTimersByTime(5000);
	jest.useRealTimers();
	return fakeWindow.location.href;
}

describe('mollie_checkout.js redirectToSuccess', () => {
	const pageConfig = { reference_doctype: 'Sales Invoice', reference_docname: 'SINV-0001' };
	const payment = { status: 'Completed', paymentID: 'tr_abc123', returnToken: 'deadbeef' };

	test('goes to /payment_success carrying the doctype, docname, payment_id and return token', () => {
		const url = new URL(followCompletedCheckout(payment, pageConfig), 'http://site.test');
		expect(url.pathname).toBe('/payment_success');
		expect(url.searchParams.get('doctype')).toBe('Sales Invoice');
		expect(url.searchParams.get('docname')).toBe('SINV-0001');
		expect(url.searchParams.get('payment_id')).toBe('tr_abc123');
		expect(url.searchParams.get('token')).toBe('deadbeef');
	});

	test('sends no token parameter when the server minted none', () => {
		const url = new URL(
			followCompletedCheckout({ status: 'Completed', paymentID: 'tr_abc123' }, pageConfig),
			'http://site.test'
		);
		expect(url.pathname).toBe('/payment_success');
		expect(url.searchParams.has('token')).toBe(false);
	});
});
