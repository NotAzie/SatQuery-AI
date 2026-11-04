import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  EarthContext,
  ProjectInvestigationCollectionCreate,
  ProjectInvestigationCollectionMemberUpdate,
  ProjectEarthView,
  ProjectInvestigationRelationshipCreate,
  ProjectInvestigationTemplateCreate,
  ProjectInvestigationTemplateUpdate,
  ProjectInvestigationCollectionUpdate,
} from "@/shared/types";
import {
  createProjectInvestigationCollection,
  createProjectNote,
  createProjectInvestigationComparison,
  createProjectInvestigationRelationship,
  createProjectInvestigationTemplate,
  applyProjectInvestigationTemplate,
  createProjectView,
  deleteProjectNote,
  deleteProjectInvestigationComparison,
  deleteProjectInvestigationCollection,
  deleteProjectInvestigationRelationship,
  deleteProjectInvestigationTemplate,
  deleteProjectView,
  getProjectInvestigation,
  getProjectInvestigationComparison,
  getProjectInvestigationComparisonResult,
  linkProjectMonitoringSchedule,
  listProjectActivity,
  listProjectMonitoringLinks,
  listProjectNotes,
  listProjectInvestigationComparisons,
  listProjectInvestigationCollections,
  listProjectInvestigationRelationships,
  listProjectInvestigationTemplates,
  listProjectInvestigationTemplateRuns,
  listProjectViews,
  listProjectWorkPage,
  restoreProjectEarthView,
  searchProject,
  unlinkProjectMonitoringSchedule,
  updateProjectNote,
  updateProjectInvestigationCollection,
  updateProjectInvestigationCollectionMembers,
  updateProjectInvestigationTemplate,
  updateProjectInvestigationTemplateRun,
} from "./projects";
import { apiUrl } from "./client";

describe("Project work-item API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests paginated notes and preserves revision-checked note updates", async () => {
    const note = {
      id: "note-1",
      project_id: "project/1",
      title: "Baseline",
      body: "Compare the dates",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      revision: 1,
    };
    const fetch = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify([note]), {
        headers: { "Content-Type": "application/json" },
      })),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(listProjectNotes("project/1", undefined, 10, 20)).resolves.toEqual([
      note,
    ]);
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project%2F1/notes?limit=10&offset=20"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );

    await createProjectNote("project/1", { title: "Baseline", body: "Compare the dates" });
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project%2F1/notes"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ title: "Baseline", body: "Compare the dates" }),
      }),
    );

    await updateProjectNote("project/1", "note/1", {
      expected_revision: 1,
      body: "Compare the dates and sources",
    });
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project%2F1/notes/note%2F1"),
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          expected_revision: 1,
          body: "Compare the dates and sources",
        }),
      }),
    );
  });

  it("requests notes scoped to an Engine investigation and source session", async () => {
    const fetch = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response("[]", { headers: { "Content-Type": "application/json" } }),
      ),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(
      listProjectNotes("project-1", undefined, 10, 5, {
        investigation_id: "investigation-1",
        investigation_session_id: "session-1",
      }),
    ).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/projects/project-1/notes?limit=10&offset=5&investigation_id=investigation-1&investigation_session_id=session-1",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("creates, lists, reads, and deletes Project investigation comparisons", async () => {
    const comparison = {
      id: "comparison-1",
      project_id: "project-1",
      title: "Before and after",
      left: { investigation_id: "investigation-1", session_id: "session-1" },
      right: { investigation_id: "investigation-2", session_id: "session-2" },
      created_at: "2026-01-01T00:00:00Z",
    };
    const fetch = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([comparison]), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(comparison), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(comparison), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    const body = {
      title: comparison.title,
      left: comparison.left,
      right: comparison.right,
    };

    await expect(listProjectInvestigationComparisons("project-1")).resolves.toEqual([
      comparison,
    ]);
    await expect(
      getProjectInvestigationComparison("project-1", "comparison-1"),
    ).resolves.toEqual(comparison);
    await expect(
      createProjectInvestigationComparison("project-1", body),
    ).resolves.toEqual(comparison);
    await expect(
      deleteProjectInvestigationComparison("project-1", "comparison-1"),
    ).resolves.toBeUndefined();

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      apiUrl("/projects/project-1/comparisons?limit=50&offset=0"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      apiUrl("/projects/project-1/comparisons/comparison-1"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      apiUrl("/projects/project-1/comparisons"),
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      apiUrl("/projects/project-1/comparisons/comparison-1"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("retrieves the Engine-authored result for a saved Project comparison", async () => {
    const result = { comparison_id: "engine-comparison-1", markdown: "# Compared evidence" };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(result), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(
      getProjectInvestigationComparisonResult("project/1", "comparison/1"),
    ).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/projects/project%2F1/comparisons/comparison%2F1/engine-result"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("requests Earth views scoped to an investigation and its source session", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response("[]", { headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(
      listProjectViews("project-1", undefined, 10, 5, {
        investigation_id: "investigation-1",
        source_session_id: "session-1",
      }),
    ).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/projects/project-1/views?limit=10&offset=5&investigation_id=investigation-1&source_session_id=session-1",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("opens a Project investigation by its linked source session", async () => {
    const investigation = {
      investigation_id: "investigation/1",
      session_id: "session/1",
    };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(investigation), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(
      getProjectInvestigation("project/1", "session/1", "investigation/1"),
    ).resolves.toEqual(investigation);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/projects/project%2F1/investigations/investigation%2F1?session_id=session%2F1",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("creates, lists, and deletes explicit investigation relationships", async () => {
    const relationship = {
      id: "relationship-1",
      project_id: "project/1",
      from_investigation: {
        investigation_id: "investigation-1",
        session_id: "session-1",
      },
      to_investigation: {
        investigation_id: "investigation-2",
        session_id: "session-2",
      },
      relationship_type: "follow_up_to" as const,
      rationale: "Revisit the same focus area later.",
      created_at: "2026-11-04T10:00:00Z",
    };
    const body: ProjectInvestigationRelationshipCreate = {
      from_investigation: relationship.from_investigation,
      to_investigation: relationship.to_investigation,
      relationship_type: relationship.relationship_type,
      rationale: relationship.rationale,
    };
    const fetch = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([relationship]), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(relationship), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);

    await expect(
      listProjectInvestigationRelationships("project/1", undefined, 10, 20),
    ).resolves.toEqual([relationship]);
    await expect(
      createProjectInvestigationRelationship("project/1", body),
    ).resolves.toEqual(relationship);
    await expect(
      deleteProjectInvestigationRelationship("project/1", "relationship/1"),
    ).resolves.toBeUndefined();
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      apiUrl(
        "/projects/project%2F1/investigation-relationships?limit=10&offset=20",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      apiUrl("/projects/project%2F1/investigation-relationships"),
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      apiUrl(
        "/projects/project%2F1/investigation-relationships/relationship%2F1",
      ),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("creates a saved Earth view from a linked-session bookmark reference", async () => {
    const view = {
      id: "view-1",
      project_id: "project-1",
      title: "Shoreline baseline",
      source_session_id: "session-1",
      source_bookmark_id: "bookmark-1",
      context: {},
      created_at: "2026-01-01T00:00:00Z",
    };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(view), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const body = {
      title: "Shoreline baseline",
      source_session_id: "session-1",
      source_bookmark_id: "bookmark-1",
    };

    await expect(createProjectView("project-1", body)).resolves.toEqual(view);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/projects/project-1/views"),
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
  });

  it("persists a saved view as a bookmark in its original session before reopening", async () => {
    const context: EarthContext = {
      camera: {
        position: { lng: 1, lat: 2 },
        height_m: 300,
        heading_deg: 0,
        pitch_deg: -90,
        roll_deg: 0,
        view_rect: null,
      },
      viewport: null,
      layers: [],
      time: null,
      instant: null,
      timeline_playback: { playing: false, speed: 1 },
      selection: null,
      drawings: [],
      captures: [],
      imagery: [],
      overlays: [],
      secondary_view: null,
      investigations: { known_ids: [], visible_ids: [] },
      selected_evidence_ids: [],
      bookmarks: [],
      camera_history: { past: [], present: null, future: [] },
      split_view: { enabled: false, sync_cameras: false },
      measurement: null,
    };
    const session = {
      id: "session-1",
      earth_workspace: {
        camera_history: { past: [], present: null, future: [] },
        bookmarks: [],
        captures: [],
      },
    };
    let updatedSession = session;
    const fetch = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const request = JSON.parse(String(init.body)) as {
          earth_workspace: typeof session.earth_workspace;
        };
        updatedSession = { ...session, earth_workspace: request.earth_workspace };
      }
      return Promise.resolve(
        new Response(JSON.stringify(updatedSession), {
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetch);
    const view: ProjectEarthView = {
      id: "view-1",
      project_id: "project-1",
      title: "Coastal baseline",
      source_session_id: "session-1",
      source_bookmark_id: "old-bookmark",
      investigation_id: null,
      source_session_exists: true,
      context,
      created_at: "2026-01-01T00:00:00Z",
    };

    const restored = await restoreProjectEarthView(view);
    const repeatedRestore = await restoreProjectEarthView(view);

    expect(restored.sessionId).toBe("session-1");
    expect(repeatedRestore).toEqual(restored);
    expect(fetch).toHaveBeenCalledTimes(3);
    const [url, options] = fetch.mock.calls[1] as [string, RequestInit];
    expect(url).toBe(apiUrl("/sessions/session-1"));
    expect(options.method).toBe("PATCH");
    const body = JSON.parse(String(options.body)) as {
      earth_workspace: { bookmarks: Array<{ id: string; name: string; context: unknown }> };
    };
    expect(body.earth_workspace.bookmarks).toHaveLength(1);
    expect(body.earth_workspace.bookmarks[0]).toMatchObject({
      id: restored.bookmarkId,
      name: "Coastal baseline",
      context,
    });
  });

  it("accepts empty successful responses when deleting Project work items", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);

    await expect(deleteProjectNote("project-1", "note-1")).resolves.toBeUndefined();
    await expect(deleteProjectView("project-1", "view-1")).resolves.toBeUndefined();
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      apiUrl("/projects/project-1/notes/note-1"),
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      apiUrl("/projects/project-1/views/view-1"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("requests stable paginated Project activity", async () => {
    const fetch = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response("[]", { headers: { "Content-Type": "application/json" } })),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(listProjectActivity("project-1", undefined, 25, 50)).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/projects/project-1/activity?limit=25&offset=50"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("filters Project activity by a session-qualified investigation reference", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response("[]", { headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(
      listProjectActivity("project-1", undefined, 10, 5, {
        investigation_id: "investigation/1",
        session_id: "session/1",
      }),
    ).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/projects/project-1/activity?limit=10&offset=5&investigation_id=investigation%2F1&session_id=session%2F1",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("creates, revises, and curates explicit investigation collections", async () => {
    const fetch = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response("[]", { headers: { "Content-Type": "application/json" } }),
      ),
    );
    vi.stubGlobal("fetch", fetch);
    await expect(
      listProjectInvestigationCollections("project-1", undefined, 10, 20),
    ).resolves.toEqual([]);
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project-1/investigation-collections?limit=10&offset=20"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );

    const create: ProjectInvestigationCollectionCreate = {
      title: "Coastal campaign",
      description: "Researcher-organized investigations",
    };
    await createProjectInvestigationCollection("project-1", create);
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project-1/investigation-collections"),
      expect.objectContaining({ method: "POST", body: JSON.stringify(create) }),
    );

    const update: ProjectInvestigationCollectionUpdate = {
      expected_revision: 1,
      title: "Coastal campaign 2026",
    };
    await updateProjectInvestigationCollection("project-1", "collection-1", update);
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project-1/investigation-collections/collection-1"),
      expect.objectContaining({ method: "PATCH", body: JSON.stringify(update) }),
    );

    const member: ProjectInvestigationCollectionMemberUpdate = {
      expected_revision: 2,
      operation: "add",
      investigation: { session_id: "session-1", investigation_id: "investigation-1" },
    };
    await updateProjectInvestigationCollectionMembers(
      "project-1",
      "collection-1",
      member,
    );
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project-1/investigation-collections/collection-1/members"),
      expect.objectContaining({ method: "PATCH", body: JSON.stringify(member) }),
    );

    await deleteProjectInvestigationCollection("project-1", "collection-1");
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project-1/investigation-collections/collection-1"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("creates and reuses revisioned researcher-authored investigation templates", async () => {
    const template: ProjectInvestigationTemplateCreate = {
      title: "Seasonal shoreline review",
      description: "Researcher-authored checklist",
      steps: [{ title: "Record the observation window" }],
    };
    const saved = {
      ...template,
      id: "template-1",
      project_id: "project-1",
      created_at: "2026-11-04T10:00:00Z",
      updated_at: "2026-11-04T10:00:00Z",
      steps: [{ id: "step-1", title: template.steps[0].title }],
      revision: 1,
    };
    const templateUpdate: ProjectInvestigationTemplateUpdate = {
      expected_revision: 1,
      title: "Revised workflow",
      description: "Updated checklist",
      steps: [{ title: "Check new evidence" }],
    };
    const revised = {
      ...saved,
      title: templateUpdate.title,
      description: templateUpdate.description,
      revision: 2,
      steps: [{ id: "step-2", title: "Check new evidence" }],
    };
    const run = {
      id: "run-1",
      project_id: "project-1",
      template_id: saved.id,
      template_revision: 1,
      template_title: saved.title,
      session_id: "session-1",
      steps: [{ ...saved.steps[0], completed: false }],
      created_at: saved.created_at,
      updated_at: saved.updated_at,
      revision: 1,
    };
    const updatedRun = {
      ...run,
      revision: 2,
      steps: [{ ...run.steps[0], completed: true }],
    };
    const fetch = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify([saved]), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(saved), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(revised), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(run), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([run]), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(updatedRun), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);

    await expect(listProjectInvestigationTemplates("project-1")).resolves.toEqual([saved]);
    await expect(createProjectInvestigationTemplate("project-1", template)).resolves.toEqual(saved);
    await expect(
      updateProjectInvestigationTemplate("project-1", saved.id, templateUpdate),
    ).resolves.toEqual(revised);
    await expect(applyProjectInvestigationTemplate("project-1", saved.id)).resolves.toEqual(run);
    await expect(listProjectInvestigationTemplateRuns("project-1")).resolves.toEqual([run]);
    await expect(
      updateProjectInvestigationTemplateRun("project-1", run.id, {
        expected_revision: 1,
        completed_step_ids: ["step-1"],
      }),
    ).resolves.toEqual(updatedRun);
    await expect(
      deleteProjectInvestigationTemplate("project-1", saved.id),
    ).resolves.toBeUndefined();
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      apiUrl("/projects/project-1/investigation-templates/template-1"),
      expect.objectContaining({ method: "PATCH", body: JSON.stringify(templateUpdate) }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      apiUrl("/projects/project-1/investigation-templates/template-1/apply"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      6,
      apiUrl("/projects/project-1/investigation-template-runs/run-1"),
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("searches saved Project work with a typed paginated query", async () => {
    const response = {
      project_id: "project/1",
      query: "shoreline change",
      results: [],
      total_count: 0,
      limit: 10,
      offset: 20,
    };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(
      searchProject("project/1", "shoreline change", undefined, 10, 20),
    ).resolves.toEqual(response);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/projects/project%2F1/search?query=shoreline+change&limit=10&offset=20",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("loads the session and investigation rows for one Project page together", async () => {
    const fetch = vi.fn().mockImplementation(
      () => new Response("[]", { headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(listProjectWorkPage("project-1", undefined, 25, 50)).resolves.toEqual({
      sessions: [],
      investigations: [],
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/projects/project-1/sessions?limit=25&offset=50"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/projects/project-1/investigations?limit=25&offset=50"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("does not return a partial Project page when one request fails", async () => {
    const fetch = vi.fn((input: RequestInfo | URL) =>
      String(input).includes("/investigations")
        ? Promise.reject(new Error("Engine unavailable"))
        : Promise.resolve(
            new Response("[]", { headers: { "Content-Type": "application/json" } }),
          ),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(listProjectWorkPage("project-1", undefined, 25, 50)).rejects.toThrow(
      "Engine unavailable",
    );
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("links and unlinks an existing Engine schedule by reference", async () => {
    const link = {
      project_id: "project-1",
      schedule_id: "schedule-1",
      mission_id: "mission-1",
      linked_at: "2026-01-01T00:00:00Z",
    };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([link]), {
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(link), {
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);

    await expect(listProjectMonitoringLinks("project-1", undefined, 20, 10)).resolves.toEqual([
      link,
    ]);
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project-1/monitoring-links?limit=20&offset=10"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );

    await linkProjectMonitoringSchedule("project-1", "schedule-1");
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project-1/monitoring-links"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ schedule_id: "schedule-1" }),
      }),
    );

    await unlinkProjectMonitoringSchedule("project-1", "schedule-1");
    expect(fetch).toHaveBeenLastCalledWith(
      apiUrl("/projects/project-1/monitoring-links/schedule-1"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
