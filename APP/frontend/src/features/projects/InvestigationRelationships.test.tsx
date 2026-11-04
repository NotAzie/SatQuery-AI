import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { InvestigationRelationships } from "./InvestigationRelationships";

describe("Project investigation relationships", () => {
  it("labels relationships as user-authored organization and offers explicit typed options", () => {
    const markup = renderToStaticMarkup(
      createElement(InvestigationRelationships, {
        projectId: "project-1",
        archived: false,
        investigations: [
          { investigation_id: "investigation-1", session_id: "session-1" },
          { investigation_id: "investigation-2", session_id: "session-2" },
        ],
        sessions: [
          {
            project_id: "project-1",
            session_id: "session-1",
            linked_at: "2026-11-04T10:00:00Z",
            session: {
              id: "session-1",
              title: "Baseline",
              engine_agent_session_id: null,
              created_at: "2026-11-04T10:00:00Z",
              updated_at: "2026-11-04T10:00:00Z",
              context: {
                focus_region: null,
                focus_time: null,
                active_investigation_ids: [],
                pinned_evidence_ids: [],
                notes: {},
              },
              earth_workspace: {
                camera_history: { past: [], present: null, future: [] },
                bookmarks: [],
                captures: [],
              },
              earth_context_snapshots: [],
              archived: false,
            },
          },
          {
            project_id: "project-1",
            session_id: "session-2",
            linked_at: "2026-11-04T10:00:00Z",
            session: {
              id: "session-2",
              title: "Follow-up",
              engine_agent_session_id: null,
              created_at: "2026-11-04T10:00:00Z",
              updated_at: "2026-11-04T10:00:00Z",
              context: {
                focus_region: null,
                focus_time: null,
                active_investigation_ids: [],
                pinned_evidence_ids: [],
                notes: {},
              },
              earth_workspace: {
                camera_history: { past: [], present: null, future: [] },
                bookmarks: [],
                captures: [],
              },
              earth_context_snapshots: [],
              archived: false,
            },
          },
        ],
      }),
    );

    expect(markup).toContain("Researcher-authored links organize investigations");
    expect(markup).toContain("not Engine findings or scientific claims");
    expect(markup).toContain('aria-label="Relationship rationale"');
    expect(markup).toContain("Follow-up to");
    expect(markup).toContain("Baseline");
    expect(markup).toContain("Follow-up");
  });
});
