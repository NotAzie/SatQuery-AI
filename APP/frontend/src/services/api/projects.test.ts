import { afterEach, describe, expect, it, vi } from "vitest";

import type { EarthContext, ProjectEarthView } from "@/shared/types";
import {
  createProjectNote,
  createProjectInvestigationComparison,
  createProjectView,
  deleteProjectNote,
  deleteProjectInvestigationComparison,
  deleteProjectView,
  getProjectInvestigation,
  getProjectInvestigationComparison,
  getProjectInvestigationComparisonResult,
  linkProjectMonitoringSchedule,
  listProjectActivity,
  listProjectMonitoringLinks,
  listProjectNotes,
  listProjectInvestigationComparisons,
  listProjectViews,
  listProjectWorkPage,
  restoreProjectEarthView,
  unlinkProjectMonitoringSchedule,
  updateProjectNote,
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
    const fetch = vi.fn().mockResolvedValue(
      new Response("[]", { headers: { "Content-Type": "application/json" } }),
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
