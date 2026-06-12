import type { APIEvent } from "@solidjs/start/server";

import { proxyWorker } from "~/lib/worker-api";

async function proxyRuns(event: APIEvent) {
  const response = await proxyWorker(event, "/jobs");
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return response;
  }

  const data = (await response.json()) as Record<string, unknown>;
  if ("jobs" in data) {
    data.runs = data.jobs;
    delete data.jobs;
  }
  if ("job" in data) {
    data.run = data.job;
    delete data.job;
  }

  return new Response(JSON.stringify(data), {
    status: response.status,
    headers: {
      "content-type": "application/json",
      "cache-control": response.headers.get("cache-control") || "no-store",
    },
  });
}

export function GET(event: APIEvent) {
  return proxyRuns(event);
}

export function POST(event: APIEvent) {
  return proxyRuns(event);
}

export function DELETE(event: APIEvent) {
  return proxyRuns(event);
}
