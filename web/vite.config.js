import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Builds into ../static, which FastAPI serves. `npm run dev` proxies the API to uvicorn on :8080.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../static", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: {
    proxy: {
      "/api": "http://localhost:8080",
      "/media": "http://localhost:8080",
      "/ws": { target: "ws://localhost:8080", ws: true },
    },
  },
});
