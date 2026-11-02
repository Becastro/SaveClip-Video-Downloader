/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: "#17221c",
        forest: "#18764e",
        mint: "#ddf4e7",
        canvas: "#f7f8f5",
      },
      boxShadow: {
        card: "0 12px 40px rgba(28, 54, 39, .07)",
      },
    },
  },
  plugins: [],
};
