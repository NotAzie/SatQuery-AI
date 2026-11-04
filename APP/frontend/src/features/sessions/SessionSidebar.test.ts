import { describe, expect, it } from "vitest";

import { isProjectSubmissionDisabled } from "./SessionSidebar";

describe("Project creation form", () => {
  it("enables submission for a non-empty title when creation is not in progress", () => {
    expect(isProjectSubmissionDisabled("  ", false)).toBe(true);
    expect(isProjectSubmissionDisabled("Field survey", false)).toBe(false);
    expect(isProjectSubmissionDisabled("Field survey", true)).toBe(true);
  });
});
