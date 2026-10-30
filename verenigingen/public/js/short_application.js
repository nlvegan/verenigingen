/* Client side of the short membership application (/word-lid).
 * The checks here only mirror the server rules for UX; the server stays the authority. */
(function () {
	const SUBMIT = 'verenigingen.api.short_application.submit_short_application';
	const CONFIRM = 'verenigingen.api.short_application.confirm_short_application';
	const MAX_REASONS = 5;

	function post(method, args) {
		return new Promise((resolve) => {
			frappe.call({
				method,
				type: 'POST',
				args,
				// website.js answers callback/error only on 200/417; `always` runs on every outcome,
				// so a 429, 403 or 5xx also ends the wait instead of leaving the button disabled.
				always: (data) => resolve(responseOf(data))
			});
		});
	}

	function responseOf(data) {
		const message = data && data.message;
		if (message && typeof message === 'object' && 'success' in message) {
			return message;
		}
		return { success: false, message: __('Er ging iets mis. Probeer het later opnieuw.') };
	}

	function init() {
		const form = document.getElementById('short-application-form');
		if (form) {
			initApplicationForm(form);
		}
		const confirmForm = document.getElementById('confirm-form');
		if (confirmForm) {
			initConfirm(confirmForm);
		}
	}

	function initConfirm(confirmForm) {
		confirmForm.addEventListener('submit', async (event) => {
			event.preventDefault();
			const button = document.getElementById('confirm-button');
			const result = document.getElementById('confirm-result');
			button.disabled = true;
			const response = await post(CONFIRM, {
				submission: confirmForm.dataset.submission,
				token: confirmForm.dataset.token
			});
			result.textContent = response.message;
			if (response.success) {
				confirmForm.style.display = 'none';
			} else {
				button.disabled = false;
			}
		});
	}

	function initApplicationForm(form) {
		const minimums = JSON.parse(form.dataset.minimums || '{}');
		const isRegular = form.dataset.shape === 'Regular';
		const state = { form, minimums, isRegular };
		const toggle = document.getElementById('wl-annual-toggle');
		if (toggle) {
			toggle.addEventListener('change', () => {
				document.getElementById('wl-frequency').value = toggle.checked ? 'Annual' : 'Monthly';
				resetAmountOnFrequencyChange(form);
				refresh(state);
			});
		}
		form.addEventListener('change', () => refresh(state));
		form.addEventListener('input', () => refresh(state));
		form.addEventListener('submit', (event) => {
			event.preventDefault();
			submit(state);
		});
		refresh(state);
	}

	function value(form, name) {
		const el = form.elements[name];
		return el ? (el.value || '').trim() : '';
	}

	function frequencyOf(form) {
		return value(form, 'frequency');
	}

	function isPostal(form) {
		return ['magazine_delivery', 'starter_guide_delivery'].some((name) => {
			const choice = value(form, name);
			return choice === 'Papier' || choice === 'Beide';
		});
	}

	function refresh(state) {
		if (!state.isRegular) {
			return;
		}
		const { form } = state;
		const frequency = frequencyOf(form);
		document.querySelectorAll('#wl-amount-block label[data-frequency]').forEach((row) => {
			row.style.display = row.dataset.frequency === frequency ? '' : 'none';
		});
		refreshDeliveryOptions(form);
		const limits = state.minimums[frequency] || { base: 0, postal: 0 };
		const minimum = isPostal(form) ? limits.postal : limits.base;
		const hint = document.getElementById('wl-minimum-hint');
		hint.textContent = minimum ? __('Minimum amount: {0}', [format(minimum)]) : '';
		const ibanHint = document.getElementById('wl-iban-hint');
		ibanHint.style.fontWeight = frequency === 'Monthly' ? '600' : '';
	}

	function format(amount) {
		return `€ ${Number(amount).toFixed(2)}`;
	}

	function refreshDeliveryOptions(form) {
		const abroad = value(form, 'country') !== 'Netherlands';
		form.querySelectorAll('.delivery-select').forEach((select) => {
			Array.from(select.options).forEach((option) => {
				option.disabled = abroad && (option.value === 'Papier' || option.value === 'Beide');
			});
			if (select.selectedOptions[0] && select.selectedOptions[0].disabled) {
				select.value = 'Digitaal';
			}
		});
	}

	// A tier belongs to one frequency. Only the selected frequency's tiers count, so a tier ticked
	// before switching Monthly/Annual can never be posted for the other period.
	function chosenAmount(form) {
		const choice = form.querySelector('input[name="amount_choice"]:checked');
		if (!choice) {
			return '';
		}
		if (choice.value === 'custom') {
			return form.querySelector('#wl-custom-amount').value;
		}
		const row = choice.closest('label[data-frequency]');
		return row && row.dataset.frequency === frequencyOf(form) ? choice.value : '';
	}

	function resetAmountOnFrequencyChange(form) {
		form.querySelectorAll('label[data-frequency] input[name="amount_choice"]').forEach((radio) => {
			if (radio.closest('label').dataset.frequency !== frequencyOf(form)) {
				radio.checked = false;
			}
		});
		const custom = form.querySelector('#wl-custom-amount');
		if (custom) {
			custom.value = '';
		}
	}

	function collect(state) {
		const { form } = state;
		const data = { door: form.dataset.door };
		Array.from(form.elements).forEach((el) => {
			if (!el.name || el.name === 'amount_choice' || el.name === 'join_reasons' || el.type === 'checkbox') {
				return;
			}
			data[el.name] = (el.value || '').trim();
		});
		['consent', 'housemate_confirmed'].forEach((name) => {
			if (form.elements[name] && form.elements[name].checked) {
				data[name] = 1;
			}
		});
		data.join_reasons = Array.from(form.querySelectorAll('input[name="join_reasons"]:checked')).map(
			(el) => el.value
		);
		if (state.isRegular) {
			data.amount = chosenAmount(form);
		}
		return data;
	}

	function problems(state, data) {
		const found = [];
		['first_name', 'last_name', 'email', 'postal_code', 'house_number', 'address_line1', 'city'].forEach((name) => {
			if (!data[name]) {
				found.push(__('Please fill in all required fields.'));
			}
		});
		if (state.isRegular) {
			found.push(...regularProblems(state, data));
		} else if (!data.housemate_of_name || !data.housemate_confirmed) {
			found.push(__('Please give the name of the paying member and confirm they live at your address.'));
		}
		if (data.join_reasons.length > MAX_REASONS) {
			found.push(__('Choose at most {0} reasons.', [MAX_REASONS]));
		}
		return Array.from(new Set(found));
	}

	function regularProblems(state, data) {
		const found = [];
		const limits = state.minimums[data.frequency] || { base: 0, postal: 0 };
		const minimum = isPostal(state.form) ? limits.postal : limits.base;
		if (!data.amount || Number(data.amount) < minimum) {
			found.push(
				minimum ? __('The amount must be at least {0}.', [format(minimum)]) : __('Please choose an amount.')
			);
		}
		if (data.frequency === 'Monthly' && !data.iban) {
			found.push(__('A monthly contribution requires an IBAN (direct debit).'));
		}
		if (!data.consent) {
			found.push(__('Please agree to the membership terms.'));
		}
		return found;
	}

	async function submit(state) {
		const error = document.getElementById('wl-error');
		const button = document.getElementById('wl-submit');
		const data = collect(state);
		const found = problems(state, data);
		error.textContent = found.join(' ');
		if (found.length) {
			return;
		}
		button.disabled = true;
		const response = await post(SUBMIT, data);
		if (response.success) {
			state.form.style.display = 'none';
			const done = document.getElementById('wl-done');
			done.textContent = response.message;
			done.style.display = '';
		} else {
			error.textContent = response.message;
			button.disabled = false;
		}
	}

	window.ShortApplication = { chosenAmount, resetAmountOnFrequencyChange };

	frappe.ready(init);
})();
