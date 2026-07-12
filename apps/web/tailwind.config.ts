import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#ffffff",
        "canvas-soft": "#f6f5f4",
        ink: "#000000",
        "ink-secondary": "#31302e",
        "ink-muted": "#615d59",
        "ink-faint": "#a39e98",
        hairline: "#e6e6e6",
        primary: "#0075de",
        "primary-active": "#005bab",
        "status-success": "#1aae39",
        "status-running": "#62aef0",
        "status-failed": "#e03e3e",
      },
      borderRadius: {
        sm: "4px",
        md: "8px",
        lg: "12px",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(0, 0, 0, 0.03)",
        panel: "0 8px 30px rgba(0, 0, 0, 0.08)",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
