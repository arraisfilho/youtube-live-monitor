import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development, /api goes to the local container (docker compose up).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8082" } },
  build: { target: "es2020", sourcemap: false },
});
