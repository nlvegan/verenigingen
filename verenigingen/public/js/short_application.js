/* Client side of the short membership application (/word-lid).
 * The checks here only mirror the server rules for UX; the server stays the authority. */
(function () {
	const SUBMIT = 'verenigingen.api.short_application.submit_short_application';
	const CONFIRM = 'verenigingen.api.short_application.confirm_short_application';
	const MAX_REASONS = 5;
	const DELIVERY_QUESTIONS = ['magazine_delivery', 'starter_guide_delivery'];
	const INTERVAL_LABELS = {
		monthly: __('per month'),
		quarterly: __('per quarter'),
		semiannually: __('every 6 months'),
		annually: __('per year')
	};

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
		// @handle_api_error failures carry `error`, not `message`: those get the generic text too.
		if (message && typeof message === 'object' && 'success' in message && typeof message.message === 'string') {
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
				showStatusLink(result, response.status_url);
			} else {
				button.disabled = false;
			}
		});
	}

	function showStatusLink(result, statusUrl) {
		// Only our own status page: the value comes from the server, but a link is never built from
		// anything that does not start with its path.
		if (typeof statusUrl !== 'string' || !statusUrl.startsWith('/application_status?')) {
			return;
		}
		const link = document.createElement('a');
		link.href = statusUrl;
		link.textContent = __('Bekijk de status van je aanmelding');
		result.appendChild(document.createElement('br'));
		result.appendChild(link);
	}

	function initApplicationForm(form) {
		const plans = JSON.parse(form.dataset.plans || '[]');
		const isRegular = form.dataset.shape === 'Regular';
		const state = { form, plans, isRegular, plan: null };
		form.addEventListener('change', (event) => {
			if (event.target.name === 'plan_choice') {
				selectPlan(state, event.target.value);
			}
			refresh(state);
		});
		form.addEventListener('input', () => refresh(state));
		form.addEventListener('submit', (event) => {
			event.preventDefault();
			submit(state);
		});
		if (isRegular) {
			bindCalculator(state);
			selectPlan(state, form.dataset.defaultPlan);
		}
		refresh(state);
	}

	function value(form, name) {
		const el = form.elements[name];
		return el ? (el.value || '').trim() : '';
	}

	function isPostal(form) {
		return DELIVERY_QUESTIONS.some((name) => {
			const choice = value(form, name);
			return choice === 'Papier' || choice === 'Beide';
		});
	}

	function minimumFor(plan, postal) {
		if (!plan) {
			return 0;
		}
		return postal ? Math.max(plan.minimum, plan.postal_minimum) : plan.minimum;
	}

	function refresh(state) {
		if (!state.isRegular) {
			return;
		}
		const { form, plan } = state;
		refreshDeliveryOptions(form);
		const minimum = minimumFor(plan, isPostal(form));
		const hint = document.getElementById('wl-minimum-hint');
		hint.textContent = minimum ? __('Minimum amount: {0}', [format(minimum)]) : '';
		const ibanHint = document.getElementById('wl-iban-hint');
		ibanHint.style.fontWeight = plan && plan.frequency === 'Monthly' ? '600' : '';
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
			// Undo a choice that is no longer available; the applicant chooses again (#1968).
			if (select.selectedOptions[0] && select.selectedOptions[0].disabled) {
				select.value = '';
			}
		});
	}

	function byId(id) {
		return document.getElementById(id);
	}

	function show(id, visible) {
		byId(id).style.display = visible ? '' : 'none';
	}

	// The plan's template decides how the amount is chosen. Choosing a plan rebuilds the amount
	// controls, so an amount ticked or typed for another plan can never be posted for this one.
	function selectPlan(state, planId) {
		const plan = state.plans.find((candidate) => candidate.id === planId) || null;
		state.plan = plan;
		byId('wl-plan').value = plan ? plan.id : '';
		renderAmount(state);
	}

	function renderAmount(state) {
		const { plan } = state;
		const mode = plan ? plan.mode : '';
		const choices = byId('wl-amount-choices');
		choices.textContent = '';
		byId('wl-custom-amount').value = '';
		byId('wl-calculated-amount').textContent = '';
		state.calculated = '';
		state.suggestion = 0;
		show('wl-fixed-amount', mode === 'Fixed');
		show('wl-custom-amount-row', mode === 'Flexible' && plan.allow_custom);
		show('wl-calculated-row', false);
		byId('income-calculator').style.display = 'none';
		if (mode === 'Fixed') {
			byId('wl-fixed-amount').textContent = `${format(plan.amount)} ${plan.billing_display}`;
		} else if (mode === 'Flexible') {
			amountChoices(plan).forEach((amount) => choices.appendChild(amountRadio(amount, plan)));
		} else if (mode === 'Income-Based') {
			showCalculator(state);
		}
	}

	// The template's suggested amount and the door's presets for this plan, lowest first.
	function amountChoices(plan) {
		const amounts = [plan.suggested, ...plan.presets].filter((amount) => amount > 0);
		return Array.from(new Set(amounts)).sort((left, right) => left - right);
	}

	function amountRadio(amount, plan) {
		const label = document.createElement('label');
		label.className = 'flex items-center gap-2 mb-1';
		const radio = document.createElement('input');
		radio.type = 'radio';
		radio.name = 'amount_choice';
		radio.value = String(amount);
		const text = document.createElement('span');
		text.textContent = amount === plan.suggested ? `${format(amount)} (${__('suggested')})` : format(amount);
		label.append(radio, text);
		return label;
	}

	function showCalculator(state) {
		const { plan } = state;
		const calculator = window.ContributionCalculator;
		byId('income-calculator').style.display = 'block';
		byId('calculator-description').textContent = (plan.calculator && plan.calculator.description) || '';
		byId('calc-payment-interval').value = calculator.intervalFor(plan.frequency);
		byId('calc-monthly-income').value = '';
		calculator.render(null);
		byId('calculator-hint').style.display = '';
	}

	function bindCalculator(state) {
		const income = byId('calc-monthly-income');
		const interval = byId('calc-payment-interval');
		const update = () => updateCalculator(state);
		income.addEventListener('input', update);
		interval.addEventListener('change', update);
		// Enter in the income box would submit the application.
		income.addEventListener('keydown', (event) => {
			if (event.key === 'Enter') {
				event.preventDefault();
			}
		});
		byId('apply-calculated-amount').addEventListener('click', () => applyCalculated(state));
	}

	function updateCalculator(state) {
		const { plan } = state;
		if (!plan || plan.mode !== 'Income-Based') {
			return;
		}
		const calculator = window.ContributionCalculator;
		const interval = byId('calc-payment-interval').value;
		const result = calculator.compute(
			plan.calculator,
			plan.mode,
			parseFloat(byId('calc-monthly-income').value) || 0,
			interval
		);
		state.suggestion = result ? result.amount : 0;
		calculator.render(result, INTERVAL_LABELS[interval]);
	}

	function applyCalculated(state) {
		if (!(state.suggestion > 0)) {
			return;
		}
		state.calculated = state.suggestion.toFixed(2);
		const interval = INTERVAL_LABELS[byId('calc-payment-interval').value];
		byId('wl-calculated-amount').textContent = `${format(state.suggestion)} ${interval}`;
		show('wl-calculated-row', true);
	}

	// The amount to post for the selected plan.
	function chosenAmount(form, plan, state) {
		if (!plan) {
			return '';
		}
		if (plan.mode === 'Fixed') {
			return String(plan.amount);
		}
		if (plan.mode === 'Income-Based') {
			return (state && state.calculated) || '';
		}
		const choice = form.querySelector('input[name="amount_choice"]:checked');
		if (!choice) {
			return '';
		}
		return choice.value === 'custom' ? form.querySelector('#wl-custom-amount').value : choice.value;
	}

	function collect(state) {
		const { form } = state;
		const data = { door: form.dataset.door };
		Array.from(form.elements).forEach((el) => {
			if (
				!el.name ||
				['amount_choice', 'plan_choice', 'join_reasons'].includes(el.name) ||
				el.type === 'checkbox'
			) {
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
			data.amount = chosenAmount(form, state.plan, state);
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
		if (!state.plan) {
			found.push(__('Please choose a payment plan.'));
		}
		const minimum = minimumFor(state.plan, isPostal(state.form));
		if (!data.amount || Number(data.amount) < minimum) {
			found.push(
				minimum ? __('The amount must be at least {0}.', [format(minimum)]) : __('Please choose an amount.')
			);
		}
		if (state.plan && state.plan.frequency === 'Monthly' && !data.iban) {
			found.push(__('A monthly contribution requires an IBAN (direct debit).'));
		}
		if (!data.consent) {
			found.push(__('Please agree to the membership terms.'));
		}
		// Rendered unanswered (#1968); a hidden question is not rendered, so it is not in the form.
		if (DELIVERY_QUESTIONS.some((name) => state.form.elements[name] && !data[name])) {
			found.push(__('Please choose how you want to receive the magazine and the starter guide.'));
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

	window.ShortApplication = {
		chosenAmount,
		problems,
		refreshDeliveryOptions,
		selectPlan,
		renderAmount,
		amountChoices,
		minimumFor
	};

	frappe.ready(init);
})();
