import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  getInvestigationEarthObjects,
  getInvestigationEvents,
  getInvestigationObservations,
  getInvestigationReport,
} from "@/services/api/chat";
import { ApiError } from "@/services/api/client";
import {
  getProject,
  getProjectInvestigation,
  getProjectInvestigationComparison,
  getProjectInvestigationComparisonResult,
} from "@/services/api/projects";
import type {
  EngineEarthObjectGeoJSON,
  EngineInvestigationComparison,
  EngineInvestigationEventPage,
  EngineInvestigationReport,
  EngineObservation,
  Project,
  ProjectInvestigationComparison,
  ProjectInvestigationRef,
} from "@/shared/types";

type InvestigationComparisonData = {
  ref: ProjectInvestigationRef;
  report: EngineInvestigationReport;
  observations: EngineObservation[];
  earthObjects: EngineEarthObjectGeoJSON;
  events: EngineInvestigationEventPage;
};

function errorMessage(reason: unknown): string {
  return reason instanceof ApiError
    ? reason.message
    : "Could not load the saved investigation comparison.";
}

async function loadInvestigation(
  projectId: string,
  ref: ProjectInvestigationRef,
  signal: AbortSignal,
): Promise<InvestigationComparisonData> {
  const verifiedRef = await getProjectInvestigation(
    projectId,
    ref.session_id,
    ref.investigation_id,
    signal,
  );
  const [report, observations, earthObjects, events] = await Promise.all([
    getInvestigationReport(verifiedRef.session_id, verifiedRef.investigation_id, signal),
    getInvestigationObservations(verifiedRef.session_id, verifiedRef.investigation_id, signal),
    getInvestigationEarthObjects(verifiedRef.session_id, verifiedRef.investigation_id, signal),
    getInvestigationEvents(
      verifiedRef.session_id,
      verifiedRef.investigation_id,
      0,
      20,
      signal,
    ),
  ]);
  return { ref: verifiedRef, report, observations, earthObjects, events };
}

export function InvestigationComparisonColumn({
  side,
  data,
}: {
  side: string;
  data: InvestigationComparisonData;
}) {
  const evidenceIds = [
    ...new Set(data.earthObjects.features.flatMap((feature) => feature.properties.evidence_ids)),
  ];
  return (
    <section
      aria-label={`${side} investigation ${data.ref.investigation_id}`}
      className="min-w-0 rounded-xl border border-white/10 bg-black/10 p-4"
    >
      <header className="border-b border-white/10 pb-3">
        <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-ink-dim">
          {side} · Engine investigation
        </p>
        <h2 className="mt-1 break-all text-sm font-semibold text-ink">
          {data.ref.investigation_id}
        </h2>
        <p className="mt-1 break-all text-[10px] text-ink-dim">
          Source session {data.ref.session_id}
        </p>
        <Link
          to={`/s/${encodeURIComponent(data.ref.session_id)}`}
          className="mt-2 inline-block text-xs text-accent hover:text-ink"
        >
          Open source session
        </Link>
      </header>

      <section className="mt-4" aria-label={`${side} Engine report`}>
        <h3 className="text-xs font-semibold text-ink">Engine report</h3>
        <p className="mt-1 break-all font-mono text-[9px] text-ink-dim">
          {data.report.report_id} · SHA-256 {data.report.report_sha256}
        </p>
        <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-ink-dim">
          {data.report.markdown || "No report text is available."}
        </pre>
      </section>

      <section className="mt-4 border-t border-white/10 pt-3" aria-label={`${side} sources`}>
        <h3 className="text-xs font-semibold text-ink">
          Engine sources ({data.observations.length})
        </h3>
        {data.observations.length === 0 ? (
          <p className="mt-2 text-[10px] text-ink-dim">No source observations recorded.</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {data.observations.map((observation) => (
              <li
                key={observation.observation_id}
                className="break-all text-[10px] leading-4 text-ink-dim"
              >
                {observation.observation_id}
                {observation.source_id ? ` · ${observation.source_id}` : ""}
                {observation.observed_at
                  ? ` · ${new Date(observation.observed_at).toLocaleString()}`
                  : ""}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-4 border-t border-white/10 pt-3" aria-label={`${side} evidence`}>
        <h3 className="text-xs font-semibold text-ink">
          Engine evidence references ({evidenceIds.length})
        </h3>
        {evidenceIds.length > 0 && (
          <ul className="mt-2 space-y-1">
            {evidenceIds.map((id) => (
              <li key={id} className="break-all font-mono text-[10px] text-ink-dim">
                {id}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-[10px] text-ink-dim">
          {data.earthObjects.features.length} Engine Earth Object
          {data.earthObjects.features.length === 1 ? "" : "s"}
        </p>
      </section>

      <section className="mt-4 border-t border-white/10 pt-3" aria-label={`${side} journal`}>
        <h3 className="text-xs font-semibold text-ink">
          Engine journal ({data.events.events.length} events shown)
        </h3>
        <p className="mt-1 text-[10px] text-ink-dim">
          {data.events.has_more
            ? "Showing the first 20 ordered events."
            : "Complete ordered journal."}
        </p>
        <ol className="mt-2 space-y-1">
          {data.events.events.map((event) => (
            <li
              key={event.sequence}
              className="break-all text-[10px] leading-4 text-ink-dim"
            >
              {event.sequence} · {event.event_type} · {event.timestamp}
            </li>
          ))}
        </ol>
      </section>
    </section>
  );
}

export function EngineInvestigationComparisonSummary({
  comparison,
}: {
  comparison: EngineInvestigationComparison;
}) {
  return (
    <section
      aria-label="Engine scientific comparison"
      className="mt-4 rounded-xl border border-white/10 bg-black/10 p-4"
    >
      <h2 className="text-sm font-semibold text-ink">Engine-authored scientific comparison</h2>
      <p className="mt-1 break-all font-mono text-[9px] text-ink-dim">
        {comparison.comparison_id} · SHA-256 {comparison.comparison_sha256}
      </p>
      <p className="mt-1 text-[10px] text-ink-dim">
        Schema {comparison.schema_version} · {comparison.temporal_method_id}@
        {comparison.temporal_method_version} · stack builder {comparison.stack_builder_version}
      </p>
      <pre className="mt-3 max-h-[32rem] overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-ink-dim">
        {comparison.markdown}
      </pre>
      <details className="mt-3 text-[10px] text-ink-dim">
        <summary className="cursor-pointer">
          Scientific limitations ({comparison.limitations.length})
        </summary>
        <ul className="mt-2 list-disc space-y-1 pl-4">
          {comparison.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}

export function InvestigationComparisonRoute() {
  const { projectId = "", comparisonId = "" } = useParams();
  return (
    <InvestigationComparisonWorkspace
      key={`${projectId}:${comparisonId}`}
      projectId={projectId}
      comparisonId={comparisonId}
    />
  );
}

function InvestigationComparisonWorkspace({
  projectId,
  comparisonId,
}: {
  projectId: string;
  comparisonId: string;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [comparison, setComparison] = useState<ProjectInvestigationComparison | null>(null);
  const [engineComparison, setEngineComparison] =
    useState<EngineInvestigationComparison | null>(null);
  const [engineComparisonError, setEngineComparisonError] = useState<string | null>(null);
  const [left, setLeft] = useState<InvestigationComparisonData | null>(null);
  const [right, setRight] = useState<InvestigationComparisonData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const [loadedProject, loadedComparison] = await Promise.all([
          getProject(projectId, controller.signal),
          getProjectInvestigationComparison(projectId, comparisonId, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        const engineResultRequest =
          loadedComparison.engine_comparison_sha256 === null
            ? Promise.resolve({
                result: null,
                error: "This saved comparison predates an Engine comparison snapshot.",
              })
            : getProjectInvestigationComparisonResult(
                projectId,
                comparisonId,
                controller.signal,
              )
                .then((result) => ({ result, error: null }))
                .catch((reason: unknown) => ({
                  result: null,
                  error: errorMessage(reason),
                }));
        const [leftData, rightData, engineResult] = await Promise.all([
          loadInvestigation(projectId, loadedComparison.left, controller.signal),
          loadInvestigation(projectId, loadedComparison.right, controller.signal),
          engineResultRequest,
        ]);
        if (controller.signal.aborted) return;
        setProject(loadedProject);
        setComparison(loadedComparison);
        setEngineComparison(engineResult.result);
        setEngineComparisonError(engineResult.error);
        setLeft(leftData);
        setRight(rightData);
      } catch (reason) {
        if (!controller.signal.aborted) setError(errorMessage(reason));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [comparisonId, projectId, reloadVersion]);

  if (loading) {
    return (
      <section
        aria-label="Investigation comparison"
        className="pointer-events-auto absolute inset-4 overflow-y-auto rounded-2xl border border-white/10 bg-surface p-6 shadow-2xl shadow-black/40 backdrop-blur-xl"
      >
        <p className="text-sm text-ink-dim" role="status">
          Loading Engine investigation comparison...
        </p>
      </section>
    );
  }

  if (error || !project || !comparison || !left || !right) {
    return (
      <section
        aria-label="Investigation comparison"
        className="pointer-events-auto absolute inset-4 overflow-y-auto rounded-2xl border border-white/10 bg-surface p-6 shadow-2xl shadow-black/40 backdrop-blur-xl"
      >
        <Link
          to={`/p/${encodeURIComponent(projectId)}`}
          className="text-sm text-accent hover:text-ink"
        >
          Back to Project
        </Link>
        <p className="mt-4 text-sm text-rose-200" role="alert">
          {error ?? "This investigation comparison is not available."}
        </p>
        <button
          type="button"
          onClick={() => {
            setLoading(true);
            setError(null);
            setReloadVersion((version) => version + 1);
          }}
          className="mt-3 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink hover:bg-white/5"
        >
          Retry
        </button>
      </section>
    );
  }

  return (
    <section
      aria-label={`Comparison ${comparison.title}`}
      className="pointer-events-auto absolute inset-4 overflow-y-auto rounded-2xl border border-white/10 bg-surface p-6 shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      <header className="border-b border-white/10 pb-4">
        <Link
          to={`/p/${encodeURIComponent(projectId)}`}
          className="text-xs text-accent hover:text-ink"
        >
          Back to {project.title}
        </Link>
        <p className="mt-3 text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
          Saved Engine comparison · {project.title}
        </p>
        <h1 className="mt-1 break-words text-lg font-semibold text-ink">{comparison.title}</h1>
        <p className="mt-1 text-[10px] text-ink-dim">
          Saved {new Date(comparison.created_at).toLocaleString()}. The Engine creates and
          persists the scientific comparison; the Platform displays its output without
          reinterpretation.
        </p>
      </header>
      {engineComparison ? (
        <EngineInvestigationComparisonSummary comparison={engineComparison} />
      ) : (
        <p className="mt-4 rounded-xl border border-white/10 p-4 text-xs text-ink-dim" role="status">
          {engineComparisonError ??
            "The Engine comparison snapshot is not available for this saved record."}
        </p>
      )}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <InvestigationComparisonColumn side="First" data={left} />
        <InvestigationComparisonColumn side="Second" data={right} />
      </div>
    </section>
  );
}
