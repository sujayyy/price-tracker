import type { Config } from "tailwindcss";

const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  // Hover styles only on devices that can hover: no sticky hover after a tap on phones.
  future: { hoverOnlyWhenSupported: true },
  theme: {
    extend: {
      colors: {
        surface: token("surface"),
        raised: token("raised"),
        sunken: token("sunken"),
        rail: token("rail"),
        line: token("line"),
        "line-strong": token("line-strong"),
        ink: token("ink"),
        muted: token("muted"),
        faint: token("faint"),
        brand: token("brand"),
        "on-brand": token("on-brand"),
        band: token("band"),
        "on-band": token("on-band"),
        accent: token("accent"),
        "on-accent": token("on-accent"),
        good: token("good"),
        "good-fill": token("good-fill"),
        bad: token("bad"),
        "bad-fill": token("bad-fill"),
        warn: token("warn"),
        "warn-fill": token("warn-fill"),
        teal: token("teal"),
        info: token("info"),
        amazon: token("amazon"),
        flipkart: token("flipkart"),
        gray: Object.fromEntries(
          ["0", "50", "100", "150", "200", "300", "400", "500", "600", "700", "800", "900"].map((k) => [k, token(`gray-${k}`)]),
        ),
      },
      fontFamily: {
        sans: ["Geist", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'Geist Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
        display: ["'Instrument Serif'", "ui-serif", "Georgia", "serif"],
      },
      boxShadow: {
        xs: "var(--shadow-xs)",
        pop: "var(--shadow-pop)",
        lift: "var(--shadow-lift)",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.23, 1, 0.32, 1)",
        "in-out": "cubic-bezier(0.77, 0, 0.175, 1)",
        drawer: "cubic-bezier(0.32, 0.72, 0, 1)",
      },
    },
  },
  plugins: [],
} satisfies Config;
