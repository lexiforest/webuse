import type { APIEvent } from "@solidjs/start/server";
import { json } from "~/lib/server/http";
import { clearModelCache, modelStatus } from "~/lib/server/models";

export async function GET(event: APIEvent) {
  if (new URL(event.request.url).searchParams.has("refresh")) clearModelCache();
  return json(await modelStatus());
}
