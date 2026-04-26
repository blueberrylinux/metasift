/**
 * Design tokens lifted directly from the MetaSift Port Scaffolding mockup.
 * Every UI value keys off these — don't invent new ones.
 *
 * Changes here ripple across every component. Treat additions as a visual
 * contract; only extend, never rename.
 */
import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Background scale — slate-950 is the app bg, 900 for panels, 800 for borders.
        ink: {
          bg: '#020617',
          panel: '#0f172a',
          border: '#1e293b',
          mid: '#334155',
          dim: '#64748b',
          soft: '#94a3b8',
          text: '#e2e8f0',
        },
        accent: {
          DEFAULT: '#10b981',
          bright: '#34d399',
          soft: '#6ee7b7',
          glow: 'rgba(16,185,129,0.12)',
        },
        warn: { DEFAULT: '#f59e0b', soft: '#fcd34d' },
        error: { DEFAULT: '#ef4444', soft: '#fca5a5' },
        info: { DEFAULT: '#06b6d4', soft: '#67e8f9' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        micro: ['9px', { lineHeight: '1.3' }],
        mini: ['10px', { lineHeight: '1.4' }],
        tiny: ['11px', { lineHeight: '1.5' }],
        sm: ['12px', { lineHeight: '1.55' }],
        body: ['13px', { lineHeight: '1.6' }],
        lg: ['14px', { lineHeight: '1.6' }],
      },
      borderRadius: {
        md: '6px',
        lg: '8px',
        xl: '14px',
        '2xl': '16px',
      },
      boxShadow: {
        float: '0 24px 48px -12px rgba(0,0,0,0.7), 0 0 0 1px rgba(30,41,59,1)',
        glow: '0 0 0 2px rgba(16,185,129,0.5)',
      },
      backgroundImage: {
        'hero-glow':
          'radial-gradient(ellipse 60% 50% at 20% 0%, rgba(16,185,129,0.12) 0%, transparent 60%), ' +
          'radial-gradient(ellipse 50% 40% at 90% 10%, rgba(16,185,129,0.08) 0%, transparent 60%)',
        'grid-bg':
          'linear-gradient(rgba(16,185,129,0.05) 1px, transparent 1px), ' +
          'linear-gradient(90deg, rgba(16,185,129,0.05) 1px, transparent 1px)',
      },
      backgroundSize: { 'grid-48': '48px 48px' },
      animation: {
        'pulse-dot': 'pulse-dot 2s ease-in-out infinite',
        typing: 'typing 1.4s infinite',
      },
      keyframes: {
        'pulse-dot': {
          '0%,100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.6', transform: 'scale(1.3)' },
        },
        typing: {
          '0%,60%,100%': { opacity: '0.2' },
          '30%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
