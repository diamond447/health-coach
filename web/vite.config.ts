import { defineConfig, Plugin } from "vite";
import preact from "@preact/preset-vite";
import { resolve } from "path";
import { readFileSync, writeFileSync } from "fs";

function serviceWorkerVersionPlugin(): Plugin {
  return {
    name: "sw-version-plugin",
    closeBundle() {
      const swPath = resolve(__dirname, "../src/health_coach/web/static/sw.js");
      try {
        const buildVersion = Date.now().toString(36);
        let content = readFileSync(swPath, "utf-8");
        content = content.replace(/__BUILD_VERSION__/g, buildVersion);
        writeFileSync(swPath, content);
      } catch (err) {
        // file may not exist if build failed or in test
      }
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [preact(), serviceWorkerVersionPlugin()],
  build: {
    outDir: resolve(__dirname, "../src/health_coach/web/static"),
    emptyOutDir: true,
  },
  test: {
    environment: "node",
  },
});
