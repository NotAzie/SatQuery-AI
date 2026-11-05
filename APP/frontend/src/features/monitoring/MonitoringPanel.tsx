import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/services/api/client";
import {
  createMission,
  createMonitoringSchedule,
  compareMonitoringSchedule,
  acknowledgeMonitoringNotification,
  getMonitoringTriggers,
  listMissions,
  listMonitoringNotifications,
  listMonitoringRuns,
  listMonitoringSchedules,
  reviseMonitoringSchedule,
  setMonitoringScheduleEnabled,
} from "@/services/api/monitoring";
import type {
  EngineMission,
  EngineMonitoringComparison,
  EngineMonitoringNotification,
  EngineMonitoringRun,
  EngineMonitoringSchedule,
  EngineMonitoringTriggerHistory,
  EngineMonitoringTriggerPolicy,
} from "@/shared/types";
import {
  buildMonitoringScheduleUpdate,
  canEditMonitoringBounds,
  monitoringScheduleDraft,
  parseRollingWindowHours,
  parseTriggerOperator,
  parseWgs84Bounds,
  triggerPolicyDraft,
  type MonitoringScheduleDraft,
  type TriggerPolicyDraft,
} from "./form";
import { appendTriggerHistoryPage } from "./history";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "The monitoring request failed.";
}

function timestamp(value: string): string {
  return new Date(value).toLocaleString();
}

export function MonitoringPanel({ embedded = false }: { embedded?: boolean }) {
  const [open, setOpen] = useState(embedded);
  const [missions, setMissions] = useState<EngineMission[]>([]);
  const [schedules, setSchedules] = useState<EngineMonitoringSchedule[]>([]);
  const [notifications, setNotifications] = useState<EngineMonitoringNotification[]>([]);
  const [selectedMissionId, setSelectedMissionId] = useState("");
  const [runsBySchedule, setRunsBySchedule] = useState<
    Record<string, EngineMonitoringRun[]>
  >({});
  const [comparisons, setComparisons] = useState<
    Record<string, EngineMonitoringComparison>
  >({});
  const [triggerHistories, setTriggerHistories] = useState<
    Record<string, EngineMonitoringTriggerHistory>
  >({});
  const [loading, setLoading] = useState(true);
  const [loadingRuns, setLoadingRuns] = useState<string | null>(null);
  const [loadingComparison, setLoadingComparison] = useState<string | null>(null);
  const [loadingTriggers, setLoadingTriggers] = useState<string | null>(null);
  const [acknowledgingNotification, setAcknowledgingNotification] = useState<string | null>(
    null,
  );
  const [busySchedule, setBusySchedule] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missionName, setMissionName] = useState("");
  const [missionObjective, setMissionObjective] = useState("");
  const [scheduleName, setScheduleName] = useState("");
  const [bbox, setBbox] = useState("");
  const [variables, setVariables] = useState("");
  const [intervalHours, setIntervalHours] = useState("24");
  const [rollingWindowHours, setRollingWindowHours] = useState("");
  const [triggerEnabled, setTriggerEnabled] = useState(false);
  const [triggerName, setTriggerName] = useState("");
  const [triggerVariable, setTriggerVariable] = useState("");
  const [triggerUnit, setTriggerUnit] = useState("");
  const [triggerOperator, setTriggerOperator] =
    useState<EngineMonitoringTriggerPolicy["operator"]>("gte");
  const [triggerThreshold, setTriggerThreshold] = useState("");
  const [creating, setCreating] = useState(false);
  const [editingSchedule, setEditingSchedule] =
    useState<EngineMonitoringSchedule | null>(null);
  const [scheduleEditDraft, setScheduleEditDraft] =
    useState<MonitoringScheduleDraft | null>(null);
  const [policyDrafts, setPolicyDrafts] = useState<TriggerPolicyDraft[]>([]);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [missionList, scheduleList, notificationList] = await Promise.all([
        listMissions(signal),
        listMonitoringSchedules(signal),
        listMonitoringNotifications({}, signal),
      ]);
      if (signal?.aborted) return;
      setMissions(missionList);
      setSchedules(scheduleList);
      setNotifications(notificationList);
      setSelectedMissionId((current) =>
        missionList.some((mission) => mission.mission_id === current)
          ? current
          : missionList.find((mission) => mission.status === "active")?.mission_id ?? "",
      );
      setError(null);
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(errorText(reason));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      listMissions(controller.signal),
      listMonitoringSchedules(controller.signal),
      listMonitoringNotifications({}, controller.signal),
    ])
      .then(([missionList, scheduleList, notificationList]) => {
        if (controller.signal.aborted) return;
        setMissions(missionList);
        setSchedules(scheduleList);
        setNotifications(notificationList);
        setSelectedMissionId(
          missionList.find((mission) => mission.status === "active")?.mission_id ?? "",
        );
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(errorText(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  async function handleCreateMission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const mission = await createMission({
        name: missionName.trim(),
        objective: missionObjective.trim(),
      });
      setMissions((current) => [mission, ...current]);
      setSelectedMissionId(mission.mission_id);
      setMissionName("");
      setMissionObjective("");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setCreating(false);
    }
  }

  async function handleCreateSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const bounds = parseWgs84Bounds(bbox);
    const hours = Number(intervalHours);
    const windowSeconds = parseRollingWindowHours(rollingWindowHours);
    const threshold = Number(triggerThreshold);
    if (!bounds) {
      setError("Enter a valid WGS 84 bounding box.");
      return;
    }
    if (!Number.isFinite(hours) || hours <= 0) {
      setError("Enter a positive schedule interval.");
      return;
    }
    if (windowSeconds === undefined) {
      setError("Enter a positive rolling window duration, or leave it blank.");
      return;
    }
    if (
      triggerEnabled &&
      (!triggerName.trim() ||
        !triggerVariable.trim() ||
        !triggerUnit.trim() ||
        !triggerThreshold.trim() ||
        !Number.isFinite(threshold))
    ) {
      setError("Complete all trigger policy fields with a finite threshold.");
      return;
    }
    if (triggerEnabled && triggerOperator.startsWith("abs_") && threshold < 0) {
      setError("An absolute-value trigger threshold cannot be negative.");
      return;
    }
    if (!selectedMissionId || !scheduleName.trim()) {
      setError("Select an active mission and provide a schedule name.");
      return;
    }

    setCreating(true);
    setError(null);
    try {
      const queryVariables = variables
        .split(",")
        .map((variable) => variable.trim())
        .filter(Boolean);
      const earthQuery = {
        bbox: bounds,
        point: null,
        geometry: null,
        temporal_start: null,
        temporal_end: null,
        crs: "OGC:CRS84",
        spatial_resolution: null,
        resolution_unit: null,
        requested_dataset_ids: [],
        requested_variables: queryVariables,
        requested_modalities: [],
        required_capabilities: [],
        region: null,
        filters: {},
        asset_preferences: [],
        asset_sampling: null,
        raster_analysis: null,
        raster_pixel_selection: null,
        raster_weighting: null,
        raster_semantics: {},
        raster_component_extraction: [],
      };
      const triggerPolicies: EngineMonitoringTriggerPolicy[] = triggerEnabled
        ? [
            {
              policy_id: crypto.randomUUID(),
              name: triggerName.trim(),
              canonical_variable: triggerVariable.trim(),
              unit: triggerUnit.trim(),
              operator: triggerOperator,
              threshold,
              follow_up_query: earthQuery,
              cooldown_seconds: 0,
              max_attempts: 1,
              retry_safe: false,
            },
          ]
        : [];
      const schedule = await createMonitoringSchedule({
        mission_id: selectedMissionId,
        name: scheduleName.trim(),
        earth_query: earthQuery,
        interval_seconds: Math.round(hours * 3600),
        rolling_window_seconds: windowSeconds,
        priority: 0,
        overlap_policy: "skip_while_running",
        trigger_policies: triggerPolicies,
      });
      setSchedules((current) => [schedule, ...current]);
      setScheduleName("");
      setBbox("");
      setVariables("");
      setRollingWindowHours("");
      setTriggerEnabled(false);
      setTriggerName("");
      setTriggerVariable("");
      setTriggerUnit("");
      setTriggerThreshold("");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setCreating(false);
    }
  }

  async function toggleSchedule(schedule: EngineMonitoringSchedule) {
    setBusySchedule(schedule.schedule_id);
    setError(null);
    try {
      const updated = await setMonitoringScheduleEnabled(
        schedule.schedule_id,
        !schedule.enabled,
      );
      setSchedules((current) =>
        current.map((item) =>
          item.schedule_id === updated.schedule_id ? updated : item,
        ),
      );
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusySchedule(null);
    }
  }

  async function showRuns(scheduleId: string) {
    setLoadingRuns(scheduleId);
    setError(null);
    try {
      const runs = await listMonitoringRuns(scheduleId);
      setRunsBySchedule((current) => ({
        ...current,
        [scheduleId]: runs,
      }));
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setLoadingRuns(null);
    }
  }

  async function compareRuns(scheduleId: string) {
    setLoadingComparison(scheduleId);
    setError(null);
    try {
      const comparison = await compareMonitoringSchedule(scheduleId);
      setComparisons((current) => ({ ...current, [scheduleId]: comparison }));
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setLoadingComparison(null);
    }
  }

  async function acknowledgeNotification(notificationId: string) {
    setAcknowledgingNotification(notificationId);
    setError(null);
    try {
      const updated = await acknowledgeMonitoringNotification(notificationId);
      setNotifications((current) =>
        current.map((item) =>
          item.notification_id === updated.notification_id ? updated : item,
        ),
      );
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setAcknowledgingNotification(null);
    }
  }

  async function loadTriggerHistory(scheduleId: string, cursor?: string) {
    setLoadingTriggers(scheduleId);
    setError(null);
    try {
      const history = await getMonitoringTriggers(scheduleId, 100, cursor);
      if (history.has_more && !history.next_cursor) {
        setError("Engine reported more trigger activity without a continuation cursor.");
        return;
      }
      if (cursor && history.has_more && history.next_cursor === cursor) {
        setError("Engine returned a trigger-history cursor that did not advance.");
        return;
      }

      const current = triggerHistories[scheduleId];
      const updated = cursor && current
        ? appendTriggerHistoryPage(current, history)
        : history;
      if (!updated) {
        setError("The schedule changed while loading trigger activity. Reload the history.");
        return;
      }
      setTriggerHistories((histories) => ({ ...histories, [scheduleId]: updated }));
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setLoadingTriggers(null);
    }
  }

  function editSchedule(schedule: EngineMonitoringSchedule) {
    setEditingSchedule(schedule);
    setScheduleEditDraft(monitoringScheduleDraft(schedule));
    setPolicyDrafts(schedule.trigger_policies.map(triggerPolicyDraft));
    setError(null);
  }

  function updateScheduleDraft(changes: Partial<MonitoringScheduleDraft>) {
    setScheduleEditDraft((current) =>
      current ? { ...current, ...changes } : current,
    );
  }

  function updatePolicyDraft(
    policyId: string,
    changes: Partial<TriggerPolicyDraft>,
  ) {
    setPolicyDrafts((current) =>
      current.map((policy) =>
        policy.policy_id === policyId ? { ...policy, ...changes } : policy,
      ),
    );
  }

  async function handleSaveSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingSchedule || !scheduleEditDraft) return;
    const update = buildMonitoringScheduleUpdate(
      editingSchedule,
      scheduleEditDraft,
      policyDrafts,
    );
    if (update === null) {
      setError(
        "Check the schedule fields and trigger policies, and make at least one change.",
      );
      return;
    }

    setBusySchedule(editingSchedule.schedule_id);
    setError(null);
    try {
      const updated = await reviseMonitoringSchedule(
        editingSchedule.schedule_id,
        update,
      );
      setSchedules((current) =>
        current.map((schedule) =>
          schedule.schedule_id === updated.schedule_id ? updated : schedule,
        ),
      );
      setEditingSchedule(null);
      setScheduleEditDraft(null);
      setPolicyDrafts([]);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusySchedule(null);
    }
  }

  const activeMissions = missions.filter((mission) => mission.status === "active");
  const unreadNotifications = notifications.filter(
    (notification) => notification.status === "unread",
  );

  return (
    <section
      aria-label="Monitoring"
      className={
        embedded
          ? "w-full text-ink"
          : "pointer-events-auto w-72 rounded-2xl border border-white/10 bg-surface/95 text-ink shadow-2xl shadow-black/40 backdrop-blur-xl"
      }
    >
      <header className="flex items-center justify-between p-3">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
            Engine investigations
          </p>
          <h2 className="mt-1 text-sm font-semibold">Monitoring</h2>
        </div>
        {!embedded && (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className="rounded-lg border border-white/10 px-2.5 py-1.5 text-xs hover:bg-white/5"
          >
            {open ? "Hide" : "Open"}
          </button>
        )}
      </header>

      {open && (
        <div className={embedded ? "space-y-3" : "max-h-[min(68vh,44rem)] space-y-3 overflow-y-auto border-t border-white/10 p-3"}>
          <div className="flex items-center justify-between">
            <p className="text-[10px] text-ink-dim">
              Schedules and results are owned by the Engine.
            </p>
            <button
              type="button"
              onClick={() => {
                setLoading(true);
                void refresh();
              }}
              className="rounded border border-white/10 px-2 py-1 text-[10px]"
            >
              Refresh
            </button>
          </div>

          {loading && <p className="text-xs text-ink-dim" role="status">Loading monitoring...</p>}

          <section aria-label="Monitoring notifications" className="border-t border-white/10 pt-3">
            <h3 className="mb-2 text-xs font-medium">
              Recent alerts ({unreadNotifications.length} unread)
            </h3>
            <ul className="space-y-2">
              {notifications.slice(0, 10).map((notification) => (
                <li
                  key={notification.notification_id}
                  className="rounded-lg bg-white/[0.03] p-2"
                >
                  <p
                    className={`text-xs font-medium ${
                      notification.severity === "error" ? "text-rose-200" : "text-amber-100"
                    }`}
                  >
                    {notification.title}
                  </p>
                  <p className="mt-1 text-[10px] leading-4 text-ink-dim">
                    {notification.detail}
                  </p>
                  <p className="mt-1 text-[9px] text-ink-dim">
                    {timestamp(notification.created_at)} · {notification.status}
                  </p>
                  {notification.status === "unread" && (
                    <button
                      type="button"
                      disabled={
                        acknowledgingNotification === notification.notification_id
                      }
                      onClick={() =>
                        void acknowledgeNotification(notification.notification_id)
                      }
                      className="mt-2 rounded border border-white/10 px-2 py-1 text-[10px] disabled:opacity-40"
                    >
                      Acknowledge
                    </button>
                  )}
                </li>
              ))}
              {!loading && notifications.length === 0 && (
                <li className="text-[10px] text-ink-dim">No monitoring alerts.</li>
              )}
            </ul>
          </section>

          <section aria-label="Missions" className="border-t border-white/10 pt-3">
            <label className="mb-1 block text-xs font-medium" htmlFor="monitoring-mission">
              Active mission
            </label>
            <select
              id="monitoring-mission"
              value={selectedMissionId}
              onChange={(event) => setSelectedMissionId(event.target.value)}
              className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
            >
              <option value="">Select a mission</option>
              {activeMissions.map((mission) => (
                <option key={mission.mission_id} value={mission.mission_id}>
                  {mission.name}
                </option>
              ))}
            </select>
            <details className="mt-2">
              <summary className="cursor-pointer text-[11px] text-ink-dim">
                Create mission
              </summary>
              <form className="mt-2 space-y-2" onSubmit={(event) => void handleCreateMission(event)}>
                <input
                  required
                  value={missionName}
                  onChange={(event) => setMissionName(event.target.value)}
                  aria-label="Mission name"
                  placeholder="Mission name"
                  className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                />
                <textarea
                  required
                  value={missionObjective}
                  onChange={(event) => setMissionObjective(event.target.value)}
                  aria-label="Mission objective"
                  placeholder="Mission objective"
                  rows={2}
                  className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                />
                <button
                  type="submit"
                  disabled={creating || !missionName.trim() || !missionObjective.trim()}
                  className="rounded-lg border border-white/10 px-2 py-1.5 text-xs disabled:opacity-40"
                >
                  Create mission
                </button>
              </form>
            </details>
          </section>

          <section aria-label="Create monitoring schedule" className="border-t border-white/10 pt-3">
            <h3 className="mb-2 text-xs font-medium">New recurring investigation</h3>
            <form className="space-y-2" onSubmit={(event) => void handleCreateSchedule(event)}>
              <input
                required
                value={scheduleName}
                onChange={(event) => setScheduleName(event.target.value)}
                aria-label="Schedule name"
                placeholder="Schedule name"
                className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
              />
              <input
                required
                value={bbox}
                onChange={(event) => setBbox(event.target.value)}
                aria-label="Bounding box west south east north"
                placeholder="W,S,E,N (WGS 84)"
                className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
              />
              <input
                value={variables}
                onChange={(event) => setVariables(event.target.value)}
                aria-label="Requested variables"
                placeholder="Variables (comma-separated)"
                className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
              />
              <label className="block text-[10px] text-ink-dim">
                Repeat every (hours)
                <input
                  required
                  type="number"
                  min="1"
                  step="1"
                  value={intervalHours}
                  onChange={(event) => setIntervalHours(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink"
                />
              </label>
              <label className="block text-[10px] text-ink-dim">
                Rolling window (hours, optional; ends when each run starts)
                <input
                  type="number"
                  min="0.01"
                  step="any"
                  value={rollingWindowHours}
                  onChange={(event) => setRollingWindowHours(event.target.value)}
                  aria-label="Rolling temporal window in hours"
                  placeholder="Use fixed EarthQuery time instead"
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink"
                />
              </label>
              <details>
                <summary className="cursor-pointer text-[10px] text-ink-dim">
                  Add an Engine trigger policy
                </summary>
                <label className="mt-2 flex items-center gap-2 text-[10px]">
                  <input
                    type="checkbox"
                    checked={triggerEnabled}
                    onChange={(event) => setTriggerEnabled(event.target.checked)}
                  />
                  Evaluate a descriptive measurement threshold
                </label>
                {triggerEnabled && (
                  <div className="mt-2 space-y-2">
                    <p className="text-[9px] leading-4 text-ink-dim">
                      The Engine only evaluates matching canonical variables and units on
                      descriptive measurements. This is an operational rule, not a significance
                      test.
                    </p>
                    <input
                      required
                      value={triggerName}
                      onChange={(event) => setTriggerName(event.target.value)}
                      aria-label="Trigger name"
                      placeholder="Policy name"
                      className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                    />
                    <input
                      required
                      value={triggerVariable}
                      onChange={(event) => setTriggerVariable(event.target.value)}
                      aria-label="Canonical variable"
                      placeholder="Canonical variable"
                      className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                    />
                    <div className="flex gap-2">
                      <select
                        value={triggerOperator}
                        onChange={(event) =>
                          setTriggerOperator(
                            event.target.value as EngineMonitoringTriggerPolicy["operator"],
                          )
                        }
                        aria-label="Trigger comparison operator"
                        className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                      >
                        <option value="gt">&gt;</option>
                        <option value="gte">&gt;=</option>
                        <option value="lt">&lt;</option>
                        <option value="lte">&lt;=</option>
                        <option value="abs_gt">absolute &gt;</option>
                        <option value="abs_gte">absolute &gt;=</option>
                      </select>
                      <input
                        required
                        type="number"
                        step="any"
                        value={triggerThreshold}
                        onChange={(event) => setTriggerThreshold(event.target.value)}
                        aria-label="Trigger threshold"
                        placeholder="Threshold"
                        className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                      />
                    </div>
                    <input
                      required
                      value={triggerUnit}
                      onChange={(event) => setTriggerUnit(event.target.value)}
                      aria-label="Exact measurement unit"
                      placeholder="Exact unit"
                      className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                    />
                    <p className="text-[9px] text-ink-dim">
                      The follow-up investigation reuses the schedule's bounding box and variables.
                    </p>
                  </div>
                )}
              </details>
              <button
                type="submit"
                disabled={
                  creating ||
                  !selectedMissionId ||
                  !scheduleName.trim() ||
                  !bbox.trim()
                }
                className="w-full rounded-lg border border-white/10 px-2 py-1.5 text-xs disabled:opacity-40"
              >
                Create schedule
              </button>
            </form>
          </section>

          <section aria-label="Monitoring schedules" className="border-t border-white/10 pt-3">
            <h3 className="mb-2 text-xs font-medium">Schedules</h3>
            <ul className="space-y-2">
              {schedules.map((schedule) => (
                <li key={schedule.schedule_id} className="rounded-lg bg-white/[0.03] p-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium">{schedule.name}</p>
                      <p className="mt-1 text-[10px] text-ink-dim">
                        {schedule.enabled ? "Enabled" : "Paused"} · revision {schedule.revision}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={busySchedule === schedule.schedule_id}
                      onClick={() => void toggleSchedule(schedule)}
                      className="shrink-0 rounded border border-white/10 px-2 py-1 text-[10px] disabled:opacity-40"
                    >
                      {schedule.enabled ? "Pause" : "Enable"}
                    </button>
                  </div>
                  <p className="mt-2 text-[10px] leading-4 text-ink-dim">
                    Next run: {timestamp(schedule.next_run_at)}
                  </p>
                  {schedule.trigger_policies.length > 0 && (
                    <p className="mt-1 text-[10px] text-ink-dim">
                      Trigger: {schedule.trigger_policies.map((policy) => policy.name).join(", ")}
                    </p>
                  )}
                  <button
                    type="button"
                    disabled={busySchedule === schedule.schedule_id}
                    onClick={() => editSchedule(schedule)}
                    className="mt-2 rounded border border-white/10 px-2 py-1 text-[10px] disabled:opacity-40"
                  >
                    Edit schedule
                  </button>
                  {editingSchedule?.schedule_id === schedule.schedule_id &&
                    scheduleEditDraft && (
                    <form
                      className="mt-2 space-y-2 border-t border-white/10 pt-2"
                      onSubmit={(event) => void handleSaveSchedule(event)}
                    >
                      <p className="text-[9px] leading-4 text-ink-dim">
                        Changes create a new Engine schedule revision. Unedited EarthQuery fields
                        and existing trigger follow-up settings are preserved.
                      </p>
                      <input
                        required
                        value={scheduleEditDraft.name}
                        onChange={(event) =>
                          updateScheduleDraft({ name: event.target.value })
                        }
                        aria-label="Edited schedule name"
                        placeholder="Schedule name"
                        className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                      />
                      {canEditMonitoringBounds(editingSchedule) ? (
                        <input
                          required
                          value={scheduleEditDraft.bbox}
                          onChange={(event) =>
                            updateScheduleDraft({ bbox: event.target.value })
                          }
                          aria-label="Edited bounding box west south east north"
                          placeholder="W,S,E,N (WGS 84)"
                          className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                        />
                      ) : (
                        <p className="text-[9px] leading-4 text-ink-dim">
                          This schedule has a non-rectangular or compound spatial query; its
                          geometry is preserved and cannot be changed in this editor.
                        </p>
                      )}
                      <input
                        value={scheduleEditDraft.variables}
                        onChange={(event) =>
                          updateScheduleDraft({ variables: event.target.value })
                        }
                        aria-label="Edited requested variables"
                        placeholder="Variables (comma-separated)"
                        className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                      />
                      <label className="block text-[10px] text-ink-dim">
                        Repeat every (hours)
                        <input
                          required
                          type="number"
                          step="any"
                          value={scheduleEditDraft.intervalHours}
                          onChange={(event) =>
                            updateScheduleDraft({ intervalHours: event.target.value })
                          }
                          className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink"
                        />
                      </label>
                      <label className="block text-[10px] text-ink-dim">
                        Rolling window (hours, blank to disable)
                        <span className="mt-1 block">
                          The Engine resolves each interval relative to that run's start time.
                        </span>
                        <input
                          type="number"
                          min="0.01"
                          step="any"
                          value={scheduleEditDraft.rollingWindowHours}
                          onChange={(event) =>
                            updateScheduleDraft({
                              rollingWindowHours: event.target.value,
                            })
                          }
                          aria-label="Edited rolling temporal window in hours"
                          className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink"
                        />
                      </label>
                      <label className="block text-[10px] text-ink-dim">
                        Priority (0-100)
                        <input
                          required
                          type="number"
                          min="0"
                          max="100"
                          step="1"
                          value={scheduleEditDraft.priority}
                          onChange={(event) =>
                            updateScheduleDraft({ priority: event.target.value })
                          }
                          className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink"
                        />
                      </label>
                      <label className="block text-[10px] text-ink-dim">
                        Overlap policy
                        <select
                          value={scheduleEditDraft.overlapPolicy}
                          onChange={(event) => {
                            if (
                              event.target.value === "allow" ||
                              event.target.value === "skip_while_running"
                            ) {
                              updateScheduleDraft({
                                overlapPolicy: event.target.value,
                              });
                            }
                          }}
                          className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink"
                        >
                          <option value="skip_while_running">Skip while running</option>
                          <option value="allow">Allow overlap</option>
                        </select>
                      </label>
                      {policyDrafts.map((policy, index) => (
                        <fieldset
                          key={policy.policy_id}
                          className="space-y-2 rounded-lg border border-white/10 p-2"
                        >
                          <legend className="px-1 text-[10px] text-ink-dim">
                            Policy {index + 1}
                          </legend>
                          <input
                            required
                            value={policy.name}
                            onChange={(event) =>
                              updatePolicyDraft(policy.policy_id, { name: event.target.value })
                            }
                            aria-label={`Policy ${index + 1} name`}
                            placeholder="Policy name"
                            className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                          />
                          <input
                            required
                            value={policy.canonical_variable}
                            onChange={(event) =>
                              updatePolicyDraft(policy.policy_id, {
                                canonical_variable: event.target.value,
                              })
                            }
                            aria-label={`Policy ${index + 1} canonical variable`}
                            placeholder="Canonical variable"
                            className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                          />
                          <div className="flex gap-2">
                            <select
                              value={policy.operator}
                              onChange={(event) => {
                                const operator = parseTriggerOperator(event.target.value);
                                if (operator) {
                                  updatePolicyDraft(policy.policy_id, { operator });
                                }
                              }}
                              aria-label={`Policy ${index + 1} comparison operator`}
                              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                            >
                              <option value="gt">&gt;</option>
                              <option value="gte">&gt;=</option>
                              <option value="lt">&lt;</option>
                              <option value="lte">&lt;=</option>
                              <option value="abs_gt">absolute &gt;</option>
                              <option value="abs_gte">absolute &gt;=</option>
                            </select>
                            <input
                              required
                              type="number"
                              step="any"
                              value={policy.threshold}
                              onChange={(event) =>
                                updatePolicyDraft(policy.policy_id, {
                                  threshold: event.target.value,
                                })
                              }
                              aria-label={`Policy ${index + 1} threshold`}
                              placeholder="Threshold"
                              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                            />
                          </div>
                          <input
                            required
                            value={policy.unit}
                            onChange={(event) =>
                              updatePolicyDraft(policy.policy_id, { unit: event.target.value })
                            }
                            aria-label={`Policy ${index + 1} exact unit`}
                            placeholder="Exact unit"
                            className="w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs"
                          />
                          <button
                            type="button"
                            onClick={() =>
                              setPolicyDrafts((current) =>
                                current.filter((item) => item.policy_id !== policy.policy_id),
                              )
                            }
                            className="rounded border border-white/10 px-2 py-1 text-[10px]"
                          >
                            Remove policy
                          </button>
                        </fieldset>
                      ))}
                      <button
                        type="button"
                        onClick={() =>
                          setPolicyDrafts((current) => [
                            ...current,
                            {
                              policy_id: crypto.randomUUID(),
                              name: "",
                              canonical_variable: "",
                              unit: "",
                              operator: "gte",
                              threshold: "",
                            },
                          ])
                        }
                        className="rounded border border-white/10 px-2 py-1 text-[10px]"
                      >
                        Add policy
                      </button>
                      <div className="flex gap-2">
                        <button
                          type="submit"
                          disabled={busySchedule === schedule.schedule_id}
                          className="rounded border border-white/10 px-2 py-1 text-[10px] disabled:opacity-40"
                        >
                          Save revision
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setEditingSchedule(null);
                            setScheduleEditDraft(null);
                            setPolicyDrafts([]);
                          }}
                          className="rounded border border-white/10 px-2 py-1 text-[10px]"
                        >
                          Cancel
                        </button>
                      </div>
                    </form>
                  )}
                  <button
                    type="button"
                    disabled={loadingRuns === schedule.schedule_id}
                    onClick={() => void showRuns(schedule.schedule_id)}
                    className="mt-2 rounded border border-white/10 px-2 py-1 text-[10px] disabled:opacity-40"
                  >
                    {loadingRuns === schedule.schedule_id ? "Loading runs..." : "Run history"}
                  </button>
                  <button
                    type="button"
                    disabled={loadingComparison === schedule.schedule_id}
                    onClick={() => void compareRuns(schedule.schedule_id)}
                    className="ml-1 mt-2 rounded border border-white/10 px-2 py-1 text-[10px] disabled:opacity-40"
                  >
                    {loadingComparison === schedule.schedule_id
                      ? "Comparing..."
                      : "Compare runs"}
                  </button>
                  {schedule.trigger_policies.length > 0 && (
                    <button
                      type="button"
                      disabled={loadingTriggers !== null}
                      onClick={() => void loadTriggerHistory(schedule.schedule_id)}
                      className="ml-1 mt-2 rounded border border-white/10 px-2 py-1 text-[10px] disabled:opacity-40"
                    >
                      {loadingTriggers === schedule.schedule_id
                        ? "Loading trigger activity..."
                        : "Trigger activity"}
                    </button>
                  )}
                  {runsBySchedule[schedule.schedule_id] && (
                    <ul className="mt-2 space-y-1 border-t border-white/10 pt-2">
                      {runsBySchedule[schedule.schedule_id]?.map((run) => (
                        <li key={run.run_id} className="text-[10px] leading-4">
                          <span className="font-medium">{run.status}</span>
                          {" · "}
                          {timestamp(run.started_at)}
                          {run.effective_temporal_start &&
                            run.effective_temporal_end && (
                              <span className="block text-ink-dim">
                                Window: {timestamp(run.effective_temporal_start)} to{" "}
                                {timestamp(run.effective_temporal_end)}
                              </span>
                            )}
                          {run.failure_type && (
                            <span className="block text-rose-200">{run.failure_type}</span>
                          )}
                        </li>
                      ))}
                      {runsBySchedule[schedule.schedule_id]?.length === 0 && (
                        <li className="text-[10px] text-ink-dim">No runs have been recorded.</li>
                      )}
                    </ul>
                  )}
                  {comparisons[schedule.schedule_id] && (
                    <details className="mt-2 border-t border-white/10 pt-2">
                      <summary className="cursor-pointer text-[10px]">
                        Engine comparison
                      </summary>
                      <p className="mt-1 break-all text-[9px] text-ink-dim">
                        SHA-256: {comparisons[schedule.schedule_id]?.comparison_sha256}
                      </p>
                      <pre className="mt-2 whitespace-pre-wrap text-[10px] leading-4 text-ink-dim">
                        {comparisons[schedule.schedule_id]?.markdown}
                      </pre>
                      <ul className="mt-2 list-disc space-y-1 pl-4 text-[9px] text-ink-dim">
                        {comparisons[schedule.schedule_id]?.limitations.map((limitation) => (
                          <li key={limitation}>{limitation}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {triggerHistories[schedule.schedule_id] && (
                    <div className="mt-2 border-t border-white/10 pt-2">
                      <ul className="space-y-1">
                        {triggerHistories[schedule.schedule_id]?.events.map((event) => (
                          <li key={event.event_id} className="text-[10px] leading-4">
                            <span className="font-medium">{event.event_type.replaceAll("_", " ")}</span>
                            {" · "}
                            {timestamp(event.occurred_at)}
                          </li>
                        ))}
                        {triggerHistories[schedule.schedule_id]?.events.length === 0 && (
                          <li className="text-[10px] text-ink-dim">
                            No trigger activity has been recorded.
                          </li>
                        )}
                      </ul>
                      {triggerHistories[schedule.schedule_id]?.has_more &&
                        triggerHistories[schedule.schedule_id]?.next_cursor && (
                        <button
                          type="button"
                          disabled={loadingTriggers !== null}
                          onClick={() =>
                            void loadTriggerHistory(
                              schedule.schedule_id,
                              triggerHistories[schedule.schedule_id]?.next_cursor ?? undefined,
                            )
                          }
                          className="mt-2 rounded border border-white/10 px-2 py-1 text-[10px] disabled:opacity-40"
                        >
                          {loadingTriggers === schedule.schedule_id
                            ? "Loading..."
                            : "Load more trigger activity"}
                        </button>
                      )}
                    </div>
                  )}
                </li>
              ))}
              {!loading && schedules.length === 0 && (
                <li className="text-[10px] text-ink-dim">No monitoring schedules yet.</li>
              )}
            </ul>
          </section>
          {error && <p className="text-xs text-rose-200" role="alert">{error}</p>}
        </div>
      )}
    </section>
  );
}
