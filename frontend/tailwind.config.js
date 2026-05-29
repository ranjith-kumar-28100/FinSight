/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        // Deep navy / charcoal backgrounds
        ink: {
          950: "#06090f",
          900: "#0b1020",
          800: "#0f172a",
          700: "#13203a",
          600: "#1c2a4a",
        },
        // Sidebar / cards
        surface: {
          DEFAULT: "rgba(255, 255, 255, 0.04)",
          strong: "rgba(255, 255, 255, 0.07)",
        },
        // Finance accents
        gain: {
          50: "#ecfdf5",
          400: "#34d399",
          500: "#10b981",
          600: "#059669",
        },
        loss: {
          50: "#fef2f2",
          400: "#f87171",
          500: "#ef4444",
          600: "#dc2626",
        },
        gold: {
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
        },
        brand: {
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
        },
        line: "rgba(148, 163, 184, 0.12)",
      },
      boxShadow: {
        glass: "0 1px 0 0 rgba(255, 255, 255, 0.04) inset, 0 24px 60px -30px rgba(0,0,0,0.6)",
      },
      backgroundImage: {
        "grid-fade":
          "radial-gradient(circle at 30% 0%, rgba(99,102,241,0.18), transparent 45%), radial-gradient(circle at 80% 100%, rgba(16,185,129,0.12), transparent 50%)",
      },
    },
  },
  plugins: [],
};
