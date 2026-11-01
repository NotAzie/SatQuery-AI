import { useRef, useState, type FormEvent } from "react";

import { useEarthController } from "@/hooks/useEarth";
import { useEarthStore } from "@/state/earthStore";

function dateInputValue(value: string | null): string {
  return value ? new Date(value).toISOString().slice(0, 10) : "";
}

export function TimelinePanel() {
  const controller = useEarthController()?.timeline;
  const timeline = useEarthStore((state) => state.timeline);
  const startInput = useRef<HTMLInputElement>(null);
  const endInput = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  const startMs = timeline.range ? new Date(timeline.range.start).getTime() : 0;
  const endMs = timeline.range ? new Date(timeline.range.end).getTime() : 0;
  const instantMs = timeline.instant?.getTime() ?? startMs;

  function applyRange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const startDate = startInput.current?.value;
    const endDate = endInput.current?.value;
    if (!controller || !startDate || !endDate) {
      setError("Choose both dates before setting the timeline range.");
      return;
    }
    try {
      controller.setRange({
        start: new Date(`${startDate}T00:00:00.000Z`).toISOString(),
        end: new Date(`${endDate}T23:59:59.999Z`).toISOString(),
      });
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The timeline range is invalid.");
    }
  }

  return (
    <form
      key={`${timeline.range?.start ?? ""}/${timeline.range?.end ?? ""}`}
      aria-label="Earth timeline"
      onSubmit={applyRange}
      className="pointer-events-auto mx-auto w-[min(46rem,calc(100vw-2rem))] rounded-2xl border border-white/10 bg-surface/90 px-4 py-3 shadow-xl shadow-black/30 backdrop-blur-xl"
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-[10px] text-ink-dim">
          Range start
          <input
            ref={startInput}
            type="date"
            defaultValue={dateInputValue(timeline.range?.start ?? null)}
            className="rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink"
          />
        </label>
        <label className="flex flex-col gap-1 text-[10px] text-ink-dim">
          Range end
          <input
            ref={endInput}
            type="date"
            defaultValue={dateInputValue(timeline.range?.end ?? null)}
            className="rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink"
          />
        </label>
        <button
          type="submit"
          disabled={!controller}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink hover:bg-white/5 disabled:opacity-40"
        >
          Set range
        </button>
        {timeline.range && (
          <>
            <input
              type="range"
              aria-label="Timeline instant"
              min={startMs}
              max={Math.max(startMs, endMs)}
              value={Math.min(Math.max(instantMs, startMs), endMs)}
              onChange={(event) => {
                if (!controller) return;
                try {
                  controller.setInstant(new Date(Number(event.target.value)));
                  setError(null);
                } catch (reason) {
                  setError(reason instanceof Error ? reason.message : "Could not set timeline.");
                }
              }}
              className="min-w-32 flex-1 accent-accent"
            />
            <button
              type="button"
              onClick={() => controller?.play(1)}
              disabled={!controller || timeline.playing}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink hover:bg-white/5 disabled:opacity-40"
            >
              Play
            </button>
            <button
              type="button"
              onClick={() => controller?.pause()}
              disabled={!controller || !timeline.playing}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink hover:bg-white/5 disabled:opacity-40"
            >
              Pause
            </button>
          </>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <p className="text-[10px] text-ink-dim">
          {timeline.instant
            ? timeline.instant.toLocaleString()
            : "Choose a range to navigate Earth time."}
        </p>
        {error && (
          <p role="alert" className="text-[10px] text-rose-200">
            {error}
          </p>
        )}
      </div>
    </form>
  );
}
