import type {
  ImageAsset,
  PreparedVisionPayload,
  PrepareVisionRequest,
  UpdateImageAssetRequest,
} from "@/shared/types";

import { apiFetch, apiUrl, ApiError } from "./client";

export type ImageOrigin = "upload" | "drag_drop" | "clipboard" | "screen_capture" | "earth_capture";

export type ImagePreparationRequest = PrepareVisionRequest;

export function listImageAssets(sessionId: string, signal?: AbortSignal): Promise<ImageAsset[]> {
  return apiFetch<ImageAsset[]>(`/vision/sessions/${encodeURIComponent(sessionId)}/assets`, {
    signal,
  });
}

export function uploadImageAsset(
  sessionId: string,
  file: File,
  origin: ImageOrigin,
  onProgress: (progress: number) => void,
  signal?: AbortSignal,
): Promise<ImageAsset> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    const abort = () => request.abort();
    request.open("POST", apiUrl(`/vision/sessions/${encodeURIComponent(sessionId)}/assets`));
    request.responseType = "json";
    request.setRequestHeader("Accept", "application/json");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        const asset = request.response as ImageAsset | null;
        if (asset === null) {
          reject(new Error("The image upload response did not contain asset metadata."));
          return;
        }
        resolve(asset);
        return;
      }
      const error = request.response as
        | { error?: { code?: string; message?: string; details?: Record<string, unknown> } }
        | null;
      reject(
        new ApiError(
          request.status,
          error?.error?.code ?? "http_error",
          error?.error?.message ?? request.statusText,
          error?.error?.details,
        ),
      );
    };
    request.onerror = () => reject(new Error("Image upload failed because the network request failed."));
    request.onabort = () => reject(new DOMException("Image upload was cancelled.", "AbortError"));
    signal?.addEventListener("abort", abort, { once: true });
    request.onloadend = () => signal?.removeEventListener("abort", abort);
    const form = new FormData();
    form.append("upload", file, file.name);
    form.append("origin", origin);
    request.send(form);
  });
}

export function deleteImageAsset(sessionId: string, assetId: string): Promise<void> {
  return fetch(
    apiUrl(
      `/vision/sessions/${encodeURIComponent(sessionId)}/assets/${encodeURIComponent(assetId)}`,
    ),
    { method: "DELETE", headers: { Accept: "application/json" } },
  ).then(async (response) => {
    if (response.ok) return;
    const body = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string; details?: Record<string, unknown> };
    } | null;
    throw new ApiError(
      response.status,
      body?.error?.code ?? "http_error",
      body?.error?.message ?? response.statusText,
      body?.error?.details,
    );
  });
}

export function updateImageAsset(
  sessionId: string,
  assetId: string,
  update: UpdateImageAssetRequest,
): Promise<ImageAsset> {
  return apiFetch<ImageAsset>(
    `/vision/sessions/${encodeURIComponent(sessionId)}/assets/${encodeURIComponent(assetId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    },
  );
}

export function prepareVisionAssets(
  sessionId: string,
  body: ImagePreparationRequest,
): Promise<PreparedVisionPayload> {
  return apiFetch<PreparedVisionPayload>(
    `/vision/sessions/${encodeURIComponent(sessionId)}/prepare`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function imageContentUrl(sessionId: string, assetId: string, thumbnail = false): string {
  const suffix = thumbnail ? "/thumbnail" : "/content";
  return apiUrl(
    `/vision/sessions/${encodeURIComponent(sessionId)}/assets/${encodeURIComponent(assetId)}${suffix}`,
  );
}
