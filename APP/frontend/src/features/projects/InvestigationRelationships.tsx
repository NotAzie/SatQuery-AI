import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "@/services/api/client";
import {
  createProjectInvestigationRelationship,
  deleteProjectInvestigationRelationship,
  listProjectInvestigationRelationships,
} from "@/services/api/projects";
import type {
  ProjectInvestigationRef,
  ProjectInvestigationRelationship,
  ProjectInvestigationRelationshipCreate,
  ProjectSessionLink,
} from "@/shared/types";

const PAGE_SIZE = 50;

const RELATIONSHIP_TYPES: Array<{
  value: ProjectInvestigationRelationshipCreate["relationship_type"];
  label: string;
}> = [
  { value: "related_to", label: "Related to" },
  { value: "follow_up_to", label: "Follow-up to" },
  { value: "baseline_for", label: "Baseline for" },
  { value: "context_for", label: "Context for" },
];

function isRelationshipType(
  value: string,
): value is ProjectInvestigationRelationshipCreate["relationship_type"] {
  return RELATIONSHIP_TYPES.some((item) => item.value === value);
}

function referenceKey(reference: ProjectInvestigationRef): string {
  return JSON.stringify([reference.session_id, reference.investigation_id]);
}

function investigationHref(projectId: string, reference: ProjectInvestigationRef): string {
  return `/p/${encodeURIComponent(projectId)}/investigations/${encodeURIComponent(reference.session_id)}/${encodeURIComponent(reference.investigation_id)}`;
}

export function InvestigationRelationships({
  projectId,
  investigations,
  sessions,
  archived,
}: {
  projectId: string;
  investigations: ProjectInvestigationRef[];
  sessions: ProjectSessionLink[];
  archived: boolean;
}) {
  const [relationships, setRelationships] = useState<ProjectInvestigationRelationship[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [fromKey, setFromKey] = useState("");
  const [toKey, setToKey] = useState("");
  const [relationshipType, setRelationshipType] =
    useState<ProjectInvestigationRelationshipCreate["relationship_type"]>("related_to");
  const [rationale, setRationale] = useState("");
  const [saving, setSaving] = useState(false);
  const [removingRelationshipId, setRemovingRelationshipId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadCount, setReloadCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void listProjectInvestigationRelationships(
      projectId,
      controller.signal,
      PAGE_SIZE,
    )
      .then((result) => {
        if (controller.signal.aborted) return;
        setRelationships(result);
        setHasMore(result.length === PAGE_SIZE);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          reason instanceof ApiError
            ? reason.message
            : "Could not load investigation relationships.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [projectId, reloadCount]);

  const availableInvestigations = investigations.filter(
    (reference, index, all) =>
      all.findIndex((candidate) => referenceKey(candidate) === referenceKey(reference)) === index,
  );
  const resolve = (key: string) =>
    availableInvestigations.find((reference) => referenceKey(reference) === key);
  const label = (reference: ProjectInvestigationRef) => {
    const title = sessions.find((item) => item.session_id === reference.session_id)?.session.title;
    return `${reference.investigation_id} · ${title || reference.session_id}`;
  };

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const from = resolve(fromKey);
    const to = resolve(toKey);
    const cleanRationale = rationale.trim();
    if (!from || !to || referenceKey(from) === referenceKey(to) || !cleanRationale) return;
    const body: ProjectInvestigationRelationshipCreate = {
      from_investigation: from,
      to_investigation: to,
      relationship_type: relationshipType,
      rationale: cleanRationale,
    };
    setSaving(true);
    setError(null);
    try {
      const created = await createProjectInvestigationRelationship(projectId, body);
      setRelationships((current) => [
        created,
        ...current.filter((item) => item.id !== created.id),
      ]);
      setRationale("");
      setHasMore((current) => current || relationships.length >= PAGE_SIZE);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not save this investigation relationship.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(relationshipId: string) {
    if (removingRelationshipId) return;
    setRemovingRelationshipId(relationshipId);
    setError(null);
    try {
      await deleteProjectInvestigationRelationship(projectId, relationshipId);
      setRelationships((current) => current.filter((item) => item.id !== relationshipId));
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not remove this investigation relationship.",
      );
    } finally {
      setRemovingRelationshipId(null);
    }
  }

  async function handleLoadMore() {
    if (loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const next = await listProjectInvestigationRelationships(
        projectId,
        undefined,
        PAGE_SIZE,
        relationships.length,
      );
      setRelationships((current) => [...current, ...next]);
      setHasMore(next.length === PAGE_SIZE);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load more investigation relationships.",
      );
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <section
      id="project-investigation-relationships"
      aria-label="Investigation relationships"
      className="mt-5 border-t border-white/10 pt-4"
    >
      <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-ink-dim">
        Investigation relationships
      </h3>
      <p className="mt-2 text-[10px] leading-4 text-ink-dim">
        Researcher-authored links organize investigations; they are not Engine findings or
        scientific claims.
      </p>
      {!archived && availableInvestigations.length >= 2 && (
        <form onSubmit={(event) => void handleCreate(event)} className="mt-3 grid gap-2">
          <label className="grid gap-1 text-[10px] text-ink-dim">
            From investigation
            <select
              aria-label="From investigation"
              value={fromKey}
              onChange={(event) => setFromKey(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
            >
              <option value="">Select an investigation</option>
              {availableInvestigations.map((item) => (
                <option key={referenceKey(item)} value={referenceKey(item)}>
                  {label(item)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-[10px] text-ink-dim">
            Relationship
            <select
              aria-label="Relationship type"
              value={relationshipType}
              onChange={(event) => {
                if (isRelationshipType(event.target.value)) {
                  setRelationshipType(event.target.value);
                }
              }}
              className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
            >
              {RELATIONSHIP_TYPES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-[10px] text-ink-dim">
            To investigation
            <select
              aria-label="To investigation"
              value={toKey}
              onChange={(event) => setToKey(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/20 px-2 py-2 text-xs text-ink"
            >
              <option value="">Select an investigation</option>
              {availableInvestigations.map((item) => (
                <option key={referenceKey(item)} value={referenceKey(item)}>
                  {label(item)}
                </option>
              ))}
            </select>
          </label>
          <textarea
            aria-label="Relationship rationale"
            maxLength={2000}
            required
            rows={2}
            value={rationale}
            onChange={(event) => setRationale(event.target.value)}
            placeholder="Why should these investigations be connected?"
            className="w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink outline-none focus:border-accent/60"
          />
          <button
            type="submit"
            disabled={
              saving ||
              !fromKey ||
              !toKey ||
              fromKey === toKey ||
              !rationale.trim()
            }
            className="justify-self-start rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink disabled:opacity-50"
          >
            {saving ? "Saving relationship..." : "Link investigations"}
          </button>
        </form>
      )}
      {!archived && availableInvestigations.length < 2 && (
        <p className="mt-3 text-xs text-ink-dim">
          Add at least two Engine investigations to create a relationship.
        </p>
      )}
      {error && (
        <p className="mt-2 text-xs text-rose-200" role="alert">
          {error}
          {!loading && relationships.length === 0 && (
            <button
              type="button"
              onClick={() => {
                setLoading(true);
                setReloadCount((current) => current + 1);
              }}
              className="ml-2 underline underline-offset-2"
            >
              Retry
            </button>
          )}
        </p>
      )}
      {loading ? (
        <p className="mt-3 text-xs text-ink-dim" role="status">
          Loading relationships...
        </p>
      ) : relationships.length === 0 ? (
        <p className="mt-3 text-xs text-ink-dim">No researcher-authored relationships yet.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {relationships.map((relationship) => (
            <li key={relationship.id} className="rounded-lg bg-black/20 p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="text-[10px] font-medium text-ink">
                  {relationship.relationship_type.replaceAll("_", " ")}
                </p>
                <button
                  type="button"
                  onClick={() => void handleDelete(relationship.id)}
                  aria-label={`Remove relationship ${relationship.id}`}
                  disabled={removingRelationshipId !== null}
                  className="shrink-0 text-[10px] text-rose-200 hover:text-rose-100"
                >
                  {removingRelationshipId === relationship.id ? "Removing..." : "Remove"}
                </button>
              </div>
              <p className="mt-1 break-words text-[10px] text-ink-dim">
                <Link
                  to={investigationHref(projectId, relationship.from_investigation)}
                  className="text-accent hover:text-ink"
                >
                  {label(relationship.from_investigation)}
                </Link>
                {" → "}
                <Link
                  to={investigationHref(projectId, relationship.to_investigation)}
                  className="text-accent hover:text-ink"
                >
                  {label(relationship.to_investigation)}
                </Link>
              </p>
              <p className="mt-2 whitespace-pre-wrap break-words text-[10px] leading-4 text-ink-dim">
                {relationship.rationale}
              </p>
              <p className="mt-1 text-[9px] text-ink-dim">
                Added {new Date(relationship.created_at).toLocaleString()}
              </p>
            </li>
          ))}
        </ul>
      )}
      {hasMore && (
        <button
          type="button"
          onClick={() => void handleLoadMore()}
          disabled={loadingMore}
          className="mt-2 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
        >
          {loadingMore ? "Loading..." : "Load more relationships"}
        </button>
      )}
    </section>
  );
}
