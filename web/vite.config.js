import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build is served by Django (whitenoise) under /static/, so assets live in /static/assets/.
// `npm run dev` proxies API and login calls to a hub running on localhost:8000.
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "../hub/web_dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/login": "http://localhost:8000",
      "/logout": "http://localhost:8000",
      "/admin": "http://localhost:8000",
    },
  },
});
