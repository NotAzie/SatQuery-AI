import type { Unsubscribe } from "./utils";

/**
 * Observable registry behind every frontend extension point (panels, layer renderers, ...).
 * Entries carry an owner so a plugin's contributions can be removed together.
 * `list()` returns a referentially stable snapshot, as `useSyncExternalStore` requires.
 */
export class Registry<T extends { id: string }> {
  private entries = new Map<string, { item: T; owner: string }>();
  private listeners = new Set<() => void>();
  private snapshot: readonly T[] = [];

  constructor(private readonly kind: string) {}

  register(item: T, owner = "core"): Unsubscribe {
    if (this.entries.has(item.id)) {
      throw new Error(`${this.kind} '${item.id}' is already registered`);
    }
    this.entries.set(item.id, { item, owner });
    this.publish();
    return () => this.remove(item.id);
  }

  unregisterOwner(owner: string): void {
    for (const [id, entry] of this.entries) {
      if (entry.owner === owner) this.entries.delete(id);
    }
    this.publish();
  }

  get(id: string): T | undefined {
    return this.entries.get(id)?.item;
  }

  list = (): readonly T[] => this.snapshot;

  subscribe = (listener: () => void): Unsubscribe => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private remove(id: string): void {
    if (this.entries.delete(id)) this.publish();
  }

  private publish(): void {
    this.snapshot = [...this.entries.values()].map((e) => e.item);
    this.listeners.forEach((l) => l());
  }
}
