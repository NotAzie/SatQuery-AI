import { useState } from "react";

import { getEngineDiscovery } from "@/services/api/engineDiscovery";
import type { EngineDiscoveryResponse } from "@/shared/types";

function formatDate(value: string | null | undefined): string | null {
  return value ? new Date(value).toLocaleDateString() : null;
}

export function EngineDiscoveryPanel() {
  const [discovery, setDiscovery] = useState<EngineDiscoveryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadDiscovery() {
    setLoading(true);
    setError(null);
    try {
      setDiscovery(await getEngineDiscovery());
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Engine discovery failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section
      aria-label="Engine data and capabilities"
      className="pointer-events-auto max-h-[min(74vh,52rem)] w-72 overflow-y-auto rounded-2xl border border-white/10 bg-surface/95 p-3 text-ink shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      <header className="mb-3">
        <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
          Engine discovery
        </p>
        <h2 className="mt-1 text-sm font-semibold">Registered data & capabilities</h2>
        <p className="mt-1 text-[10px] leading-4 text-ink-dim">
          Earth capability status and image-analysis capabilities describe Engine registrations,
          not Agent tool schemas. Registrations do not guarantee data access or scientific suitability.
        </p>
      </header>

      <button
        type="button"
        disabled={loading}
        onClick={() => void loadDiscovery()}
        className="rounded-lg border border-white/10 px-2 py-1.5 text-xs disabled:opacity-40"
      >
        {loading ? "Loading Engine metadata..." : discovery ? "Refresh" : "Load Engine metadata"}
      </button>

      {error && <p className="mt-2 text-xs text-rose-200" role="alert">{error}</p>}

      {discovery && (
        <div className="mt-3 space-y-3">
          <section aria-label="Image analysis capabilities">
            <h3 className="text-xs font-medium">
              Image-analysis capabilities ({discovery.image_capabilities.length})
            </h3>
            <ul className="mt-2 space-y-2">
              {discovery.image_capabilities.map((capability) => (
                <li
                  key={capability.tool}
                  className="rounded-lg border border-white/10 p-2 text-[10px] leading-4"
                >
                  <p className="font-medium">
                    {capability.tool.replaceAll("_", " ")}
                    {" · "}
                    {capability.available ? "available" : "unavailable"}
                  </p>
                  <p className="text-ink-dim">{capability.description}</p>
                  {capability.unavailable_reason && (
                    <p className="mt-1 text-ink-dim">{capability.unavailable_reason}</p>
                  )}
                  <p className="mt-1 text-ink-dim">
                    Intent: {capability.intent.toLowerCase().replaceAll("_", " ")}
                    {" · "}
                    Required images: {capability.requires_images}
                  </p>
                </li>
              ))}
              {discovery.image_capabilities.length === 0 && (
                <li className="text-[10px] text-ink-dim">
                  The Engine reports no image-analysis capabilities.
                </li>
              )}
            </ul>
          </section>

          <section aria-label="Registered Engine datasets">
            <h3 className="text-xs font-medium">
              Registered datasets ({discovery.datasets.length})
            </h3>
            <ul className="mt-2 space-y-2">
              {discovery.datasets.map((dataset) => {
                const start = formatDate(dataset.temporal_coverage?.start);
                const end = formatDate(dataset.temporal_coverage?.end);
                return (
                  <li
                    key={`${dataset.connector_id}:${dataset.dataset_id}`}
                    className="rounded-lg border border-white/10 p-2 text-[10px] leading-4"
                  >
                    <p className="font-medium">{dataset.dataset_id}</p>
                    <p className="text-ink-dim">
                      {dataset.provider}
                      {" · "}
                      {dataset.connector_id}
                      {dataset.version ? ` · ${dataset.version}` : ""}
                    </p>
                    {dataset.modalities.length > 0 && (
                      <p className="mt-1">Modalities: {dataset.modalities.join(", ")}</p>
                    )}
                    {dataset.variables.length > 0 && (
                      <p className="mt-1">Variables: {dataset.variables.join(", ")}</p>
                    )}
                    {dataset.capabilities.length > 0 && (
                      <p className="mt-1">Capabilities: {dataset.capabilities.join(", ")}</p>
                    )}
                    {(start || end) && (
                      <p className="mt-1 text-ink-dim">
                        Declared temporal coverage: {start ?? "open"} – {end ?? "open"}
                      </p>
                    )}
                    {dataset.deprecated && (
                      <p className="mt-1 text-amber-200">Deprecated registration</p>
                    )}
                  </li>
                );
              })}
              {discovery.datasets.length === 0 && (
                <li className="text-[10px] text-ink-dim">
                  The Engine reports no registered datasets.
                </li>
              )}
            </ul>
          </section>

          <section aria-label="Registered Earth modalities">
            <h3 className="text-xs font-medium">
              Earth modalities ({discovery.earth_capabilities.modalities.length})
            </h3>
            <ul className="mt-2 space-y-2">
              {discovery.earth_capabilities.modalities.map((modality) => (
                <li
                  key={modality.modality_id}
                  className="rounded-lg border border-white/10 p-2 text-[10px] leading-4"
                >
                  <p className="font-medium">
                    {modality.label ?? modality.modality_id}
                    {" · "}
                    {modality.status.replaceAll("_", " ")}
                  </p>
                  {modality.description && (
                    <p className="text-ink-dim">{modality.description}</p>
                  )}
                  {modality.dataset_ids.length > 0 && (
                    <p className="mt-1">Datasets: {modality.dataset_ids.join(", ")}</p>
                  )}
                  {modality.variables.length > 0 && (
                    <p className="mt-1">Variables: {modality.variables.join(", ")}</p>
                  )}
                </li>
              ))}
              {discovery.earth_capabilities.modalities.length === 0 && (
                <li className="text-[10px] text-ink-dim">
                  The Engine reports no registered Earth modalities.
                </li>
              )}
            </ul>
          </section>

          <section aria-label="Registered Agent tools">
            <h3 className="text-xs font-medium">
              Agent tools ({discovery.agent_tools.length})
            </h3>
            <p className="mt-1 text-[10px] leading-4 text-ink-dim">
              Read-only contracts from the Engine. Listing a tool does not invoke it.
            </p>
            <ul className="mt-2 space-y-2">
              {discovery.agent_tools.map((tool) => (
                <li
                  key={tool.tool_id}
                  className="rounded-lg border border-white/10 p-2 text-[10px] leading-4"
                >
                  <p className="font-medium">
                    {tool.tool_id}
                    {" · "}
                    {tool.availability}
                  </p>
                  <p className="text-ink-dim">{tool.description}</p>
                  <p className="mt-1 text-ink-dim">
                    {tool.requires_execution_authorization
                      ? "Requires explicit execution consent"
                      : "No execution consent required"}
                    {" · "}
                    Visible to model by default: {tool.model_visible_without_consent ? "yes" : "no"}
                    {" · "}
                    Visible with execution consent: {tool.model_visible_with_execution_consent ? "yes" : "no"}
                  </p>
                  <details className="mt-1">
                    <summary className="cursor-pointer">Input schema</summary>
                    <pre className="mt-1 overflow-x-auto text-ink-dim">
                      {JSON.stringify(tool.input_schema, null, 2)}
                    </pre>
                  </details>
                </li>
              ))}
              {discovery.agent_tools.length === 0 && (
                <li className="text-[10px] text-ink-dim">
                  The Engine reports no registered Agent tools.
                </li>
              )}
            </ul>
          </section>
        </div>
      )}
    </section>
  );
}
