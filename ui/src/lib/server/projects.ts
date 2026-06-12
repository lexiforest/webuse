import { desc, eq } from "drizzle-orm";

import { db } from "./db";
import { projects } from "./schema";

export type ProjectRow = {
  id: number;
  name: string;
  type: "source" | "yaml" | "python" | "git";
  target: string;
  status: string;
  updatedAt: string;
};

export type ProjectDetail = ProjectRow & {
  config?: Record<string, unknown>;
};

export type CreateProjectInput = {
  name: string;
  type: "source" | "yaml" | "python" | "git";
  target: string;
  config?: Record<string, unknown>;
};

const booksToScrapeConfig = {
  name: "Books to Scrape",
  spiders: {
    books: {
      start_urls: ["https://books.toscrape.com/"],
      allowed_domains: ["books.toscrape.com"],
      max_depth: 1,
      pages: {
        default: {
          follow: [{ css: ".next a", same_domain: true }],
          extract: {
            books: {
              item_css: ".product_pod",
              fields: {
                title: {
                  css: "h3 a",
                  attr: "title",
                },
                price: ".price_color",
                availability: ".availability",
              },
            },
          },
        },
      },
    },
  },
};

function serializeDate(value: Date) {
  return value.toISOString().replace("T", " ").slice(0, 16);
}

function toProjectRow(project: typeof projects.$inferSelect): ProjectRow {
  return {
    id: project.id,
    name: project.name,
    type: project.type,
    target: project.gitUrl || "https://books.toscrape.com/",
    status: "Ready",
    updatedAt: serializeDate(project.updatedAt),
  };
}

function toProjectDetail(project: typeof projects.$inferSelect): ProjectDetail {
  return {
    ...toProjectRow(project),
    config: project.config ?? undefined,
  };
}

export function listProjects(): ProjectRow[] {
  return db.select().from(projects).orderBy(desc(projects.updatedAt)).all().map(toProjectRow);
}

export function getProject(id: number): ProjectDetail | undefined {
  const project = db.select().from(projects).where(eq(projects.id, id)).get();
  return project ? toProjectDetail(project) : undefined;
}

export function createBooksToScrapeProject(): ProjectRow {
  return createProject({
    name: "Books to Scrape",
    type: "source",
    target: "https://books.toscrape.com/",
    config: booksToScrapeConfig,
  });
}

export function createProject(input: CreateProjectInput): ProjectRow {
  const now = new Date();
  const result = db
    .insert(projects)
    .values({
      name: input.name,
      type: input.type,
      gitUrl: input.target,
      config: input.config,
      createdAt: now,
      updatedAt: now,
    })
    .returning()
    .get();

  return toProjectRow(result);
}

export function updateProject(id: number, input: CreateProjectInput): ProjectDetail | undefined {
  const now = new Date();
  const result = db
    .update(projects)
    .set({
      name: input.name,
      type: input.type,
      gitUrl: input.target,
      config: input.config,
      updatedAt: now,
    })
    .where(eq(projects.id, id))
    .returning()
    .get();

  return result ? toProjectDetail(result) : undefined;
}

export function deleteProject(id: number) {
  db.delete(projects).where(eq(projects.id, id)).run();
}
