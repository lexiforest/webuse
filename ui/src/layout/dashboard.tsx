import { A } from "@solidjs/router";
import { For, type ParentProps } from "solid-js";
import type { IconTypes } from "solid-icons/lib";
import {
  FiActivity,
  FiClipboard,
  FiDatabase,
  FiFileText,
  FiFolder,
  FiSettings,
} from "solid-icons/fi";

const tabs = [
  { href: "/", label: "Overview", icon: FiActivity },
  { href: "/projects", label: "Projects", icon: FiFolder },
  { href: "/jobs", label: "Jobs", icon: FiClipboard },
  { href: "/logs", label: "Logs", icon: FiFileText },
  { href: "/data", label: "Data", icon: FiDatabase },
  { href: "/settings", label: "Settings", icon: FiSettings },
];

export default function Dashboard(props: ParentProps<{ currentTab: string }>) {
  return (
    <div class="fixed inset-0 flex flex-col bg-gray-900 text-white md:flex-row">
      <header class="shrink-0 border-b border-gray-700 bg-gray-800 px-3 py-3 md:hidden">
        <div class="mb-3 flex items-center justify-between gap-3">
          <A href="/" class="text-lg font-bold text-sky-400">
            webuse
          </A>
          <span class="text-sm text-gray-500">crawler console</span>
        </div>
        <nav class="-mx-3 overflow-x-auto px-3">
          <ul class="flex min-w-max gap-2">
            <For each={tabs}>{tab => <Tab {...tab} active={props.currentTab === tab.label.toLowerCase()} />}</For>
          </ul>
        </nav>
      </header>

      <aside class="hidden w-64 shrink-0 flex-col bg-gray-800 p-6 md:flex">
        <A href="/" class="mb-6 text-xl font-bold text-sky-400">
          webuse
        </A>
        <nav class="flex-grow">
          <ul class="space-y-2">
            <For each={tabs}>{tab => <Tab {...tab} active={props.currentTab === tab.label.toLowerCase()} />}</For>
          </ul>
        </nav>
        <div class="mt-auto border-t border-gray-700 pt-4 text-sm text-gray-500">Local scraping tasks</div>
      </aside>

      <main class="min-h-0 min-w-0 flex-grow overflow-auto p-3 sm:p-4">
        <div class="mx-auto min-h-full w-full max-w-7xl bg-gray-800 p-4 shadow-lg sm:rounded-lg sm:p-6">
          {props.children}
        </div>
      </main>
    </div>
  );
}

function Tab(props: { href: string; label: string; icon: IconTypes; active: boolean }) {
  const Icon = props.icon;

  return (
    <li>
      <A
        href={props.href}
        aria-current={props.active ? "page" : undefined}
        class={`flex items-center gap-2 whitespace-nowrap rounded-lg px-4 py-2 transition-colors ${
          props.active ? "bg-sky-600 text-white" : "text-gray-300 hover:bg-gray-700"
        }`}
      >
        <span
          class={`grid h-6 w-6 shrink-0 place-items-center rounded ${
            props.active ? "bg-sky-500/30 text-white" : "bg-gray-700 text-sky-300"
          }`}
          aria-hidden="true"
        >
          <Icon size={17} stroke-width={2} />
        </span>
        <span>{props.label}</span>
      </A>
    </li>
  );
}
