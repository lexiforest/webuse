import type { APIEvent } from "@solidjs/start/server";

import { proxyWorker } from "~/lib/worker-api";

export function GET(event: APIEvent) {
  return proxyWorker(event, "/jobs");
}

export function POST(event: APIEvent) {
  return proxyWorker(event, "/jobs");
}

export function DELETE(event: APIEvent) {
  return proxyWorker(event, "/jobs");
}
