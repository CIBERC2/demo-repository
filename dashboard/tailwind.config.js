/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        c2: {
          bg: "#0a0e1a",
          surface: "#111827",
          border: "#1f2937",
          accent: "#00d4ff",
          green: "#00ff88",
          red: "#ff4444",
          yellow: "#ffd700",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
};
