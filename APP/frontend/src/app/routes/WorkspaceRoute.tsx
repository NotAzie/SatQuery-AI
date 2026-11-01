import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { getSession, updateSessionEarthWorkspace } from "@/services/api/sessions";
import { useEarthStore } from "@/state/earthStore";
import { useSessionStore } from "@/state/sessionStore";

/**
 * `/` starts a fresh workspace, `/s/:sessionId` resumes one. The route renders nothing itself:
 * the globe and panels are persistent in AppShell; the route only selects the session.
 */
export function WorkspaceRoute() {
  const { sessionId } = useParams();
  const setActiveSession = useSessionStore((s) => s.setActiveSession);

  useEffect(() => {
    setActiveSession(sessionId ?? null);
    if (!sessionId) return () => setActiveSession(null);

    const abort = new AbortController();
    let unsubscribe: (() => void) | null = null;
    let saveTimer: ReturnType<typeof setTimeout> | null = null;
    let pendingSave = Promise.resolve();
    const scheduleSave = () => {
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        pendingSave = pendingSave
          .then(async () => {
            if (abort.signal.aborted) return;
            await updateSessionEarthWorkspace(
              sessionId,
              useSessionStore.getState().snapshotWorkspace(),
              abort.signal,
            );
            useSessionStore.getState().setPersistenceError(null);
          })
          .catch((reason: unknown) => {
            if (!abort.signal.aborted) {
              useSessionStore
                .getState()
                .setPersistenceError(
                  reason instanceof Error ? reason.message : "Could not save Earth workspace.",
                );
            }
          });
      }, 400);
    };
    void getSession(sessionId, abort.signal)
      .then((session) => {
        if (abort.signal.aborted) return;
        const current = useSessionStore.getState().snapshotWorkspace();
        const serverWorkspace = session.earth_workspace;
        const serverHasState =
          serverWorkspace.bookmarks.length > 0 ||
          serverWorkspace.camera_history.present !== null ||
          serverWorkspace.camera_history.past.length > 0 ||
          serverWorkspace.captures.length > 0;
        const localHasState =
          current.bookmarks.length > 0 ||
          current.camera_history.present !== null ||
          current.camera_history.past.length > 0 ||
          current.captures.length > 0;
        const initial = serverHasState ? serverWorkspace : current;
        useSessionStore.getState().hydrateWorkspace(initial);
        useEarthStore.getState().setCaptures(initial.captures);
        unsubscribe = useSessionStore.subscribe((state, previous) => {
          if (
            state.bookmarks === previous.bookmarks &&
            state.cameraHistory === previous.cameraHistory &&
            state.captures === previous.captures
          ) {
            return;
          }
          scheduleSave();
        });
        if (!serverHasState && localHasState) scheduleSave();
      })
      .catch((reason: unknown) => {
        if (!abort.signal.aborted) {
          useSessionStore
            .getState()
            .setPersistenceError(
              reason instanceof Error ? reason.message : "Could not load Earth workspace.",
            );
        }
      });

    return () => {
      abort.abort();
      unsubscribe?.();
      if (saveTimer) clearTimeout(saveTimer);
      setActiveSession(null);
    };
  }, [sessionId, setActiveSession]);

  return null;
}
