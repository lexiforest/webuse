import { Router } from "@solidjs/router";
import { FileRoutes } from "@solidjs/start/router";
import { Suspense } from "solid-js";
import { QueryClient, QueryClientProvider } from "@tanstack/solid-query";
import { ModelStatusProvider } from "~/components/ModelIndicator";
import { SidebarProvider } from "~/components/SidebarProvider";
import { HarnessNotificationsProvider } from "~/components/HarnessNotifications";
import "./app.css";

export default function App() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 4000 } } });
  return (
    <Router
      root={props => (
        <QueryClientProvider client={queryClient}><ModelStatusProvider><SidebarProvider><HarnessNotificationsProvider><Suspense>{props.children}</Suspense></HarnessNotificationsProvider></SidebarProvider></ModelStatusProvider></QueryClientProvider>
      )}
    >
      <FileRoutes />
    </Router>
  );
}
