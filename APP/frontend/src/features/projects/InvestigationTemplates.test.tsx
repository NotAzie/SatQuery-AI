import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { InvestigationTemplates } from "./InvestigationTemplates";

describe("Project investigation templates", () => {
  it("explains the user-authored workflow boundary and exposes a checklist editor", () => {
    const markup = renderToStaticMarkup(
      createElement(
        MemoryRouter,
        null,
        createElement(InvestigationTemplates, {
          projectId: "project-1",
          archived: false,
          onActivityChange: () => undefined,
        }),
      ),
    );
    expect(markup).toContain("Investigation templates");
    expect(markup).toContain("researcher-authored workflow checklists");
    expect(markup).toContain("do not instruct or replace Engine planning");
    expect(markup).toContain('aria-label="Template steps"');
    expect(markup).toContain("Save reusable workflow");
  });

  it("does not offer workflow creation controls for archived Projects", () => {
    const markup = renderToStaticMarkup(
      createElement(
        MemoryRouter,
        null,
        createElement(InvestigationTemplates, {
          projectId: "project-1",
          archived: true,
          onActivityChange: () => undefined,
        }),
      ),
    );
    expect(markup).not.toContain('aria-label="Template steps"');
    expect(markup).not.toContain("Save reusable workflow");
  });
});
