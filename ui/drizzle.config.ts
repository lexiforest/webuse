import { defineConfig } from "drizzle-kit";

export default defineConfig({
  schema: "./src/lib/server/schema.ts",
  out: "./drizzle",
  dialect: "sqlite",
  dbCredentials: {
    url: process.env.WEBUSE_DB_PATH || "./webuse.sqlite",
  },
});
