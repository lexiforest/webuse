export default function About() {
  return (
    <main class="min-h-screen bg-slate-50 px-5 py-8 text-slate-950">
      <section class="mx-auto max-w-3xl rounded border border-slate-200 bg-white p-5">
        <h1 class="text-2xl font-semibold">GUI</h1>
        <div class="mt-4 space-y-4 text-sm leading-6 text-slate-700">
          <p>The builder generates YAML or TOML task files for `webuse fetch` and `webuse crawl`.</p>
          <p>Run locally from the `ui/` directory:</p>
          <pre class="rounded bg-slate-950 p-3 text-slate-50">pnpm install{"\n"}pnpm dev</pre>
          <p>Open the local URL printed by Vite, then use the preview command with the generated config file.</p>
        </div>
      </section>
    </main>
  );
}
