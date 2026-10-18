import type { APIEvent } from "@solidjs/start/server";
import { json } from "~/lib/server/http";
import { store } from "~/lib/server/store";

export function GET(event: APIEvent) {
  const raw = new URL(event.request.url).searchParams.get("after");
  const after = raw === null ? undefined : Number(raw);
  if (after !== undefined && (!Number.isSafeInteger(after) || after < 0)) return json({ error: "Invalid completion cursor." }, 400);
  return json(store.assistantCompletions(after));
}
