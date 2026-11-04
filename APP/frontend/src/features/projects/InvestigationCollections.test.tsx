import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { InvestigationCollections } from "./InvestigationCollections";

describe("Project investigation collections", () => {
  it("explains explicit collection ownership and exposes researcher organization controls", () => {
    const markup = renderToStaticMarkup(
      createElement(InvestigationCollections, {
        projectId: "project-1",
        archived: false,
        investigations: [
          { investigation_id: "investigation-1", session_id: "session-1" },
        ],
        sessions: [],
        onActivityChange: () => undefined,
      }),
    );
    expect(markup).toContain("Investigation collections");
    expect(markup).toContain("Curate explicit groups of Engine investigations");
    expect(markup).toContain("do not infer relationships or scientific meaning");
    expect(markup).toContain('aria-label="Collection title"');
    expect(markup).toContain("Create collection");
  });

  it("does not offer collection creation controls for archived Projects", () => {
    const markup = renderToStaticMarkup(
      createElement(InvestigationCollections, {
        projectId: "project-1",
        archived: true,
        investigations: [],
        sessions: [],
        onActivityChange: () => undefined,
      }),
    );
    expect(markup).not.toContain('aria-label="Collection title"');
    expect(markup).not.toContain("Create collection");
  });
});
