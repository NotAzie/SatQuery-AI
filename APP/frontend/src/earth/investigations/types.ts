import type { EarthCommand } from "@/shared/types";

type ShowInvestigationCommand = Extract<EarthCommand, { type: "show_investigation" }>;

/** Composes camera, overlays and timeline into one visual story per investigation. */
export interface InvestigationVisualizer {
  show(command: ShowInvestigationCommand): Promise<void>;
  /** Live progress while the Engine works (e.g. sweep animation over the study area). */
  setProgress(investigationId: string, fraction: number | null): void;
  dismiss(investigationId: string): void;
}
