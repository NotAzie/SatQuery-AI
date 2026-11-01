import { describe, expect, it } from "vitest";

import { visibleAgentMessage } from "./messageContent";

describe("visibleAgentMessage", () => {
  it("hides the Platform-added context block from the user's transcript", () => {
    expect(
      visibleAgentMessage(
        "user",
        "Question\n\n--- Platform workspace context (JSON) ---\n{\"camera\":{}}",
      ),
    ).toBe("Question");
  });

  it("preserves ordinary user text and all assistant messages", () => {
    const text = "A regular message";
    expect(visibleAgentMessage("user", text)).toBe(text);
    expect(visibleAgentMessage("assistant", text)).toBe(text);
  });
});
