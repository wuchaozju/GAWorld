/**
 * Tailwind CSS configuration for FOS (Future of Society) frontend.
 *
 * Maps the `brand` color scale to CSS custom properties from tokens.css
 * so all brand-* utility classes respond to light/dark theme switching.
 */

module.exports = {
  darkMode: ['selector', '.theme-dark'],
  content: [
    "./index.html",
    "./App.tsx",
    "./index.tsx",
    "./components/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./pages/**/*.{ts,tsx}",
    "./services/**/*.{ts,tsx}",
    "./store/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: 'var(--ss-brand-soft)',
          100: 'var(--ss-brand-soft)',
          200: 'var(--ss-brand-soft)',
          300: 'var(--ss-brand-soft)',
          400: 'var(--ss-brand-primary)',
          500: 'var(--ss-brand-primary)',
          600: 'var(--ss-brand-primary)',
          700: 'var(--ss-brand-hover)',
          800: 'var(--ss-brand-hover)',
          900: 'var(--ss-brand-on)',
        },
      },
      transitionDuration: {
        '250': '250ms',
      },
    },
  },
  plugins: [],
};
