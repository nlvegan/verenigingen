/**
 * @fileoverview Unit tests for the REAL ValidationService class.
 *
 * The pre-existing validation-service.test.js re-implements the rules inline (a
 * copy) and therefore measures 0% of the shipped module. This suite requires the
 * real module (verenigingen/public/js/services/validation-service.js) so its
 * synchronous validation, label/message lookup, summary generation, caching and
 * debounced async paths are actually covered.
 *
 * The API service is injected as a test double — it is the server/HTTP boundary,
 * not business logic. All synchronous validation is exercised against the real
 * code; the async path is driven with Jest fake timers through the real 500ms
 * debounce.
 */

require('../../public/js/services/validation-service.js');
const ValidationService = window.ValidationService;

/** Build a ValidationService with a controllable fake API. */
function makeService(apiOverrides = {}) {
	const api = {
		validateEmail: jest.fn(async () => ({ valid: true })),
		validatePostalCode: jest.fn(async () => ({ valid: true })),
		validatePhoneNumber: jest.fn(async () => ({ valid: true })),
		validateBirthDate: jest.fn(async () => ({ valid: true, age: 30 })),
		...apiOverrides
	};
	return { service: new ValidationService(api), api };
}

describe('ValidationService (real module)', () => {
	describe('synchronous field validation', () => {
		let service;
		beforeEach(() => {
			service = makeService().service;
		});

		test('returns valid:true for an unknown field (no rule)', async () => {
			await expect(service.validateField('nickname', 'whatever')).resolves.toEqual({ valid: true });
		});

		test('flags a required field that is empty', async () => {
			const result = await service.validateField('firstName', '');
			expect(result.valid).toBe(false);
			expect(result.type).toBe('required');
			expect(result.message).toBe('First name is required');
		});

		test('enforces minLength with a friendly label', async () => {
			const result = await service.validateField('firstName', 'J');
			expect(result.valid).toBe(false);
			expect(result.type).toBe('minLength');
			expect(result.message).toContain('at least 2 characters');
		});

		test('enforces maxLength', async () => {
			const result = await service.validateField('city', 'x'.repeat(101));
			expect(result.valid).toBe(false);
			expect(result.type).toBe('maxLength');
		});

		test('rejects names with digits via the pattern rule', async () => {
			const result = await service.validateField('lastName', 'Vri3s');
			expect(result.valid).toBe(false);
			expect(result.type).toBe('pattern');
			expect(result.message).toContain('letters');
		});

		test('accepts a Dutch surname with tussenvoegsel and apostrophe', async () => {
			await expect(service.validateField('lastName', 'van der Berg-d\'Or'))
				.resolves.toEqual({ valid: true });
		});

		test('skips further checks for an optional empty field', async () => {
			// phone is not required; empty value short-circuits to valid before async
			await expect(service.validateField('phone', '')).resolves.toEqual({ valid: true });
		});
	});

	describe('field labels and pattern messages', () => {
		let service;
		beforeEach(() => {
			service = makeService().service;
		});

		test('maps known fields to human labels and falls back to the raw name', () => {
			expect(service._getFieldLabel('postalCode')).toBe('Postal code');
			expect(service._getFieldLabel('unknownField')).toBe('unknownField');
		});

		test('provides a field-specific pattern message, else a generic one', () => {
			expect(service._getPatternErrorMessage('email')).toContain('valid email');
			expect(service._getPatternErrorMessage('country')).toContain('valid country');
		});
	});

	describe('validateFields (multi-field)', () => {
		test('aggregates errors and reports overall validity', async () => {
			const { service } = makeService();
			const result = await service.validateFields(
				{ firstName: '', lastName: 'Doe', city: 'Utrecht', country: 'Netherlands' },
				['firstName', 'lastName', 'city', 'country']
			);
			expect(result.valid).toBe(false);
			expect(result.errors).toHaveLength(1);
			expect(result.errors[0].field).toBe('firstName');
			expect(result.summary.total).toBe(4);
			expect(result.summary.invalid).toBe(1);
			expect(result.summary.valid).toBe(3);
		});

		test('reports valid:true when all sync fields pass', async () => {
			const { service } = makeService();
			const result = await service.validateFields(
				{ firstName: 'Jan', lastName: 'Jansen', address: 'Hoofdstraat 1', city: 'Utrecht', country: 'Netherlands' },
				['firstName', 'lastName', 'address', 'city', 'country']
			);
			expect(result.valid).toBe(true);
			expect(result.errors).toHaveLength(0);
		});
	});

	describe('validateStep', () => {
		test('an empty step (no fields) is always valid', async () => {
			const { service } = makeService();
			const result = await service.validateStep(3, {});
			expect(result.valid).toBe(true);
			expect(result.summary.total).toBe(0);
		});

		test('an out-of-range step maps to no fields', async () => {
			const { service } = makeService();
			const result = await service.validateStep(99, {});
			expect(result.valid).toBe(true);
		});
	});

	describe('async validation (debounced, real timers driven by fake clock)', () => {
		beforeEach(() => jest.useFakeTimers());
		afterEach(() => {
			jest.runOnlyPendingTimers();
			jest.useRealTimers();
		});

		test('email passes basic checks then calls the API after the debounce', async () => {
			const { service, api } = makeService({
				validateEmail: jest.fn(async () => ({ valid: true, message: 'Email available' }))
			});

			const promise = service.validateField('email', 'jan@example.com');
			await jest.advanceTimersByTimeAsync(500);
			const result = await promise;

			expect(api.validateEmail).toHaveBeenCalledWith('jan@example.com');
			expect(result.valid).toBe(true);
			expect(result.message).toBe('Email available');
		});

		test('caches a successful async result (second call skips the API)', async () => {
			const { service, api } = makeService({
				validateEmail: jest.fn(async () => ({ valid: true }))
			});

			const p1 = service.validateField('email', 'cache@example.com');
			await jest.advanceTimersByTimeAsync(500);
			await p1;

			const p2 = service.validateField('email', 'cache@example.com');
			await jest.advanceTimersByTimeAsync(500);
			await p2;

			expect(api.validateEmail).toHaveBeenCalledTimes(1);
		});

		test('surfaces a network error as an unavailable-validation result', async () => {
			const { service } = makeService({
				validateEmail: jest.fn(async () => {
					throw new Error('network down');
				})
			});

			const promise = service.validateField('email', 'boom@example.com');
			await jest.advanceTimersByTimeAsync(500);
			const result = await promise;

			expect(result.valid).toBe(false);
			expect(result.type).toBe('network');
		});

		test('_validateAge passes an under-12 warning through', async () => {
			const { service } = makeService({
				validateBirthDate: jest.fn(async () => ({ valid: true, age: 8 }))
			});

			const promise = service.validateField('birthDate', '2018-01-01');
			await jest.advanceTimersByTimeAsync(500);
			const result = await promise;

			expect(result.valid).toBe(true);
			expect(result.warning).toContain('parental consent');
			expect(result.age).toBe(8);
		});

		test('_validateAge returns the API failure verbatim', async () => {
			const { service } = makeService({
				validateBirthDate: jest.fn(async () => ({ valid: false, message: 'Future date' }))
			});

			const promise = service.validateField('birthDate', '2999-01-01');
			await jest.advanceTimersByTimeAsync(500);
			const result = await promise;

			expect(result.valid).toBe(false);
			expect(result.message).toBe('Future date');
		});

		test('postalCode runs its custom format validation through the API', async () => {
			const { service, api } = makeService({
				validatePostalCode: jest.fn(async () => ({ valid: true, city: 'Utrecht' }))
			});

			const promise = service.validateField('postalCode', '3511AB', { country: 'Netherlands' });
			await jest.advanceTimersByTimeAsync(500);
			const result = await promise;

			expect(api.validatePostalCode).toHaveBeenCalledWith('3511AB', 'Netherlands');
			expect(result.valid).toBe(true);
		});
	});

	// Realistic input cases ported from the legacy validation-service.test.js
	// (which tested an inline COPY of the rules at 0% real coverage). Here they
	// run against the SHIPPED module. Pattern *rejections* resolve synchronously
	// in _validateBasic before the async branch, so no timers are needed.
	describe('realistic input patterns (real module)', () => {
		let service;
		let api;
		beforeEach(() => {
			({ service, api } = makeService());
		});

		test.each(['Pieter', 'Jan-Willem', 'O\'Connor', 'José', 'Anne-Marie'])(
			'accepts Dutch/international first name %p',
			async (name) => {
				await expect(service.validateField('firstName', name)).resolves.toEqual({ valid: true });
			}
		);

		test.each(['John123', 'User@Name'])('rejects a malformed name %p', async (name) => {
			const result = await service.validateField('firstName', name);
			expect(result.valid).toBe(false);
			expect(result.type).toBe('pattern');
		});

		test.each(['invalid.email', '@domain.com', 'user@'])(
			'rejects a malformed email %p without calling the API',
			async (email) => {
				const result = await service.validateField('email', email);
				expect(result.valid).toBe(false);
				expect(result.type).toBe('pattern');
				expect(api.validateEmail).not.toHaveBeenCalled();
			}
		);

		test.each(['abc-def-ghij', '12'])('rejects a malformed phone %p', async (phone) => {
			const result = await service.validateField('phone', phone);
			expect(result.valid).toBe(false);
			expect(result.type).toBe('pattern');
		});
	});

	describe('well-formed email/phone reach the API after the debounce', () => {
		beforeEach(() => jest.useFakeTimers());
		afterEach(() => {
			jest.runOnlyPendingTimers();
			jest.useRealTimers();
		});

		test.each(['member@example.com', 'test.user+tag@domain.org', 'user123@test-domain.nl'])(
			'%p passes the pattern and is sent to the email API',
			async (email) => {
				const { service, api } = makeService({ validateEmail: jest.fn(async () => ({ valid: true })) });
				const promise = service.validateField('email', email);
				await jest.advanceTimersByTimeAsync(500);
				const result = await promise;
				expect(api.validateEmail).toHaveBeenCalledWith(email);
				expect(result.valid).toBe(true);
			}
		);

		test.each(['+31 6 12345678', '06-12345678', '(020) 123-4567'])(
			'well-formed phone %p passes the pattern and is sent to the phone API',
			async (phone) => {
				const { service, api } = makeService({ validatePhoneNumber: jest.fn(async () => ({ valid: true })) });
				const promise = service.validateField('phone', phone, { country: 'Netherlands' });
				await jest.advanceTimersByTimeAsync(500);
				const result = await promise;
				expect(api.validatePhoneNumber).toHaveBeenCalled();
				expect(result.valid).toBe(true);
			}
		);
	});

	describe('_performAPIValidation routing', () => {
		test('routes phone to the phone API and unknown fields to valid:true', async () => {
			const { service, api } = makeService({
				validatePhoneNumber: jest.fn(async () => ({ valid: true }))
			});
			await service._performAPIValidation('phone', '+31612345678', { country: 'Netherlands' });
			expect(api.validatePhoneNumber).toHaveBeenCalledWith('+31612345678', 'Netherlands');

			await expect(service._performAPIValidation('somethingElse', 'x', {}))
				.resolves.toEqual({ valid: true });
		});
	});

	describe('_validateAge for centenarians', () => {
		test('an age over 100 is accepted and the age is echoed back', async () => {
			const { service } = makeService({
				validateBirthDate: jest.fn(async () => ({ valid: true, age: 104 }))
			});
			const result = await service._validateAge('1920-01-01', {});
			expect(result.valid).toBe(true);
			expect(result.age).toBe(104);
		});
	});

	describe('real-time UI rendering (jsdom)', () => {
		function buildField() {
			const input = document.createElement('input');
			const wrapper = document.createElement('div');
			wrapper.appendChild(input);
			document.body.appendChild(wrapper);
			return input;
		}

		test('renders a valid state with a feedback element', () => {
			const { service } = makeService();
			const input = buildField();

			service._showValidationResult(input, { valid: true, message: 'Looks good!' });

			expect(input.classList.contains('is-valid')).toBe(true);
			const feedback = input.parentNode.querySelector('.feedback');
			expect(feedback.classList.contains('valid-feedback')).toBe(true);
			expect(feedback.textContent).toBe('Looks good!');
		});

		test('renders an invalid state', () => {
			const { service } = makeService();
			const input = buildField();

			service._showValidationResult(input, { valid: false, message: 'Bad value' });

			expect(input.classList.contains('is-invalid')).toBe(true);
			expect(input.parentNode.querySelector('.feedback').textContent).toBe('Bad value');
		});

		test('renders a warning over a valid result', () => {
			const { service } = makeService();
			const input = buildField();

			service._showValidationResult(input, { valid: true, warning: 'Heads up' });

			const feedback = input.parentNode.querySelector('.feedback');
			expect(feedback.classList.contains('text-warning')).toBe(true);
			expect(feedback.textContent).toBe('Heads up');
		});

		test('shows a transient validating state', () => {
			const { service } = makeService();
			const input = buildField();

			service._showValidationState(input, 'validating');

			expect(input.classList.contains('is-validating')).toBe(true);
			expect(input.parentNode.querySelector('.feedback').textContent).toBe('Validating...');
		});

		test('reuses an existing feedback element instead of creating duplicates', () => {
			const { service } = makeService();
			const input = buildField();
			const first = service._ensureFeedbackElement(input);
			const second = service._ensureFeedbackElement(input);
			expect(first).toBe(second);
			expect(input.parentNode.querySelectorAll('.feedback')).toHaveLength(1);
		});

		test('setupRealTimeValidation wires events and validates on input', async () => {
			const { service } = makeService();
			const input = buildField();

			const returned = service.setupRealTimeValidation(input, 'firstName', () => ({}));
			expect(returned).toBe(input);
			expect(input.dataset.validationState).toBe('pending');

			// firstName is synchronous: an empty value is invalid, no debounce timer.
			input.value = '';
			input.dispatchEvent(new Event('input'));
			await Promise.resolve();
			await Promise.resolve();

			expect(input.dataset.validationState).toBe('invalid');
		});

		test('a blur event with a value shows the validating state first', async () => {
			const { service } = makeService();
			const input = buildField();
			service.setupRealTimeValidation(input, 'firstName', {});

			input.value = 'Jan';
			input.dispatchEvent(new Event('blur'));
			await Promise.resolve();
			await Promise.resolve();

			// Valid name -> ends valid after the validating flash.
			expect(input.dataset.validationState).toBe('valid');
		});
	});

	describe('validation summary counts warnings and invalids directly', () => {
		test('_generateValidationSummary tallies valid, invalid and warnings', () => {
			const { service } = makeService();
			const summary = service._generateValidationSummary({
				a: { valid: true },
				b: { valid: true, warning: 'w' },
				c: { valid: false }
			});
			expect(summary).toEqual({ total: 3, valid: 2, invalid: 1, warnings: 1 });
		});
	});

	describe('cache + stats utilities', () => {
		test('clearCache(pattern) removes only matching entries', () => {
			const { service } = makeService();
			service.validationCache.set('email:a@b.com', { valid: true });
			service.validationCache.set('phone:12345', { valid: true });

			service.clearCache('email');

			expect(service.validationCache.has('email:a@b.com')).toBe(false);
			expect(service.validationCache.has('phone:12345')).toBe(true);
		});

		test('clearCache() with no pattern empties the cache', () => {
			const { service } = makeService();
			service.validationCache.set('x', 1);
			service.clearCache();
			expect(service.validationCache.size).toBe(0);
		});

		test('getValidationStats reports cache, timers and rule counts', () => {
			const { service } = makeService();
			service.validationCache.set('x', 1);
			const stats = service.getValidationStats();
			expect(stats.cacheSize).toBe(1);
			expect(stats.activeTimers).toBe(0);
			expect(stats.rules).toBeGreaterThan(0);
		});
	});
});
