import type { ImageAsset } from "@/shared/types";

export type ImageSource =
  | { kind: "file"; file: File }
  | { kind: "clipboard"; file: File }
  | { kind: "screen"; blob: Blob }
  | { kind: "earth"; blob: Blob };

export interface PendingImage {
  localId: string;
  source: ImageSource;
  previewUrl: string;
  status: "pending" | "uploading" | "ready" | "failed";
  progress: number;
  asset?: ImageAsset;
  error?: string;
}

/** Single entry point for every way an image can arrive; yields previews and uploads them. */
export interface ImageIntake {
  add(source: ImageSource): PendingImage;
  remove(localId: string): void;
  readonly images: readonly PendingImage[];
}
