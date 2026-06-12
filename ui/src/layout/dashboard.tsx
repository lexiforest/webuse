import { A } from "@solidjs/router";
import { For, Show, createSignal, onMount, type ParentProps } from "solid-js";
import { AiFillCloud, AiFillGithub } from "solid-icons/ai";
import type { IconTypes } from "solid-icons/lib";
import {
  FiActivity,
  FiChevronsLeft,
  FiChevronsRight,
  FiClipboard,
  FiDatabase,
  FiFileText,
  FiFolder,
  FiSettings,
} from "solid-icons/fi";

const tabs = [
  { href: "/", label: "Overview", icon: FiActivity },
  { href: "/projects", label: "Projects", icon: FiFolder },
  { href: "/runs", label: "Runs", icon: FiClipboard },
  { href: "/logs", label: "Logs", icon: FiFileText },
  { href: "/data", label: "Data", icon: FiDatabase },
  { href: "/settings", label: "Settings", icon: FiSettings },
];

const navStorageKey = "webuse:nav-collapsed";
let navCollapsed = false;

export default function Dashboard(props: ParentProps<{ currentTab: string }>) {
  const [collapsed, setCollapsed] = createSignal(navCollapsed);

  onMount(() => {
    navCollapsed = window.localStorage.getItem(navStorageKey) === "true";
    setCollapsed(navCollapsed);
  });

  const toggleCollapsed = () => {
    const next = !collapsed();
    navCollapsed = next;
    setCollapsed(next);
    window.localStorage.setItem(navStorageKey, String(next));
  };

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
            <For each={tabs}>{tab => <Tab {...tab} active={props.currentTab === tab.label.toLowerCase()} compact={false} />}</For>
          </ul>
        </nav>
      </header>

      <aside
        class={`hidden shrink-0 flex-col bg-gray-800 transition-[width,padding] duration-200 md:flex ${
          collapsed() ? "w-18 px-3 py-6" : "w-64 p-6"
        }`}
      >
        <div class={`mb-6 flex h-8 items-center gap-2 ${collapsed() ? "justify-center" : "justify-between"}`}>
          <Show when={!collapsed()}>
            <A href="/" class="min-w-0 text-xl font-bold text-sky-400">
              webuse
            </A>
          </Show>
          <button
            aria-label={collapsed() ? "Expand navigation" : "Collapse navigation"}
            class="grid h-8 w-8 shrink-0 cursor-pointer place-items-center rounded border border-gray-700 bg-gray-900 text-gray-300 transition-colors hover:bg-gray-700 hover:text-white"
            type="button"
            onClick={toggleCollapsed}
          >
            {collapsed() ? (
              <FiChevronsRight size={15} stroke-width={2} aria-hidden="true" />
            ) : (
              <FiChevronsLeft size={15} stroke-width={2} aria-hidden="true" />
            )}
          </button>
        </div>
        <nav class="flex-grow">
          <ul class="space-y-2">
            <For each={tabs}>
              {tab => (
                <Tab
                  {...tab}
                  active={props.currentTab === tab.label.toLowerCase()}
                  compact={collapsed()}
                />
              )}
            </For>
          </ul>
        </nav>
        <div class={`mt-auto flex flex-col gap-2 border-t border-gray-700 pt-4 text-sm text-gray-500 ${collapsed() ? "items-center" : ""}`}>
          <div class="flex items-center gap-2">
            <AiFillGithub size={16} aria-hidden="true" />
            <Show when={!collapsed()}>
              <span>github:</span>
              <a class="text-sky-400 hover:text-sky-300" href="https://github.com/lexiforest/webuse">
                lexiforest/webuse
              </a>
            </Show>
          </div>
          <div class="flex items-center gap-2">
            <AiFillCloud size={16} aria-hidden="true" />
            <Show when={!collapsed()}>
              <span>hosting:</span>
              <a class="text-sky-400 hover:text-sky-300" href="https://impersonate.pro">
                impersonate.pro
              </a>
            </Show>
          </div>
        </div>
      </aside>

      <main class="min-h-0 min-w-0 flex-grow overflow-auto p-2">
        <div class="flex h-full min-h-full w-full flex-col bg-gray-800 p-3 shadow-lg sm:rounded-lg">
          {props.children}
        </div>
      </main>
    </div>
  );
}

function Tab(props: { href: string; label: string; icon: IconTypes; active: boolean; compact: boolean }) {
  const Icon = props.icon;

  return (
    <li>
      <A
        href={props.href}
        aria-current={props.active ? "page" : undefined}
        title={props.compact ? props.label : undefined}
        class={`flex items-center gap-2 whitespace-nowrap rounded-lg py-2 transition-colors ${
          props.active ? "bg-sky-600 text-white" : "text-gray-300 hover:bg-gray-700"
        } ${props.compact ? "justify-center px-2" : "px-4"}`}
      >
        <span
          class={`grid h-6 w-6 shrink-0 place-items-center rounded ${
            props.active ? "bg-sky-500/30 text-white" : "bg-gray-700 text-sky-300"
          }`}
          aria-hidden="true"
        >
          <Icon size={17} stroke-width={2} />
        </span>
        <Show when={!props.compact}>
          <span>{props.label}</span>
        </Show>
      </A>
    </li>
  );
}
