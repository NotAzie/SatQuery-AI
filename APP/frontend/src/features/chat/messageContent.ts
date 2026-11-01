const PLATFORM_CONTEXT_MARKER = "\n\n--- Platform workspace context (JSON) ---\n";

export function visibleAgentMessage(role: string, content: string): string {
  if (role !== "user") return content;
  const marker = content.lastIndexOf(PLATFORM_CONTEXT_MARKER);
  return marker < 0 ? content : content.slice(0, marker);
}
