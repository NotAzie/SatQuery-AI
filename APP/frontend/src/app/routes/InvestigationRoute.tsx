import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "@/services/api/client";
import {
  addInvestigationHypothesis,
  getInvestigationEarthObjects,
  getInvestigationEvents,
  getInvestigationHypotheses,
  getInvestigationObservations,
  getInvestigationReasoning,
  getInvestigationReproducibility,
  getInvestigationReport,
  transitionInvestigationHypothesis,
} from "@/services/api/chat";
import {
  getProject,
  createProjectView,
  createProjectNote,
  deleteProjectNote,
  deleteProjectView,
  getProjectInvestigation,
  listProjectViews,
  listProjectNotes,
  restoreProjectEarthView,
  updateProjectNote,
} from "@/services/api/projects";
import { imageContentUrl } from "@/services/api/vision";
import { getSession } from "@/services/api/sessions";
import type {
  EngineEarthObjectGeoJSON,
  EngineInvestigationEvent,
  EngineInvestigationEventPage,
  EngineInvestigationReport,
  EngineInvestigationReasoningResponse,
  EngineInvestigationReproducibilityBundle,
  EngineScientificFinding,
  EngineHypothesisLifecycleResponse,
  EngineHypothesisRecord,
  EngineHypothesisTransitionRequest,
  EngineObservation,
  Project,
  ProjectInvestigationRef,
  ProjectNote,
  ProjectEarthView,
  Session,
} from "@/shared/types";

const EVENT_PAGE_SIZE = 50;
const HYPOTHESIS_TRANSITION_STATUSES: readonly EngineHypothesisTransitionRequest["status"][] = [
  "active",
  "under_review",
  "superseded",
  "withdrawn",
  "closed",
];

function isHypothesisTransitionStatus(
  value: string,
): value is EngineHypothesisTransitionRequest["status"] {
  return HYPOTHESIS_TRANSITION_STATUSES.some((status) => status === value);
}

type InvestigationRecords = {
  report: EngineInvestigationReport;
  observations: EngineObservation[];
  earthObjects: EngineEarthObjectGeoJSON;
};

function messageFromError(reason: unknown): string {
  if (reason instanceof ApiError) return reason.message;
  return "Could not load this Engine investigation.";
}

export function InvestigationEarthViewDetails({
  view,
}: {
  view: {
    context: {
      camera: { position: { lat: number; lng: number } };
      imagery: { asset_id: string }[];
      measurement: { kind: string; unit: string; value: number | null } | null;
    };
    source_session_exists: boolean;
    source_session_id: string;
  };
}) {
  return (
    <>
      <p className="mt-1 text-[10px] text-ink-dim">
        Camera {view.context.camera.position.lat.toFixed(4)},{" "}
        {view.context.camera.position.lng.toFixed(4)} · {view.context.imagery.length} image
        reference{view.context.imagery.length === 1 ? "" : "s"}
      </p>
      {view.context.measurement && (
        <p className="mt-1 text-[10px] text-ink-dim">
          Presentation measurement: {view.context.measurement.value ?? "—"}{" "}
          {view.context.measurement.unit} ({view.context.measurement.kind})
        </p>
      )}
      {view.source_session_exists && view.context.imagery.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2">
          {view.context.imagery.map((image) => (
            <li key={image.asset_id} className="max-w-24">
              <img
                src={imageContentUrl(view.source_session_id, image.asset_id, true)}
                alt={`Session image ${image.asset_id}`}
                loading="lazy"
                className="h-16 w-24 rounded-md object-cover"
              />
              <p className="mt-1 truncate text-[9px] text-ink-dim">{image.asset_id}</p>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function InvestigationReasoningDetails({
  response,
}: {
  response: EngineInvestigationReasoningResponse;
}) {
  if (response.status === "not_evaluated" || !response.reasoning) {
    return (
      <p className="mt-3 text-xs text-ink-dim">
        The Engine has not produced a scientific reasoning report for this investigation.
      </p>
    );
  }

  const { reasoning } = response;
  const findings = reasoning.findings;

  return (
    <div className="mt-3 grid gap-3">
      <p className="text-xs text-ink-dim">
        Engine status: <span className="text-ink">{reasoning.status.replaceAll("_", " ")}</span>
        {" · "}
        {reasoning.engine_id} {reasoning.engine_version}
      </p>
      <section aria-label="Scientific conclusion" className="rounded-lg bg-black/20 p-3">
        <h3 className="text-xs font-medium text-ink">
          Conclusion · {reasoning.conclusion.status.replaceAll("_", " ")}
        </h3>
        <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-ink-dim">
          {reasoning.conclusion.explanation}
        </p>
        {reasoning.conclusion.missing_evidence.length > 0 && (
          <p className="mt-2 text-xs text-ink-dim">
            Missing evidence: {reasoning.conclusion.missing_evidence.join("; ")}
          </p>
        )}
      </section>
      <section aria-label="Evidence sufficiency" className="rounded-lg bg-black/20 p-3">
        <h3 className="text-xs font-medium text-ink">
          Method input status · {reasoning.sufficiency.status.replaceAll("_", " ")}
        </h3>
        <p className="mt-1 text-xs leading-5 text-ink-dim">
          {reasoning.sufficiency.explanation}
        </p>
        {reasoning.sufficiency.unmet_preconditions.length > 0 && (
          <p className="mt-2 text-xs text-ink-dim">
            Unmet method inputs: {reasoning.sufficiency.unmet_preconditions.join("; ")}
          </p>
        )}
      </section>
      <section aria-label="Engine findings">
        <h3 className="text-xs font-medium text-ink">Findings ({findings.length})</h3>
        {findings.length === 0 ? (
          <p className="mt-1 text-xs text-ink-dim">The Engine report contains no findings.</p>
        ) : (
          <ul className="mt-2 grid gap-2">
            {findings.map((finding: EngineScientificFinding) => (
              <li key={finding.finding_id} className="rounded-lg border border-white/10 p-3">
                <p className="text-xs font-medium text-ink">{finding.statement}</p>
                <p className="mt-1 text-[10px] text-ink-dim">
                  {finding.evidential_relation} · rule {finding.rule_id} v{finding.rule_version}
                </p>
                <p className="mt-1 text-[10px] text-ink-dim">
                  Observations: {finding.observation_ids.join(", ")}
                </p>
                {finding.limitations.length > 0 && (
                  <p className="mt-1 text-[10px] text-ink-dim">
                    Limitations: {finding.limitations.join("; ")}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      {reasoning.limitations.length > 0 && (
        <p className="text-[10px] leading-4 text-ink-dim">
          Report limitations: {reasoning.limitations.join("; ")}
        </p>
      )}
    </div>
  );
}

export function InvestigationReproducibilityDetails({
  bundle,
}: {
  bundle: EngineInvestigationReproducibilityBundle;
}) {
  function downloadBundle() {
    const blob = new Blob([JSON.stringify(bundle, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const safeInvestigationId = bundle.investigation_id.replace(/[^a-zA-Z0-9._-]/g, "_");
    anchor.href = url;
    anchor.download = `${safeInvestigationId}-reproducibility.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  const hashes = Object.entries(bundle.artifact_hashes).sort(([left], [right]) =>
    left.localeCompare(right),
  );

  return (
    <div className="mt-3 grid gap-3">
      <p className="text-xs text-ink-dim">
        Schema {bundle.schema_version} · exported {new Date(bundle.exported_at).toLocaleString()}
      </p>
      <p className="break-all font-mono text-[10px] text-ink-dim">
        Bundle SHA-256: {bundle.bundle_sha256}
      </p>
      <p className="text-xs text-ink-dim">
        {hashes.length} artifact digest{hashes.length === 1 ? "" : "s"} ·{" "}
        {bundle.missing_artifacts.length} missing artifact
        {bundle.missing_artifacts.length === 1 ? "" : "s"}
      </p>
      {hashes.length > 0 && (
        <ul className="grid gap-1">
          {hashes.map(([name, digest]) => (
            <li
              key={name}
              className="flex flex-wrap justify-between gap-x-3 text-[10px] text-ink-dim"
            >
              <span>{name}</span>
              <code className="break-all">{digest}</code>
            </li>
          ))}
        </ul>
      )}
      {bundle.missing_artifacts.length > 0 && (
        <div className="rounded-lg border border-amber-200/20 bg-amber-200/5 p-3">
          <h3 className="text-xs font-medium text-ink">
            Artifacts not available in this export
          </h3>
          <ul className="mt-1 list-inside list-disc text-xs text-ink-dim">
            {bundle.missing_artifacts.map((artifact) => (
              <li key={artifact}>{artifact}</li>
            ))}
          </ul>
        </div>
      )}
      <button
        type="button"
        onClick={downloadBundle}
        className="justify-self-start rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink hover:bg-white/5"
      >
        Download complete reproducibility bundle (JSON)
      </button>
    </div>
  );
}

function mergeEvents(
  current: EngineInvestigationEvent[],
  incoming: EngineInvestigationEventPage["events"],
): EngineInvestigationEvent[] {
  const sequences = new Set(current.map((event) => event.sequence));
  const merged = [...current];
  for (const event of incoming) {
    if (sequences.has(event.sequence)) continue;
    sequences.add(event.sequence);
    merged.push(event);
  }
  return merged;
}

export function InvestigationRoute() {
  const { projectId = "", sessionId = "", investigationId = "" } = useParams();
  return (
    <InvestigationWorkspace
      key={`${projectId}:${sessionId}:${investigationId}`}
      projectId={projectId}
      sessionId={sessionId}
      investigationId={investigationId}
    />
  );
}

function InvestigationWorkspace({
  projectId,
  sessionId,
  investigationId,
}: {
  projectId: string;
  sessionId: string;
  investigationId: string;
}) {
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [target, setTarget] = useState<ProjectInvestigationRef | null>(null);
  const [sourceSession, setSourceSession] = useState<Session | null>(null);
  const [records, setRecords] = useState<InvestigationRecords | null>(null);
  const [events, setEvents] = useState<EngineInvestigationEvent[]>([]);
  const [hypothesisLifecycle, setHypothesisLifecycle] =
    useState<EngineHypothesisLifecycleResponse | null>(null);
  const [reasoning, setReasoning] = useState<EngineInvestigationReasoningResponse | null>(null);
  const [reproducibility, setReproducibility] =
    useState<EngineInvestigationReproducibilityBundle | null>(null);
  const [notes, setNotes] = useState<ProjectNote[]>([]);
  const [views, setViews] = useState<ProjectEarthView[]>([]);
  const [hasMoreViews, setHasMoreViews] = useState(false);
  const [hasMoreNotes, setHasMoreNotes] = useState(false);
  const [nextSequence, setNextSequence] = useState(0);
  const [hasMoreEvents, setHasMoreEvents] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [loadingNotes, setLoadingNotes] = useState(false);
  const [loadingViews, setLoadingViews] = useState(false);
  const [hypothesisLoading, setHypothesisLoading] = useState(true);
  const [reasoningLoading, setReasoningLoading] = useState(true);
  const [reproducibilityLoading, setReproducibilityLoading] = useState(true);
  const [savingViewBookmarkId, setSavingViewBookmarkId] = useState<string | null>(null);
  const [restoringViewId, setRestoringViewId] = useState<string | null>(null);
  const [notesLoading, setNotesLoading] = useState(true);
  const [viewsLoading, setViewsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [hypothesisError, setHypothesisError] = useState<string | null>(null);
  const [reasoningError, setReasoningError] = useState<string | null>(null);
  const [reproducibilityError, setReproducibilityError] = useState<string | null>(null);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [viewsError, setViewsError] = useState<string | null>(null);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteBody, setNoteBody] = useState("");
  const [hypothesisProposition, setHypothesisProposition] = useState("");
  const [hypothesisSourceText, setHypothesisSourceText] = useState("");
  const [hypothesisActor, setHypothesisActor] = useState("");
  const [hypothesisRationale, setHypothesisRationale] = useState("");
  const [transitionActors, setTransitionActors] = useState<Record<string, string>>({});
  const [transitionRationales, setTransitionRationales] = useState<Record<string, string>>({});
  const [transitionStatuses, setTransitionStatuses] = useState<
    Record<string, EngineHypothesisTransitionRequest["status"]>
  >({});
  const [savingHypothesis, setSavingHypothesis] = useState(false);
  const [transitioningHypothesisId, setTransitioningHypothesisId] = useState<string | null>(null);
  const [editingNote, setEditingNote] = useState<ProjectNote | null>(null);
  const [savingNote, setSavingNote] = useState(false);
  const [deletingNoteId, setDeletingNoteId] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const eventController = useRef<AbortController | null>(null);
  const notesController = useRef<AbortController | null>(null);
  const viewsController = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    eventController.current?.abort();
    notesController.current?.abort();
    viewsController.current?.abort();

    void (async () => {
      try {
        const [loadedProject, loadedTarget] = await Promise.all([
          getProject(projectId, controller.signal),
          getProjectInvestigation(
            projectId,
            sessionId,
            investigationId,
            controller.signal,
          ),
        ]);
        if (controller.signal.aborted) return;
        const [report, observations, earthObjects, eventPage, loadedSession] =
          await Promise.all([
            getInvestigationReport(sessionId, investigationId, controller.signal),
            getInvestigationObservations(sessionId, investigationId, controller.signal),
            getInvestigationEarthObjects(sessionId, investigationId, controller.signal),
            getInvestigationEvents(
              sessionId,
              investigationId,
              0,
              EVENT_PAGE_SIZE,
              controller.signal,
            ),
            getSession(sessionId, controller.signal),
          ]);
        if (controller.signal.aborted) return;
        setProject(loadedProject);
        setTarget(loadedTarget);
        setSourceSession(loadedSession);
        setRecords({ report, observations, earthObjects });
        setEvents(eventPage.events);
        setNextSequence(eventPage.next_sequence);
        setHasMoreEvents(eventPage.has_more);
        void getInvestigationHypotheses(sessionId, investigationId, controller.signal)
          .then((lifecycle) => {
            if (!controller.signal.aborted) {
              setHypothesisLifecycle(lifecycle);
              setHypothesisError(null);
              setHypothesisLoading(false);
            }
          })
          .catch((reason: unknown) => {
            if (!controller.signal.aborted) {
              setHypothesisError(
                reason instanceof ApiError
                  ? reason.message
                  : "Could not load the Engine hypothesis lifecycle.",
              );
              setHypothesisLoading(false);
            }
          });
        void getInvestigationReasoning(sessionId, investigationId, controller.signal)
          .then((loadedReasoning) => {
            if (!controller.signal.aborted) {
              setReasoning(loadedReasoning);
              setReasoningError(null);
              setReasoningLoading(false);
            }
          })
          .catch((reason: unknown) => {
            if (!controller.signal.aborted) {
              setReasoningError(
                reason instanceof ApiError
                  ? reason.message
                  : "Could not load Engine scientific reasoning.",
              );
              setReasoningLoading(false);
            }
          });
        void getInvestigationReproducibility(
          sessionId,
          investigationId,
          controller.signal,
        )
          .then((loadedBundle) => {
            if (!controller.signal.aborted) {
              setReproducibility(loadedBundle);
              setReproducibilityError(null);
              setReproducibilityLoading(false);
            }
          })
          .catch((reason: unknown) => {
            if (!controller.signal.aborted) {
              setReproducibilityError(
                reason instanceof ApiError
                  ? reason.message
                  : "Could not load the Engine reproducibility bundle.",
              );
              setReproducibilityLoading(false);
            }
          });
        void listProjectViews(projectId, controller.signal, EVENT_PAGE_SIZE, 0, {
          investigation_id: investigationId,
          source_session_id: sessionId,
        })
          .then((loadedViews) => {
            if (!controller.signal.aborted) {
              setViews(loadedViews);
              setHasMoreViews(loadedViews.length === EVENT_PAGE_SIZE);
              setViewsLoading(false);
            }
          })
          .catch((reason: unknown) => {
            if (!controller.signal.aborted) {
              setViewsLoading(false);
              setViewsError(
                reason instanceof ApiError
                  ? reason.message
                  : "Could not load Earth views for this investigation.",
              );
            }
          });
        void listProjectNotes(
          projectId,
          controller.signal,
          EVENT_PAGE_SIZE,
          0,
          {
            investigation_id: investigationId,
            investigation_session_id: sessionId,
          },
        )
          .then((loadedNotes) => {
            if (!controller.signal.aborted) {
              setNotes(loadedNotes);
              setHasMoreNotes(loadedNotes.length === EVENT_PAGE_SIZE);
              setNotesLoading(false);
            }
          })
          .catch((reason: unknown) => {
            if (!controller.signal.aborted) {
              setNotesLoading(false);
              setNotesError(
                reason instanceof ApiError
                  ? reason.message
                  : "Could not load notes for this investigation.",
              );
            }
          });
      } catch (reason) {
        if (!controller.signal.aborted) setError(messageFromError(reason));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();

    return () => {
      controller.abort();
      eventController.current?.abort();
      notesController.current?.abort();
      viewsController.current?.abort();
    };
  }, [investigationId, projectId, reloadVersion, sessionId]);

  async function loadMoreEvents() {
    if (!target || loadingEvents) return;
    eventController.current?.abort();
    const controller = new AbortController();
    eventController.current = controller;
    setLoadingEvents(true);
    setEventsError(null);
    try {
      const page = await getInvestigationEvents(
        target.session_id,
        target.investigation_id,
        nextSequence,
        EVENT_PAGE_SIZE,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setEvents((current) => mergeEvents(current, page.events));
      setNextSequence(page.next_sequence);
      setHasMoreEvents(page.has_more);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setEventsError(
          reason instanceof ApiError
            ? reason.message
            : "Could not load more Engine investigation events.",
        );
      }
    } finally {
      if (!controller.signal.aborted) setLoadingEvents(false);
    }
  }

  async function loadMoreViews() {
    if (!target || loadingViews) return;
    viewsController.current?.abort();
    const controller = new AbortController();
    viewsController.current = controller;
    setLoadingViews(true);
    setViewsError(null);
    try {
      const page = await listProjectViews(
        projectId,
        controller.signal,
        EVENT_PAGE_SIZE,
        views.length,
        {
          investigation_id: target.investigation_id,
          source_session_id: target.session_id,
        },
      );
      if (controller.signal.aborted) return;
      setViews((current) => [...current, ...page]);
      setHasMoreViews(page.length === EVENT_PAGE_SIZE);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setViewsError(
          reason instanceof ApiError
            ? reason.message
            : "Could not load more Earth views for this investigation.",
        );
      }
    } finally {
      if (!controller.signal.aborted) setLoadingViews(false);
    }
  }

  async function saveEarthView(bookmarkId: string, title: string) {
    if (
      !target ||
      savingViewBookmarkId ||
      views.some((view) => view.source_bookmark_id === bookmarkId)
    ) {
      return;
    }
    setSavingViewBookmarkId(bookmarkId);
    setViewsError(null);
    try {
      const view = await createProjectView(projectId, {
        title,
        source_session_id: target.session_id,
        source_bookmark_id: bookmarkId,
        investigation_id: target.investigation_id,
      });
      setViews((current) => [view, ...current]);
    } catch (reason) {
      setViewsError(
        reason instanceof ApiError
          ? reason.message
          : "Could not save this Earth view to the investigation.",
      );
    } finally {
      setSavingViewBookmarkId(null);
    }
  }

  async function restoreEarthView(view: ProjectEarthView) {
    setRestoringViewId(view.id);
    setViewsError(null);
    try {
      const restored = await restoreProjectEarthView(view);
      const query = new URLSearchParams({ restoreBookmark: restored.bookmarkId });
      navigate(`/s/${encodeURIComponent(restored.sessionId)}?${query.toString()}`);
    } catch (reason) {
      setViewsError(
        reason instanceof ApiError
          ? reason.message
          : "Could not restore this Earth view in its source session.",
      );
    } finally {
      setRestoringViewId(null);
    }
  }

  async function removeEarthView(viewId: string) {
    setViewsError(null);
    try {
      await deleteProjectView(projectId, viewId);
      setViews((current) => current.filter((view) => view.id !== viewId));
    } catch (reason) {
      setViewsError(
        reason instanceof ApiError
          ? reason.message
          : "Could not remove this Earth view.",
      );
    }
  }

  async function loadMoreNotes() {
    if (!target || loadingNotes) return;
    notesController.current?.abort();
    const controller = new AbortController();
    notesController.current = controller;
    setLoadingNotes(true);
    setNotesError(null);
    try {
      const page = await listProjectNotes(
        projectId,
        controller.signal,
        EVENT_PAGE_SIZE,
        notes.length,
        {
          investigation_id: target.investigation_id,
          investigation_session_id: target.session_id,
        },
      );
      if (controller.signal.aborted) return;
      setNotes((current) => [...current, ...page]);
      setHasMoreNotes(page.length === EVENT_PAGE_SIZE);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setNotesError(
          reason instanceof ApiError
            ? reason.message
            : "Could not load more notes for this investigation.",
        );
      }
    } finally {
      if (!controller.signal.aborted) setLoadingNotes(false);
    }
  }

  async function handleCreateNote(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!target || !noteTitle.trim() || !noteBody.trim()) return;
    setSavingNote(true);
    setNotesError(null);
    try {
      const created = await createProjectNote(projectId, {
        title: noteTitle.trim(),
        body: noteBody.trim(),
        investigation_id: target.investigation_id,
        investigation_session_id: target.session_id,
      });
      setNotes((current) => [created, ...current]);
      setNoteTitle("");
      setNoteBody("");
    } catch (reason) {
      setNotesError(
        reason instanceof ApiError
          ? reason.message
          : "Could not save this investigation note.",
      );
    } finally {
      setSavingNote(false);
    }
  }

  async function handleUpdateNote(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingNote || !editingNote.title.trim() || !editingNote.body.trim()) return;
    setSavingNote(true);
    setNotesError(null);
    try {
      const updated = await updateProjectNote(projectId, editingNote.id, {
        expected_revision: editingNote.revision,
        title: editingNote.title.trim(),
        body: editingNote.body.trim(),
      });
      setNotes((current) => [updated, ...current.filter((note) => note.id !== updated.id)]);
      setEditingNote(null);
    } catch (reason) {
      setNotesError(
        reason instanceof ApiError ? reason.message : "Could not update this investigation note.",
      );
    } finally {
      setSavingNote(false);
    }
  }

  async function handleDeleteNote(noteId: string) {
    if (deletingNoteId) return;
    setDeletingNoteId(noteId);
    setNotesError(null);
    try {
      await deleteProjectNote(projectId, noteId);
      setNotes((current) => current.filter((note) => note.id !== noteId));
      setEditingNote((current) => (current?.id === noteId ? null : current));
    } catch (reason) {
      setNotesError(
        reason instanceof ApiError ? reason.message : "Could not delete this investigation note.",
      );
    } finally {
      setDeletingNoteId(null);
    }
  }

  async function reloadHypothesisLifecycle() {
    setHypothesisLoading(true);
    setHypothesisError(null);
    try {
      const lifecycle = await getInvestigationHypotheses(sessionId, investigationId);
      setHypothesisLifecycle(lifecycle);
    } catch (reason) {
      setHypothesisError(
        reason instanceof ApiError
          ? reason.message
          : "Could not reload the Engine hypothesis lifecycle.",
      );
    } finally {
      setHypothesisLoading(false);
    }
  }

  async function reloadInvestigationReasoning() {
    setReasoningLoading(true);
    setReasoningError(null);
    try {
      const loadedReasoning = await getInvestigationReasoning(sessionId, investigationId);
      setReasoning(loadedReasoning);
    } catch (reason) {
      setReasoningError(
        reason instanceof ApiError
          ? reason.message
          : "Could not reload Engine scientific reasoning.",
      );
    } finally {
      setReasoningLoading(false);
    }
  }

  async function reloadReproducibilityBundle() {
    setReproducibilityLoading(true);
    setReproducibilityError(null);
    try {
      const loadedBundle = await getInvestigationReproducibility(sessionId, investigationId);
      setReproducibility(loadedBundle);
    } catch (reason) {
      setReproducibilityError(
        reason instanceof ApiError
          ? reason.message
          : "Could not reload the Engine reproducibility bundle.",
      );
    } finally {
      setReproducibilityLoading(false);
    }
  }

  async function handleAddHypothesis(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !target ||
      !hypothesisProposition.trim() ||
      !hypothesisSourceText.trim() ||
      !hypothesisActor.trim() ||
      !hypothesisRationale.trim()
    ) {
      return;
    }
    setSavingHypothesis(true);
    setHypothesisError(null);
    try {
      await addInvestigationHypothesis(sessionId, investigationId, {
        hypothesis_id: globalThis.crypto.randomUUID(),
        proposition: hypothesisProposition.trim(),
        source_text: hypothesisSourceText.trim(),
        origin: "explicit",
        competing_group_id: null,
        parent_hypothesis_ids: [],
        composition: null,
        actor: hypothesisActor.trim(),
        rationale: hypothesisRationale.trim(),
      });
      setHypothesisProposition("");
      setHypothesisSourceText("");
      setHypothesisRationale("");
      await reloadHypothesisLifecycle();
    } catch (reason) {
      setHypothesisError(
        reason instanceof ApiError
          ? reason.message
          : "Could not register this hypothesis with the Engine.",
      );
    } finally {
      setSavingHypothesis(false);
    }
  }

  async function handleHypothesisTransition(
    hypothesis: EngineHypothesisRecord,
    status: EngineHypothesisTransitionRequest["status"],
  ) {
    const actor = transitionActors[hypothesis.hypothesis_id]?.trim() ?? "";
    const rationale = transitionRationales[hypothesis.hypothesis_id]?.trim() ?? "";
    if (!actor || !rationale || transitioningHypothesisId) return;
    setTransitioningHypothesisId(hypothesis.hypothesis_id);
    setHypothesisError(null);
    try {
      await transitionInvestigationHypothesis(
        sessionId,
        investigationId,
        hypothesis.hypothesis_id,
        {
          expected_version: hypothesis.version,
          status,
          actor,
          rationale,
        },
      );
      setTransitionRationales((current) => ({ ...current, [hypothesis.hypothesis_id]: "" }));
      await reloadHypothesisLifecycle();
    } catch (reason) {
      setHypothesisError(
        reason instanceof ApiError
          ? reason.message
          : "The Engine could not apply this hypothesis transition.",
      );
    } finally {
      setTransitioningHypothesisId(null);
    }
  }

  if (loading) {
    return (
      <section
        aria-label="Investigation workspace"
        className="pointer-events-auto absolute inset-4 overflow-y-auto rounded-2xl border border-white/10 bg-surface p-6 shadow-2xl shadow-black/40 backdrop-blur-xl"
      >
        <p className="text-sm text-ink-dim" role="status">
          Loading Engine investigation...
        </p>
      </section>
    );
  }

  if (error || !project || !target || !records || !sourceSession) {
    return (
      <section
        aria-label="Investigation workspace"
        className="pointer-events-auto absolute inset-4 overflow-y-auto rounded-2xl border border-white/10 bg-surface p-6 shadow-2xl shadow-black/40 backdrop-blur-xl"
      >
        <Link
          to={`/p/${encodeURIComponent(projectId)}`}
          className="text-sm text-accent hover:text-ink"
        >
          Back to Project
        </Link>
        <p className="mt-4 text-sm text-rose-200" role="alert">
          {error ?? "This investigation is not available in the selected Project."}
        </p>
        <button
          type="button"
          onClick={() => {
            setLoading(true);
            setError(null);
            setNotesError(null);
            setEventsError(null);
            setHypothesisError(null);
            setHypothesisLoading(true);
            setNotesLoading(true);
            setViewsLoading(true);
            setViewsError(null);
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
      aria-label={`Investigation ${target.investigation_id}`}
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
          Engine investigation · {project.title}
        </p>
        <h1 className="mt-1 break-all text-lg font-semibold text-ink">
          {target.investigation_id}
        </h1>
        <p className="mt-1 text-xs text-ink-dim">
          From {target.session_id}
        </p>
        <Link
          to={`/s/${encodeURIComponent(target.session_id)}`}
          className="mt-3 inline-block rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink hover:bg-white/5"
        >
          Open source session and Earth workspace
        </Link>
      </header>

      <section aria-labelledby="investigation-reasoning-heading" className="mt-5">
        <h2 id="investigation-reasoning-heading" className="text-sm font-semibold text-ink">
          Engine scientific reasoning
        </h2>
        <p className="mt-1 text-[10px] leading-4 text-ink-dim">
          Findings and limitations are reported by the Engine. Method input sufficiency does not
          establish scientific evidence sufficiency.
        </p>
        {reasoningError && (
          <div className="mt-2 text-xs text-rose-200" role="alert">
            <p>{reasoningError}</p>
            <button
              type="button"
              onClick={() => void reloadInvestigationReasoning()}
              className="mt-1 underline underline-offset-2"
            >
              Reload scientific reasoning
            </button>
          </div>
        )}
        {reasoningLoading ? (
          <p className="mt-3 text-xs text-ink-dim" role="status">
            Loading Engine scientific reasoning...
          </p>
        ) : reasoning ? (
          <InvestigationReasoningDetails response={reasoning} />
        ) : null}
      </section>

      <section aria-labelledby="investigation-reproducibility-heading" className="mt-5">
        <h2
          id="investigation-reproducibility-heading"
          className="text-sm font-semibold text-ink"
        >
          Reproducibility and provenance
        </h2>
        <p className="mt-1 text-[10px] leading-4 text-ink-dim">
          This Engine-generated export records available investigation artifacts and their
          digests. Missing artifacts are shown explicitly; a digest does not certify scientific
          validity.
        </p>
        {reproducibilityError && (
          <div className="mt-2 text-xs text-rose-200" role="alert">
            <p>{reproducibilityError}</p>
            <button
              type="button"
              onClick={() => void reloadReproducibilityBundle()}
              className="mt-1 underline underline-offset-2"
            >
              Reload reproducibility bundle
            </button>
          </div>
        )}
        {reproducibilityLoading ? (
          <p className="mt-3 text-xs text-ink-dim" role="status">
            Loading Engine reproducibility bundle...
          </p>
        ) : reproducibility ? (
          <InvestigationReproducibilityDetails bundle={reproducibility} />
        ) : null}
      </section>

      <section aria-labelledby="investigation-hypotheses-heading" className="mt-5">
        <h2
          id="investigation-hypotheses-heading"
          className="text-sm font-semibold text-ink"
        >
          Engine hypothesis lifecycle
        </h2>
        <p className="mt-1 text-[10px] leading-4 text-ink-dim">
          Hypotheses, versions, and status transitions are stored by the Engine. Record only
          explicit propositions; the Platform does not evaluate whether they are true.
        </p>
        {hypothesisError && (
          <div className="mt-2 text-xs text-rose-200" role="alert">
            <p>{hypothesisError}</p>
            <button
              type="button"
              onClick={() => void reloadHypothesisLifecycle()}
              className="mt-1 underline underline-offset-2"
            >
              Reload hypothesis lifecycle
            </button>
          </div>
        )}
        {hypothesisLoading ? (
          <p className="mt-3 text-xs text-ink-dim" role="status">
            Loading Engine hypotheses...
          </p>
        ) : hypothesisLifecycle?.status === "unavailable" ? (
          <p className="mt-3 text-xs text-rose-200" role="alert">
            Engine hypothesis history is unavailable
            {hypothesisLifecycle.restoration_error
              ? `: ${hypothesisLifecycle.restoration_error}`
              : "."}
          </p>
        ) : hypothesisLifecycle ? (
          <>
            {!project.archived && (
              <form
                onSubmit={(event) => void handleAddHypothesis(event)}
                className="mt-3 grid gap-2 rounded-lg bg-black/20 p-3"
              >
                <h3 className="text-xs font-medium text-ink">Register an explicit hypothesis</h3>
                <input
                  aria-label="Hypothesis proposition"
                  maxLength={4000}
                  placeholder="Proposition to investigate"
                  value={hypothesisProposition}
                  onChange={(event) => setHypothesisProposition(event.target.value)}
                  className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink outline-none focus:border-accent/60"
                />
                <textarea
                  aria-label="Hypothesis source text"
                  maxLength={4000}
                  rows={2}
                  placeholder="Source statement or context"
                  value={hypothesisSourceText}
                  onChange={(event) => setHypothesisSourceText(event.target.value)}
                  className="resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink outline-none focus:border-accent/60"
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  <input
                    aria-label="Hypothesis actor"
                    maxLength={160}
                    placeholder="Researcher / actor"
                    value={hypothesisActor}
                    onChange={(event) => setHypothesisActor(event.target.value)}
                    className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink outline-none focus:border-accent/60"
                  />
                  <input
                    aria-label="Hypothesis rationale"
                    maxLength={4000}
                    placeholder="Why record this hypothesis?"
                    value={hypothesisRationale}
                    onChange={(event) => setHypothesisRationale(event.target.value)}
                    className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink outline-none focus:border-accent/60"
                  />
                </div>
                <button
                  type="submit"
                  disabled={
                    savingHypothesis ||
                    !hypothesisProposition.trim() ||
                    !hypothesisSourceText.trim() ||
                    !hypothesisActor.trim() ||
                    !hypothesisRationale.trim()
                  }
                  className="justify-self-start rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink disabled:opacity-50"
                >
                  {savingHypothesis ? "Registering with Engine..." : "Register hypothesis"}
                </button>
              </form>
            )}
            {(hypothesisLifecycle.graph?.hypotheses.length ?? 0) === 0 ? (
              <p className="mt-3 text-xs text-ink-dim">
                No Engine hypotheses have been registered for this investigation.
              </p>
            ) : (
              <ul className="mt-3 grid gap-2">
                {hypothesisLifecycle.graph?.hypotheses.map((hypothesis) => {
                  const hypothesisEvents = hypothesisLifecycle.events.filter(
                    (event) => event.hypothesis_id === hypothesis.hypothesis_id,
                  );
                  return (
                    <li
                      key={hypothesis.hypothesis_id}
                      className="rounded-lg border border-white/10 bg-black/20 p-3"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <h3 className="break-words text-xs font-medium text-ink">
                            {hypothesis.proposition}
                          </h3>
                          <p className="mt-1 break-all text-[10px] text-ink-dim">
                            {hypothesis.hypothesis_id} · {hypothesis.origin} ·{" "}
                            {hypothesis.lifecycle} · version {hypothesis.version}
                          </p>
                        </div>
                      </div>
                      <p className="mt-2 whitespace-pre-wrap break-words text-[10px] leading-4 text-ink-dim">
                        Source: {hypothesis.source_text}
                      </p>
                      {hypothesis.parent_hypothesis_ids.length > 0 && (
                        <p className="mt-1 break-all text-[10px] text-ink-dim">
                          Parent hypotheses: {hypothesis.parent_hypothesis_ids.join(", ")}
                          {hypothesis.composition ? ` · ${hypothesis.composition}` : ""}
                        </p>
                      )}
                      {!project.archived && hypothesis.lifecycle !== "closed" && (
                        <form
                          onSubmit={(event) => {
                            event.preventDefault();
                            void handleHypothesisTransition(
                              hypothesis,
                              transitionStatuses[hypothesis.hypothesis_id] ?? "active",
                            );
                          }}
                          className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]"
                        >
                          <select
                            aria-label={`Next lifecycle state for ${hypothesis.hypothesis_id}`}
                            value={transitionStatuses[hypothesis.hypothesis_id] ?? "active"}
                            onChange={(event) => {
                              const { value } = event.target;
                              if (!isHypothesisTransitionStatus(value)) return;
                              setTransitionStatuses((current) => ({
                                ...current,
                                [hypothesis.hypothesis_id]: value,
                              }));
                            }}
                            className="rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[10px] text-ink"
                          >
                            <option value="active">Active</option>
                            <option value="under_review">Under review</option>
                            <option value="superseded">Superseded</option>
                            <option value="withdrawn">Withdrawn</option>
                            <option value="closed">Closed</option>
                          </select>
                          <input
                            aria-label={`Transition actor for ${hypothesis.hypothesis_id}`}
                            maxLength={160}
                            placeholder="Actor"
                            value={transitionActors[hypothesis.hypothesis_id] ?? ""}
                            onChange={(event) =>
                              setTransitionActors((current) => ({
                                ...current,
                                [hypothesis.hypothesis_id]: event.target.value,
                              }))
                            }
                            className="rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[10px] text-ink"
                          />
                          <input
                            aria-label={`Transition rationale for ${hypothesis.hypothesis_id}`}
                            maxLength={4000}
                            placeholder="Rationale"
                            value={transitionRationales[hypothesis.hypothesis_id] ?? ""}
                            onChange={(event) =>
                              setTransitionRationales((current) => ({
                                ...current,
                                [hypothesis.hypothesis_id]: event.target.value,
                              }))
                            }
                            className="rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[10px] text-ink"
                          />
                          <button
                            type="submit"
                            disabled={
                              transitioningHypothesisId !== null ||
                              !transitionActors[hypothesis.hypothesis_id]?.trim() ||
                              !transitionRationales[hypothesis.hypothesis_id]?.trim()
                            }
                            className="rounded-lg border border-white/10 px-2 py-1.5 text-[10px] text-ink disabled:opacity-50"
                          >
                            {transitioningHypothesisId === hypothesis.hypothesis_id
                              ? "Saving..."
                              : "Transition"}
                          </button>
                        </form>
                      )}
                      {hypothesisEvents.length > 0 && (
                        <ol className="mt-3 space-y-1 border-t border-white/10 pt-2">
                          {hypothesisEvents.map((event) => (
                            <li
                              key={event.event_id}
                              className="text-[10px] leading-4 text-ink-dim"
                            >
                              {event.from_status ?? "created"} → {event.to_status} ·{" "}
                              {event.actor} · {event.rationale} ·{" "}
                              {new Date(event.occurred_at).toLocaleString()}
                            </li>
                          ))}
                        </ol>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        ) : (
          <p className="mt-3 text-xs text-ink-dim" role="status">
            Engine hypothesis lifecycle has not loaded.
          </p>
        )}
      </section>

      <section aria-labelledby="investigation-notes-heading" className="mt-5">
        <h2
          id="investigation-notes-heading"
          className="text-sm font-semibold text-ink"
        >
          Investigation notes
        </h2>
        <p className="mt-1 text-[10px] leading-4 text-ink-dim">
          Platform notes are workspace annotations, not Engine evidence or scientific findings.
        </p>
        {notesError && (
          <p className="mt-2 text-xs text-rose-200" role="alert">
            {notesError}
          </p>
        )}
        {!project.archived && (
          <form onSubmit={(event) => void handleCreateNote(event)} className="mt-3 grid gap-2 md:grid-cols-[minmax(12rem,1fr)_2fr_auto]">
            <input
              aria-label="Investigation note title"
              maxLength={160}
              placeholder="Note title"
              value={noteTitle}
              onChange={(event) => setNoteTitle(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-ink outline-none focus:border-accent/60"
            />
            <textarea
              aria-label="Investigation note"
              maxLength={20_000}
              rows={2}
              placeholder="Record a question, interpretation, or next step..."
              value={noteBody}
              onChange={(event) => setNoteBody(event.target.value)}
              className="resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-ink outline-none focus:border-accent/60"
            />
            <button
              type="submit"
              disabled={savingNote || !noteTitle.trim() || !noteBody.trim()}
              className="self-start rounded-lg border border-white/10 px-3 py-2 text-xs text-ink disabled:opacity-50"
            >
              {savingNote ? "Saving..." : "Add note"}
            </button>
          </form>
        )}
        {notesLoading ? (
          <p className="mt-3 text-xs text-ink-dim" role="status">
            Loading investigation notes...
          </p>
        ) : notes.length === 0 ? (
          <p className="mt-3 text-xs text-ink-dim">
            No notes are attached to this investigation.
          </p>
        ) : (
          <ul className="mt-3 grid gap-2 md:grid-cols-2">
            {notes.map((note) => (
              <li key={note.id} className="rounded-lg bg-black/20 p-3">
                {editingNote?.id === note.id ? (
                  <form onSubmit={(event) => void handleUpdateNote(event)} className="space-y-2">
                    <input
                      aria-label="Edit investigation note title"
                      maxLength={160}
                      value={editingNote.title}
                      onChange={(event) =>
                        setEditingNote({ ...editingNote, title: event.target.value })
                      }
                      className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-sm text-ink outline-none"
                    />
                    <textarea
                      aria-label="Edit investigation note content"
                      maxLength={20_000}
                      rows={4}
                      value={editingNote.body}
                      onChange={(event) =>
                        setEditingNote({ ...editingNote, body: event.target.value })
                      }
                      className="w-full resize-y rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-sm text-ink outline-none"
                    />
                    <div className="flex gap-2">
                      <button
                        type="submit"
                        disabled={
                          savingNote || !editingNote.title.trim() || !editingNote.body.trim()
                        }
                        className="text-xs text-accent disabled:opacity-50"
                      >
                        {savingNote ? "Saving..." : "Save"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingNote(null)}
                        disabled={savingNote}
                        className="text-xs text-ink-dim disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="break-words text-xs font-medium text-ink">{note.title}</h3>
                      {!project.archived && (
                        <div className="flex shrink-0 gap-2">
                          <button
                            type="button"
                            onClick={() => setEditingNote(note)}
                            disabled={deletingNoteId !== null}
                            className="text-xs text-accent hover:text-ink disabled:opacity-50"
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleDeleteNote(note.id)}
                            disabled={deletingNoteId !== null}
                            className="text-xs text-rose-200 hover:text-rose-100 disabled:opacity-50"
                          >
                            {deletingNoteId === note.id ? "Deleting..." : "Delete"}
                          </button>
                        </div>
                      )}
                    </div>
                    <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-ink-dim">
                      {note.body}
                    </p>
                    <time
                      dateTime={note.updated_at}
                      className="mt-2 block text-[10px] text-ink-dim"
                    >
                      Updated {new Date(note.updated_at).toLocaleString()}
                    </time>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        {hasMoreNotes && (
          <button
            type="button"
            onClick={() => void loadMoreNotes()}
            disabled={loadingNotes}
            className="mt-2 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
          >
            {loadingNotes ? "Loading..." : "Load more notes"}
          </button>
        )}
      </section>

      <section aria-labelledby="investigation-views-heading" className="mt-5">
        <h2
          id="investigation-views-heading"
          className="text-sm font-semibold text-ink"
        >
          Investigation maps and saved Earth views
        </h2>
        <p className="mt-1 text-[10px] leading-4 text-ink-dim">
          Save an existing source-session bookmark to preserve its EarthContext with this
          investigation. This is presentation context, not scientific evidence.
        </p>
        {viewsError && (
          <div className="mt-2 text-xs text-rose-200" role="alert">
            <p>{viewsError}</p>
            <button
              type="button"
              onClick={() => {
                setViewsLoading(true);
                setViewsError(null);
                setReloadVersion((version) => version + 1);
              }}
              className="mt-1 underline underline-offset-2"
            >
              Retry
            </button>
          </div>
        )}
        {viewsLoading ? (
          <p className="mt-3 text-xs text-ink-dim" role="status">
            Loading investigation Earth views...
          </p>
        ) : sourceSession.earth_workspace.bookmarks.length === 0 ? (
          <p className="mt-3 text-xs text-ink-dim">
            No saved Earth bookmarks exist in the source session yet. Create one in the source
            workspace, then return here to attach it to this investigation.
          </p>
        ) : (
          <ul className="mt-3 grid gap-2 md:grid-cols-2">
            {sourceSession.earth_workspace.bookmarks.map((bookmark) => {
              const saved = views.some(
                (view) => view.source_bookmark_id === bookmark.id,
              );
              return (
                <li
                  key={bookmark.id}
                  className="flex items-center justify-between gap-3 rounded-lg bg-black/20 p-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-ink">{bookmark.name}</p>
                    <p className="mt-1 truncate text-[10px] text-ink-dim">
                      Bookmark {bookmark.id}
                    </p>
                  </div>
                  {!project.archived && (
                    <button
                      type="button"
                      disabled={saved || savingViewBookmarkId !== null || Boolean(viewsError)}
                      onClick={() => void saveEarthView(bookmark.id, bookmark.name)}
                      className="shrink-0 rounded-lg border border-white/10 px-2 py-1 text-[10px] text-ink disabled:opacity-50"
                    >
                      {saved
                        ? "Saved"
                        : savingViewBookmarkId === bookmark.id
                          ? "Saving..."
                          : "Attach to investigation"}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {views.length > 0 && (
          <ul className="mt-3 grid gap-2 md:grid-cols-2">
            {views.map((view) => (
              <li key={view.id} className="rounded-lg border border-white/10 p-3">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="break-words text-xs font-medium text-ink">{view.title}</h3>
                  {!project.archived && (
                    <button
                      type="button"
                      onClick={() => void removeEarthView(view.id)}
                      className="shrink-0 text-[10px] text-rose-200 hover:text-rose-100"
                    >
                      Remove
                    </button>
                  )}
                </div>
                <p className="mt-1 break-all text-[10px] text-ink-dim">
                  Source bookmark {view.source_bookmark_id}
                </p>
                <InvestigationEarthViewDetails view={view} />
                <time
                  dateTime={view.created_at}
                  className="mt-1 block text-[10px] text-ink-dim"
                >
                  Saved {new Date(view.created_at).toLocaleString()}
                </time>
                {view.source_session_exists ? (
                  <button
                    type="button"
                    disabled={restoringViewId === view.id}
                    onClick={() => void restoreEarthView(view)}
                    className="mt-2 text-xs text-accent hover:text-ink disabled:opacity-50"
                  >
                    {restoringViewId === view.id ? "Restoring..." : "Restore Earth view"}
                  </button>
                ) : (
                  <p className="mt-2 text-[10px] text-ink-dim">
                    The source session is no longer available; this snapshot remains readable.
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
        {hasMoreViews && (
          <button
            type="button"
            onClick={() => void loadMoreViews()}
            disabled={loadingViews}
            className="mt-2 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
          >
            {loadingViews ? "Loading..." : "Load more Earth views"}
          </button>
        )}
      </section>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <section aria-labelledby="investigation-report-heading">
          <h2
            id="investigation-report-heading"
            className="text-sm font-semibold text-ink"
          >
            Engine report
          </h2>
          <div className="mt-2 rounded-lg bg-black/20 p-4">
            <p className="text-xs text-ink-dim">Report {records.report.report_id}</p>
            <p className="mt-1 break-all font-mono text-[10px] text-ink-dim">
              SHA-256 {records.report.report_sha256}
            </p>
            <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-xs leading-5 text-ink">
              {records.report.markdown}
            </pre>
          </div>
        </section>

        <section aria-labelledby="investigation-evidence-heading">
          <h2
            id="investigation-evidence-heading"
            className="text-sm font-semibold text-ink"
          >
            Engine evidence references ({records.earthObjects.features.length})
          </h2>
          {records.earthObjects.features.length === 0 ? (
            <p className="mt-2 text-xs text-ink-dim">
              The Engine returned no mappable Earth Objects for this investigation.
            </p>
          ) : (
            <ul className="mt-2 space-y-2">
              {records.earthObjects.features.map((feature) => (
                <li key={feature.id} className="rounded-lg bg-black/20 p-3">
                  <p className="break-all text-xs font-medium text-ink">{feature.id}</p>
                  <p className="mt-1 break-all text-[10px] text-ink-dim">
                    Evidence IDs: {feature.properties.evidence_ids.join(", ") || "none"}
                  </p>
                  <p className="mt-1 break-all text-[10px] text-ink-dim">
                    Source observation IDs:{" "}
                    {feature.properties.source_observation_ids.join(", ") || "none"}
                  </p>
                </li>
              ))}
            </ul>
          )}
          {records.earthObjects["satquery:omitted_objects"].length > 0 && (
            <p className="mt-2 text-[10px] text-ink-dim">
              {records.earthObjects["satquery:omitted_objects"].length} Engine objects were
              omitted from the map export under its declared geometry policy.
            </p>
          )}
        </section>

        <section aria-labelledby="investigation-sources-heading">
          <h2
            id="investigation-sources-heading"
            className="text-sm font-semibold text-ink"
          >
            Engine source observations ({records.observations.length})
          </h2>
          {records.observations.length === 0 ? (
            <p className="mt-2 text-xs text-ink-dim">
              The Engine returned no source observations for this investigation.
            </p>
          ) : (
            <ul className="mt-2 space-y-2">
              {records.observations.map((observation) => (
                <li
                  key={observation.observation_id}
                  className="rounded-lg bg-black/20 p-3"
                >
                  <p className="break-all text-xs font-medium text-ink">
                    {observation.observation_id}
                  </p>
                  <p className="mt-1 break-all text-[10px] text-ink-dim">
                    {observation.dataset
                      ? `${observation.dataset.connector_id} · ${observation.dataset.dataset_id}`
                      : observation.source_id || "Source not specified"}
                  </p>
                  {observation.observed_at && (
                    <time
                      dateTime={observation.observed_at}
                      className="mt-1 block text-[10px] text-ink-dim"
                    >
                      {new Date(observation.observed_at).toLocaleString()}
                    </time>
                  )}
                  <details className="mt-2">
                    <summary className="cursor-pointer text-[10px] text-ink-dim">
                      Engine provenance and metadata
                    </summary>
                    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[10px] text-ink-dim">
                      {JSON.stringify(
                        {
                          provenance: observation.provenance,
                          provider_metadata: observation.provider_metadata,
                          source_document: observation.source_document,
                          assets: observation.assets,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="investigation-history-heading">
          <h2
            id="investigation-history-heading"
            className="text-sm font-semibold text-ink"
          >
            Engine execution history
          </h2>
          <p className="mt-1 text-[10px] leading-4 text-ink-dim">
            Events, sequence numbers, and hashes are returned by the Engine. The Platform displays
            them without interpreting event payloads or recalculating scientific state.
          </p>
          {events.length === 0 ? (
            <p className="mt-2 text-xs text-ink-dim">
              The Engine returned no journal events for this investigation.
            </p>
          ) : (
            <ol className="mt-2 space-y-2">
              {events.map((event) => (
                <li
                  key={`${target.session_id}:${target.investigation_id}:${event.sequence}`}
                  className="rounded-lg bg-black/20 p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="break-all text-xs font-medium text-ink">
                      #{event.sequence} · {event.event_type}
                    </p>
                    <time
                      dateTime={event.timestamp}
                      className="shrink-0 text-[9px] text-ink-dim"
                    >
                      {new Date(event.timestamp).toLocaleString()}
                    </time>
                  </div>
                  <p className="mt-1 break-all text-[10px] text-ink-dim">
                    Plan {event.plan_id} · SHA-256 {event.event_sha256}
                  </p>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-[10px] text-ink-dim">
                      Engine event payload and chain reference
                    </summary>
                    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[10px] text-ink-dim">
                      {JSON.stringify(
                        {
                          previous_event_sha256: event.previous_event_sha256,
                          payload: event.payload,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </li>
              ))}
            </ol>
          )}
          {eventsError && (
            <p className="mt-2 text-xs text-rose-200" role="alert">
              {eventsError}
            </p>
          )}
          {hasMoreEvents && (
            <button
              type="button"
              onClick={() => void loadMoreEvents()}
              disabled={loadingEvents}
              className="mt-2 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
            >
              {loadingEvents ? "Loading..." : "Load more Engine events"}
            </button>
          )}
        </section>
      </div>
    </section>
  );
}
