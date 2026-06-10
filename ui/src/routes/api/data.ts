import type { APIEvent } from "@solidjs/start/server";

import { proxyWorker } from "~/lib/worker-api";

export function GET(event: APIEvent) {
  return proxyWorker(event, "/data");
}
