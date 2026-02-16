/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ["Space Grotesk", "sans-serif"],
        body: ["IBM Plex Sans", "sans-serif"],
      },
      colors: {
        ink: "#f4f7fb",
        panel: "#111827",
        panelsoft: "#1f2937",
        accent: "#22d3ee",
        ember: "#fb7185",
      },
      boxShadow: {
        neon: "0 0 0 1px rgba(34,211,238,.16), 0 10px 35px rgba(15,23,42,.45)",
      },
    },
  },
};
