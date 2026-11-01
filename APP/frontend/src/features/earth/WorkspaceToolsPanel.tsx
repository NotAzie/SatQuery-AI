import { useState, type FormEvent } from "react";

import { useEarthController } from "@/hooks/useEarth";
import { useEarthStore, snapshotEarthContext } from "@/state/earthStore";
import { useSessionStore } from "@/state/sessionStore";
import type { DrawingKind, MeasurementKind } from "@/earth/workspace/types";

const drawingKinds: DrawingKind[] = ["point", "line", "polygon", "rectangle", "circle"];
const measurementKinds: MeasurementKind[] = ["distance", "area", "coordinates", "elevation"];

function message(error: unknown): string {
  return error instanceof Error ? error.message : "The Earth workspace action failed.";
}

export function WorkspaceToolsPanel() {
  const controller = useEarthController();
  const camera = useEarthStore((state) => state.camera);
  const selection = useEarthStore((state) => state.selection);
  const drawings = useEarthStore((state) => state.drawings);
  const measurement = useEarthStore((state) => state.measurement);
  const splitView = useEarthStore((state) => state.splitView);
  const syncCameras = useEarthStore((state) => state.syncCameras);
  const setSplitView = useEarthStore((state) => state.setSplitView);
  const setSyncCameras = useEarthStore((state) => state.setSyncCameras);
  const bookmarks = useSessionStore((state) => state.bookmarks);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const persistenceError = useSessionStore((state) => state.persistenceError);
  const undoCamera = useSessionStore((state) => state.undoCamera);
  const redoCamera = useSessionStore((state) => state.redoCamera);
  const addBookmark = useSessionStore((state) => state.addBookmark);
  const renameBookmark = useSessionStore((state) => state.renameBookmark);
  const updateBookmark = useSessionStore((state) => state.updateBookmark);
  const deleteBookmark = useSessionStore((state) => state.deleteBookmark);
  const history = useSessionStore((state) => state.cameraHistory);
  const [bookmarkName, setBookmarkName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function run(action: () => void) {
    try {
      action();
      setError(null);
    } catch (reason) {
      setError(message(reason));
    }
  }

  function saveBookmark(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const context = snapshotEarthContext();
    if (!context) {
      setError("The Earth camera is not ready yet.");
      return;
    }
    try {
      addBookmark(bookmarkName, context);
      setBookmarkName("");
      setError(null);
    } catch (reason) {
      setError(message(reason));
    }
  }

  return (
    <section
      aria-label="Earth workspace tools"
      className="pointer-events-auto max-h-[min(74vh,52rem)] w-72 overflow-y-auto rounded-2xl border border-white/10 bg-surface/95 p-3 text-ink shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      <header className="mb-3">
        <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
          Earth workspace
        </p>
        <h2 className="mt-1 text-sm font-semibold">Navigation & tools</h2>
      </header>

      <section aria-label="Camera history" className="border-t border-white/10 py-3">
        <h3 className="mb-2 text-xs font-medium">Camera history</h3>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={!history.present || history.past.length === 0 || !controller}
            onClick={() => {
              run(() => {
                const previous = undoCamera();
                if (previous) controller?.camera.restore(previous);
              });
            }}
            className="flex-1 rounded-lg border border-white/10 px-2 py-1.5 text-xs disabled:opacity-40"
          >
            Undo
          </button>
          <button
            type="button"
            disabled={!history.future.length || !controller}
            onClick={() => {
              run(() => {
                const next = redoCamera();
                if (next) controller?.camera.restore(next);
              });
            }}
            className="flex-1 rounded-lg border border-white/10 px-2 py-1.5 text-xs disabled:opacity-40"
          >
            Redo
          </button>
        </div>
      </section>

      <section aria-label="Earth bookmarks" className="border-t border-white/10 py-3">
        <h3 className="mb-2 text-xs font-medium">Bookmarks</h3>
        <form className="flex gap-2" onSubmit={saveBookmark}>
          <input
            value={bookmarkName}
            onChange={(event) => setBookmarkName(event.target.value)}
            aria-label="Bookmark name"
            placeholder="Name this view"
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={!activeSessionId || !camera || !bookmarkName.trim()}
            className="rounded-lg border border-white/10 px-2 py-1.5 text-xs disabled:opacity-40"
          >
            Save
          </button>
        </form>
        <ul className="mt-2 space-y-1">
          {bookmarks.map((bookmark) => (
            <li key={bookmark.id} className="rounded-lg bg-white/[0.03] p-2">
              <p className="truncate text-xs font-medium">{bookmark.name}</p>
              <p className="mb-2 mt-1 text-[10px] text-ink-dim">
                {bookmark.context.camera.position.lat.toFixed(3)},{" "}
                {bookmark.context.camera.position.lng.toFixed(3)}
              </p>
              <div className="flex flex-wrap gap-1">
                <button
                  type="button"
                  className="rounded border border-white/10 px-2 py-1 text-[10px]"
                  onClick={() =>
                    run(() => controller?.camera.restore(bookmark.context.camera))
                  }
                >
                  Fly to
                </button>
                <button
                  type="button"
                  className="rounded border border-white/10 px-2 py-1 text-[10px]"
                  onClick={() => {
                    const name = window.prompt("Rename bookmark", bookmark.name);
                    if (name !== null) run(() => renameBookmark(bookmark.id, name));
                  }}
                >
                  Rename
                </button>
                <button
                  type="button"
                  className="rounded border border-white/10 px-2 py-1 text-[10px]"
                  onClick={() => {
                    const context = snapshotEarthContext();
                    if (context) run(() => updateBookmark(bookmark.id, context));
                  }}
                >
                  Update
                </button>
                <button
                  type="button"
                  className="rounded border border-rose-300/20 px-2 py-1 text-[10px] text-rose-200"
                  onClick={() => run(() => deleteBookmark(bookmark.id))}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
          {bookmarks.length === 0 && (
            <li className="py-1 text-[10px] text-ink-dim">No saved views in this session.</li>
          )}
        </ul>
      </section>

      <section aria-label="Earth selection" className="border-t border-white/10 py-3">
        <h3 className="mb-1 text-xs font-medium">Selection</h3>
        {selection ? (
          <p className="break-all text-[10px] text-ink-dim">
            {selection.entity_id}
            {selection.position &&
              ` · ${selection.position.lat.toFixed(4)}, ${selection.position.lng.toFixed(4)}`}
          </p>
        ) : (
          <p className="text-[10px] text-ink-dim">Select an entity on the globe.</p>
        )}
      </section>

      <section aria-label="Drawing tools" className="border-t border-white/10 py-3">
        <h3 className="mb-2 text-xs font-medium">Presentation drawings</h3>
        <div className="flex flex-wrap gap-1">
          {drawingKinds.map((kind) => (
            <button
              key={kind}
              type="button"
              onClick={() => controller?.workspace.startDrawing(kind)}
              disabled={!controller}
              className="rounded-lg border border-white/10 px-2 py-1.5 text-[10px] capitalize disabled:opacity-40"
            >
              {kind}
            </button>
          ))}
          <button
            type="button"
            onClick={() => run(() => controller?.workspace.finishDrawing())}
            disabled={!controller}
            className="rounded-lg border border-accent/30 px-2 py-1.5 text-[10px] disabled:opacity-40"
          >
            Finish
          </button>
          <button
            type="button"
            onClick={() => controller?.workspace.cancelInteraction()}
            disabled={!controller}
            className="rounded-lg border border-white/10 px-2 py-1.5 text-[10px] disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
        <ul className="mt-2 space-y-1">
          {drawings.map((drawing) => (
            <li key={drawing.id} className="flex items-center justify-between gap-2 text-[10px]">
              <span className="truncate">{drawing.name}</span>
              <button
                type="button"
                aria-label={`Delete ${drawing.name}`}
                onClick={() =>
                  controller?.workspace.replaceDrawings(
                    drawings.filter((item) => item.id !== drawing.id),
                  )
                }
                className="text-rose-200"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[9px] text-ink-dim">
          Drawings are local presentation objects; they never start Engine work.
        </p>
      </section>

      <section aria-label="Measurement tools" className="border-t border-white/10 py-3">
        <h3 className="mb-2 text-xs font-medium">Measurements</h3>
        <div className="flex flex-wrap gap-1">
          {measurementKinds.map((kind) => (
            <button
              key={kind}
              type="button"
              onClick={() => controller?.workspace.startMeasurement(kind)}
              disabled={!controller}
              className="rounded-lg border border-white/10 px-2 py-1.5 text-[10px] capitalize disabled:opacity-40"
            >
              {kind}
            </button>
          ))}
          <button
            type="button"
            onClick={() => controller?.workspace.cancelInteraction()}
            disabled={!controller}
            className="rounded-lg border border-white/10 px-2 py-1.5 text-[10px] disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
        {measurement && (
          <p className="mt-2 text-[10px] text-ink-dim" role="status">
            {measurement.value === null
              ? measurement.kind === "elevation"
                ? "Elevation is unavailable at this location."
                : `${measurement.position.lat.toFixed(5)}, ${measurement.position.lng.toFixed(5)}`
              : `${measurement.value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${measurement.unit}`}
          </p>
        )}
        {measurement?.kind === "area" && (
          <p className="mt-1 text-[9px] text-ink-dim">Right-click to finish the area measurement.</p>
        )}
      </section>

      <section aria-label="Split view settings" className="border-t border-white/10 py-3">
        <h3 className="mb-2 text-xs font-medium">Split view</h3>
        <label className="flex items-center gap-2 text-[10px] text-ink-dim">
          <input
            type="checkbox"
            checked={splitView}
            onChange={(event) => setSplitView(event.target.checked)}
          />
          Show second globe
        </label>
        <label className="mt-2 flex items-center gap-2 text-[10px] text-ink-dim">
          <input
            type="checkbox"
            checked={syncCameras}
            disabled={!splitView}
            onChange={(event) => setSyncCameras(event.target.checked)}
          />
          Synchronize cameras
        </label>
      </section>

      {error && (
        <p className="border-t border-rose-300/15 pt-2 text-[10px] text-rose-200" role="alert">
          {error}
        </p>
      )}
      {persistenceError && (
        <p className="border-t border-rose-300/15 pt-2 text-[10px] text-rose-200" role="alert">
          Workspace persistence: {persistenceError}
        </p>
      )}
    </section>
  );
}
