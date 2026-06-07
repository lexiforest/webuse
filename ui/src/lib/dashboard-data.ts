export type Project = {
  id: number;
  name: string;
  type: "source" | "git";
  target: string;
  updatedAt: string;
  status: string;
};

export type Job = {
  id: number;
  project: string;
  status: "queued" | "running" | "succeeded" | "failed";
  startedAt: string;
  duration: string;
  items: number;
};

export type LogLine = {
  id: number;
  jobId: number;
  stream: "stdout" | "stderr";
  message: string;
  time: string;
};

export type DataItem = {
  id: number;
  jobId: number;
  url: string;
  item: Record<string, unknown>;
};

export const projects: Project[] = [
  {
    id: 1,
    name: "Catalog crawler",
    type: "git",
    target: "https://github.com/example/catalog-task.git",
    updatedAt: "2026-06-03 14:20",
    status: "Ready",
  },
  {
    id: 2,
    name: "Pricing monitor",
    type: "source",
    target: "pricing-task.tar.gz",
    updatedAt: "2026-06-02 18:05",
    status: "Needs review",
  },
];

export const jobs: Job[] = [
  {
    id: 1024,
    project: "Catalog crawler",
    status: "running",
    startedAt: "2026-06-03 15:10",
    duration: "4m 12s",
    items: 184,
  },
  {
    id: 1023,
    project: "Pricing monitor",
    status: "succeeded",
    startedAt: "2026-06-03 13:40",
    duration: "8m 45s",
    items: 42,
  },
  {
    id: 1022,
    project: "Catalog crawler",
    status: "failed",
    startedAt: "2026-06-03 10:15",
    duration: "1m 08s",
    items: 0,
  },
];

export const logs: LogLine[] = [
  { id: 1, jobId: 1024, stream: "stdout", time: "15:10:02", message: "queued seed https://example.com/catalog" },
  { id: 2, jobId: 1024, stream: "stdout", time: "15:10:19", message: "fetched 24 pages, extracted 184 items" },
  { id: 3, jobId: 1022, stream: "stderr", time: "10:16:08", message: "selector failed: primary product price" },
];

export const dataItems: DataItem[] = [
  {
    id: 1,
    jobId: 1024,
    url: "https://example.com/products/alpha",
    item: { title: "Alpha Gadget", price: "$19.00", href: "/products/alpha" },
  },
  {
    id: 2,
    jobId: 1024,
    url: "https://example.com/products/beta",
    item: { title: "Beta Gadget", price: "$29.00", href: "/products/beta" },
  },
];
