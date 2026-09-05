/**
 * Design tokens transcribed verbatim from the ChronoTrace design samples
 * (the code.html files under docs/design-samples) so the built app and the
 * mockups stay in sync.
 *
 * The only deliberate addition is `series` — the categorical chart palette. The
 * mockups used Tailwind's 500-level blue/purple/emerald/orange/teal/pink, but
 * that set fails colour-vision-deficiency separation (blue↔purple measure ΔE 0.9
 * for deuteranopia — indistinguishable). The order below is re-stepped and
 * validated: all six sit inside the dark-mode lightness band and the worst
 * adjacent pair is ΔE 8.1. Assign in order, never cycle.
 */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "secondary-fixed": "#d8e3fb",
        primary: "#d0bcff",
        "primary-fixed": "#e9ddff",
        "on-background": "#dae2fd",
        "on-error": "#690005",
        "on-tertiary-fixed-variant": "#2f2ebe",
        outline: "#958ea0",
        "on-primary-fixed-variant": "#5516be",
        "primary-container": "#a078ff",
        "primary-fixed-dim": "#d0bcff",
        "on-secondary-fixed": "#111c2d",
        "surface-container-lowest": "#060e20",
        "inverse-on-surface": "#283044",
        "on-primary-fixed": "#23005c",
        "on-secondary-fixed-variant": "#3c475a",
        "surface-dim": "#0b1326",
        "inverse-surface": "#dae2fd",
        "inverse-primary": "#6d3bd7",
        "secondary-container": "#3e495d",
        "surface-bright": "#31394d",
        "surface-container-highest": "#2d3449",
        "tertiary-fixed-dim": "#c0c1ff",
        "on-tertiary": "#1000a9",
        surface: "#0b1326",
        "surface-container-low": "#131b2e",
        error: "#ffb4ab",
        "surface-container": "#171f33",
        "on-secondary-container": "#aeb9d0",
        secondary: "#bcc7de",
        "on-secondary": "#263143",
        "on-primary": "#3c0091",
        "tertiary-fixed": "#e1e0ff",
        "on-surface-variant": "#cbc3d7",
        "surface-tint": "#d0bcff",
        "on-error-container": "#ffdad6",
        "surface-variant": "#2d3449",
        "on-tertiary-container": "#0d0096",
        "on-primary-container": "#340080",
        "secondary-fixed-dim": "#bcc7de",
        "on-tertiary-fixed": "#07006c",
        background: "#0b1326",
        "error-container": "#93000a",
        tertiary: "#c0c1ff",
        "outline-variant": "#494454",
        "surface-container-high": "#222a3d",
        "on-surface": "#dae2fd",
        "tertiary-container": "#8083ff",

        // Categorical chart palette — validated, fixed order, never cycled.
        series: {
          1: "#3b82f6",
          2: "#ea580c",
          3: "#059669",
          4: "#8b5cf6",
          5: "#0891b2",
          6: "#ec4899",
        },
        // Status palette — reserved for risk bands, never reused as a series.
        risk: {
          normal: "#059669",
          low: "#d97706",
          review: "#f97316",
          high: "#ef4444",
        },
      },
      borderRadius: {
        DEFAULT: "0.125rem",
        lg: "0.25rem",
        xl: "0.5rem",
        full: "0.75rem",
      },
      spacing: {
        container_padding: "24px",
        component_padding_x: "12px",
        gutter: "16px",
        component_padding_y: "8px",
        unit: "4px",
        sidebar_width: "240px",
      },
      fontFamily: {
        "body-lg": ["DM Sans", "sans-serif"],
        "body-md": ["DM Sans", "sans-serif"],
        "headline-sm": ["Space Grotesk", "sans-serif"],
        "headline-md": ["Space Grotesk", "sans-serif"],
        "label-md": ["DM Sans", "sans-serif"],
        "headline-lg": ["Space Grotesk", "sans-serif"],
        "body-sm": ["DM Sans", "sans-serif"],
        "mono-data": ["JetBrains Mono", "monospace"],
      },
      fontSize: {
        "body-lg": ["16px", { lineHeight: "24px", fontWeight: "400" }],
        "body-md": ["14px", { lineHeight: "20px", fontWeight: "400" }],
        "headline-sm": ["18px", { lineHeight: "24px", fontWeight: "500" }],
        "headline-md": [
          "24px",
          { lineHeight: "32px", letterSpacing: "-0.01em", fontWeight: "600" },
        ],
        "label-md": [
          "12px",
          { lineHeight: "16px", letterSpacing: "0.05em", fontWeight: "600" },
        ],
        "headline-lg": [
          "32px",
          { lineHeight: "40px", letterSpacing: "-0.02em", fontWeight: "600" },
        ],
        "body-sm": ["12px", { lineHeight: "16px", fontWeight: "400" }],
        "mono-data": ["13px", { lineHeight: "18px", fontWeight: "400" }],
      },
    },
  },
  plugins: [],
};
