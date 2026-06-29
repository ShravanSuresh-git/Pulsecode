import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#151814",
        paper: "#f5f2ea",
        moss: "#536b49",
        rust: "#a75736",
        cobalt: "#355c9a",
        amber: "#d39b31"
      },
      boxShadow: {
        soft: "0 20px 55px rgba(21, 24, 20, 0.12)"
      }
    }
  },
  plugins: []
};

export default config;

