import type { APIEvent } from "@solidjs/start/server";

import { proxyWorker } from "~/lib/worker-api";

export async function GET(event: APIEvent) {
  return proxyWorker(event, "/projects");
}

export async function POST(event: APIEvent) {
  return proxyWorker(event, "/projects");
}

export async function PUT(event: APIEvent) {
  return proxyWorker(event, "/projects");
}

export async function DELETE(event: APIEvent) {
  return proxyWorker(event, "/projects");
}
