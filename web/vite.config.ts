import { defineConfig, Plugin } from "vite";
import preact from "@preact/preset-vite";
import { resolve } from "path";
import { readFileSync, writeFileSync } from "fs";

/** Stamps sw.js with the build version and the list of emitted assets to precache. */
function serviceWorkerPlugin(): Plugin {
  let assets: string[] = [];
  return {
    name: "sw-precache-plugin",
    apply: "build",
    generateBundle(_options, bundle) {
      assets = Object.keys(bundle)
        .filter((file) => file.startsWith("assets/"))
        .map((file) => `/${file}`)
        .sort();
    },
    closeBundle() {
      const swPath = resolve(__dirname, "../src/health_coach/web/static/sw.js");
      try {
        const buildVersion = Date.now().toString(36);
        let content = readFileSync(swPath, "utf-8");
        content = content.replace(/__BUILD_VERSION__/g, buildVersion);
        content = content.replace('"__PRECACHE_ASSETS__"', JSON.stringify(JSON.stringify(assets)));
        writeFileSync(swPath, content);
      } catch (err) {
        // file may not exist if build failed or in test
      }
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [preact(), serviceWorkerPlugin()],
  build: {
    outDir: resolve(__dirname, "../src/health_coach/web/static"),
    emptyOutDir: true,
  },
  test: {
    environment: "node",
  },
});
