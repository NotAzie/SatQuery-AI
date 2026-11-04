import { lazy, Suspense } from "react";
import { Outlet } from "react-router-dom";

import { PanelHost } from "@/plugins/PanelHost";

const EarthStage = lazy(() =>
  import("@/earth/globe/EarthStage").then((module) => ({
    default: module.EarthStage,
  })),
);

/**
 * The Earth is the workspace: the globe is mounted once, full-bleed, and survives navigation.
 * Everything else floats above it in named slots and never captures pointer events outside its
 * own bounds, so the globe stays directly manipulable.
 */
export function AppShell() {
  return (
    <div className="relative h-full w-full overflow-hidden bg-void">
      <Suspense
        fallback={
          <div
            className="absolute inset-0 bg-void"
            role="status"
            aria-label="Loading Earth workspace"
          />
        }
      >
        <EarthStage />
      </Suspense>
      <div className="pointer-events-none absolute inset-0 flex">
        <aside className="flex flex-col justify-end p-4">
          <PanelHost slot="left" />
        </aside>
        <main className="relative flex-1">
          <Outlet />
          <PanelHost slot="overlay" />
        </main>
        <aside className="flex flex-col justify-end p-4">
          <PanelHost slot="right" />
        </aside>
      </div>
      <footer className="pointer-events-none absolute inset-x-0 bottom-0">
        <PanelHost slot="bottom" />
      </footer>
    </div>
  );
}
