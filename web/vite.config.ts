import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          motion: ["framer-motion"],
          markdown: ["react-markdown"],
          query: ["@tanstack/react-query", "zustand"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://127.0.0.1:8787",
      "/healthz": "http://127.0.0.1:8787",
      "/metrics": "http://127.0.0.1:8787",
    },
  },
});
