/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0d12",
        panel: "#141821",
        border: "#232733",
        accent: "#6ee7b7",
        warn: "#fbbf24",
        danger: "#f87171",
      },
    },
  },
  plugins: [],
};
