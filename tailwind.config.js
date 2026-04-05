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
        panel: "#1a1a1a",
        panelsoft: "#242424",
        ember: "#fb7185",
      },
      boxShadow: {
        neon: "0 0 0 1px rgba(255,255,255,.07), 0 10px 35px rgba(0,0,0,.5)",
      },
    },
  },
};
