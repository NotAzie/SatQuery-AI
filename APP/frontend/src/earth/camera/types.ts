import type { CameraState, EarthCommand } from "@/shared/types";
import type { Unsubscribe } from "@/shared/utils";

type FlyToCommand = Extract<EarthCommand, { type: "fly_to" }>;

export interface CameraController {
  flyTo(command: FlyToCommand): Promise<void>;
  restore(state: CameraState): void;
  getState(): CameraState;
  /** Fires when camera movement ends (not per frame). */
  onSettle(listener: (state: CameraState) => void): Unsubscribe;
}
