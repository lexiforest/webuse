import { Cron } from "croner";

function schedule(expression: string) {
  if (expression.trim().split(/\s+/).length !== 5) throw new Error("Expected a five-field cron expression.");
  return new Cron(expression, { mode: "5-part", paused: true, timezone: "UTC" });
}

export function validCron(expression: string) {
  try { return schedule(expression).nextRun() !== null; } catch { return false; }
}

export function nextCronTime(expression: string, after = Date.now()) {
  const next = schedule(expression).nextRun(new Date(after));
  if (!next) throw new Error("Cron expression has no future occurrence.");
  return next.getTime();
}
