/* The income calculator of the membership application forms, shared by the full form
 * (apply_for_membership.html) and the short form (/word-lid, short_application.js).
 *
 * `settings` is the `contribution_settings` the server builds for a dues template
 * (MembershipApplicationService._build_contribution_settings). The result is only a suggestion: the
 * server checks the amount an applicant submits against the template, never the income. */
(function (root) {
	const INTERVAL_MULTIPLIERS = { monthly: 1, quarterly: 3, semiannually: 6, annually: 12 };
	const FREQUENCY_INTERVALS = {
		Monthly: 'monthly',
		Quarterly: 'quarterly',
		'Semi-Annual': 'semiannually',
		Annual: 'annually',
		Annually: 'annually'
	};
	const DEFAULT_INTERVAL = 'quarterly';
	const DEFAULT_REFERENCE_INCOME = 3500;
	const DEFAULT_LOWER_THRESHOLD = 2200;
	const DEFAULT_PERCENTAGE = 0.75;

	function intervalFor(billingFrequency) {
		return FREQUENCY_INTERVALS[billingFrequency] || DEFAULT_INTERVAL;
	}

	function isProgressive(mode, settings) {
		return (
			(mode === 'Income-Based' && settings.calculation_type === 'Progressive') ||
			(mode === 'Progressive' && !!settings.progressive)
		);
	}

	function progressive(settings, monthlyIncome, multiplier) {
		const prog = settings.progressive || {};
		const referenceIncome = prog.reference_income || DEFAULT_REFERENCE_INCOME;
		const lowerThreshold = prog.lower_threshold || DEFAULT_LOWER_THRESHOLD;
		let percentage;
		if (monthlyIncome <= lowerThreshold) {
			percentage = 0.5; // minimum 0.5%
		} else if (monthlyIncome >= referenceIncome) {
			percentage = 1.0; // maximum 1%
		} else {
			const ratio = (monthlyIncome - lowerThreshold) / (referenceIncome - lowerThreshold);
			percentage = 0.5 + ratio * 0.5; // 0.5% to 1%
		}
		const position = ((monthlyIncome - lowerThreshold) / (referenceIncome - lowerThreshold)) * 100;
		return {
			kind: 'progressive',
			percentage,
			amount: ((monthlyIncome * percentage) / 100) * multiplier,
			position: Math.min(100, Math.max(0, position))
		};
	}

	function percentageBased(settings, monthlyIncome, multiplier) {
		const percentage =
			settings.percentage || (settings.calculator && settings.calculator.percentage) || DEFAULT_PERCENTAGE;
		return { kind: 'percentage', percentage, amount: ((monthlyIncome * percentage) / 100) * multiplier };
	}

	/** The suggestion for a monthly net income, or null when there is nothing to calculate. */
	function compute(settings, mode, monthlyIncome, interval) {
		const income = Number(monthlyIncome);
		if (!(income > 0) || !settings) {
			return null;
		}
		const multiplier = INTERVAL_MULTIPLIERS[interval] || INTERVAL_MULTIPLIERS[DEFAULT_INTERVAL];
		if (isProgressive(mode, settings)) {
			return { ...progressive(settings, income, multiplier), income };
		}
		if (mode === 'Calculator' || mode === 'Income-Based') {
			return { ...percentageBased(settings, income, multiplier), income };
		}
		return null;
	}

	function show(doc, id, visible) {
		const el = doc.getElementById(id);
		if (el) {
			el.style.display = visible ? 'block' : 'none';
		}
	}

	function text(doc, id, value) {
		const el = doc.getElementById(id);
		if (el) {
			el.textContent = value;
		}
	}

	/** Shows `result` in the calculator markup (templates/includes/contribution_calculator.html). */
	function render(result, intervalLabel, doc) {
		doc = doc || document;
		if (!result) {
			['calc-result', 'progressive-calc-result', 'apply-calculated-amount'].forEach((id) => show(doc, id, false));
			return;
		}
		const amount = `€${result.amount.toFixed(2)}`;
		if (result.kind === 'progressive') {
			text(doc, 'progressive-percentage', `${result.percentage.toFixed(2)}%`);
			text(doc, 'progressive-suggested-amount', amount);
			text(doc, 'progressive-payment-frequency', intervalLabel);
			text(doc, 'progressive-monthly-income', result.income.toFixed(0));
			text(doc, 'progressive-percentage-detail', `${result.percentage.toFixed(2)}%`);
			const marker = doc.getElementById('progressive-position-marker');
			if (marker) {
				marker.style.left = `${result.position}%`;
			}
		} else {
			text(doc, 'calc-suggested-amount', amount);
			text(doc, 'calc-payment-frequency', intervalLabel);
			text(doc, 'calc-income-percentage', `${result.percentage}%`);
		}
		show(doc, 'calc-result', result.kind === 'percentage');
		show(doc, 'progressive-calc-result', result.kind === 'progressive');
		show(doc, 'apply-calculated-amount', true);
		show(doc, 'calculator-hint', false);
	}

	const api = { compute, render, intervalFor, INTERVAL_MULTIPLIERS, FREQUENCY_INTERVALS };
	root.ContributionCalculator = api;
	if (typeof module !== 'undefined' && module.exports) {
		module.exports = api;
	}
})(typeof window !== 'undefined' ? window : globalThis);
