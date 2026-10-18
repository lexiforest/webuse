import { open } from "node:fs/promises";
import { StringDecoder } from "node:string_decoder";
import { store } from "./store";

// Read only appended bytes. A line split across writes is held until complete;
// the final unterminated line is considered when the worker exits.
export function recordCollector(jobId: number, path: string) {
  let offset = 0;
  let remainder = "";
  let decoder = new StringDecoder("utf8");
  let pending = Promise.resolve();
  let busy = false;
  const insert = (line: string) => {
    if (!line.trim()) return;
    let item;
    try {
      item = JSON.parse(line);
      if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error();
    } catch { store.appendLog(jobId, "stderr", "ignored malformed JSONL output line"); return; }
    store.insertDataItem(jobId, item);
  };
  const read = async (final: boolean) => {
    let file;
    try { file = await open(path, "r"); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
    try {
      const size = (await file.stat()).size;
      if (size < offset) {
        offset = 0; remainder = ""; decoder = new StringDecoder("utf8");
        store.clearDataItems(jobId);
      }
      const end = final ? size : Math.min(size, offset + 1024 * 1024);
      const buffer = Buffer.alloc(64 * 1024);
      while (offset < end) {
        const { bytesRead } = await file.read(buffer, 0, Math.min(buffer.length, end - offset), offset);
        if (!bytesRead) break;
        offset += bytesRead;
        const lines = (remainder + decoder.write(buffer.subarray(0, bytesRead))).split("\n");
        remainder = lines.pop()!;
        for (const line of lines) insert(line);
      }
      if (final) { insert(remainder + decoder.end()); remainder = ""; }
    } finally { await file.close(); }
  };
  const flush = (final = false) => {
    if (busy && !final) return pending;
    busy = true;
    pending = pending.then(() => read(final)).catch(error => {
      store.appendLog(jobId, "stderr", `Could not read execution output: ${(error as Error).message}`);
    }).finally(() => { busy = false; });
    return pending;
  };
  const timer = setInterval(() => void flush(), 500);
  return { async stop() { clearInterval(timer); await flush(true); } };
}
