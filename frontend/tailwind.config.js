/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['Manrope', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors: {
        ink: '#14231d',
        canvas: '#f3f6f2',
        moss: '#245c47',
        lime: '#b7e45e',
      },
      boxShadow: {
        soft: '0 18px 50px rgba(25, 58, 45, 0.08)',
      },
    },
  },
  plugins: [],
}

