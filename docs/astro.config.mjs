import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

const site = process.env.DOCS_SITE ?? process.env.READTHEDOCS_CANONICAL_URL;
const base = process.env.DOCS_BASE ?? (site ? new URL(site).pathname : "/");

export default defineConfig({
  site,
  base,
  trailingSlash: "always",
  integrations: [
    starlight({
      title: "webuse",
      customCss: ["./src/styles/custom.css"],
      sidebar: [
        { label: "Overview", slug: "" },
        {
          label: "User Guide",
          items: [
            { slug: "user-guide/quick-start" },
            { slug: "user-guide/harness" },
            { slug: "user-guide/dashboard" },
            { slug: "user-guide/async" },
            { slug: "user-guide/extraction" },
            { slug: "user-guide/deployment" },
            { slug: "user-guide/cloud" },
            { slug: "user-guide/vs-scrapy" },
            { slug: "user-guide/faq" },
          ],
        },
        {
          label: "References",
          items: [
            { slug: "references/cli" },
            { slug: "references/config" },
            { slug: "references/pipelines" },
            { slug: "references/signals" },
            { slug: "references/agentic" },
          ],
        },
        {
          label: "Advanced Usage",
          items: [
            { slug: "advanced/agentic" },
            { slug: "advanced/request-hooks" },
            { slug: "advanced/state" },
          ],
        },
        {
          label: "Contributing",
          items: [
            { slug: "advanced/overview" },
            { slug: "advanced/engine" },
            { slug: "advanced/spider" },
            { slug: "advanced/cli-internals" },
            { slug: "advanced/harness-internals" },
            { slug: "advanced/monitoring" },
            { slug: "advanced/package-release" },
          ],
        },
      ],
    }),
  ],
});
