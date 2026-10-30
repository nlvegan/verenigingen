/**
 * @fileoverview /word-lid posts through frappe.call, whose website build answers only 200 and 417
 * through callback/error. Every other outcome (429 rate limit, 403, 5xx) must still end the wait:
 * re-enable the button and show a generic message.
 */

global.frappe = { ready: jest.fn(), call: jest.fn() };
global.__ = (s) => s;

require('../../public/js/short_application.js');

const init = frappe.ready.mock.calls[0][0];
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function renderConfirm() {
	document.body.innerHTML = `
		<form id="confirm-form" data-submission="S-1" data-token="t">
			<button id="confirm-button" type="submit">Bevestig</button>
		</form>
		<p id="confirm-result"></p>`;
	init();
	return document.getElementById('confirm-form');
}

// What website.js does for a response: statusCode handlers (200 -> callback, 417 -> error) and
// then, for every status, `always` with the parsed body.
function respond(status, body) {
	frappe.call.mockImplementation((opts) => {
		if (status === 200 && opts.callback) opts.callback(body);
		if (status === 417 && opts.error) opts.error(body);
		if (opts.always) opts.always(body);
	});
}

async function confirmWith(status, body) {
	respond(status, body);
	const form = renderConfirm();
	form.dispatchEvent(new Event('submit', { cancelable: true }));
	await flush();
	return {
		form,
		button: document.getElementById('confirm-button'),
		result: document.getElementById('confirm-result')
	};
}

describe('short application post', () => {
	test.each([429, 403, 502])('a %i response re-enables the button with a generic message', async (status) => {
		const { button, result } = await confirmWith(status, {});
		expect(button.disabled).toBe(false);
		expect(result.textContent).toBe('Er ging iets mis. Probeer het later opnieuw.');
	});

	test('a refusal from the server is shown as sent', async () => {
		const { button, result } = await confirmWith(200, { message: { success: false, message: 'Ongeldig' } });
		expect(button.disabled).toBe(false);
		expect(result.textContent).toBe('Ongeldig');
	});

	test('a success hides the form', async () => {
		const { form, result } = await confirmWith(200, { message: { success: true, message: 'Bedankt' } });
		expect(result.textContent).toBe('Bedankt');
		expect(form.style.display).toBe('none');
	});
});
