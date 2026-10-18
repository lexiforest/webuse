import { A, useNavigate } from "@solidjs/router";
import { createContext, createSignal, For, onCleanup, onMount, useContext, type ParentProps } from "solid-js";
import { Button } from "~/components/ui/button";

type Completion = { id: number; projectId: number; project: string; outcome: "completed" | "failed" | "stopped" };
const PermissionContext = createContext<{
  permission: () => NotificationPermission | "unsupported";
  enable: () => Promise<void>;
}>();
const cursorKey = "webuse:harness-completion-cursor";

export function HarnessNotificationsProvider(props: ParentProps) {
  const navigate = useNavigate();
  const [permission, setPermission] = createSignal<NotificationPermission | "unsupported">("unsupported");
  const [notices, setNotices] = createSignal<Completion[]>([]);
  const refreshPermission = () => setPermission("Notification" in window && window.isSecureContext ? Notification.permission : "unsupported");
  const enable = async () => {
    try { setPermission(await Notification.requestPermission()); }
    catch { refreshPermission(); }
  };
  const dismiss = (id: number) => setNotices(current => current.filter(notice => notice.id !== id));
  const title = (completion: Completion) => completion.outcome === "failed" ? "Harness needs attention" : "Harness finished";

  onMount(() => {
    refreshPermission();
    let cursor: number | undefined;
    try {
      const stored = sessionStorage.getItem(cursorKey);
      if (stored !== null && Number.isSafeInteger(Number(stored)) && Number(stored) >= 0) cursor = Number(stored);
    } catch { /* Storage can be disabled in private browsing. */ }
    let disposed = false;
    let pending: AbortController | undefined;
    const notifications = new Set<Notification>();
    const notify = async (completion: Completion) => {
      const display = () => {
        if (disposed || permission() !== "granted") return;
        try {
          const key = "webuse:harness-last-notified";
          if (Number(localStorage.getItem(key) || 0) >= completion.id) return;
          localStorage.setItem(key, String(completion.id));
        } catch { /* Notifications still work without storage. */ }
        try {
          const notification = new Notification(title(completion), { body: completion.project, tag: `webuse-harness-${completion.id}` });
          notifications.add(notification);
          notification.onclose = () => notifications.delete(notification);
          notification.onclick = () => {
            window.focus();
            navigate(`/projects/${completion.projectId}`);
            dismiss(completion.id);
            notification.close();
          };
        } catch { /* Some browsers only support service-worker notifications; keep the in-app notice. */ }
      };
      if (navigator.locks) await navigator.locks.request("webuse-harness-notification", display);
      else display();
    };
    const refresh = async () => {
      refreshPermission();
      if (pending) return;
      const request = new AbortController();
      pending = request;
      try {
        const response = await fetch(`/api/assistant-completions${cursor === undefined ? "" : `?after=${cursor}`}`, { signal: request.signal });
        if (!response.ok) throw new Error("Completion status unavailable");
        const data = await response.json() as { cursor: number; completions: Completion[] };
        if (disposed) return;
        for (const completion of data.completions) {
          if (completion.outcome === "stopped") continue;
          setNotices(current => [...current.filter(item => item.id !== completion.id), completion].slice(-5));
          const viewingProject = window.location.pathname.match(/^\/projects\/(\d+)(?:\/|$)/)?.[1] === String(completion.projectId);
          if (document.visibilityState !== "visible" || !viewingProject) void notify(completion);
        }
        if (data.completions.length) window.dispatchEvent(new Event("webuse:projects-changed"));
        cursor = data.cursor;
        try { sessionStorage.setItem(cursorKey, String(cursor)); } catch { /* Optional reload recovery. */ }
      } catch { /* Retry after transient failures without advancing the cursor. */ }
      finally { pending = undefined; }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 2000);
    window.addEventListener("focus", refresh);
    onCleanup(() => {
      disposed = true;
      pending?.abort();
      clearInterval(timer);
      window.removeEventListener("focus", refresh);
      for (const notification of notifications) notification.close();
    });
  });

  return (
    <PermissionContext.Provider value={{ permission, enable }}>
      {props.children}
      <div class="pointer-events-none fixed bottom-4 right-4 z-[60] flex max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        <For each={notices()}>{notice => (
          <div class="pointer-events-auto flex w-80 max-w-full items-start gap-3 rounded-lg border border-gray-600 bg-gray-900 p-3 text-sm text-white shadow-xl">
            <A class="min-w-0 flex-1" href={`/projects/${notice.projectId}`} onClick={() => dismiss(notice.id)}>
              <div class="font-medium">{title(notice)}</div>
              <div class="truncate text-gray-400">{notice.project}</div>
            </A>
            <button type="button" class="text-gray-400 hover:text-white" aria-label="Dismiss notification" onClick={() => dismiss(notice.id)}>×</button>
          </div>
        )}</For>
      </div>
    </PermissionContext.Provider>
  );
}

export function HarnessNotificationSettings() {
  const { permission, enable } = useContext(PermissionContext)!;
  return (
    <section class="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-700 p-4">
      <div>
        <h2 class="font-medium text-white">Harness notifications</h2>
        <p class="mt-1 text-sm text-gray-400">Notify when a background turn finishes. Keep a Webuse tab open to receive notifications.</p>
        <p class="mt-1 text-xs text-gray-500">{permission() === "denied" ? "Notifications are blocked. Allow them in your browser's site settings." : permission() === "unsupported" ? "Browser notifications are unavailable here. Completion notices still appear inside Webuse." : permission() === "granted" ? "Browser notifications are enabled." : "Enable browser notifications to be notified outside Webuse."}</p>
      </div>
      <Button variant="outline" type="button" disabled={permission() !== "default"} onClick={() => void enable()}>Enable notifications</Button>
    </section>
  );
}
