import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "@/services/api/client";
import {
  createProjectInvestigationCollection,
  deleteProjectInvestigationCollection,
  listProjectInvestigationCollections,
  updateProjectInvestigationCollection,
  updateProjectInvestigationCollectionMembers,
} from "@/services/api/projects";
import type {
  ProjectInvestigationCollection,
  ProjectInvestigationRef,
  ProjectSessionLink,
} from "@/shared/types";

const PAGE_SIZE = 50;

function referenceKey(reference: ProjectInvestigationRef): string {
  return JSON.stringify([reference.session_id, reference.investigation_id]);
}

function investigationHref(projectId: string, reference: ProjectInvestigationRef): string {
  return `/p/${encodeURIComponent(projectId)}/investigations/${encodeURIComponent(reference.session_id)}/${encodeURIComponent(reference.investigation_id)}`;
}

export function InvestigationCollections({
  projectId,
  investigations,
  sessions,
  archived,
  onActivityChange,
}: {
  projectId: string;
  investigations: ProjectInvestigationRef[];
  sessions: ProjectSessionLink[];
  archived: boolean;
  onActivityChange: () => void;
}) {
  const [collections, setCollections] = useState<ProjectInvestigationCollection[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [selectedMembers, setSelectedMembers] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void listProjectInvestigationCollections(projectId, controller.signal, PAGE_SIZE)
      .then((result) => {
        if (controller.signal.aborted) return;
        setCollections(result);
        setHasMore(result.length === PAGE_SIZE);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          reason instanceof ApiError
            ? reason.message
            : "Could not load investigation collections.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [projectId]);

  const availableInvestigations = investigations.filter(
    (reference, index, all) =>
      all.findIndex((candidate) => referenceKey(candidate) === referenceKey(reference)) === index,
  );
  const label = (reference: ProjectInvestigationRef) => {
    const title = sessions.find((item) => item.session_id === reference.session_id)?.session.title;
    return `${reference.investigation_id} · ${title || reference.session_id}`;
  };

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const created = await createProjectInvestigationCollection(projectId, {
        title: title.trim(),
        description: description.trim(),
      });
      setCollections((current) => [created, ...current]);
      setHasMore((current) => current || collections.length >= PAGE_SIZE);
      setTitle("");
      setDescription("");
      onActivityChange();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not create this investigation collection.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleSave(collection: ProjectInvestigationCollection) {
    if (!editTitle.trim()) return;
    setBusyId(collection.id);
    setError(null);
    try {
      const updated = await updateProjectInvestigationCollection(projectId, collection.id, {
        expected_revision: collection.revision,
        title: editTitle.trim(),
        description: editDescription.trim(),
      });
      setCollections((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setEditingId(null);
      onActivityChange();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not update this collection. Reload the Project and retry.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function handleMemberChange(
    collection: ProjectInvestigationCollection,
    operation: "add" | "remove",
    investigation: ProjectInvestigationRef,
  ) {
    setBusyId(collection.id);
    setError(null);
    try {
      const updated = await updateProjectInvestigationCollectionMembers(
        projectId,
        collection.id,
        {
          expected_revision: collection.revision,
          operation,
          investigation,
        },
      );
      setCollections((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setSelectedMembers((current) => ({ ...current, [collection.id]: "" }));
      onActivityChange();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not update collection membership. Reload the Project and retry.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(collection: ProjectInvestigationCollection) {
    setBusyId(collection.id);
    setError(null);
    try {
      await deleteProjectInvestigationCollection(projectId, collection.id);
      setCollections((current) => current.filter((item) => item.id !== collection.id));
      onActivityChange();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not delete this collection.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function handleLoadMore() {
    if (loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const next = await listProjectInvestigationCollections(
        projectId,
        undefined,
        PAGE_SIZE,
        collections.length,
      );
      setCollections((current) => [...current, ...next]);
      setHasMore(next.length === PAGE_SIZE);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load more investigation collections.",
      );
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <section
      id="project-investigation-collections"
      aria-label="Investigation collections"
      className="mt-5 border-t border-white/10 pt-4"
    >
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
        Investigation collections
      </h3>
      <p className="mt-2 text-[10px] leading-4 text-ink-dim">
        Curate explicit groups of Engine investigations for a research campaign or review.
        Collections organize references only; they do not infer relationships or scientific meaning.
      </p>
      {error && (
        <p className="mt-2 text-xs text-rose-200" role="alert">
          {error}
        </p>
      )}
      {!archived && (
        <form onSubmit={(event) => void handleCreate(event)} className="mt-3 grid gap-2">
          <input
            aria-label="Collection title"
            maxLength={160}
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Campaign or collection name"
            className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink"
          />
          <textarea
            aria-label="Collection description"
            maxLength={4000}
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Researcher-authored purpose or scope"
            className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink"
          />
          <button
            type="submit"
            disabled={saving || !title.trim()}
            className="justify-self-start rounded-lg bg-accent px-3 py-2 text-xs font-medium text-black disabled:opacity-50"
          >
            {saving ? "Creating..." : "Create collection"}
          </button>
        </form>
      )}
      {loading ? (
        <p className="mt-3 text-xs text-ink-dim" role="status">
          Loading collections...
        </p>
      ) : collections.length === 0 ? (
        <p className="mt-3 text-xs text-ink-dim">No investigation collections yet.</p>
      ) : (
        <div className="mt-3 space-y-3">
          {collections.map((collection) => {
            const memberKeys = new Set(collection.investigations.map(referenceKey));
            const availableToAdd = availableInvestigations.filter(
              (reference) => !memberKeys.has(referenceKey(reference)),
            );
            const editing = editingId === collection.id;
            const busy = busyId === collection.id;
            return (
              <article
                key={collection.id}
                id={`investigation-collection-${encodeURIComponent(collection.id)}`}
                className="rounded-lg border border-white/10 bg-black/20 p-3"
              >
                {editing ? (
                  <div className="grid gap-2">
                    <input
                      aria-label={`Edit ${collection.title} title`}
                      maxLength={160}
                      value={editTitle}
                      onChange={(event) => setEditTitle(event.target.value)}
                      className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
                    />
                    <textarea
                      aria-label={`Edit ${collection.title} description`}
                      maxLength={4000}
                      rows={2}
                      value={editDescription}
                      onChange={(event) => setEditDescription(event.target.value)}
                      className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
                    />
                    <div className="flex gap-3 text-[10px]">
                      <button
                        type="button"
                        disabled={busy || !editTitle.trim()}
                        onClick={() => void handleSave(collection)}
                        className="text-accent disabled:opacity-50"
                      >
                        Save changes
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => setEditingId(null)}
                        className="text-ink-dim disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h4 className="break-words text-xs font-medium text-ink">
                          {collection.title}
                        </h4>
                        {collection.description && (
                          <p className="mt-1 break-words text-[10px] leading-4 text-ink-dim">
                            {collection.description}
                          </p>
                        )}
                        <p className="mt-1 text-[9px] text-ink-dim">
                          {collection.investigations.length} investigation
                          {collection.investigations.length === 1 ? "" : "s"} · revision{" "}
                          {collection.revision}
                        </p>
                      </div>
                      {!archived && (
                        <div className="flex shrink-0 gap-2 text-[10px]">
                          <button
                            type="button"
                            onClick={() => {
                              setEditingId(collection.id);
                              setEditTitle(collection.title);
                              setEditDescription(collection.description);
                            }}
                            className="text-accent"
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void handleDelete(collection)}
                            className="text-rose-200 disabled:opacity-50"
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                    {collection.investigations.length > 0 ? (
                      <ul className="mt-2 space-y-1">
                        {collection.investigations.map((reference) => (
                          <li
                            key={referenceKey(reference)}
                            className="flex items-center justify-between gap-2 text-[10px]"
                          >
                            <Link
                              to={investigationHref(projectId, reference)}
                              className="truncate text-accent hover:text-ink"
                            >
                              {label(reference)}
                            </Link>
                            {!archived && (
                              <button
                                type="button"
                                disabled={busy}
                                aria-label={`Remove ${reference.investigation_id} from ${collection.title}`}
                                onClick={() =>
                                  void handleMemberChange(collection, "remove", reference)
                                }
                                className="shrink-0 text-rose-200 disabled:opacity-50"
                              >
                                Remove
                              </button>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-2 text-[10px] text-ink-dim">
                        No investigations in this collection.
                      </p>
                    )}
                    {!archived && availableToAdd.length > 0 && (
                      <label className="mt-3 grid gap-1 text-[10px] text-ink-dim">
                        Add a Project investigation
                        <select
                          aria-label={`Add investigation to ${collection.title}`}
                          value={selectedMembers[collection.id] ?? ""}
                          disabled={busy}
                          onChange={(event) =>
                            setSelectedMembers((current) => ({
                              ...current,
                              [collection.id]: event.target.value,
                            }))
                          }
                          className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
                        >
                          <option value="">Select an investigation</option>
                          {availableToAdd.map((reference) => (
                            <option key={referenceKey(reference)} value={referenceKey(reference)}>
                              {label(reference)}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          disabled={busy || !selectedMembers[collection.id]}
                          onClick={() => {
                            const selected = availableToAdd.find(
                              (reference) =>
                                referenceKey(reference) === selectedMembers[collection.id],
                            );
                            if (selected) {
                              void handleMemberChange(collection, "add", selected);
                            }
                          }}
                          className="justify-self-start text-accent disabled:opacity-50"
                        >
                          Add investigation
                        </button>
                      </label>
                    )}
                  </>
                )}
              </article>
            );
          })}
        </div>
      )}
      {hasMore && (
        <button
          type="button"
          onClick={() => void handleLoadMore()}
          disabled={loadingMore}
          className="mt-2 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
        >
          {loadingMore ? "Loading..." : "Load older collections"}
        </button>
      )}
    </section>
  );
}
