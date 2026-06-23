import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'trade-green': '#22c55e',
        'trade-red': '#ef4444',
        'trade-yellow': '#f59e0b',
      },
    },
  },
  plugins: [],
} satisfies Config
