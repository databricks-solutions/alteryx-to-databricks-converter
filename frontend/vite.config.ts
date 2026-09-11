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
    // Default to a fast node environment for pure-logic tests (warning parsing,
    // deploy-status, CSV). Component tests opt into jsdom per-file with a
    // `// @vitest-environment jsdom` docblock at the top of the file.
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["src/test-setup.ts"],
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
