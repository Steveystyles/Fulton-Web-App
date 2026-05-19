import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        saints: {
          black: "#0a0a0d",
          red: "#d71920",
          deep: "#15161b",
          paper: "#f4f5f7",
          line: "#dedfe4",
        },
      },
      boxShadow: {
        soft: "0 14px 38px rgba(12, 12, 18, 0.12)",
        nav: "0 -10px 28px rgba(10, 10, 13, 0.16)",
      },
    },
  },
  plugins: [],
} satisfies Config;
