import { readFileSync } from "node:fs";
import { defineConfig } from "@solidjs/start/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  serialization: { mode: "json" },
  vite: {
    plugins: [tailwindcss()]
  },
  server: {
    preset: "node-server",
    plugins: ["./server/plugins/orchestrator.ts"],
    noExternals: true,
    // CommonJS needs mutable Node builtins; ws can use its JavaScript fallbacks.
    commonJS: { esmExternals: false, ignore: ["bufferutil", "utf-8-validate"] },
    rollupConfig: {
      external: ["node:sqlite"],
      plugins: [{
        name: "raw-assets",
        load(id: string) {
          if (id.endsWith("?raw")) {
            return `export default ${JSON.stringify(readFileSync(id.slice(0, -4), "utf8"))};`;
          }
        }
      }]
    }
  }
});
