import { useEffect, type ReactNode } from "react";

import { EarthProvider } from "@/earth/EarthProvider";
import { AgentChat } from "@/features/chat/AgentChat";
import { WorkspaceDrawerProvider } from "@/features/workspace/SatQueryWorkspaceDrawer";
import { PluginHostProvider, usePluginHost } from "@/plugins/PluginHostProvider";

function RegisterCorePanels() {
  const host = usePluginHost();

  useEffect(
    () => {
      const unregisterChat = host.panels.register(
        {
          id: "core.chat",
          title: "Conversation",
          slot: "overlay",
          order: 0,
          component: AgentChat,
        },
        "core",
      );
      return () => {
        unregisterChat();
      };
    },
    [host],
  );
  return null;
}

/** Cross-cutting context, outermost first. Add new app-wide providers here only. */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <PluginHostProvider>
      <RegisterCorePanels />
      <EarthProvider>
        <WorkspaceDrawerProvider>{children}</WorkspaceDrawerProvider>
      </EarthProvider>
    </PluginHostProvider>
  );
}
