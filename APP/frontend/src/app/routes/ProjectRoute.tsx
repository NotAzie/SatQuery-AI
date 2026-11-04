import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "@/services/api/client";
import {
  getProject,
  createProjectNote,
  createProjectInvestigationComparison,
  createProjectView,
  deleteProjectNote,
  deleteProjectInvestigationComparison,
  deleteProjectView,
  listProjectInvestigations,
  listProjectInvestigationComparisons,
  listProjectActivity,
  listProjectNotes,
  linkProjectSession,
  linkProjectMonitoringSchedule,
  listProjectMonitoringLinks,
  listProjectSessions,
  listProjectWorkPage,
  listProjectViews,
  listUnlinkedSessions,
  restoreProjectEarthView,
  searchProject,
  updateProjectNote,
  updateProject,
  unlinkProjectMonitoringSchedule,
} from "@/services/api/projects";
import { listMonitoringRuns, listMonitoringSchedules } from "@/services/api/monitoring";
import { imageContentUrl } from "@/services/api/vision";
import { InvestigationRelationships } from "@/features/projects/InvestigationRelationships";
import { InvestigationCollections } from "@/features/projects/InvestigationCollections";
import { InvestigationTemplates } from "@/features/projects/InvestigationTemplates";
import type {
  Project,
  ProjectActivity,
  ProjectEarthView,
  ProjectInvestigationComparison,
  ProjectInvestigationRef,
  ProjectNote,
  ProjectMonitoringLink,
  ProjectSessionLink,
  ProjectSearchHit,
  Session,
  EngineMonitoringRun,
  EngineMonitoringSchedule,
} from "@/shared/types";
import { useSessionStore } from "@/state/sessionStore";

const PROJECT_PAGE_SIZE = 50;

function getProjectSearchHref(projectId: string, hit: ProjectSearchHit): string {
  if (hit.kind === "project") return "#project-header";
  if (hit.kind === "comparison") {
    return `/p/${encodeURIComponent(projectId)}/comparisons/${encodeURIComponent(hit.id)}`;
  }
  if (hit.kind === "investigation_template") return "#project-investigation-templates";
  if (hit.kind === "investigation_collection") return "#project-investigation-collections";
  if (hit.kind === "session" && hit.session_id) {
    return `/s/${encodeURIComponent(hit.session_id)}`;
  }
  if (hit.session_id && hit.investigation_id) {
    return `/p/${encodeURIComponent(projectId)}/investigations/${encodeURIComponent(hit.session_id)}/${encodeURIComponent(hit.investigation_id)}`;
  }
  if (hit.session_id) return `/s/${encodeURIComponent(hit.session_id)}`;
  if (hit.kind === "relationship") return "#project-investigation-relationships";
  return hit.kind === "note" ? "#project-notes" : "#project-earth-views";
}

const PROJECT_ACTIVITY_LABELS: Record<ProjectActivity["action"], string> = {
  "project.created": "Project created",
  "project.updated": "Project updated",
  "project.archived": "Project archived",
  "project.unarchived": "Project reopened",
  "session.linked": "Session added",
  "note.created": "Note created",
  "note.updated": "Note edited",
  "note.deleted": "Note deleted",
  "earth_view.saved": "Earth view saved",
  "earth_view.deleted": "Earth view deleted",
  "investigation_comparison.created": "Investigation comparison saved",
  "investigation_comparison.deleted": "Investigation comparison removed",
  "investigation_relationship.created": "Investigation relationship recorded",
  "investigation_relationship.deleted": "Investigation relationship removed",
  "investigation_collection.created": "Investigation collection created",
  "investigation_collection.updated": "Investigation collection updated",
  "investigation_collection.deleted": "Investigation collection deleted",
  "investigation_collection.member_added": "Investigation added to a collection",
  "investigation_collection.member_removed": "Investigation removed from a collection",
  "investigation_template.created": "Investigation template saved",
  "investigation_template.updated": "Investigation template revised",
  "investigation_template.deleted": "Investigation template removed",
  "investigation_template.applied": "Investigation template applied",
  "investigation_template_run.updated": "Template workflow progress updated",
  "monitoring.linked": "Monitoring schedule linked",
  "monitoring.unlinked": "Monitoring schedule unlinked",
};

export function ProjectRoute() {
  const { projectId = "" } = useParams();
  return <ProjectWorkspace key={projectId} projectId={projectId} />;
}

function ProjectWorkspace({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [sessions, setSessions] = useState<ProjectSessionLink[]>([]);
  const [investigations, setInvestigations] = useState<ProjectInvestigationRef[]>([]);
  const [comparisons, setComparisons] = useState<ProjectInvestigationComparison[]>([]);
  const [activity, setActivity] = useState<ProjectActivity[]>([]);
  const [activityInvestigationKey, setActivityInvestigationKey] = useState("");
  const [monitoringLinks, setMonitoringLinks] = useState<ProjectMonitoringLink[]>([]);
  const [monitoringSchedules, setMonitoringSchedules] = useState<EngineMonitoringSchedule[]>([]);
  const [monitoringRuns, setMonitoringRuns] = useState<
    Record<string, EngineMonitoringRun[]>
  >({});
  const [notes, setNotes] = useState<ProjectNote[]>([]);
  const [views, setViews] = useState<ProjectEarthView[]>([]);
  const [unlinkedSessions, setUnlinkedSessions] = useState<Session[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [monitoringError, setMonitoringError] = useState<string | null>(null);
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [comparisonsLoading, setComparisonsLoading] = useState(true);
  const [creatingComparison, setCreatingComparison] = useState(false);
  const [comparisonTitle, setComparisonTitle] = useState("");
  const [leftInvestigationIndex, setLeftInvestigationIndex] = useState("");
  const [rightInvestigationIndex, setRightInvestigationIndex] = useState("");
  const [linkingSessionId, setLinkingSessionId] = useState<string | null>(null);
  const [hasMoreSessions, setHasMoreSessions] = useState(false);
  const [hasMoreActivity, setHasMoreActivity] = useState(false);
  const [hasMoreComparisons, setHasMoreComparisons] = useState(false);
  const [activityLoading, setActivityLoading] = useState(false);
  const [hasMoreNotes, setHasMoreNotes] = useState(false);
  const [hasMoreViews, setHasMoreViews] = useState(false);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteBody, setNoteBody] = useState("");
  const [editingNote, setEditingNote] = useState<ProjectNote | null>(null);
  const [savingNote, setSavingNote] = useState(false);
  const [savingViewKey, setSavingViewKey] = useState<string | null>(null);
  const [restoringViewId, setRestoringViewId] = useState<string | null>(null);
  const [monitoringScheduleId, setMonitoringScheduleId] = useState("");
  const [linkingMonitoring, setLinkingMonitoring] = useState(false);
  const [loadingMonitoringRuns, setLoadingMonitoringRuns] = useState<string | null>(null);
  const [monitoringSchedulesLoading, setMonitoringSchedulesLoading] = useState(true);
  const [projectSearchQuery, setProjectSearchQuery] = useState("");
  const [searchedProjectQuery, setSearchedProjectQuery] = useState("");
  const [projectSearchResults, setProjectSearchResults] = useState<ProjectSearchHit[]>([]);
  const [projectSearchTotal, setProjectSearchTotal] = useState(0);
  const [projectSearchLoading, setProjectSearchLoading] = useState(false);
  const [projectSearchLoadingMore, setProjectSearchLoadingMore] = useState(false);
  const [projectSearchError, setProjectSearchError] = useState<string | null>(null);
  const projectSearchController = useRef<AbortController | null>(null);
  const activityInvestigation = investigations.find(
    (reference) =>
      JSON.stringify([reference.session_id, reference.investigation_id]) ===
      activityInvestigationKey,
  );
  const [hasMoreMonitoringLinks, setHasMoreMonitoringLinks] = useState(false);
  const sortedMonitoringSchedules = [...monitoringSchedules].sort(
    (left, right) =>
      left.name.localeCompare(right.name) || left.schedule_id.localeCompare(right.schedule_id),
  );
  const linkedMonitoringScheduleIds = new Set(
    monitoringLinks.map((link) => link.schedule_id),
  );

  async function handleProjectSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (projectSearchLoading || projectSearchLoadingMore) return;
    const query = projectSearchQuery.trim();
    if (!query) {
      setProjectSearchError("Enter a search term.");
      return;
    }
    setProjectSearchLoading(true);
    setProjectSearchError(null);
    setSearchedProjectQuery("");
    setProjectSearchResults([]);
    setProjectSearchTotal(0);
    projectSearchController.current?.abort();
    const controller = new AbortController();
    projectSearchController.current = controller;
    try {
      const response = await searchProject(
        projectId,
        query,
        controller.signal,
        PROJECT_PAGE_SIZE,
        0,
      );
      if (controller.signal.aborted) return;
      setSearchedProjectQuery(query);
      setProjectSearchResults(response.results);
      setProjectSearchTotal(response.total_count);
    } catch (reason) {
      if (controller.signal.aborted) return;
      setProjectSearchError(
        reason instanceof ApiError
          ? reason.message
          : "Could not search this Project's saved work.",
      );
    } finally {
      if (!controller.signal.aborted) setProjectSearchLoading(false);
    }
  }

  async function handleLoadMoreProjectSearch() {
    if (!searchedProjectQuery || projectSearchLoadingMore) return;
    setProjectSearchLoadingMore(true);
    setProjectSearchError(null);
    projectSearchController.current?.abort();
    const controller = new AbortController();
    projectSearchController.current = controller;
    try {
      const response = await searchProject(
        projectId,
        searchedProjectQuery,
        controller.signal,
        PROJECT_PAGE_SIZE,
        projectSearchResults.length,
      );
      if (controller.signal.aborted) return;
      setProjectSearchResults((current) => [...current, ...response.results]);
      setProjectSearchTotal(response.total_count);
    } catch (reason) {
      if (controller.signal.aborted) return;
      setProjectSearchError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load more Project search results.",
      );
    } finally {
      if (!controller.signal.aborted) setProjectSearchLoadingMore(false);
    }
  }

  useEffect(() => {
    return () => projectSearchController.current?.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getProject(projectId, controller.signal),
      listProjectSessions(projectId, controller.signal, PROJECT_PAGE_SIZE),
      listUnlinkedSessions(controller.signal),
      listProjectNotes(projectId, controller.signal, PROJECT_PAGE_SIZE),
      listProjectViews(projectId, controller.signal, PROJECT_PAGE_SIZE),
      listProjectActivity(projectId, controller.signal, PROJECT_PAGE_SIZE),
      listProjectMonitoringLinks(projectId, controller.signal, PROJECT_PAGE_SIZE),
    ])
      .then(async ([
        loadedProject,
        loadedSessions,
        unlinked,
        loadedNotes,
        loadedViews,
        loadedActivity,
        loadedMonitoringLinks,
      ]) => {
        if (controller.signal.aborted) return;
        setProject(loadedProject);
        setSessions(loadedSessions);
        setUnlinkedSessions(unlinked);
        setNotes(loadedNotes);
        setViews(loadedViews);
        setActivity(loadedActivity);
        setMonitoringLinks(loadedMonitoringLinks);
        setHasMoreMonitoringLinks(loadedMonitoringLinks.length === PROJECT_PAGE_SIZE);
        setHasMoreNotes(loadedNotes.length === PROJECT_PAGE_SIZE);
        setHasMoreViews(loadedViews.length === PROJECT_PAGE_SIZE);
        setHasMoreActivity(loadedActivity.length === PROJECT_PAGE_SIZE);
        setHasMoreSessions(loadedSessions.length === PROJECT_PAGE_SIZE);
        setError(null);
        setLoadError(null);
        setLoadedProjectId(projectId);
        setCatalogLoading(true);
        setComparisonsLoading(true);
        void listProjectInvestigationComparisons(
          projectId,
          controller.signal,
          PROJECT_PAGE_SIZE,
        )
          .then((loadedComparisons) => {
            if (!controller.signal.aborted) {
              setComparisons(loadedComparisons);
              setHasMoreComparisons(loadedComparisons.length === PROJECT_PAGE_SIZE);
              setComparisonError(null);
            }
          })
          .catch((reason: unknown) => {
            if (!controller.signal.aborted) {
              setComparisonError(
                reason instanceof ApiError
                  ? reason.message
                  : "Could not load Project investigation comparisons.",
              );
            }
          })
          .finally(() => {
            if (!controller.signal.aborted) setComparisonsLoading(false);
          });
        try {
          const projectInvestigations = await listProjectInvestigations(
            projectId,
            controller.signal,
            PROJECT_PAGE_SIZE,
          );
          if (!controller.signal.aborted) {
            setInvestigations(projectInvestigations);
            setLeftInvestigationIndex(projectInvestigations.length > 0 ? "0" : "");
            setRightInvestigationIndex(projectInvestigations.length > 1 ? "1" : "");
            setCatalogError(null);
          }
        } catch (reason) {
          if (!controller.signal.aborted) {
            setCatalogError(
              reason instanceof ApiError
                ? reason.message
                : "Could not load Engine investigations for this Project.",
            );
          }
        } finally {
          if (!controller.signal.aborted) setCatalogLoading(false);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(
            reason instanceof ApiError ? reason.message : "Could not load this Project.",
          );
          setLoadedProjectId(projectId);
        }
      });
      listMonitoringSchedules(controller.signal)
      .then((schedules) => {
        if (!controller.signal.aborted) {
          setMonitoringSchedules(schedules);
          setMonitoringError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setMonitoringError(
            reason instanceof ApiError
              ? reason.message
              : "Could not load Engine monitoring schedules.",
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setMonitoringSchedulesLoading(false);
      });
    return () => controller.abort();
  }, [projectId]);

  async function handleLinkSession(sessionId: string) {
    setLinkingSessionId(sessionId);
    setError(null);
    try {
      const link = await linkProjectSession(projectId, sessionId);
      setUnlinkedSessions((current) => current.filter((session) => session.id !== sessionId));
      await refreshProjectActivity();
      setSessions((current) => [link, ...current].slice(0, PROJECT_PAGE_SIZE));
      setHasMoreSessions(true);
      setCatalogLoading(true);
      setCatalogError(null);
      try {
        const firstSessionPage = await listProjectSessions(
          projectId,
          undefined,
          PROJECT_PAGE_SIZE,
        );
        setSessions(firstSessionPage);
        setHasMoreSessions(firstSessionPage.length === PROJECT_PAGE_SIZE);
      } catch (reason) {
        setError(
          reason instanceof ApiError
            ? `Session was added, but Project history could not be refreshed: ${reason.message}`
            : "Session was added, but Project history could not be refreshed.",
        );
      }
      try {
        const newInvestigations = await listProjectInvestigations(
          projectId,
          undefined,
          PROJECT_PAGE_SIZE,
        );
        setInvestigations(newInvestigations);
        setCatalogError(null);
      } catch (reason) {
        setCatalogError(
          reason instanceof ApiError
            ? reason.message
            : "Could not refresh Engine investigations for this Project.",
        );
      } finally {
        setCatalogLoading(false);
      }
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not add this session.");
    } finally {
      setLinkingSessionId(null);
    }
  }

  async function handleRetryCatalog() {
    setCatalogLoading(true);
    setCatalogError(null);
    try {
      const currentInvestigations = await listProjectInvestigations(
        projectId,
        undefined,
        PROJECT_PAGE_SIZE,
      );
      setInvestigations(currentInvestigations);
    } catch (reason) {
      setCatalogError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load Engine investigations for this Project.",
      );
    } finally {
      setCatalogLoading(false);
    }
  }

  async function handleCreateComparison(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leftIndex = Number(leftInvestigationIndex);
    const rightIndex = Number(rightInvestigationIndex);
    const left = investigations[leftIndex];
    const right = investigations[rightIndex];
    if (
      !project ||
      project.archived ||
      !comparisonTitle.trim() ||
      !Number.isInteger(leftIndex) ||
      !Number.isInteger(rightIndex) ||
      !left ||
      !right ||
      (left.session_id === right.session_id &&
        left.investigation_id === right.investigation_id)
    ) {
      return;
    }
    setCreatingComparison(true);
    setComparisonError(null);
    try {
      const comparison = await createProjectInvestigationComparison(projectId, {
        title: comparisonTitle.trim(),
        left,
        right,
      });
      setComparisons((current) => [comparison, ...current]);
      setComparisonTitle("");
      await refreshProjectActivity();
    } catch (reason) {
      setComparisonError(
        reason instanceof ApiError
          ? reason.message
          : "Could not save this investigation comparison.",
      );
    } finally {
      setCreatingComparison(false);
    }
  }

  async function handleDeleteComparison(comparisonId: string) {
    setComparisonError(null);
    try {
      await deleteProjectInvestigationComparison(projectId, comparisonId);
      setComparisons((current) =>
        current.filter((comparison) => comparison.id !== comparisonId),
      );
      await refreshProjectActivity();
    } catch (reason) {
      setComparisonError(
        reason instanceof ApiError
          ? reason.message
          : "Could not remove this investigation comparison.",
      );
    }
  }

  async function handleLoadMoreComparisons() {
    if (comparisonsLoading || !hasMoreComparisons) return;
    setComparisonsLoading(true);
    setComparisonError(null);
    try {
      const next = await listProjectInvestigationComparisons(
        projectId,
        undefined,
        PROJECT_PAGE_SIZE,
        comparisons.length,
      );
      setComparisons((current) => [...current, ...next]);
      setHasMoreComparisons(next.length === PROJECT_PAGE_SIZE);
    } catch (reason) {
      setComparisonError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load more Project investigation comparisons.",
      );
    } finally {
      setComparisonsLoading(false);
    }
  }

  async function handleRetryComparisons() {
    setComparisonsLoading(true);
    setComparisonError(null);
    try {
      const current = await listProjectInvestigationComparisons(
        projectId,
        undefined,
        PROJECT_PAGE_SIZE,
      );
      setComparisons(current);
      setHasMoreComparisons(current.length === PROJECT_PAGE_SIZE);
    } catch (reason) {
      setComparisonError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load Project investigation comparisons.",
      );
    } finally {
      setComparisonsLoading(false);
    }
  }

  async function refreshProjectActivity() {
    try {
      const current = await listProjectActivity(
        projectId,
        undefined,
        PROJECT_PAGE_SIZE,
        0,
        activityInvestigation,
      );
      setActivity(current);
      setHasMoreActivity(current.length === PROJECT_PAGE_SIZE);
      setActivityError(null);
    } catch (reason) {
      setActivityError(
        reason instanceof ApiError ? reason.message : "Could not refresh Project activity.",
      );
    }
  }

  async function handleLoadMoreActivity() {
    setActivityLoading(true);
    try {
      const next = await listProjectActivity(
        projectId,
        undefined,
        PROJECT_PAGE_SIZE,
        activity.length,
        activityInvestigation,
      );
      setActivity((current) => [...current, ...next]);
      setHasMoreActivity(next.length === PROJECT_PAGE_SIZE);
      setActivityError(null);
    } catch (reason) {
      setActivityError(
        reason instanceof ApiError ? reason.message : "Could not load more Project activity.",
      );
    } finally {
      setActivityLoading(false);
    }
  }

  async function handleActivityInvestigationChange(value: string) {
    const selected = investigations.find(
      (reference) =>
        JSON.stringify([reference.session_id, reference.investigation_id]) === value,
    );
    setActivityInvestigationKey(value);
    setActivity([]);
    setHasMoreActivity(false);
    setActivityLoading(true);
    setActivityError(null);
    try {
      const current = await listProjectActivity(
        projectId,
        undefined,
        PROJECT_PAGE_SIZE,
        0,
        selected,
      );
      setActivity(current);
      setHasMoreActivity(current.length === PROJECT_PAGE_SIZE);
    } catch (reason) {
      setActivityError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load the investigation timeline.",
      );
    } finally {
      setActivityLoading(false);
    }
  }

  async function handleLinkMonitoringSchedule() {
    if (!monitoringScheduleId) return;
    setLinkingMonitoring(true);
    setMonitoringError(null);
    try {
      const link = await linkProjectMonitoringSchedule(projectId, monitoringScheduleId);
      setMonitoringLinks((current) =>
        [link, ...current.filter((item) => item.schedule_id !== link.schedule_id)].slice(
          0,
          PROJECT_PAGE_SIZE,
        ),
      );
      if (monitoringLinks.length >= PROJECT_PAGE_SIZE) setHasMoreMonitoringLinks(true);
      await refreshMonitoringLinks();
      setMonitoringScheduleId("");
      await refreshProjectActivity();
    } catch (reason) {
      setMonitoringError(
        reason instanceof ApiError
          ? reason.message
          : "Could not link this Engine monitoring schedule.",
      );
    } finally {
      setLinkingMonitoring(false);
    }
  }

  async function handleUnlinkMonitoringSchedule(scheduleId: string) {
    setMonitoringError(null);
    try {
      await unlinkProjectMonitoringSchedule(projectId, scheduleId);
      await refreshMonitoringLinks();
      setMonitoringRuns((current) => {
        const next = { ...current };
        delete next[scheduleId];
        return next;
      });
      await refreshProjectActivity();
    } catch (reason) {
      setMonitoringError(
        reason instanceof ApiError
          ? reason.message
          : "Could not remove this schedule from the Project.",
      );
    }
  }

  async function refreshMonitoringLinks() {
    try {
      const current = await listProjectMonitoringLinks(
        projectId,
        undefined,
        PROJECT_PAGE_SIZE,
      );
      setMonitoringLinks(current);
      setHasMoreMonitoringLinks(current.length === PROJECT_PAGE_SIZE);
      setMonitoringError(null);
    } catch (reason) {
      setMonitoringError(
        reason instanceof ApiError
          ? reason.message
          : "Could not refresh Project monitoring links.",
      );
    }
  }

  async function handleLoadMoreMonitoringLinks() {
    try {
      const next = await listProjectMonitoringLinks(
        projectId,
        undefined,
        PROJECT_PAGE_SIZE,
        monitoringLinks.length,
      );
      setMonitoringLinks((current) => [...current, ...next]);
      setHasMoreMonitoringLinks(next.length === PROJECT_PAGE_SIZE);
    } catch (reason) {
      setMonitoringError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load more Project monitoring links.",
      );
    }
  }

  async function handleLoadMonitoringRuns(scheduleId: string) {
    setLoadingMonitoringRuns(scheduleId);
    setMonitoringError(null);
    try {
      const runs = await listMonitoringRuns(scheduleId);
      setMonitoringRuns((current) => ({ ...current, [scheduleId]: runs }));
    } catch (reason) {
      setMonitoringError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load Engine monitoring runs.",
      );
    } finally {
      setLoadingMonitoringRuns(null);
    }
  }

  async function handleRetryMonitoringSchedules() {
    setMonitoringSchedulesLoading(true);
    setMonitoringError(null);
    try {
      setMonitoringSchedules(await listMonitoringSchedules());
    } catch (reason) {
      setMonitoringError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load Engine monitoring schedules.",
      );
    } finally {
      setMonitoringSchedulesLoading(false);
    }
  }

  async function handleLoadMoreSessions() {
    setLoadingMore(true);
    setError(null);
    try {
      const offset = sessions.length;
      const page = await listProjectWorkPage(
        projectId,
        undefined,
        PROJECT_PAGE_SIZE,
        offset,
      );
      setSessions((current) => [...current, ...page.sessions]);
      setHasMoreSessions(page.sessions.length === PROJECT_PAGE_SIZE);
      setInvestigations((current) => [...current, ...page.investigations]);
      setCatalogError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load more Project work.");
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleCreateNote(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!noteTitle.trim() || !noteBody.trim()) return;
    setSavingNote(true);
    setError(null);
    try {
      const created = await createProjectNote(projectId, {
        title: noteTitle.trim(),
        body: noteBody.trim(),
      });
      setNotes((current) => [created, ...current]);
      await refreshProjectActivity();
      setNoteTitle("");
      setNoteBody("");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not create this note.");
    } finally {
      setSavingNote(false);
    }
  }

  async function handleUpdateNote(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingNote || !editingNote.title.trim() || !editingNote.body.trim()) return;
    setSavingNote(true);
    setError(null);
    try {
      const updated = await updateProjectNote(projectId, editingNote.id, {
        expected_revision: editingNote.revision,
        title: editingNote.title.trim(),
        body: editingNote.body.trim(),
      });
      setNotes((current) => [updated, ...current.filter((note) => note.id !== updated.id)]);
      await refreshProjectActivity();
      setEditingNote(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not update this note.");
    } finally {
      setSavingNote(false);
    }
  }

  async function handleDeleteNote(noteId: string) {
    setError(null);
    try {
      await deleteProjectNote(projectId, noteId);
      setNotes((current) => current.filter((note) => note.id !== noteId));
      await refreshProjectActivity();
      if (editingNote?.id === noteId) setEditingNote(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not delete this note.");
    }
  }

  async function handleSaveEarthView(
    sessionId: string,
    bookmarkId: string,
    title: string,
  ) {
    const key = `${sessionId}:${bookmarkId}`;
    setSavingViewKey(key);
    setError(null);
    try {
      const view = await createProjectView(projectId, {
        title,
        source_session_id: sessionId,
        source_bookmark_id: bookmarkId,
      });
      setViews((current) => [view, ...current]);
      await refreshProjectActivity();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not save this Earth view.");
    } finally {
      setSavingViewKey(null);
    }
  }

  async function handleDeleteEarthView(viewId: string) {
    setError(null);
    try {
      await deleteProjectView(projectId, viewId);
      setViews((current) => current.filter((view) => view.id !== viewId));
      await refreshProjectActivity();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not delete this Earth view.");
    }
  }

  async function handleRestoreEarthView(view: ProjectEarthView) {
    setRestoringViewId(view.id);
    setError(null);
    try {
      const restored = await restoreProjectEarthView(view);
      const query = new URLSearchParams({ restoreBookmark: restored.bookmarkId });
      navigate(`/s/${encodeURIComponent(restored.sessionId)}?${query.toString()}`);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not restore this Earth view in its source session.",
      );
    } finally {
      setRestoringViewId(null);
    }
  }

  async function handleLoadMoreNotes() {
    try {
      const next = await listProjectNotes(projectId, undefined, PROJECT_PAGE_SIZE, notes.length);
      setNotes((current) => [...current, ...next]);
      setHasMoreNotes(next.length === PROJECT_PAGE_SIZE);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load more notes.");
    }
  }

  async function handleLoadMoreViews() {
    try {
      const next = await listProjectViews(projectId, undefined, PROJECT_PAGE_SIZE, views.length);
      setViews((current) => [...current, ...next]);
      setHasMoreViews(next.length === PROJECT_PAGE_SIZE);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load more Earth views.");
    }
  }

  async function handleSaveProject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project || !editTitle.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateProject(project.id, {
        expected_revision: project.revision,
        title: editTitle.trim(),
      });
      setProject(updated);
      setEditing(false);
      await refreshProjectActivity();
      window.dispatchEvent(new Event("satquery:projects-updated"));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not update this Project.");
    } finally {
      setSaving(false);
    }
  }

  async function handleArchiveProject() {
    if (!project) return;
    setSaving(true);
    setError(null);
    try {
      await updateProject(project.id, {
        expected_revision: project.revision,
        archived: true,
      });
      window.dispatchEvent(new Event("satquery:projects-updated"));
      navigate("/");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not archive this Project.");
      setSaving(false);
    }
  }

  useEffect(() => {
    useSessionStore.getState().setActiveSession(null);
  }, [projectId]);

  if (loadedProjectId !== projectId) {
    return <p className="pointer-events-auto p-6 text-sm text-ink-dim">Loading Project...</p>;
  }
  if (loadError || !project) {
    return (
      <p className="pointer-events-auto rounded-xl bg-surface p-6 text-sm text-rose-200" role="alert">
        {loadError ?? "Project not found."}
      </p>
    );
  }

  return (
    <section
      id="project-header"
      aria-label={`${project.title} Project`}
      className="pointer-events-auto absolute right-4 top-4 max-h-[min(60vh,40rem)] w-[min(28rem,calc(100%-2rem))] overflow-y-auto rounded-2xl border border-white/10 bg-surface p-5 shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
        Investigation Project
      </p>
      {editing ? (
        <form onSubmit={(event) => void handleSaveProject(event)} className="mt-2 flex gap-2">
          <input
            autoFocus
            aria-label="Project name"
            maxLength={160}
            value={editTitle}
            onChange={(event) => setEditTitle(event.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-sm text-ink outline-none focus:border-accent/60"
          />
          <button
            type="submit"
            disabled={saving || !editTitle.trim()}
            className="rounded-lg border border-white/10 px-2 py-1 text-xs text-ink disabled:opacity-50"
          >
            Save
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="rounded-lg px-2 py-1 text-xs text-ink-dim"
          >
            Cancel
          </button>
        </form>
      ) : (
        <div className="mt-2 flex items-center justify-between gap-2">
          <h2 className="min-w-0 flex-1 truncate text-lg font-semibold text-ink">
            {project.title}
          </h2>
          {!project.archived && (
            <button
              type="button"
              onClick={() => {
                setEditTitle(project.title);
                setEditing(true);
              }}
              className="text-xs text-accent hover:text-ink"
            >
              Rename
            </button>
          )}
        </div>
      )}
      {project.description && (
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-dim">
          {project.description}
        </p>
      )}
      <p className="mt-3 text-xs text-ink-dim">
        {project.archived ? "Archived" : "Active"} · {sessions.length}{" "}
        {sessions.length === 1 ? "session" : "sessions"}
      </p>
      {error && (
        <p className="mt-3 text-xs text-rose-200" role="alert">
          {error}
        </p>
      )}
      {!project.archived && (
        <button
          type="button"
          onClick={() => void handleArchiveProject()}
          disabled={saving}
          className="mt-3 text-xs text-rose-200 hover:text-rose-100 disabled:opacity-50"
        >
          Archive Project
        </button>
      )}
      <div className="mt-5 border-t border-white/10 pt-4">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
          Search Project work
        </h3>
        <p className="mt-2 text-[10px] leading-4 text-ink-dim">
          Search saved notes, Earth views, comparisons, collections, sessions, and Project details.
          Engine-authored scientific content is not searched or reinterpreted here.
        </p>
        <form onSubmit={(event) => void handleProjectSearch(event)} className="mt-3 flex gap-2">
          <input
            aria-label="Search Project work"
            type="search"
            maxLength={200}
            value={projectSearchQuery}
            onChange={(event) => setProjectSearchQuery(event.target.value)}
            placeholder="Search notes, places, or IDs..."
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink outline-none focus:border-accent/60"
          />
          <button
            type="submit"
            disabled={projectSearchLoading || projectSearchLoadingMore}
            className="rounded-lg border border-white/10 px-3 py-2 text-xs text-ink disabled:opacity-50"
          >
            {projectSearchLoading ? "Searching..." : "Search"}
          </button>
        </form>
        {projectSearchError && (
          <p className="mt-2 text-xs text-rose-200" role="alert">
            {projectSearchError}
          </p>
        )}
        {searchedProjectQuery && !projectSearchLoading && (
          <p className="mt-2 text-[10px] text-ink-dim" role="status">
            {projectSearchTotal} saved {projectSearchTotal === 1 ? "record" : "records"} for
            {" "}{searchedProjectQuery}
          </p>
        )}
        {projectSearchResults.length > 0 && (
          <ul className="mt-2 space-y-2">
            {projectSearchResults.map((hit) => (
              <li key={`${hit.kind}:${hit.id}`} className="rounded-lg bg-black/20 p-3">
                <Link
                  to={getProjectSearchHref(projectId, hit)}
                  className="break-words text-xs font-medium text-accent hover:text-ink"
                >
                  {hit.title}
                </Link>
                <p className="mt-1 break-words text-[10px] leading-4 text-ink-dim">
                  {hit.summary}
                </p>
                <p className="mt-1 text-[9px] text-ink-dim">
                  {hit.kind.replace("_", " ")} · Matched: {hit.matched_terms.join(", ")}
                </p>
              </li>
            ))}
          </ul>
        )}
        {projectSearchResults.length < projectSearchTotal && (
          <button
            type="button"
            onClick={() => void handleLoadMoreProjectSearch()}
            disabled={projectSearchLoadingMore}
            className="mt-2 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
          >
            {projectSearchLoadingMore ? "Loading..." : "Load more search results"}
          </button>
        )}
      </div>
      <div className="mt-5 border-t border-white/10 pt-4">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
          Investigations
        </h3>
        {catalogLoading ? (
          <p className="mt-3 text-sm text-ink-dim" role="status">
            Loading Engine investigations...
          </p>
        ) : catalogError ? (
          <div className="mt-3 text-sm text-rose-200" role="alert">
            <p>Engine investigations could not be loaded: {catalogError}</p>
            <button
              type="button"
              onClick={() => void handleRetryCatalog()}
              className="mt-2 underline underline-offset-2"
            >
              Retry
            </button>
          </div>
        ) : investigations.length === 0 ? (
          <p className="mt-3 text-sm text-ink-dim">
            No Engine investigations are linked to this Project yet.
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {investigations.map(({ investigation_id, session_id }) => {
              const sessionTitle =
                sessions.find(({ session }) => session.id === session_id)?.session.title ||
                "Untitled session";
              return (
                <li key={`${session_id}:${investigation_id}`}>
                  <div className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-white/5">
                    <div className="min-w-0 flex-1">
                      <Link
                        to={`/p/${encodeURIComponent(projectId)}/investigations/${encodeURIComponent(session_id)}/${encodeURIComponent(investigation_id)}`}
                        className="block truncate text-sm text-accent hover:text-ink"
                      >
                        {investigation_id}
                      </Link>
                      <p className="mt-1 truncate text-[10px] text-ink-dim">
                        In {sessionTitle}
                      </p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {!catalogLoading && !catalogError && (
        <InvestigationRelationships
          projectId={projectId}
          investigations={investigations}
          sessions={sessions}
          archived={project.archived}
        />
      )}
      <InvestigationCollections
        projectId={projectId}
        investigations={investigations}
        sessions={sessions}
        archived={project.archived}
        onActivityChange={() => void refreshProjectActivity()}
      />
      <InvestigationTemplates
        projectId={projectId}
        archived={project.archived}
        onActivityChange={() => void refreshProjectActivity()}
      />
      <div className="mt-5 border-t border-white/10 pt-4">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
          Investigation comparisons
        </h3>
        <p className="mt-2 text-[10px] leading-4 text-ink-dim">
          Ask the Engine to align explicitly resolved measurements and eligible exact-support
          temporal records. Results include limitations and are descriptive, not scientific
          conclusions.
        </p>
        {comparisonError && (
          <div className="mt-2 text-xs text-rose-200" role="alert">
            <p>{comparisonError}</p>
            <button
              type="button"
              onClick={() => void handleRetryComparisons()}
              className="mt-1 underline underline-offset-2"
            >
              Retry
            </button>
          </div>
        )}
        {!project.archived && investigations.length >= 2 && (
          <form
            onSubmit={(event) => void handleCreateComparison(event)}
            className="mt-3 grid gap-2"
          >
            <input
              aria-label="Comparison title"
              maxLength={160}
              placeholder="Comparison title"
              value={comparisonTitle}
              onChange={(event) => setComparisonTitle(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-ink outline-none focus:border-accent/60"
            />
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="grid gap-1 text-[10px] text-ink-dim">
                First investigation
                <select
                  aria-label="First investigation"
                  value={leftInvestigationIndex}
                  onChange={(event) => setLeftInvestigationIndex(event.target.value)}
                  className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
                >
                  {investigations.map((item, index) => {
                    const title =
                      sessions.find(({ session }) => session.id === item.session_id)?.session
                        .title || "Untitled session";
                    return (
                      <option key={`${item.session_id}:${item.investigation_id}`} value={index}>
                        {item.investigation_id} · {title}
                      </option>
                    );
                  })}
                </select>
              </label>
              <label className="grid gap-1 text-[10px] text-ink-dim">
                Second investigation
                <select
                  aria-label="Second investigation"
                  value={rightInvestigationIndex}
                  onChange={(event) => setRightInvestigationIndex(event.target.value)}
                  className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
                >
                  {investigations.map((item, index) => {
                    const title =
                      sessions.find(({ session }) => session.id === item.session_id)?.session
                        .title || "Untitled session";
                    return (
                      <option key={`${item.session_id}:${item.investigation_id}`} value={index}>
                        {item.investigation_id} · {title}
                      </option>
                    );
                  })}
                </select>
              </label>
            </div>
            <button
              type="submit"
              disabled={
                creatingComparison ||
                !comparisonTitle.trim() ||
                leftInvestigationIndex === rightInvestigationIndex
              }
              className="justify-self-start rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink disabled:opacity-50"
            >
              {creatingComparison ? "Comparing in Engine..." : "Create comparison"}
            </button>
          </form>
        )}
        {comparisonsLoading ? (
          <p className="mt-3 text-xs text-ink-dim" role="status">
            Loading comparisons...
          </p>
        ) : comparisons.length === 0 ? (
          <p className="mt-3 text-sm text-ink-dim">
            {investigations.length < 2
              ? "Link at least two Engine investigations to compare them."
              : "No saved investigation comparisons yet."}
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {comparisons.map((comparison) => (
              <li
                key={comparison.id}
                className="flex items-start justify-between gap-2 rounded-lg bg-black/20 p-3"
              >
                <div className="min-w-0">
                  <Link
                    to={`/p/${encodeURIComponent(projectId)}/comparisons/${encodeURIComponent(comparison.id)}`}
                    className="break-words text-sm text-accent hover:text-ink"
                  >
                    {comparison.title}
                  </Link>
                  <p className="mt-1 break-all text-[10px] text-ink-dim">
                    {comparison.left.investigation_id} vs. {comparison.right.investigation_id}
                  </p>
                </div>
                {!project.archived && (
                  <button
                    type="button"
                    onClick={() => void handleDeleteComparison(comparison.id)}
                    className="shrink-0 text-[10px] text-rose-200 hover:text-rose-100"
                  >
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {hasMoreComparisons && (
          <button
            type="button"
            onClick={() => void handleLoadMoreComparisons()}
            disabled={comparisonsLoading}
            className="mt-2 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
          >
            {comparisonsLoading ? "Loading..." : "Load older comparisons"}
          </button>
        )}
      </div>
      <div className="mt-5 border-t border-white/10 pt-4">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
          Investigation timeline
        </h3>
        <p className="mt-2 text-[10px] leading-4 text-ink-dim">
          Filter durable Project actions by an explicitly linked Engine investigation. These are
          Platform workflow events; session messages are not treated as scientific events.
        </p>
        {investigations.length > 0 && (
          <label className="mt-3 grid max-w-xl gap-1 text-[10px] text-ink-dim">
            Investigation
            <select
              aria-label="Filter investigation timeline"
              value={activityInvestigationKey}
              onChange={(event) => void handleActivityInvestigationChange(event.target.value)}
              disabled={activityLoading}
              className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink disabled:opacity-50"
            >
              <option value="">All Project activity</option>
              {investigations.map((reference) => {
                const key = JSON.stringify([
                  reference.session_id,
                  reference.investigation_id,
                ]);
                const sessionTitle =
                  sessions.find((item) => item.session_id === reference.session_id)?.session
                    .title || reference.session_id;
                return (
                  <option key={key} value={key}>
                    {reference.investigation_id} · {sessionTitle}
                  </option>
                );
              })}
            </select>
          </label>
        )}
        {activityError ? (
          <div className="mt-3 text-xs text-rose-200" role="alert">
            <p>Investigation timeline could not be loaded: {activityError}</p>
            <button
              type="button"
              onClick={() => void refreshProjectActivity()}
              className="mt-2 underline underline-offset-2"
            >
              Retry
            </button>
          </div>
        ) : activityLoading && activity.length === 0 ? (
          <p className="mt-3 text-sm text-ink-dim" role="status">
            Loading investigation timeline...
          </p>
        ) : activity.length === 0 ? (
          <p className="mt-3 text-sm text-ink-dim">No matching Project activity has been recorded.</p>
        ) : (
          <ol className="mt-3 space-y-2">
            {activity.map((item) => {
              const linkedSessionAvailable = item.session_id
                ? sessions.some(({ session }) => session.id === item.session_id)
                : false;
              return (
                <li
                  key={item.id}
                  className="rounded-lg border-l border-accent/40 bg-black/10 py-2 pl-3 pr-2"
                >
                  <p className="text-xs text-ink">
                    {PROJECT_ACTIVITY_LABELS[item.action]}
                    {item.label ? ` · ${item.label}` : ""}
                  </p>
                  <time
                    dateTime={item.occurred_at}
                    className="mt-1 block text-[10px] text-ink-dim"
                  >
                    {new Date(item.occurred_at).toLocaleString()}
                  </time>
                  {item.session_id &&
                    (linkedSessionAvailable ? (
                      <Link
                        to={`/s/${encodeURIComponent(item.session_id)}`}
                        className="mt-1 inline-block break-all text-[10px] text-accent hover:text-ink"
                      >
                        Open session {item.session_id}
                      </Link>
                    ) : (
                      <p className="mt-1 break-all text-[10px] text-ink-dim">
                        Session reference {item.session_id}
                      </p>
                    ))}
                  {item.investigations.length > 0 && (
                    <p className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[10px]">
                      <span className="text-ink-dim">Investigations:</span>
                      {item.investigations.map((reference) => (
                        <Link
                          key={`${reference.session_id}:${reference.investigation_id}`}
                          to={`/p/${encodeURIComponent(projectId)}/investigations/${encodeURIComponent(reference.session_id)}/${encodeURIComponent(reference.investigation_id)}`}
                          className="break-all text-accent hover:text-ink"
                        >
                          {reference.investigation_id}
                        </Link>
                      ))}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        )}
        {hasMoreActivity && !activityError && (
          <button
            type="button"
            onClick={() => void handleLoadMoreActivity()}
            disabled={activityLoading}
            className="mt-2 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
          >
            {activityLoading ? "Loading..." : "Load older activity"}
          </button>
        )}
      </div>
      <div className="mt-5 border-t border-white/10 pt-4">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
          Project monitoring
        </h3>
        <p className="mt-2 text-[10px] leading-4 text-ink-dim">
          Projects store references only. Missions, schedules, runs, and execution remain
          Engine-owned; manage schedule settings in the Monitoring panel.
        </p>
        {monitoringError && (
          <div className="mt-3 text-xs text-rose-200" role="alert">
            <p>{monitoringError}</p>
            <button
              type="button"
              onClick={() => void handleRetryMonitoringSchedules()}
              className="mt-2 underline underline-offset-2"
            >
              Retry schedule list
            </button>
          </div>
        )}
        {!project.archived && (
          <div className="mt-3 flex gap-2">
            <select
              aria-label="Engine schedule to link"
              value={monitoringScheduleId}
              onChange={(event) => setMonitoringScheduleId(event.target.value)}
              disabled={monitoringSchedulesLoading}
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink"
            >
              <option value="">
                {monitoringSchedulesLoading
                  ? "Loading Engine schedules..."
                  : "Select an Engine schedule"}
              </option>
              {sortedMonitoringSchedules
                .filter((schedule) => !linkedMonitoringScheduleIds.has(schedule.schedule_id))
                .map((schedule) => (
                  <option key={schedule.schedule_id} value={schedule.schedule_id}>
                    {schedule.name} · {schedule.schedule_id}
                  </option>
                ))}
            </select>
            <button
              type="button"
              onClick={() => void handleLinkMonitoringSchedule()}
              disabled={!monitoringScheduleId || linkingMonitoring}
              className="rounded-lg border border-white/10 px-2 py-1 text-xs text-ink disabled:opacity-50"
            >
              {linkingMonitoring ? "Linking..." : "Add"}
            </button>
          </div>
        )}
        {monitoringLinks.length === 0 ? (
          <p className="mt-3 text-sm text-ink-dim">
            No Engine monitoring schedules are linked to this Project.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {monitoringLinks.map((link) => {
              const schedule = monitoringSchedules.find(
                (item) => item.schedule_id === link.schedule_id,
              );
              const runs = monitoringRuns[link.schedule_id];
              return (
                <li key={link.schedule_id} className="rounded-lg bg-black/20 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="break-all text-xs font-medium text-ink">
                      {schedule?.name ?? "Engine schedule unavailable"}
                    </h4>
                    {!project.archived && (
                      <button
                        type="button"
                        onClick={() => void handleUnlinkMonitoringSchedule(link.schedule_id)}
                        className="shrink-0 text-[10px] text-rose-200 hover:text-rose-100"
                      >
                        Remove link
                      </button>
                    )}
                  </div>
                  <p className="mt-1 break-all text-[10px] text-ink-dim">
                    Schedule {link.schedule_id} · Mission {link.mission_id}
                  </p>
                  {schedule && (
                    <p className="mt-1 text-[10px] text-ink-dim">
                      {schedule.enabled ? "Enabled" : "Disabled"} · Next run{" "}
                      {new Date(schedule.next_run_at).toLocaleString()}
                    </p>
                  )}
                  {!schedule && (
                    <p className="mt-1 text-[10px] text-ink-dim">
                      This reference is retained, but the Engine no longer lists its schedule.
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => void handleLoadMonitoringRuns(link.schedule_id)}
                    disabled={loadingMonitoringRuns === link.schedule_id || !schedule}
                    className="mt-2 text-[10px] text-accent hover:text-ink disabled:opacity-50"
                  >
                    {loadingMonitoringRuns === link.schedule_id
                      ? "Loading Engine runs..."
                      : runs
                        ? "Refresh Engine runs"
                        : "Review Engine runs"}
                  </button>
                  {runs && (
                    <ol className="mt-2 space-y-1">
                      {runs.length === 0 ? (
                        <li className="text-[10px] text-ink-dim">
                          The Engine has not returned runs for this schedule.
                        </li>
                      ) : (
                        runs.map((run) => (
                          <li
                            key={run.run_id}
                            className="rounded-md border-l border-white/10 py-1 pl-2"
                          >
                            <p className="break-all text-[10px] text-ink">
                              {run.status} · {run.run_id}
                            </p>
                            <p className="text-[9px] text-ink-dim">
                              Started {new Date(run.started_at).toLocaleString()}
                              {run.investigation_id
                                ? ` · Investigation ${run.investigation_id}`
                                : ""}
                            </p>
                          </li>
                        ))
                      )}
                    </ol>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {hasMoreMonitoringLinks && (
          <button
            type="button"
            onClick={() => void handleLoadMoreMonitoringLinks()}
            className="mt-2 text-xs text-ink-dim hover:text-ink"
          >
            Load more linked schedules
          </button>
        )}
      </div>
      <div id="project-notes" className="mt-5 border-t border-white/10 pt-4">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
          Project notes
        </h3>
        {!project.archived && (
          <form onSubmit={(event) => void handleCreateNote(event)} className="mt-3 space-y-2">
            <input
              aria-label="Note title"
              maxLength={160}
              placeholder="Note title"
              value={noteTitle}
              onChange={(event) => setNoteTitle(event.target.value)}
              className="w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-ink outline-none focus:border-accent/60"
            />
            <textarea
              aria-label="Note content"
              maxLength={20_000}
              placeholder="Record a question, interpretation, or next step..."
              value={noteBody}
              onChange={(event) => setNoteBody(event.target.value)}
              rows={3}
              className="w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-ink outline-none focus:border-accent/60"
            />
            <button
              type="submit"
              disabled={savingNote || !noteTitle.trim() || !noteBody.trim()}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink disabled:opacity-50"
            >
              Add note
            </button>
          </form>
        )}
        {notes.length === 0 ? (
          <p className="mt-3 text-sm text-ink-dim">No Project notes yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {notes.map((note) => (
              <li key={note.id} className="rounded-lg bg-black/20 p-3">
                {editingNote?.id === note.id ? (
                  <form onSubmit={(event) => void handleUpdateNote(event)} className="space-y-2">
                    <input
                      aria-label="Edit note title"
                      maxLength={160}
                      value={editingNote.title}
                      onChange={(event) =>
                        setEditingNote({ ...editingNote, title: event.target.value })
                      }
                      className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-sm text-ink outline-none"
                    />
                    <textarea
                      aria-label="Edit note content"
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
                        disabled={savingNote || !editingNote.title.trim() || !editingNote.body.trim()}
                        className="text-xs text-accent disabled:opacity-50"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingNote(null)}
                        className="text-xs text-ink-dim"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="break-words text-sm font-medium text-ink">{note.title}</h4>
                      {!project.archived && (
                        <div className="flex shrink-0 gap-2">
                          <button
                            type="button"
                            onClick={() => setEditingNote(note)}
                            className="text-xs text-accent hover:text-ink"
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleDeleteNote(note.id)}
                            className="text-xs text-rose-200 hover:text-rose-100"
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                    {note.investigation_id && note.investigation_session_id && (
                      <Link
                        to={`/p/${encodeURIComponent(projectId)}/investigations/${encodeURIComponent(note.investigation_session_id)}/${encodeURIComponent(note.investigation_id)}`}
                        className="mt-1 inline-block break-all text-[10px] text-accent hover:text-ink"
                      >
                        Linked to investigation {note.investigation_id}
                      </Link>
                    )}
                    <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-5 text-ink-dim">
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
            onClick={() => void handleLoadMoreNotes()}
            className="mt-2 text-xs text-ink-dim hover:text-ink"
          >
            Load older notes
          </button>
        )}
      </div>
      <div id="project-earth-views" className="mt-5 border-t border-white/10 pt-4">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
          Saved Earth views
        </h3>
        {views.length === 0 ? (
          <p className="mt-3 text-sm text-ink-dim">
            No saved views. Save a bookmark from a linked session below.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {views.map((view) => (
              <li key={view.id} className="rounded-lg bg-black/20 p-3">
                <div className="flex items-start justify-between gap-2">
                  <h4 className="break-words text-sm font-medium text-ink">{view.title}</h4>
                  {!project.archived && (
                    <button
                      type="button"
                      onClick={() => void handleDeleteEarthView(view.id)}
                      className="shrink-0 text-xs text-rose-200 hover:text-rose-100"
                    >
                      Delete
                    </button>
                  )}
                </div>
                <p className="mt-1 text-[10px] text-ink-dim">
                  Camera {view.context.camera.position.lat.toFixed(4)},{" "}
                  {view.context.camera.position.lng.toFixed(4)} ·{" "}
                  {view.context.imagery.length} image reference
                  {view.context.imagery.length === 1 ? "" : "s"}
                </p>
                {view.investigation_id && (
                  <Link
                    to={`/p/${encodeURIComponent(projectId)}/investigations/${encodeURIComponent(view.source_session_id)}/${encodeURIComponent(view.investigation_id)}`}
                    className="mt-1 inline-block break-all text-[10px] text-accent hover:text-ink"
                  >
                    Part of investigation {view.investigation_id}
                  </Link>
                )}
                {view.context.measurement && (
                  <p className="mt-1 text-[10px] text-ink-dim">
                    Presentation measurement: {view.context.measurement.value ?? "—"}{" "}
                    {view.context.measurement.unit} ({view.context.measurement.kind})
                  </p>
                )}
                {view.context.imagery.length > 0 && (
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {view.context.imagery.map((image) => (
                      <li key={image.asset_id} className="max-w-24">
                        <img
                          src={imageContentUrl(view.source_session_id, image.asset_id, true)}
                          alt={`Session image ${image.asset_id}`}
                          loading="lazy"
                          className="h-16 w-24 rounded-md object-cover"
                        />
                        <p className="mt-1 truncate text-[9px] text-ink-dim">
                          {image.asset_id}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
                {view.source_session_exists ? (
                  <button
                    type="button"
                    disabled={restoringViewId === view.id}
                    onClick={() => void handleRestoreEarthView(view)}
                    className="mt-2 inline-block text-xs text-accent hover:text-ink disabled:opacity-50"
                  >
                    {restoringViewId === view.id ? "Restoring…" : "Restore Earth view"}
                  </button>
                ) : (
                  <p className="mt-2 break-all text-[10px] text-ink-dim">
                    Original session unavailable ({view.source_session_id}); this Earth-context
                    snapshot is retained.
                  </p>
                )}
                <time
                  dateTime={view.created_at}
                  className="mt-2 block text-[10px] text-ink-dim"
                >
                  Saved {new Date(view.created_at).toLocaleString()}
                </time>
              </li>
            ))}
          </ul>
        )}
        {hasMoreViews && (
          <button
            type="button"
            onClick={() => void handleLoadMoreViews()}
            className="mt-2 text-xs text-ink-dim hover:text-ink"
          >
            Load older views
          </button>
        )}
      </div>
      <div className="mt-5 border-t border-white/10 pt-4">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
          Work history
        </h3>
        {sessions.length === 0 ? (
          <p className="mt-3 text-sm text-ink-dim">
            No sessions yet. Create one from this Project in the workspace navigation.
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {sessions.map(({ session }) => (
              <li key={session.id} className="rounded-lg hover:bg-white/5">
                <Link
                  to={`/s/${encodeURIComponent(session.id)}`}
                  className="block px-3 py-2 text-sm text-ink"
                >
                  {session.title || "Untitled session"}
                  <span className="mt-1 block text-[10px] text-ink-dim">
                    Updated {new Date(session.updated_at).toLocaleString()}
                  </span>
                </Link>
                {session.earth_workspace.bookmarks.length > 0 && (
                  <ul className="space-y-1 px-3 pb-2">
                    {session.earth_workspace.bookmarks.map((bookmark) => {
                      const key = `${session.id}:${bookmark.id}`;
                      return (
                        <li
                          key={bookmark.id}
                          className="flex items-center justify-between gap-2 text-[10px] text-ink-dim"
                        >
                          <span className="min-w-0 truncate">Earth bookmark: {bookmark.name}</span>
                          {!project.archived && (
                            <button
                              type="button"
                              disabled={savingViewKey === key}
                              onClick={() =>
                                void handleSaveEarthView(
                                  session.id,
                                  bookmark.id,
                                  bookmark.name,
                                )
                              }
                              className="shrink-0 text-accent hover:text-ink disabled:opacity-50"
                            >
                              {savingViewKey === key ? "Saving..." : "Save view"}
                            </button>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
        {hasMoreSessions && (
          <button
            type="button"
            onClick={() => void handleLoadMoreSessions()}
            disabled={loadingMore}
            className="mt-2 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
          >
            {loadingMore ? "Loading..." : "Load more"}
          </button>
        )}
      </div>
      {!project.archived && unlinkedSessions.length > 0 && (
        <div className="mt-5 border-t border-white/10 pt-4">
          <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
            Add existing session
          </h3>
          <ul className="mt-2 space-y-1">
            {unlinkedSessions.map((session) => (
              <li key={session.id} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate px-2 py-1.5 text-xs text-ink-dim">
                  {session.title || "Untitled session"}
                </span>
                <button
                  type="button"
                  onClick={() => void handleLinkSession(session.id)}
                  disabled={linkingSessionId !== null}
                  className="rounded-lg border border-white/10 px-2 py-1 text-xs text-ink hover:bg-white/5"
                >
                  {linkingSessionId === session.id ? "Adding..." : "Add"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
