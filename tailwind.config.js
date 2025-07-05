/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./verenigingen/templates/**/*.html",
    "./verenigingen/www/**/*.html",
    "./verenigingen/public/js/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        // Verenigingen brand colors - RSP Red, Pine Green, Royal Purple
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
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
      },
      borderRadius: {
        'xl': '1rem',
        '2xl': '1.5rem',
      },
      boxShadow: {
        'soft': '0 2px 15px 0 rgba(0, 0, 0, 0.1)',
        'card': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
      }
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}
