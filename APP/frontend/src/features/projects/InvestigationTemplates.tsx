import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "@/services/api/client";
import {
  applyProjectInvestigationTemplate,
  createProjectInvestigationTemplate,
  deleteProjectInvestigationTemplate,
  listProjectInvestigationTemplateRuns,
  listProjectInvestigationTemplates,
  updateProjectInvestigationTemplate,
  updateProjectInvestigationTemplateRun,
} from "@/services/api/projects";
import type {
  ProjectInvestigationTemplate,
  ProjectInvestigationTemplateRun,
  ProjectInvestigationTemplateUpdate,
} from "@/shared/types";

const PAGE_SIZE = 50;

export function InvestigationTemplates({
  projectId,
  archived,
  onActivityChange,
}: {
  projectId: string;
  archived: boolean;
  onActivityChange: () => void;
}) {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<ProjectInvestigationTemplate[]>([]);
  const [runs, setRuns] = useState<ProjectInvestigationTemplateRun[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [stepsText, setStepsText] = useState("");
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editStepsText, setEditStepsText] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMoreTemplates, setLoadingMoreTemplates] = useState(false);
  const [loadingMoreRuns, setLoadingMoreRuns] = useState(false);
  const [hasMoreTemplates, setHasMoreTemplates] = useState(false);
  const [hasMoreRuns, setHasMoreRuns] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      listProjectInvestigationTemplates(projectId, controller.signal, PAGE_SIZE),
      listProjectInvestigationTemplateRuns(projectId, controller.signal, PAGE_SIZE),
    ])
      .then(([loadedTemplates, loadedRuns]) => {
        if (controller.signal.aborted) return;
        setTemplates(loadedTemplates);
        setRuns(loadedRuns);
        setHasMoreTemplates(loadedTemplates.length === PAGE_SIZE);
        setHasMoreRuns(loadedRuns.length === PAGE_SIZE);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof ApiError ? reason.message : "Could not load templates.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [projectId]);

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const steps = stepsText
      .split(/\r?\n/)
      .map((step) => step.trim())
      .filter(Boolean);
    const [firstStep, ...remainingSteps] = steps;
    if (!title.trim() || !firstStep || steps.length > 30) return;
    setSaving(true);
    setError(null);
    try {
      const created = await createProjectInvestigationTemplate(projectId, {
        title: title.trim(),
        description: description.trim(),
        steps: [
          { title: firstStep },
          ...remainingSteps.map((step) => ({ title: step })),
        ],
      });
      setTemplates((current) => [created, ...current]);
      setHasMoreTemplates((current) => current || templates.length >= PAGE_SIZE);
      setTitle("");
      setDescription("");
      setStepsText("");
      onActivityChange();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not save this template.");
    } finally {
      setSaving(false);
    }
  }

  async function handleApply(templateId: string) {
    setBusyId(templateId);
    setError(null);
    try {
      const run = await applyProjectInvestigationTemplate(projectId, templateId);
      setRuns((current) => [run, ...current]);
      setHasMoreRuns((current) => current || runs.length >= PAGE_SIZE);
      onActivityChange();
      navigate(`/s/${encodeURIComponent(run.session_id)}`);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not start this workflow.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(templateId: string) {
    setBusyId(templateId);
    setError(null);
    try {
      await deleteProjectInvestigationTemplate(projectId, templateId);
      setTemplates((current) => current.filter((template) => template.id !== templateId));
      onActivityChange();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not delete this template.");
    } finally {
      setBusyId(null);
    }
  }

  function handleBeginEdit(template: ProjectInvestigationTemplate) {
    setEditingTemplateId(template.id);
    setEditTitle(template.title);
    setEditDescription(template.description);
    setEditStepsText(template.steps.map((step) => step.title).join("\n"));
  }

  async function handleUpdateTemplate(
    event: React.FormEvent<HTMLFormElement>,
    template: ProjectInvestigationTemplate,
  ) {
    event.preventDefault();
    const steps = editStepsText
      .split(/\r?\n/)
      .map((step) => step.trim())
      .filter(Boolean);
    const [firstStep, ...remainingSteps] = steps;
    if (!editTitle.trim() || !firstStep || steps.length > 30) return;
    const update: ProjectInvestigationTemplateUpdate = {
      expected_revision: template.revision,
      title: editTitle.trim(),
      description: editDescription.trim(),
      steps: [
        { title: firstStep },
        ...remainingSteps.map((step) => ({ title: step })),
      ],
    };
    setBusyId(template.id);
    setError(null);
    try {
      const updated = await updateProjectInvestigationTemplate(
        projectId,
        template.id,
        update,
      );
      setTemplates((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setEditingTemplateId(null);
      onActivityChange();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not update this template. Reload the Project and retry.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function handleToggle(run: ProjectInvestigationTemplateRun, stepId: string) {
    setBusyId(run.id);
    setError(null);
    const completed = new Set(
      run.steps.filter((step) => step.completed).map((step) => step.id),
    );
    if (completed.has(stepId)) completed.delete(stepId);
    else completed.add(stepId);
    try {
      const updated = await updateProjectInvestigationTemplateRun(projectId, run.id, {
        expected_revision: run.revision,
        completed_step_ids: [...completed],
      });
      setRuns((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      onActivityChange();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not update workflow progress. Reload the Project and retry.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function handleLoadMoreTemplates() {
    if (loadingMoreTemplates) return;
    setLoadingMoreTemplates(true);
    setError(null);
    try {
      const next = await listProjectInvestigationTemplates(
        projectId,
        undefined,
        PAGE_SIZE,
        templates.length,
      );
      setTemplates((current) => [...current, ...next]);
      setHasMoreTemplates(next.length === PAGE_SIZE);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load more templates.");
    } finally {
      setLoadingMoreTemplates(false);
    }
  }

  async function handleLoadMoreRuns() {
    if (loadingMoreRuns) return;
    setLoadingMoreRuns(true);
    setError(null);
    try {
      const next = await listProjectInvestigationTemplateRuns(
        projectId,
        undefined,
        PAGE_SIZE,
        runs.length,
      );
      setRuns((current) => [...current, ...next]);
      setHasMoreRuns(next.length === PAGE_SIZE);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load more workflow runs.");
    } finally {
      setLoadingMoreRuns(false);
    }
  }

  return (
    <section
      id="project-investigation-templates"
      aria-label="Investigation templates"
      className="mt-5 border-t border-white/10 pt-4"
    >
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
        Investigation templates
      </h3>
      <p className="mt-2 text-[10px] leading-4 text-ink-dim">
        Save researcher-authored workflow checklists and reuse them in new Project sessions.
        Edit a template to create a new revision; existing runs keep their original checklist.
        Templates organize work only; they do not instruct or replace Engine planning.
      </p>
      {error && (
        <p className="mt-2 text-xs text-rose-200" role="alert">
          {error}
        </p>
      )}
      {!archived && (
        <form onSubmit={(event) => void handleCreate(event)} className="mt-3 grid gap-2">
          <input
            aria-label="Template title"
            maxLength={160}
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Workflow name"
            className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink"
          />
          <textarea
            aria-label="Template description"
            maxLength={2000}
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="When should this workflow be reused?"
            className="resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink"
          />
          <textarea
            aria-label="Template steps"
            required
            rows={4}
            value={stepsText}
            onChange={(event) => setStepsText(event.target.value)}
            placeholder={"One researcher-authored checklist step per line\nExample: Record the observation period"}
            className="resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink"
          />
          <button
            type="submit"
            disabled={saving || !title.trim() || stepsText.split(/\r?\n/).filter((step) => step.trim()).length > 30}
            className="justify-self-start rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink disabled:opacity-50"
          >
            {saving ? "Saving template..." : "Save reusable workflow"}
          </button>
        </form>
      )}
      {loading ? (
        <p className="mt-3 text-xs text-ink-dim" role="status">
          Loading templates...
        </p>
      ) : templates.length === 0 ? (
        <p className="mt-3 text-xs text-ink-dim">No reusable workflows have been saved.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {templates.map((template) => {
            const editing = editingTemplateId === template.id;
            return (
              <li key={template.id} className="rounded-lg bg-black/20 p-3">
                {editing ? (
                  <form
                    onSubmit={(event) => void handleUpdateTemplate(event, template)}
                    className="grid gap-2"
                  >
                    <input
                      aria-label="Edit template title"
                      maxLength={160}
                      required
                      value={editTitle}
                      onChange={(event) => setEditTitle(event.target.value)}
                      className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
                    />
                    <textarea
                      aria-label="Edit template description"
                      maxLength={2000}
                      rows={2}
                      value={editDescription}
                      onChange={(event) => setEditDescription(event.target.value)}
                      className="resize-y rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
                    />
                    <textarea
                      aria-label="Edit template steps"
                      required
                      rows={4}
                      value={editStepsText}
                      onChange={(event) => setEditStepsText(event.target.value)}
                      className="resize-y rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
                    />
                    <div className="flex gap-3 text-[10px]">
                      <button
                        type="submit"
                        disabled={
                          busyId !== null ||
                          !editTitle.trim() ||
                          editStepsText.split(/\r?\n/).filter((step) => step.trim()).length > 30
                        }
                        className="text-accent disabled:opacity-50"
                      >
                        {busyId === template.id ? "Saving..." : "Save template revision"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingTemplateId(null)}
                        disabled={busyId !== null}
                        className="text-ink-dim disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-xs font-medium text-ink">{template.title}</p>
                        <p className="mt-1 text-[9px] text-ink-dim">
                          Revision {template.revision}
                        </p>
                      </div>
                      {!archived && (
                        <div className="flex gap-2 text-[10px]">
                          <button
                            type="button"
                            onClick={() => handleBeginEdit(template)}
                            disabled={busyId !== null}
                            className="text-accent disabled:opacity-50"
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleDelete(template.id)}
                            disabled={busyId !== null}
                            className="text-rose-200 disabled:opacity-50"
                          >
                            Remove
                          </button>
                        </div>
                      )}
                    </div>
                    {template.description && (
                      <p className="mt-1 whitespace-pre-wrap text-[10px] text-ink-dim">
                        {template.description}
                      </p>
                    )}
                    <ol className="mt-2 list-decimal space-y-1 pl-4 text-[10px] text-ink-dim">
                      {template.steps.map((step) => <li key={step.id}>{step.title}</li>)}
                    </ol>
                    {!archived && (
                      <button
                        type="button"
                        onClick={() => void handleApply(template.id)}
                        disabled={busyId !== null}
                        className="mt-2 rounded-lg border border-white/10 px-3 py-1.5 text-[10px] text-ink disabled:opacity-50"
                      >
                        {busyId === template.id ? "Starting..." : "Start workflow"}
                      </button>
                    )}
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {hasMoreTemplates && (
        <button
          type="button"
          onClick={() => void handleLoadMoreTemplates()}
          disabled={loadingMoreTemplates}
          className="mt-2 text-xs text-ink-dim disabled:opacity-50"
        >
          {loadingMoreTemplates ? "Loading..." : "Load more templates"}
        </button>
      )}
      {runs.length > 0 && (
        <div className="mt-4">
          <h4 className="text-[10px] font-medium uppercase tracking-wide text-ink-dim">
            Workflow progress
          </h4>
          <ul className="mt-2 space-y-2">
            {runs.map((run) => (
              <li key={run.id} className="rounded-lg bg-black/10 p-3">
                <Link
                  to={`/s/${encodeURIComponent(run.session_id)}`}
                  className="text-xs text-accent hover:text-ink"
                >
                  {run.template_title} · Template revision {run.template_revision} · Open session
                </Link>
                <ul className="mt-2 space-y-1">
                  {run.steps.map((step) => (
                    <li key={step.id}>
                      <label className="flex items-start gap-2 text-[10px] text-ink-dim">
                        <input
                          type="checkbox"
                          checked={step.completed}
                          disabled={busyId !== null}
                          onChange={() => void handleToggle(run, step.id)}
                          aria-label={`Complete ${step.title}`}
                        />
                        <span className={step.completed ? "line-through" : ""}>{step.title}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
      {hasMoreRuns && (
        <button
          type="button"
          onClick={() => void handleLoadMoreRuns()}
          disabled={loadingMoreRuns}
          className="mt-2 text-xs text-ink-dim disabled:opacity-50"
        >
          {loadingMoreRuns ? "Loading..." : "Load more workflow runs"}
        </button>
      )}
    </section>
  );
}
