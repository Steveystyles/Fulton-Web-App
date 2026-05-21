import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        saints: {
          black: "#050505",
          ink: "#111114",
          charcoal: "#18181b",
          white: "#ffffff",
          paper: "#f4f4f1",
          mist: "#e9e9e4",
          line: "#d7d7d0",
          red: "#d71920",
          redDark: "#a90f18",
          redSoft: "#fff0f1",
        },
      },
      boxShadow: {
        soft: "0 18px 45px rgba(5, 5, 5, 0.12)",
        card: "0 12px 32px rgba(5, 5, 5, 0.10)",
        nav: "0 -14px 34px rgba(5, 5, 5, 0.18)",
      },
      backgroundImage: {
        "saints-stripes":
          "repeating-linear-gradient(90deg, #050505 0 22px, #ffffff 22px 34px)",
        "saints-stripes-subtle":
          "repeating-linear-gradient(90deg, rgba(5, 5, 5, 0.05) 0 18px, rgba(255, 255, 255, 0.22) 18px 28px)",
        "matchday-glow":
          "radial-gradient(circle at 50% 0%, rgba(215, 25, 32, 0.22), transparent 34rem)",
      },
    },
  },
  plugins: [],
} satisfies Config;
