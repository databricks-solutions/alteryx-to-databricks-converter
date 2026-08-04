import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __BUILD_SHA__: JSON.stringify(process.env.BUILD_SHA || "dev"),
    __BUILD_DATE__: JSON.stringify(process.env.BUILD_DATE || ""),
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    // Node environment is enough: the tested modules are pure logic (warning
    // parsing, deploy-status rules) with no DOM. Add jsdom if component tests
    // are introduced later.
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
  build: {
    outDir: "dist",
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-charts": ["recharts"],
          "vendor-shiki": ["shiki"],
          "vendor-motion": ["motion"],
          "vendor-xyflow": ["@xyflow/react"],
        },
      },
    },
  },
});
