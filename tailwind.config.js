/**
 * @fileoverview Tailwind CSS Configuration - Styling framework setup for Verenigingen
 *
 * This module configures Tailwind CSS for the Verenigingen association management
 * system, defining custom brand colors, typography, spacing, and design tokens
 * that align with the organization's visual identity and user experience
 * requirements.
 *
 * Key Features:
 * - Custom brand color palette (RSP Red, Pine Green, Royal Purple)
 * - Semantic color system for consistent UI states
 * - Extended spacing and border radius utilities
 * - Custom shadows for depth and elevation
 * - Form plugin integration for enhanced form styling
 * - Content scanning for optimal build performance
 *
 * Brand Color System:
 * - Primary (RSP Red #cf3131): Main brand color for primary actions
 * - Secondary (Pine Green #01796F): Secondary brand color and success states
 * - Accent (Royal Purple #663399): Accent color for highlights and CTAs
 * - Semantic colors: Success, Warning, Danger with consistent shades
 *
 * Design Tokens:
 * - 50-900 color scale for each brand color
 * - System font stack for optimal cross-platform rendering
 * - Extended spacing values for custom layouts
 * - Enhanced border radius options
 * - Custom shadow utilities for cards and elements
 *
 * Content Sources:
 * - HTML templates in verenigingen/templates/
 * - Web pages in verenigingen/www/
 * - JavaScript files in verenigingen/public/js/
 *
 * Usage:
 * ```html
 * <!-- Primary brand color -->
 * <button class="bg-primary-500 hover:bg-primary-600">Submit</button>
 *
 * <!-- Success state -->
 * <div class="text-success-600 bg-success-50">Success message</div>
 *
 * <!-- Custom shadows -->
 * <div class="shadow-card rounded-xl">Card component</div>
 * ```
 *
 * Performance Optimization:
 * - Content scanning ensures only used classes are included
 * - Tree-shaking eliminates unused styles
 * - Optimized for production builds
 *
 * Plugin Integration:
 * - @tailwindcss/forms: Enhanced form styling and accessibility
 * - Future plugins can be added for additional functionality
 *
 * @module tailwind.config
 * @version 1.3.0
 * @since 1.0.0
 * @requires tailwindcss
 * @requires @tailwindcss/forms
 * @see {@link https://tailwindcss.com/docs/configuration|Tailwind Configuration}
 * @see {@link verenigingen/templates/|HTML Templates}
 * @see {@link verenigingen/public/css/|CSS Styles}
 *
 * @author Verenigingen System
 * @copyright 2024 Verenigingen
 */

/** @type {import('tailwindcss').Config} */
module.exports = {
  /** @type {Array<string>} File patterns to scan for class usage */
  content: [
    "./verenigingen/templates/**/*.html",
    "./verenigingen/www/**/*.html",
    "./verenigingen/public/js/**/*.js"
  ],

  /** @type {Object} Theme configuration and customizations */
  theme: {
    /** @type {Object} Extensions to the default Tailwind theme */
    extend: {
      /** @type {Object} Custom color palette based on brand identity */
      colors: {
        // Verenigingen brand colors - RSP Red, Pine Green, Royal Purple

        /** @type {Object} Primary brand color (RSP Red) with 50-900 scale */
        primary: {
          50: '#fef2f2',
          100: '#fee2e2',
          200: '#fecaca',
          300: '#fca5a5',
          400: '#f87171',
          500: '#cf3131',  // RSP Red - Main brand color
          600: '#b82828',
          700: '#a01f1f',
          800: '#891717',
          900: '#721212',
        },
        /** @type {Object} Secondary brand color (Pine Green) with 50-900 scale */
        secondary: {
          50: '#f0f9f0',
          100: '#dcf2dc',
          200: '#bae5ba',
          300: '#86d186',
          400: '#4fb74f',
          500: '#01796F',  // Pine Green
          600: '#016B63',
          700: '#015A54',
          800: '#014A44',
          900: '#013A35',
        },

        /** @type {Object} Accent brand color (Royal Purple) with 50-900 scale */
        accent: {
          50: '#f8f4ff',
          100: '#f0e7ff',
          200: '#e4d3ff',
          300: '#d1b3ff',
          400: '#b885ff',
          500: '#663399',  // Royal Purple
          600: '#5c2e8a',
          700: '#4f277a',
          800: '#42206b',
          900: '#35195c',
        },
        /** @type {Object} Success state color (Pine Green variant) */
        success: {
          50: '#f0f9f0',
          100: '#dcf2dc',
          200: '#bae5ba',
          300: '#86d186',
          400: '#4fb74f',
          500: '#01796F',  // Pine Green for success
          600: '#016B63',
          700: '#015A54',
          800: '#014A44',
          900: '#013A35',
        },

        /** @type {Object} Warning state color (Amber/Orange palette) */
        warning: {
          50: '#fffbeb',
          100: '#fef3c7',
          200: '#fde68a',
          300: '#fcd34d',
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
          800: '#92400e',
          900: '#78350f',
        },
        /** @type {Object} Danger/Error state color (RSP Red variant) */
        danger: {
          50: '#fef2f2',
          100: '#fee2e2',
          200: '#fecaca',
          300: '#fca5a5',
          400: '#f87171',
          500: '#cf3131',  // RSP Red for danger
          600: '#b82828',
          700: '#a01f1f',
          800: '#891717',
          900: '#721212',
        }
      },

      /** @type {Object} Custom font family definitions */
      fontFamily: {
        /** @type {Array<string>} System font stack for optimal rendering */
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },

      /** @type {Object} Custom spacing utilities beyond default scale */
      spacing: {
        /** @type {string} 18 = 4.5rem (72px) for custom layouts */
        '18': '4.5rem',
        /** @type {string} 88 = 22rem (352px) for wide containers */
        '88': '22rem',
      },

      /** @type {Object} Custom border radius utilities */
      borderRadius: {
        /** @type {string} Extra large border radius */
        'xl': '1rem',
        /** @type {string} Extra extra large border radius */
        '2xl': '1.5rem',
      },

      /** @type {Object} Custom box shadow utilities for depth */
      boxShadow: {
        /** @type {string} Soft shadow for subtle elevation */
        'soft': '0 2px 15px 0 rgba(0, 0, 0, 0.1)',
        /** @type {string} Card shadow for component elevation */
        'card': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
      }
    },
  },

  /** @type {Array} Tailwind CSS plugins for enhanced functionality */
  plugins: [
    /** @type {Plugin} Forms plugin for enhanced form styling */
    require('@tailwindcss/forms'),
  ],
}
