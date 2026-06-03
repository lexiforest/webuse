export default function Nav() {
  return (
    <nav class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex h-12 w-full max-w-7xl items-center justify-between px-5">
        <a href="/" class="text-sm font-semibold text-slate-950">
          webuse
        </a>
        <div class="flex items-center gap-4 text-sm text-slate-600">
          <a href="/" class="hover:text-slate-950">
            Builder
          </a>
          <a href="/about" class="hover:text-slate-950">
            Docs
          </a>
        </div>
      </div>
    </nav>
  );
}
