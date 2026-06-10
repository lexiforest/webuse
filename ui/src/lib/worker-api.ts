import type { APIEvent } from "@solidjs/start/server";

const workerUrl = process.env.WEBUSE_WORKER_URL || "http://127.0.0.1:8787";

export async function proxyWorker(event: APIEvent, pathname: string) {
  const sourceUrl = new URL(event.request.url);
  const targetUrl = new URL(pathname, workerUrl);
  targetUrl.search = sourceUrl.search;

  const headers = new Headers();
  const contentType = event.request.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }

  const body =
    event.request.method === "GET" || event.request.method === "HEAD"
      ? undefined
      : await event.request.text();

  const response = await fetch(targetUrl, {
    method: event.request.method,
    headers,
    body,
  });

  return new Response(response.body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") || "application/json",
      "cache-control": "no-store",
    },
  });
}
