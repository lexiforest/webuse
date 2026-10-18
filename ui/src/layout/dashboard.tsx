import { A, useLocation } from "@solidjs/router";
import ModelIndicator from "~/components/ModelIndicator";
import { For, Show, type ParentProps } from "solid-js";
import { useSidebar } from "~/components/SidebarProvider";
import { AiFillCloud, AiFillGithub } from "solid-icons/ai";
import type { IconTypes } from "solid-icons";
import {
  FiActivity,
  FiChevronDown,
  FiChevronRight,
  FiChevronsLeft,
  FiChevronsRight,
  FiClipboard,
  FiDatabase,
  FiEdit,
  FiFileText,
  FiFolder,
  FiSettings,
} from "solid-icons/fi";

const tabs = [
  { href: "/", label: "New", icon: FiEdit },
  { href: "/projects", label: "Projects", icon: FiFolder },
  { href: "/stats", label: "Stats", icon: FiActivity },
  { href: "/executions", label: "Executions", icon: FiClipboard },
  { href: "/logs", label: "Logs", icon: FiFileText },
  { href: "/data", label: "Data", icon: FiDatabase },
  { href: "/settings", label: "Settings", icon: FiSettings },
];

export default function Dashboard(props: ParentProps<{ currentTab: string }>) {
  const location = useLocation();
  const { collapsed, projectsExpanded, projects, projectsLoading, projectsError, refreshProjects, toggleCollapsed, toggleProjects } = useSidebar();
  const activeProjectId = () => Number(location.pathname.match(/^\/projects\/(\d+)(?:\/|$)/)?.[1]);

  const projectList = (id: string) => (
    <ul id={id} class="mt-1 max-h-[40vh] space-y-1 overflow-y-auto border-l border-gray-700 pl-2 text-sm">
      <li><A href="/projects" end class="block rounded px-3 py-2 text-gray-400 hover:bg-gray-700 hover:text-white">All projects</A></li>
      <Show when={projectsLoading()}><li class="px-3 py-2 text-gray-500">Loading projects…</li></Show>
      <Show when={projectsError()}>
        <li><button type="button" class="px-3 py-2 text-left text-amber-300" onClick={() => refreshProjects()}>Could not load projects. Retry</button></li>
      </Show>
      <For each={projects()} fallback={<Show when={!projectsLoading() && !projectsError()}><li class="px-3 py-2 text-gray-500">No projects yet.</li></Show>}>
        {project => (
          <li><A href={`/projects/${project.id}`} title={project.name}
            aria-current={activeProjectId() === project.id ? "page" : undefined}
            class={`block truncate rounded px-3 py-2 ${activeProjectId() === project.id ? "bg-sky-500/15 text-sky-300" : "text-gray-300 hover:bg-gray-700 hover:text-white"}`}>
            {project.name}
          </A></li>
        )}
      </For>
    </ul>
  );

  return (
    <div class="fixed inset-0 flex flex-col bg-gray-900 text-white md:flex-row">
      <header class="shrink-0 border-b border-gray-700 bg-gray-800 px-3 py-3 md:hidden">
        <div class="mb-3 flex items-center justify-between gap-3">
          <A href="/" class="text-lg font-bold text-sky-400">
            webuse
          </A>
          <div class="min-w-0 max-w-[70%]"><ModelIndicator /></div>
        </div>
        <nav class="-mx-3 overflow-x-auto px-3">
          <ul class="flex min-w-max gap-2">
            <For each={tabs}>{tab => tab.href === "/projects" ? (
              <ProjectsNavigation active={props.currentTab === "projects"} compact={false} open={projectsExpanded()}
                controls="mobile-projects" onToggle={() => toggleProjects()} />
            ) : <Tab {...tab} active={props.currentTab === tab.label.toLowerCase()} compact={false} />}</For>
          </ul>
        </nav>
        <Show when={projectsExpanded()}>{projectList("mobile-projects")}</Show>
      </header>

      <aside
        class={`hidden shrink-0 flex-col border-r border-gray-700 bg-gray-800 transition-[width,padding] duration-200 md:flex ${
          collapsed() ? "w-18 px-3 py-6" : "w-64 p-6"
        }`}
      >
        <div class={`mb-6 flex h-8 items-center ${collapsed() ? "justify-center" : ""}`}>
          <A href="/" class={`min-w-0 font-bold text-sky-400 ${collapsed() ? "text-xs" : "text-xl"}`}>
            webuse
          </A>
        </div>
        <nav class="min-h-0 flex-1 overflow-y-auto">
          <ul class="space-y-2">
            <For each={tabs}>
              {tab => tab.href === "/projects" ? (
                <ProjectsNavigation active={props.currentTab === "projects"} compact={collapsed()}
                  open={!collapsed() && projectsExpanded()} controls="desktop-projects" onToggle={() => toggleProjects(collapsed())}>
                  <Show when={!collapsed() && projectsExpanded()}>{projectList("desktop-projects")}</Show>
                </ProjectsNavigation>
              ) : (
                <Tab
                  {...tab}
                  active={props.currentTab === tab.label.toLowerCase()}
                  compact={collapsed()}
                />
              )}
            </For>
          </ul>
        </nav>
        <div class={`mt-auto flex pb-4 pt-4 ${collapsed() ? "justify-center" : ""}`}>
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
        <div class={`flex flex-col gap-2 border-t border-gray-700 pt-4 text-sm text-gray-500 ${collapsed() ? "items-center" : ""}`}>
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

      <main class="min-h-0 min-w-0 flex-grow overflow-auto">
        <div class="flex h-full min-h-full w-full flex-col bg-gray-800 p-3">
          <div class="fixed right-3 top-3 z-40 hidden max-w-48 md:block"><ModelIndicator /></div>
          {props.children}
        </div>
      </main>
    </div>
  );
}

function ProjectsNavigation(props: ParentProps<{ active: boolean; compact: boolean; open: boolean; controls: string; onToggle: () => void }>) {
  return (
    <li>
      <button type="button" aria-label="Projects" aria-expanded={props.open} aria-controls={props.controls}
        title={props.compact ? "Projects" : undefined} onClick={props.onToggle}
        class={`flex w-full cursor-pointer items-center gap-2 whitespace-nowrap rounded-lg py-2 transition-colors ${props.active ? "bg-sky-600 text-white" : "text-gray-300 hover:bg-gray-700"} ${props.compact ? "justify-center px-2" : "px-4"}`}>
        <span class={`grid h-6 w-6 shrink-0 place-items-center rounded ${props.active ? "bg-sky-500/30 text-white" : "bg-gray-700 text-sky-300"}`}>
          <FiFolder size={17} stroke-width={2} aria-hidden="true" />
        </span>
        <Show when={!props.compact}>
          <span class="flex-1 text-left">Projects</span>
          <Show when={props.open} fallback={<FiChevronRight size={14} aria-hidden="true" />}><FiChevronDown size={14} aria-hidden="true" /></Show>
        </Show>
      </button>
      {props.children}
    </li>
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
