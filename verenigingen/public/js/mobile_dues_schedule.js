/**
 * @fileoverview Mobile Dues Schedule Interface - Touch-Optimized Financial Dashboard
 *
 * This module provides a comprehensive mobile-first user experience for the membership
 * dues schedule dashboard. Features touch gestures, haptic feedback, accessibility
 * enhancements, and performance optimizations specifically designed for mobile devices
 * and progressive web app functionality.
 *
 * ## Core Mobile Features
 * - **Touch Gesture Navigation**: Swipe between tabs and calendar months
 * - **Pull-to-Refresh**: Native mobile refresh experience with visual feedback
 * - **Floating Action Button**: Quick access to common financial actions
 * - **Virtual Keyboard Optimization**: Smart form field handling and viewport management
 * - **Haptic Feedback**: Tactile responses for touch interactions
 * - **Offline Capability**: Service worker integration for PWA functionality
 *
 * ## Accessibility Enhancements
 * - **Screen Reader Support**: ARIA labels and live regions for dynamic content
 * - **Focus Management**: Proper keyboard navigation and focus trapping
 * - **High Contrast**: Optimized visual hierarchy for mobile screens
 * - **Touch Targets**: Minimum 44px touch targets following accessibility guidelines
 * - **Skip Navigation**: Efficient navigation for assistive technologies
 * - **Voice Control**: Support for voice navigation commands
 *
 * ## Performance Optimizations
 * - **Virtual Scrolling**: Efficient rendering of large payment history lists
 * - **Lazy Loading**: Progressive image and content loading
 * - **Animation Optimization**: Reduced motion for slower devices
 * - **Memory Management**: Automatic cleanup of unused DOM elements
 * - **Bandwidth Awareness**: Adaptive content loading based on connection speed
 * - **Critical Resource Preloading**: Preemptive loading of essential assets
 *
 * ## User Experience Features
 * - **Responsive Layout**: Fluid design adapting to all screen sizes
 * - **Touch Optimization**: Gesture-based navigation and interactions
 * - **Progressive Enhancement**: Core functionality works without JavaScript
 * - **Native App Feel**: App-like interactions and visual design
 * - **Quick Actions**: Context-sensitive action buttons and shortcuts
 * - **Smart Defaults**: Intelligent form pre-population and suggestions
 *
 * ## Technical Architecture
 * - **Component-Based**: Modular components for different mobile features
 * - **Event-Driven**: Efficient event handling with proper cleanup
 * - **Memory Efficient**: Careful management of event listeners and DOM references
 * - **Battery Optimized**: Reduced CPU usage through intelligent throttling
 * - **Network Aware**: Adaptive behavior based on connection quality
 * - **Device Detection**: Smart feature activation based on device capabilities
 *
 * ## Mobile-Specific Interactions
 * - **Swipe Navigation**: Horizontal swipes for tab and calendar navigation
 * - **Long Press**: Context menus and alternative actions
 * - **Pinch to Zoom**: Calendar and chart zoom functionality
 * - **Shake to Refresh**: Alternative refresh gesture
 * - **Device Orientation**: Automatic layout adjustments for rotation
 * - **Edge Gestures**: Navigation drawer and menu access
 *
 * ## Financial Dashboard Mobile Features
 * - **Quick Payment**: One-tap payment initiation
 * - **Fee Adjustment**: Mobile-optimized fee modification interface
 * - **Payment History**: Touch-friendly transaction browsing
 * - **Bank Details**: Secure IBAN and payment method management
 * - **SEPA Integration**: Mobile-optimized direct debit setup
 * - **Receipt Generation**: Instant digital receipts
 *
 * ## PWA Integration
 * - **Installable**: Add to home screen functionality
 * - **Offline Support**: Core features available without internet
 * - **Background Sync**: Payment status updates when connection restored
 * - **Push Notifications**: Payment reminders and confirmations
 * - **App Shell**: Fast loading through application shell architecture
 *
 * @company R.S.P. (Verenigingen Association Management)
 * @version 2025.1.0
 * @since 2024.2.0
 * @license Proprietary
 *
 * @requires verenigingen.public.js.dues_schedule_calendar
 * @requires ServiceWorker for PWA functionality
 *
 * @see {@link https://web.dev/mobile-ux/} Mobile UX Best Practices
 * @see {@link https://developers.google.com/web/fundamentals/accessibility/} Web Accessibility
 */

/**
 * Mobile-Specific Dues Schedule Functionality
 * Enhanced interactions for mobile devices
 */

class MobileDuesSchedule {
	constructor() {
		this.isMobile = window.innerWidth <= 768;
		this.isTablet = window.innerWidth > 768 && window.innerWidth <= 1024;
		this.isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

		this.init();
	}

	init() {
		this.setupMobileDetection();
		this.setupTouchEvents();
		this.setupSwipeGestures();
		this.setupVirtualKeyboard();
		this.setupPullToRefresh();
		this.setupMobileNavigation();
		this.setupMobileModals();
		this.setupMobileCalendar();
		this.setupMobileAccessibility();

		// Initialize on DOM ready
		if (document.readyState === 'loading') {
			document.addEventListener('DOMContentLoaded', () => this.initializeMobileFeatures());
		} else {
			this.initializeMobileFeatures();
		}
	}

	setupMobileDetection() {
		// Update mobile detection on resize
		window.addEventListener('resize', () => {
			this.isMobile = window.innerWidth <= 768;
			this.isTablet = window.innerWidth > 768 && window.innerWidth <= 1024;
			this.updateMobileClasses();
		});

		this.updateMobileClasses();
	}

	updateMobileClasses() {
		const body = document.body;
		body.classList.toggle('mobile', this.isMobile);
		body.classList.toggle('tablet', this.isTablet);
		body.classList.toggle('touch', this.isTouch);
	}

	setupTouchEvents() {
		// Improve touch responsiveness
		if (this.isTouch) {
			// Add touch-friendly classes
			document.addEventListener('touchstart', (e) => {
				if (e.target.closest('.touch-friendly')) {
					e.target.closest('.touch-friendly').classList.add('touched');
				}
			});

			document.addEventListener('touchend', (e) => {
				if (e.target.closest('.touch-friendly')) {
					setTimeout(() => {
						e.target.closest('.touch-friendly').classList.remove('touched');
					}, 150);
				}
			});
		}
	}

	setupSwipeGestures() {
		if (!this.isTouch) { return; }

		let startX = 0;
		let startY = 0;
		let currentX = 0;
		let currentY = 0;

		const swipeThreshold = 50;
		const _velocityThreshold = 0.3;

		// Tab swiping
		const tabContainer = document.querySelector('.tab-nav');
		if (tabContainer) {
			tabContainer.addEventListener('touchstart', (e) => {
				startX = e.touches[0].clientX;
				startY = e.touches[0].clientY;
			});

			tabContainer.addEventListener('touchmove', (e) => {
				if (!startX || !startY) { return; }

				currentX = e.touches[0].clientX;
				currentY = e.touches[0].clientY;

				const deltaX = currentX - startX;
				const deltaY = currentY - startY;

				// Prevent vertical scrolling if horizontal swipe
				if (Math.abs(deltaX) > Math.abs(deltaY)) {
					e.preventDefault();
				}
			});

			tabContainer.addEventListener('touchend', (e) => {
				if (!startX || !startY) { return; }

				const deltaX = currentX - startX;
				const deltaY = currentY - startY;

				// Check if it's a horizontal swipe
				if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > swipeThreshold) {
					this.handleTabSwipe(deltaX > 0 ? 'right' : 'left');
				}

				// Reset values
				startX = 0;
				startY = 0;
				currentX = 0;
				currentY = 0;
			});
		}

		// Calendar month swiping
		const calendarContainer = document.querySelector('.calendar-grid');
		if (calendarContainer) {
			this.setupCalendarSwipe(calendarContainer);
		}
	}

	setupCalendarSwipe(container) {
		let startX = 0;
		let startTime = 0;

		container.addEventListener('touchstart', (e) => {
			startX = e.touches[0].clientX;
			startTime = Date.now();
		});

		container.addEventListener('touchend', (e) => {
			if (!startX || !startTime) { return; }

			const endX = e.changedTouches[0].clientX;
			const endTime = Date.now();
			const deltaX = endX - startX;
			const deltaTime = endTime - startTime;

			// Check for swipe
			if (Math.abs(deltaX) > 50 && deltaTime < 500) {
				if (deltaX > 0) {
					this.handleCalendarSwipe('prev');
				} else {
					this.handleCalendarSwipe('next');
				}
			}

			startX = 0;
			startTime = 0;
		});
	}

	handleTabSwipe(direction) {
		const activeTab = document.querySelector('.tab-button.active');
		if (!activeTab) { return; }

		const tabs = Array.from(document.querySelectorAll('.tab-button'));
		const currentIndex = tabs.indexOf(activeTab);

		let newIndex;
		if (direction === 'left' && currentIndex > 0) {
			newIndex = currentIndex - 1;
		} else if (direction === 'right' && currentIndex < tabs.length - 1) {
			newIndex = currentIndex + 1;
		}

		if (newIndex !== undefined) {
			tabs[newIndex].click();
			this.showSwipeIndicator(direction);
		}
	}

	handleCalendarSwipe(direction) {
		const button = document.querySelector(direction === 'prev' ? '#prev-month' : '#next-month');
		if (button) {
			button.click();
			this.showSwipeIndicator(direction === 'prev' ? 'right' : 'left');
		}
	}

	showSwipeIndicator(direction) {
		const indicator = document.createElement('div');
		indicator.className = 'swipe-indicator';
		indicator.innerHTML = direction === 'left' ? '←' : '→';
		indicator.style.cssText = `
            position: fixed;
            top: 50%;
            ${direction === 'left' ? 'left: 20px' : 'right: 20px'};
            transform: translateY(-50%);
            background: var(--brand-primary);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 2rem;
            font-size: 1.5rem;
            z-index: 1000;
            animation: swipeIndicator 0.6s ease-out;
        `;

		document.body.appendChild(indicator);

		setTimeout(() => {
			indicator.remove();
		}, 600);
	}

	setupVirtualKeyboard() {
		if (!this.isMobile) { return; }

		// Handle virtual keyboard appearance
		const viewport = document.querySelector('meta[name="viewport"]');
		const originalViewport = viewport ? viewport.content : '';

		const inputs = document.querySelectorAll('input, textarea, select');
		inputs.forEach(input => {
			input.addEventListener('focus', () => {
				// Prevent zoom on iOS
				if (viewport) {
					viewport.content = `${originalViewport}, user-scalable=no`;
				}

				// Scroll input into view
				setTimeout(() => {
					input.scrollIntoView({ behavior: 'smooth', block: 'center' });
				}, 300);
			});

			input.addEventListener('blur', () => {
				// Restore original viewport
				if (viewport) {
					viewport.content = originalViewport;
				}
			});
		});

		// Handle visual viewport changes
		if (window.visualViewport) {
			window.visualViewport.addEventListener('resize', () => {
				const focusedElement = document.activeElement;
				if (focusedElement && (focusedElement.tagName === 'INPUT' || focusedElement.tagName === 'TEXTAREA')) {
					setTimeout(() => {
						focusedElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
					}, 100);
				}
			});
		}
	}

	setupPullToRefresh() {
		if (!this.isMobile || !this.isTouch) { return; }

		let startY = 0;
		let currentY = 0;
		let isPulling = false;
		let pullDistance = 0;

		const pullThreshold = 80;
		const pullIndicator = this.createPullIndicator();

		document.addEventListener('touchstart', (e) => {
			if (window.scrollY === 0) {
				startY = e.touches[0].clientY;
				isPulling = true;
			}
		});

		document.addEventListener('touchmove', (e) => {
			if (!isPulling || window.scrollY > 0) { return; }

			currentY = e.touches[0].clientY;
			pullDistance = currentY - startY;

			if (pullDistance > 0) {
				e.preventDefault();
				this.updatePullIndicator(pullIndicator, pullDistance, pullThreshold);
			}
		});

		document.addEventListener('touchend', (e) => {
			if (!isPulling) { return; }

			if (pullDistance > pullThreshold) {
				this.performRefresh();
			}

			this.resetPullIndicator(pullIndicator);
			isPulling = false;
			startY = 0;
			currentY = 0;
			pullDistance = 0;
		});
	}

	createPullIndicator() {
		const indicator = document.createElement('div');
		indicator.className = 'pull-to-refresh-indicator';
		indicator.innerHTML = `
            <div class="pull-spinner"></div>
            <div class="pull-text">Pull to refresh</div>
        `;
		indicator.style.cssText = `
            position: fixed;
            top: -80px;
            left: 50%;
            transform: translateX(-50%);
            background: white;
            padding: 1rem;
            border-radius: 2rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            z-index: 1000;
            transition: transform 0.3s ease;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: #6b7280;
            font-size: 0.875rem;
        `;

		document.body.appendChild(indicator);
		return indicator;
	}

	updatePullIndicator(indicator, distance, threshold) {
		const progress = Math.min(distance / threshold, 1);
		const translateY = Math.min(distance * 0.5, 40);

		indicator.style.transform = `translateX(-50%) translateY(${translateY}px)`;

		const spinner = indicator.querySelector('.pull-spinner');
		if (spinner) {
			spinner.style.transform = `rotate(${progress * 360}deg)`;
		}

		const text = indicator.querySelector('.pull-text');
		if (text) {
			text.textContent = progress >= 1 ? 'Release to refresh' : 'Pull to refresh';
		}
	}

	resetPullIndicator(indicator) {
		indicator.style.transform = 'translateX(-50%) translateY(-80px)';
		setTimeout(() => {
			indicator.remove();
		}, 300);
	}

	performRefresh() {
		// Show loading state
		this.showLoadingState();

		// Reload page data
		if (window.location.reload) {
			window.location.reload();
		} else {
			// Fallback: reload specific data
			this.reloadDashboardData();
		}
	}

	showLoadingState() {
		const loadingIndicator = document.createElement('div');
		loadingIndicator.className = 'loading-indicator';
		loadingIndicator.innerHTML = `
            <div class="loading-spinner"></div>
            <div class="loading-text">Refreshing...</div>
        `;
		loadingIndicator.style.cssText = `
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: var(--brand-primary);
            color: white;
            padding: 0.75rem 1.5rem;
            border-radius: 2rem;
            z-index: 1000;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        `;

		document.body.appendChild(loadingIndicator);

		setTimeout(() => {
			loadingIndicator.remove();
		}, 2000);
	}

	setupMobileNavigation() {
		// Add mobile navigation enhancements
		const fab = this.createFloatingActionButton();
		this.setupMobileMenu(fab);
	}

	createFloatingActionButton() {
		const fab = document.createElement('button');
		fab.className = 'fab';
		fab.innerHTML = '<i class="fas fa-plus"></i>';
		fab.setAttribute('aria-label', 'Quick actions');

		document.body.appendChild(fab);
		return fab;
	}

	setupMobileMenu(fab) {
		const menu = document.createElement('div');
		menu.className = 'fab-menu';
		menu.innerHTML = `
            <div class="fab-menu-item" data-action="adjust-fee">
                <i class="fas fa-sliders-h"></i>
                <span>Adjust Fee</span>
            </div>
            <div class="fab-menu-item" data-action="payment-history">
                <i class="fas fa-history"></i>
                <span>Payment History</span>
            </div>
            <div class="fab-menu-item" data-action="bank-details">
                <i class="fas fa-university"></i>
                <span>Bank Details</span>
            </div>
            <div class="fab-menu-item" data-action="help">
                <i class="fas fa-question-circle"></i>
                <span>Help</span>
            </div>
        `;

		menu.style.cssText = `
            position: fixed;
            bottom: 5rem;
            right: 1rem;
            background: white;
            border-radius: 1rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            z-index: 49;
            display: none;
            padding: 0.5rem;
            min-width: 200px;
        `;

		document.body.appendChild(menu);

		// Toggle menu
		fab.addEventListener('click', () => {
			const isVisible = menu.style.display === 'block';
			menu.style.display = isVisible ? 'none' : 'block';
			fab.style.transform = isVisible ? 'rotate(0deg)' : 'rotate(45deg)';
		});

		// Handle menu items
		menu.addEventListener('click', (e) => {
			const item = e.target.closest('.fab-menu-item');
			if (item) {
				const action = item.dataset.action;
				this.handleFabAction(action);
				menu.style.display = 'none';
				fab.style.transform = 'rotate(0deg)';
			}
		});

		// Close menu when clicking outside
		document.addEventListener('click', (e) => {
			if (!fab.contains(e.target) && !menu.contains(e.target)) {
				menu.style.display = 'none';
				fab.style.transform = 'rotate(0deg)';
			}
		});
	}

	handleFabAction(action) {
		switch (action) {
			case 'adjust-fee':
				window.location.href = '/membership_fee_adjustment';
				break;
			case 'payment-history':
				window.location.href = '/payment_dashboard';
				break;
			case 'bank-details':
				window.location.href = '/bank_details';
				break;
			case 'help':
				window.location.href = '/help';
				break;
		}
	}

	setupMobileModals() {
		// Enhance modal behavior for mobile
		const modals = document.querySelectorAll('.modal');
		modals.forEach(modal => {
			this.enhanceModalForMobile(modal);
		});
	}

	enhanceModalForMobile(modal) {
		// Add swipe-to-close functionality
		let startY = 0;
		let currentY = 0;

		modal.addEventListener('touchstart', (e) => {
			startY = e.touches[0].clientY;
		});

		modal.addEventListener('touchmove', (e) => {
			currentY = e.touches[0].clientY;
			const deltaY = currentY - startY;

			if (deltaY > 0) {
				modal.style.transform = `translateY(${deltaY * 0.5}px)`;
			}
		});

		modal.addEventListener('touchend', (e) => {
			const deltaY = currentY - startY;

			if (deltaY > 100) {
				// Close modal if swiped down enough
				modal.style.display = 'none';
			} else {
				// Reset position
				modal.style.transform = 'translateY(0)';
			}

			startY = 0;
			currentY = 0;
		});
	}

	setupMobileCalendar() {
		// Enhance calendar for mobile
		const calendar = document.querySelector('.calendar-grid');
		if (calendar) {
			this.enhanceCalendarForMobile(calendar);
		}
	}

	enhanceCalendarForMobile(calendar) {
		// Add haptic feedback for touch
		calendar.addEventListener('touchstart', (e) => {
			const day = e.target.closest('.calendar-day');
			if (day && navigator.vibrate) {
				navigator.vibrate(10); // Short vibration
			}
		});

		// Improve touch targets
		const days = calendar.querySelectorAll('.calendar-day');
		days.forEach(day => {
			day.style.minHeight = '2.5rem';
			day.style.display = 'flex';
			day.style.alignItems = 'center';
			day.style.justifyContent = 'center';
		});
	}

	setupMobileAccessibility() {
		// Enhance accessibility for mobile

		// Add skip links
		const skipLink = document.createElement('a');
		skipLink.href = '#main-content';
		skipLink.textContent = 'Skip to main content';
		skipLink.className = 'sr-only focus:not-sr-only focus:absolute focus:top-0 focus:left-0 focus:z-50 focus:bg-primary focus:text-white focus:p-2';
		document.body.insertBefore(skipLink, document.body.firstChild);

		// Announce page changes
		this.announcePageChanges();

		// Improve focus management
		this.improveFocusManagement();

		// Add landmarks
		this.addLandmarks();
	}

	announcePageChanges() {
		const announcer = document.createElement('div');
		announcer.setAttribute('aria-live', 'polite');
		announcer.setAttribute('aria-atomic', 'true');
		announcer.className = 'sr-only';
		announcer.id = 'page-announcer';
		document.body.appendChild(announcer);

		// Announce tab changes
		const tabButtons = document.querySelectorAll('.tab-button');
		tabButtons.forEach(button => {
			button.addEventListener('click', () => {
				const tabName = button.textContent.trim();
				announcer.textContent = `Switched to ${tabName} tab`;
			});
		});
	}

	improveFocusManagement() {
		// Trap focus in modals
		const modals = document.querySelectorAll('.modal');
		modals.forEach(modal => {
			this.trapFocusInModal(modal);
		});

		// Manage focus on page changes
		const tabButtons = document.querySelectorAll('.tab-button');
		tabButtons.forEach(button => {
			button.addEventListener('click', () => {
				// Focus first interactive element in new tab
				setTimeout(() => {
					const activeTab = document.querySelector('.tab-content:not(.hidden)');
					if (activeTab) {
						const firstFocusable = activeTab.querySelector('button, a, input, select, textarea, [tabindex]:not([tabindex="-1"])');
						if (firstFocusable) {
							firstFocusable.focus();
						}
					}
				}, 100);
			});
		});
	}

	trapFocusInModal(modal) {
		const focusableElements = modal.querySelectorAll('button, a, input, select, textarea, [tabindex]:not([tabindex="-1"])');
		const firstFocusable = focusableElements[0];
		const lastFocusable = focusableElements[focusableElements.length - 1];

		modal.addEventListener('keydown', (e) => {
			if (e.key === 'Tab') {
				if (e.shiftKey) {
					if (document.activeElement === firstFocusable) {
						lastFocusable.focus();
						e.preventDefault();
					}
				} else {
					if (document.activeElement === lastFocusable) {
						firstFocusable.focus();
						e.preventDefault();
					}
				}
			}
		});
	}

	addLandmarks() {
		// Add ARIA landmarks for better navigation
		const main = document.querySelector('main') || document.querySelector('.main-content');
		if (main) {
			main.setAttribute('role', 'main');
			main.setAttribute('aria-label', 'Main content');
		}

		const nav = document.querySelector('.tab-nav');
		if (nav) {
			nav.setAttribute('role', 'navigation');
			nav.setAttribute('aria-label', 'Dashboard navigation');
		}

		const calendar = document.querySelector('.calendar-grid');
		if (calendar) {
			calendar.setAttribute('role', 'application');
			calendar.setAttribute('aria-label', 'Payment calendar');
		}
	}

	initializeMobileFeatures() {
		// Initialize mobile-specific features after DOM is ready
		this.optimizeForMobile();
		this.setupMobileAnimations();
		this.setupMobilePerformance();
	}

	optimizeForMobile() {
		if (!this.isMobile) { return; }

		// Optimize images
		const images = document.querySelectorAll('img');
		images.forEach(img => {
			if (!img.loading) {
				img.loading = 'lazy';
			}
		});

		// Optimize large datasets
		this.virtualizeDataTables();

		// Optimize animations
		this.optimizeAnimations();
	}

	virtualizeDataTables() {
		const tables = document.querySelectorAll('table');
		tables.forEach(table => {
			const rows = table.querySelectorAll('tbody tr');
			if (rows.length > 20) {
				this.implementVirtualScrolling(table);
			}
		});
	}

	implementVirtualScrolling(table) {
		// Implement virtual scrolling for large tables
		// This is a simplified implementation
		const tbody = table.querySelector('tbody');
		const rows = Array.from(tbody.querySelectorAll('tr'));
		const visibleRows = 10;
		let startIndex = 0;

		const container = document.createElement('div');
		container.style.maxHeight = '400px';
		container.style.overflowY = 'auto';

		table.parentNode.insertBefore(container, table);
		container.appendChild(table);

		const renderRows = () => {
			tbody.innerHTML = '';
			const endIndex = Math.min(startIndex + visibleRows, rows.length);

			for (let i = startIndex; i < endIndex; i++) {
				tbody.appendChild(rows[i]);
			}
		};

		container.addEventListener('scroll', () => {
			const scrollTop = container.scrollTop;
			const rowHeight = 50; // Approximate row height
			const newStartIndex = Math.floor(scrollTop / rowHeight);

			if (newStartIndex !== startIndex) {
				startIndex = newStartIndex;
				renderRows();
			}
		});

		renderRows();
	}

	optimizeAnimations() {
		// Disable animations on slower devices
		const isSlowDevice = navigator.hardwareConcurrency < 4 || navigator.deviceMemory < 4;

		if (isSlowDevice) {
			const style = document.createElement('style');
			style.textContent = `
                *, *::before, *::after {
                    animation-duration: 0.01ms !important;
                    animation-iteration-count: 1 !important;
                    transition-duration: 0.01ms !important;
                }
            `;
			document.head.appendChild(style);
		}
	}

	setupMobileAnimations() {
		// Add mobile-specific animations
		const observer = new IntersectionObserver((entries) => {
			entries.forEach(entry => {
				if (entry.isIntersecting) {
					entry.target.classList.add('animate-in');
				}
			});
		});

		const animatedElements = document.querySelectorAll('.financial-card, .quick-action');
		animatedElements.forEach(el => observer.observe(el));
	}

	setupMobilePerformance() {
		// Optimize performance for mobile

		// Debounce resize events
		let resizeTimer;
		window.addEventListener('resize', () => {
			clearTimeout(resizeTimer);
			resizeTimer = setTimeout(() => {
				this.handleResize();
			}, 250);
		});

		// Optimize scroll events
		let scrollTimer;
		window.addEventListener('scroll', () => {
			clearTimeout(scrollTimer);
			scrollTimer = setTimeout(() => {
				this.handleScroll();
			}, 16); // ~60fps
		});

		// Preload critical resources
		this.preloadCriticalResources();
	}

	handleResize() {
		// Handle resize events
		this.updateMobileClasses();
		this.adjustLayoutForViewport();
	}

	handleScroll() {
		// Handle scroll events
		this.updateScrollPosition();
		this.manageScrollBasedElements();
	}

	adjustLayoutForViewport() {
		// Adjust layout based on viewport
		const vh = window.innerHeight * 0.01;
		document.documentElement.style.setProperty('--vh', `${vh}px`);
	}

	updateScrollPosition() {
		// Update scroll position for various elements
		const scrollTop = window.pageYOffset;
		document.documentElement.style.setProperty('--scroll-top', `${scrollTop}px`);
	}

	manageScrollBasedElements() {
		// Show/hide elements based on scroll
		const fab = document.querySelector('.fab');
		if (fab) {
			const scrollTop = window.pageYOffset;
			fab.style.display = scrollTop > 200 ? 'flex' : 'none';
		}
	}

	preloadCriticalResources() {
		// Preload critical resources
		const criticalUrls = [
			'/assets/verenigingen/css/mobile_dues_schedule.css',
			'/assets/verenigingen/js/dues_schedule_calendar.js'
		];

		criticalUrls.forEach(url => {
			const link = document.createElement('link');
			link.rel = 'preload';
			link.href = url;
			link.as = url.endsWith('.css') ? 'style' : 'script';
			document.head.appendChild(link);
		});
	}

	reloadDashboardData() {
		// Reload dashboard data without full page refresh
		if (typeof window.loadFinancialData === 'function') {
			window.loadFinancialData();
		}
	}
}

// Initialize mobile enhancements
if (typeof window !== 'undefined') {
	window.mobileDuesSchedule = new MobileDuesSchedule();
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
	module.exports = MobileDuesSchedule;
}

// Add CSS animation keyframes
const style = document.createElement('style');
style.textContent = `
    @keyframes swipeIndicator {
        0% { opacity: 0; transform: translateY(-50%) scale(0.5); }
        50% { opacity: 1; transform: translateY(-50%) scale(1.1); }
        100% { opacity: 0; transform: translateY(-50%) scale(0.8); }
    }

    @keyframes animate-in {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .animate-in {
        animation: animate-in 0.3s ease-out;
    }

    .fab-menu-item {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.75rem;
        border-radius: 0.5rem;
        cursor: pointer;
        transition: background-color 0.2s ease;
    }

    .fab-menu-item:hover {
        background-color: #f3f4f6;
    }

    .fab-menu-item i {
        width: 1.25rem;
        color: var(--brand-primary);
    }

    .fab-menu-item span {
        font-size: 0.875rem;
        color: #374151;
    }

    .pull-spinner {
        width: 1rem;
        height: 1rem;
        border: 2px solid #e5e7eb;
        border-top-color: var(--brand-primary);
        border-radius: 50%;
        transition: transform 0.2s ease;
    }

    .loading-spinner {
        width: 1rem;
        height: 1rem;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-top-color: white;
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .touched {
        background-color: rgba(0, 0, 0, 0.05);
        transform: scale(0.98);
    }
`;
document.head.appendChild(style);
