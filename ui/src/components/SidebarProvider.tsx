import { createContext, createSignal, onCleanup, onMount, useContext, type Accessor, type ParentProps } from "solid-js";

type ProjectLink = { id: number; name: string };
type SidebarState = {
  collapsed: Accessor<boolean>;
  projectsExpanded: Accessor<boolean>;
  projects: Accessor<ProjectLink[]>;
  projectsLoading: Accessor<boolean>;
  projectsError: Accessor<boolean>;
  refreshProjects: () => void;
  toggleCollapsed: () => void;
  toggleProjects: (expandNavigation?: boolean) => void;
};

const SidebarContext = createContext<SidebarState>();
const navStorageKey = "webuse:nav-collapsed";
const projectsStorageKey = "webuse:projects-expanded";

export function SidebarProvider(props: ParentProps) {
  const [collapsed, setCollapsed] = createSignal(false);
  const [projectsExpanded, setProjectsExpanded] = createSignal(true);
  const [projects, setProjects] = createSignal<ProjectLink[]>([]);
  const [projectsLoading, setProjectsLoading] = createSignal(true);
  const [projectsError, setProjectsError] = createSignal(false);
  let pending: AbortController | undefined;

  const refresh = async (force = false) => {
    if (pending && !force) return;
    pending?.abort();
    const request = new AbortController();
    pending = request;
    try {
      const response = await fetch("/api/projects", { signal: request.signal });
      if (!response.ok) throw new Error("Could not load projects");
      const data = await response.json() as { projects: ProjectLink[] };
      if (!request.signal.aborted) {
        setProjects(data.projects);
        setProjectsError(false);
      }
    } catch {
      if (!request.signal.aborted) setProjectsError(true);
    } finally {
      if (pending === request) pending = undefined;
      if (!request.signal.aborted) setProjectsLoading(false);
    }
  };
  const refreshProjects = () => { void refresh(true); };

  onMount(() => {
    setCollapsed(window.localStorage.getItem(navStorageKey) === "true");
    setProjectsExpanded(window.localStorage.getItem(projectsStorageKey) !== "false");
    void refresh();
    const timer = setInterval(() => void refresh(), 10_000);
    window.addEventListener("webuse:projects-changed", refreshProjects);
    window.addEventListener("focus", refreshProjects);
    onCleanup(() => {
      pending?.abort();
      clearInterval(timer);
      window.removeEventListener("webuse:projects-changed", refreshProjects);
      window.removeEventListener("focus", refreshProjects);
    });
  });

  const toggleCollapsed = () => {
    const next = !collapsed();
    setCollapsed(next);
    window.localStorage.setItem(navStorageKey, String(next));
  };
  const toggleProjects = (expandNavigation = false) => {
    const open = expandNavigation || !projectsExpanded();
    if (expandNavigation) {
      setCollapsed(false);
      window.localStorage.setItem(navStorageKey, "false");
    }
    setProjectsExpanded(open);
    window.localStorage.setItem(projectsStorageKey, String(open));
    if (open) refreshProjects();
  };

  return (
    <SidebarContext.Provider value={{ collapsed, projectsExpanded, projects, projectsLoading, projectsError, refreshProjects, toggleCollapsed, toggleProjects }}>
      {props.children}
    </SidebarContext.Provider>
  );
}

export function useSidebar() {
  return useContext(SidebarContext)!;
}
