import { lazy, Suspense } from "react";
import { Outlet } from "react-router-dom";

import {
  SatQueryWorkspaceDrawer,
  useWorkspaceDrawer,
} from "@/features/workspace/SatQueryWorkspaceDrawer";
import { PanelHost } from "@/plugins/PanelHost";

const EarthStage = lazy(() =>
  import("@/earth/globe/EarthStage").then((module) => ({
    default: module.EarthStage,
  })),
);

/**
 * The Earth is the workspace: the globe is mounted once, full-bleed, and survives navigation.
 * Product-level surfaces float above the Earth only when requested. God's Eye owns the Earth
 * workspace chrome and interactions.
 */
export function AppShell() {
  const workspaceDrawer = useWorkspaceDrawer();

  return (
    <div className="pointer-events-none fixed inset-0 z-[160] overflow-hidden">
      <Suspense
        fallback={
          <div
            className="absolute inset-0"
            role="status"
            aria-label="Loading Earth workspace"
          />
        }
      >
        <EarthStage />
      </Suspense>
      <main className="pointer-events-none absolute inset-0">
        <Outlet />
        <PanelHost slot="overlay" />
      </main>
      <SatQueryWorkspaceDrawer
        open={workspaceDrawer.open}
        onClose={workspaceDrawer.closeWorkspace}
      />
    </div>
  );
}
