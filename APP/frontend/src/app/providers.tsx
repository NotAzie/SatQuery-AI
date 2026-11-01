import { useEffect, type ReactNode } from "react";

import { EarthProvider } from "@/earth";
import { AgentChat } from "@/features/chat/AgentChat";
import { SessionSidebar } from "@/features/sessions/SessionSidebar";
import { TimelinePanel } from "@/features/timeline/TimelinePanel";
import { WorkspaceToolsPanel } from "@/features/earth/WorkspaceToolsPanel";
import { VisionAttachments } from "@/features/vision/VisionAttachments";
import { PluginHostProvider, usePluginHost } from "@/plugins/PluginHostProvider";

function RegisterCorePanels() {
  const host = usePluginHost();

  useEffect(
    () => {
      const unregisterSessions = host.panels.register(
        {
          id: "core.sessions",
          title: "Sessions",
          slot: "left",
          order: 0,
          component: SessionSidebar,
        },
        "core",
      );
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
      const unregisterTimeline = host.panels.register(
        {
          id: "core.timeline",
          title: "Earth timeline",
          slot: "bottom",
          order: 0,
          component: TimelinePanel,
        },
        "core",
      );
      const unregisterEarthTools = host.panels.register(
        {
          id: "core.earth-tools",
          title: "Earth tools",
          slot: "right",
          order: 0,
          component: WorkspaceToolsPanel,
        },
        "core",
      );
      const unregisterVision = host.panels.register(
        {
          id: "core.vision",
          title: "Image attachments",
          slot: "right",
          order: 10,
          component: VisionAttachments,
        },
        "core",
      );
      return () => {
        unregisterSessions();
        unregisterChat();
        unregisterTimeline();
        unregisterEarthTools();
        unregisterVision();
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
      <EarthProvider>{children}</EarthProvider>
    </PluginHostProvider>
  );
}
