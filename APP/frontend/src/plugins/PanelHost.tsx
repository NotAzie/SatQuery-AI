import { useSyncExternalStore } from "react";

import { usePluginHost } from "./PluginHostProvider";
import type { PanelSlot } from "./types";

/**
 * Renders every panel registered for a slot, core and plugin alike: first-party features register
 * through the same registry that plugins use, so there is exactly one way to put UI on screen.
 */
export function PanelHost({ slot }: { slot: PanelSlot }) {
  const { panels } = usePluginHost();
  const all = useSyncExternalStore(panels.subscribe, panels.list);
  const inSlot = all.filter((p) => p.slot === slot).sort((a, b) => a.order - b.order);
  if (inSlot.length === 0) return null;
  return (
    <>
      {inSlot.map(({ id, component: Panel }) => (
        <div
          key={id}
          className={slot === "bottom" ? "pointer-events-none" : "pointer-events-auto"}
        >
          <Panel />
        </div>
      ))}
    </>
  );
}
