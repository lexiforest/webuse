import { parse } from "yaml";

type File = { path: string; content: string };
const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};

export function visualSpiders(project: Record<string, unknown>, files: File[]) {
  const spiders: { name: string; config: Record<string, unknown> }[] = [];
  const notes: string[] = [];
  const lookup = (path: string) => files.find(file => file.path === path.replace(/^\.\//, ""));
  for (const [name, entry] of Object.entries(record(project.spiders))) {
    const config = record(entry);
    const target = typeof entry === "string" ? entry : config.config || config.path || config.module;
    if (!target) { spiders.push({ name, config }); continue; }
    if (typeof target !== "string") continue;
    let path = target;
    let source = lookup(path);
    if (!source && !/\.(py|ya?ml)$/.test(path)) {
      path = path.split(":")[0].replace(/\./g, "/") + ".py";
      source = lookup(path);
    }
    if (path.endsWith(".py") && source) {
      const reference = source.content.match(/^\s*spider_config_path\s*=\s*["']([^"']+)["']/m)?.[1];
      if (!reference) { notes.push(`${name}: Python behavior is inferred from source in the Python graph.`); continue; }
      path = reference;
      source = lookup(path);
      notes.push(`${name}: showing ${path}; Python overrides and callbacks are not evaluated.`);
    }
    if (!source) { notes.push(`${name}: ${path} is not available in the editor.`); continue; }
    if (!/\.ya?ml$/.test(path)) { notes.push(`${name}: ${path} cannot be visualized as YAML.`); continue; }
    try { spiders.push({ name, config: record(parse(source.content)) }); }
    catch { notes.push(`${name}: invalid YAML in ${path}.`); }
  }
  return { spiders, notes };
}
