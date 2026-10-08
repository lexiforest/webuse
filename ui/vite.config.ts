import { defineConfig } from "vite";
import { nitro } from "nitro/vite";
import { solidStart } from "@solidjs/start/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  server: { port: 2951 },
  preview: { port: 2951 },
  plugins: [
    solidStart(),
    tailwindcss(),
    nitro()
  ],
  nitro: {
    plugins: ["./server/plugins/orchestrator.ts"]
  }
});
