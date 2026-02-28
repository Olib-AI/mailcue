import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react-router")) {
            return "router";
          }
          if (id.includes("node_modules/@tanstack/react-query")) {
            return "query";
          }
          if (id.includes("@tiptap") || id.includes("prosemirror")) {
            return "tiptap";
          }
        },
      },
    },
  },
});
