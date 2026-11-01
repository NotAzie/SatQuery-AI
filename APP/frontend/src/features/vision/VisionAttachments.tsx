import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type PointerEvent,
} from "react";

import type {
  CameraState,
  EarthCaptureMetadata,
  GeoReference,
  ImageAsset,
} from "@/shared/types";
import {
  deleteImageAsset,
  imageContentUrl,
  listImageAssets,
  updateImageAsset,
  uploadImageAsset,
  type ImageOrigin,
} from "@/services/api/vision";
import { ApiError } from "@/services/api/client";
import { useEarthController } from "@/hooks/useEarth";
import { useEarthStore } from "@/state/earthStore";
import { useSessionStore } from "@/state/sessionStore";
import { useVisionStore } from "@/state/visionStore";
import { scaleCropToImage } from "./crop";

const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MAX_ATTACHMENTS = 8;
const ACCEPTED_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/tiff"]);
const ACCEPTED_EXTENSIONS = /\.(png|jpe?g|webp|tiff?)$/i;

interface UploadProgress {
  id: string;
  filename: string;
  fraction: number;
}

interface RegionCapture {
  image: Blob;
  camera: CameraState;
  capturedAt: string;
}

interface CroppedRegion {
  image: Blob;
  pixelRegion: { left: number; top: number; width: number; height: number };
  viewportWidth: number;
  viewportHeight: number;
}

function isImageCandidate(file: File): boolean {
  return file.type.startsWith("image/") || ACCEPTED_EXTENSIONS.test(file.name);
}

function messageOf(reason: unknown): string {
  return reason instanceof ApiError
    ? reason.message
    : reason instanceof Error
      ? reason.message
      : "Image processing failed.";
}

function asFile(blob: Blob, filename: string): File {
  return new File([blob], filename, { type: blob.type || "image/png" });
}

function parseOptionalNumbers(values: string[], label: string): number[] | null {
  const empty = values.map((value) => !value.trim());
  if (empty.every(Boolean)) return null;
  if (empty.some(Boolean)) throw new RangeError(`Provide every ${label} value or leave them blank.`);
  const numbers = values.map(Number);
  if (!numbers.every(Number.isFinite)) {
    throw new RangeError(`${label} values must be finite numbers.`);
  }
  return numbers;
}

function formatOptionalNumber(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toString() : "";
}

export function VisionAttachments() {
  const sessionId = useSessionStore((state) => state.activeSessionId);
  return (
    <VisionAttachmentSession
      key={sessionId ?? "no-session"}
      sessionId={sessionId}
    />
  );
}

interface VisionAttachmentSessionProps {
  sessionId: string | null;
}

function VisionAttachmentSession({ sessionId }: VisionAttachmentSessionProps) {
  const addCapture = useSessionStore((state) => state.addCapture);
  const setEarthCaptures = useEarthStore((state) => state.setCaptures);
  const setSelectedAssets = useVisionStore((state) => state.setSelectedAssets);
  const panelOpen = useVisionStore((state) => state.panelOpen);
  const setPanelOpen = useVisionStore((state) => state.setPanelOpen);
  const captures = useEarthStore((state) => state.captures);
  const earth = useEarthController();
  const fileInput = useRef<HTMLInputElement>(null);
  const [assets, setAssets] = useState<ImageAsset[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [progress, setProgress] = useState<UploadProgress[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [viewerAsset, setViewerAsset] = useState<ImageAsset | null>(null);
  const [regionCapture, setRegionCapture] = useState<RegionCapture | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    void listImageAssets(sessionId, controller.signal)
      .then(setAssets)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(messageOf(reason));
        }
      });
    return () => controller.abort();
  }, [sessionId]);

  useEffect(() => {
    setSelectedAssets(assets.filter((asset) => selectedIds.includes(asset.id)));
  }, [assets, selectedIds, setSelectedAssets]);

  const uploadFiles = useCallback(
    async (files: File[], origin: ImageOrigin): Promise<ImageAsset[]> => {
      if (!sessionId) {
        setError("Open a Platform session before adding images.");
        return [];
      }
      const available = MAX_ATTACHMENTS - selectedIds.length;
      if (files.length > available) {
        setError(`A message can include at most ${MAX_ATTACHMENTS} images.`);
        files = files.slice(0, Math.max(0, available));
      }
      const successful: ImageAsset[] = [];
      for (const file of files) {
        if (
          !ACCEPTED_TYPES.has(file.type) &&
          !(
            (file.type === "" || file.type === "application/octet-stream") &&
            ACCEPTED_EXTENSIONS.test(file.name)
          )
        ) {
          setError(`${file.name}: choose a PNG, JPEG, WebP, or TIFF image.`);
          continue;
        }
        if (file.size > MAX_FILE_BYTES) {
          setError(`${file.name}: the image exceeds the 20 MiB size limit.`);
          continue;
        }
        setError(null);
        const uploadId = crypto.randomUUID();
        setProgress((current) => [...current, { id: uploadId, filename: file.name, fraction: 0 }]);
        try {
          const asset = await uploadImageAsset(sessionId, file, origin, (fraction) => {
            setProgress((current) =>
              current.map((item) =>
                item.id === uploadId ? { ...item, fraction } : item,
              ),
            );
          });
          successful.push(asset);
          setAssets((current) => [...current.filter((item) => item.id !== asset.id), asset]);
          setSelectedIds((current) =>
            current.includes(asset.id) || current.length >= MAX_ATTACHMENTS
              ? current
              : [...current, asset.id],
          );
        } catch (reason) {
          setError(`${file.name}: ${messageOf(reason)}`);
        } finally {
          setProgress((current) => current.filter((item) => item.id !== uploadId));
        }
      }
      return successful;
    },
    [selectedIds.length, sessionId],
  );

  const addEarthCapture = useCallback(async () => {
    if (!earth || !sessionId) {
      setError("The Earth workspace must be ready before capturing its view.");
      return;
    }
    try {
      const image = await earth.capture.captureEarth();
      const file = asFile(image, `earth-view-${Date.now()}.png`);
      const [asset] = await uploadFiles([file], "earth_capture");
      if (!asset) return;
      const capture: EarthCaptureMetadata = {
        id: crypto.randomUUID(),
        asset_id: asset.id,
        captured_at: new Date().toISOString(),
        source: "viewport",
        camera: earth.camera.getState(),
        region: null,
        pixel_region: null,
        viewport_width_px: asset.width,
        viewport_height_px: asset.height,
      };
      addCapture(capture);
      setEarthCaptures([...captures, capture]);
    } catch (reason) {
      setError(messageOf(reason));
    }
  }, [addCapture, captures, earth, sessionId, setEarthCaptures, uploadFiles]);

  const captureEarthRegion = useCallback(async () => {
    if (!earth) {
      setError("The Earth workspace must be ready before capturing a region.");
      return;
    }
    try {
      const camera = earth.camera.getState();
      const capturedAt = new Date().toISOString();
      const image = await earth.capture.captureEarth();
      setRegionCapture({ image, camera, capturedAt });
    } catch (reason) {
      setError(messageOf(reason));
    }
  }, [earth]);

  const saveEarthRegion = useCallback(
    async (crop: CroppedRegion) => {
      if (!regionCapture) return;
      try {
        const file = asFile(crop.image, `earth-region-${Date.now()}.png`);
        const [asset] = await uploadFiles([file], "earth_capture");
        if (!asset) return;
        const capture: EarthCaptureMetadata = {
          id: crypto.randomUUID(),
          asset_id: asset.id,
          captured_at: regionCapture.capturedAt,
          source: "region",
          camera: regionCapture.camera,
          region: null,
          pixel_region: crop.pixelRegion,
          viewport_width_px: crop.viewportWidth,
          viewport_height_px: crop.viewportHeight,
        };
        addCapture(capture);
        setEarthCaptures([...captures, capture]);
        setRegionCapture(null);
      } catch (reason) {
        setError(messageOf(reason));
      }
    },
    [addCapture, captures, regionCapture, setEarthCaptures, uploadFiles],
  );

  const addScreenCapture = useCallback(async () => {
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setError("Screen capture is not available in this browser.");
      return;
    }
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const video = document.createElement("video");
      video.srcObject = stream;
      await video.play();
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext("2d");
      if (!context || !canvas.width || !canvas.height) {
        throw new Error("The browser did not provide a capturable screen frame.");
      }
      context.drawImage(video, 0, 0);
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob(
          (captured) =>
            captured
              ? resolve(captured)
              : reject(new Error("Could not encode the screen capture.")),
          "image/png",
        );
      });
      await uploadFiles([asFile(blob, `screen-capture-${Date.now()}.png`)], "screen_capture");
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      stream?.getTracks().forEach((track) => track.stop());
    }
  }, [uploadFiles]);

  useEffect(() => {
    const handlePaste = (event: ClipboardEvent) => {
      const files = Array.from(event.clipboardData?.items ?? [])
        .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
      if (files.length) {
        event.preventDefault();
        void uploadFiles(files, "clipboard");
      }
    };
    document.addEventListener("paste", handlePaste);
    return () => document.removeEventListener("paste", handlePaste);
  }, [uploadFiles]);

  const toggleSelection = (assetId: string) => {
    setSelectedIds((current) => {
      if (current.includes(assetId)) return current.filter((id) => id !== assetId);
      if (current.length >= MAX_ATTACHMENTS) {
        setError(`A message can include at most ${MAX_ATTACHMENTS} images.`);
        return current;
      }
      setError(null);
      return [...current, assetId];
    });
  };

  const removeAsset = async (asset: ImageAsset) => {
    if (!sessionId) return;
    try {
      await deleteImageAsset(sessionId, asset.id);
      setAssets((current) => current.filter((item) => item.id !== asset.id));
      setSelectedIds((current) => current.filter((id) => id !== asset.id));
      setViewerAsset(null);
      const remaining = captures.filter((capture) => capture.asset_id !== asset.id);
      if (remaining.length !== captures.length) {
        setEarthCaptures(remaining);
        for (const capture of captures) {
          if (capture.asset_id === asset.id) useSessionStore.getState().deleteCapture(capture.id);
        }
      }
    } catch (reason) {
      setError(messageOf(reason));
    }
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    void uploadFiles(
      Array.from(event.dataTransfer.files).filter(isImageCandidate),
      "drag_drop",
    );
  };

  if (!panelOpen) return null;

  return (
    <div
      className={`w-[min(22rem,calc(100vw-2rem))] space-y-2 rounded-xl border bg-surface/95 p-2 text-ink shadow-xl ${
        dragging ? "border-accent bg-accent/10" : "border-white/10"
      }`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      aria-label="Image attachments"
    >
      <input
        ref={fileInput}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/tiff"
        multiple
        className="hidden"
        onChange={(event) => {
          void uploadFiles(Array.from(event.currentTarget.files ?? []), "upload");
          event.currentTarget.value = "";
        }}
      />
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="ml-auto rounded-full border border-white/10 px-3 py-1 text-[11px] text-ink-dim hover:text-ink"
          onClick={() => setPanelOpen(false)}
        >
          Close
        </button>
        <button
          type="button"
          className="rounded-full border border-white/10 px-3 py-1 text-[11px] text-ink-dim hover:text-ink"
          onClick={() => fileInput.current?.click()}
          disabled={!sessionId}
        >
          Add images
        </button>
        <button
          type="button"
          className="rounded-full border border-white/10 px-3 py-1 text-[11px] text-ink-dim hover:text-ink"
          onClick={() => void addScreenCapture()}
          disabled={!sessionId}
        >
          Capture screen
        </button>
        <button
          type="button"
          className="rounded-full border border-white/10 px-3 py-1 text-[11px] text-ink-dim hover:text-ink"
          onClick={() => void addEarthCapture()}
          disabled={!sessionId || !earth}
        >
          Capture Earth view
        </button>
        <button
          type="button"
          className="rounded-full border border-white/10 px-3 py-1 text-[11px] text-ink-dim hover:text-ink"
          onClick={() => void captureEarthRegion()}
          disabled={!sessionId || !earth}
        >
          Capture Earth region
        </button>
        <span className="self-center text-[10px] text-ink-dim">
          Drop or paste images · {selectedIds.length}/{MAX_ATTACHMENTS} attached
        </span>
      </div>
      {progress.map((item) => (
        <div key={item.id} className="text-[11px] text-ink-dim">
          Uploading {item.filename}
          <progress className="ml-2 w-24 align-middle" max={1} value={item.fraction} />
        </div>
      ))}
      {sessionId && assets.length > 0 && (
        <div className="flex max-h-24 flex-wrap gap-2 overflow-auto">
          {assets.map((asset) => (
            <div key={asset.id} className="relative">
              <button
                type="button"
                aria-label={`Preview ${asset.filename ?? "image"}`}
                onClick={() => setViewerAsset(asset)}
                className="h-14 w-14 overflow-hidden rounded-lg border border-white/10"
              >
                <img
                  src={imageContentUrl(sessionId, asset.id, true)}
                  alt={asset.filename ?? "Attached image"}
                  className="h-full w-full object-cover"
                />
              </button>
              <input
                type="checkbox"
                aria-label={`Attach ${asset.filename ?? "image"}`}
                checked={selectedIds.includes(asset.id)}
                onChange={() => toggleSelection(asset.id)}
                className="absolute left-1 top-1 accent-accent"
              />
              <button
                type="button"
                aria-label={`Delete ${asset.filename ?? "image"}`}
                onClick={() => void removeAsset(asset)}
                className="absolute -right-1 -top-1 rounded-full bg-black/80 px-1 text-xs text-white"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      {error && (
        <p role="alert" className="text-[11px] text-rose-200">
          {error}
        </p>
      )}
      {viewerAsset && sessionId && (
        <ImageViewer
          key={viewerAsset.id}
          asset={viewerAsset}
          sessionId={sessionId}
          onClose={() => setViewerAsset(null)}
          onUpdated={(updated) => {
            setAssets((current) => current.map((asset) => (asset.id === updated.id ? updated : asset)));
            setViewerAsset(updated);
          }}
          onError={setError}
        />
      )}
      {regionCapture && (
        <RegionCropper
          image={regionCapture.image}
          onCancel={() => setRegionCapture(null)}
          onCrop={(crop) => void saveEarthRegion(crop)}
          onError={setError}
        />
      )}
    </div>
  );
}

interface RegionCropperProps {
  image: Blob;
  onCancel: () => void;
  onCrop: (crop: CroppedRegion) => void;
  onError: (message: string) => void;
}

function RegionCropper({ image, onCancel, onCrop, onError }: RegionCropperProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [selection, setSelection] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
  } | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const imageRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    const objectUrl = URL.createObjectURL(image);
    const probe = new Image();
    probe.onload = () => setUrl(objectUrl);
    probe.onerror = () => onError("Could not display the captured Earth viewport.");
    probe.src = objectUrl;
    return () => {
      probe.onload = null;
      probe.onerror = null;
      URL.revokeObjectURL(objectUrl);
    };
  }, [image, onError]);

  const pointerPosition = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(rect.width, event.clientX - rect.left)),
      y: Math.max(0, Math.min(rect.height, event.clientY - rect.top)),
    };
  };

  const cropImage = async () => {
    try {
      const source = imageRef.current;
      if (!source || !selection || selection.width < 1 || selection.height < 1) return;
      const crop = scaleCropToImage(
        selection,
        { width: source.clientWidth, height: source.clientHeight },
        { width: source.naturalWidth, height: source.naturalHeight },
      );
      if (!crop) {
        onError("Select a non-empty area inside the captured viewport.");
        return;
      }
      const canvas = document.createElement("canvas");
      canvas.width = crop.width;
      canvas.height = crop.height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Could not crop the selected Earth region.");
      context.drawImage(
        source,
        crop.left,
        crop.top,
        crop.width,
        crop.height,
        0,
        0,
        crop.width,
        crop.height,
      );
      const cropped = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob(
          (blob) =>
            blob ? resolve(blob) : reject(new Error("Could not encode the Earth crop.")),
          "image/png",
        );
      });
      onCrop({
        image: cropped,
        pixelRegion: crop,
        viewportWidth: source.naturalWidth,
        viewportHeight: source.naturalHeight,
      });
    } catch (reason) {
      onError(messageOf(reason));
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Select Earth capture region"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
    >
      <div className="max-h-[90vh] max-w-[95vw] overflow-auto rounded-2xl border border-white/10 bg-surface p-4 text-ink shadow-2xl">
        <p className="mb-3 text-sm">Drag over the captured viewport to select a pixel crop.</p>
        {url && (
          <div
            className="relative inline-block max-w-full touch-none cursor-crosshair"
            onPointerDown={(event) => {
              const point = pointerPosition(event);
              start.current = point;
              event.currentTarget.setPointerCapture(event.pointerId);
              setSelection({ left: point.x, top: point.y, width: 0, height: 0 });
            }}
            onPointerMove={(event) => {
              if (!start.current) return;
              const point = pointerPosition(event);
              setSelection({
                left: Math.min(start.current.x, point.x),
                top: Math.min(start.current.y, point.y),
                width: Math.abs(start.current.x - point.x),
                height: Math.abs(start.current.y - point.y),
              });
            }}
            onPointerUp={() => {
              start.current = null;
            }}
          >
            <img
              ref={imageRef}
              src={url}
              alt="Captured Earth viewport"
              className="block max-h-[65vh] max-w-[85vw] select-none object-contain"
            />
            {selection && (
              <div
                className="pointer-events-none absolute border-2 border-accent bg-accent/20"
                style={{
                  left: selection.left,
                  top: selection.top,
                  width: selection.width,
                  height: selection.height,
                }}
              />
            )}
          </div>
        )}
        <div className="mt-3 flex justify-end gap-2">
          <button type="button" className="rounded border border-white/10 px-3 py-1" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="rounded bg-accent px-3 py-1 text-white disabled:opacity-40"
            onClick={() => void cropImage()}
            disabled={!selection || selection.width < 2 || selection.height < 2}
          >
            Save selected region
          </button>
        </div>
      </div>
    </div>
  );
}

interface ImageViewerProps {
  asset: ImageAsset;
  sessionId: string;
  onClose: () => void;
  onUpdated: (asset: ImageAsset) => void;
  onError: (message: string) => void;
}

function ImageViewer({ asset, sessionId, onClose, onUpdated, onError }: ImageViewerProps) {
  const frame = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragOrigin, setDragOrigin] = useState<{ x: number; y: number } | null>(null);
  const [longitude, setLongitude] = useState(asset.georef?.center?.lng.toString() ?? "");
  const [latitude, setLatitude] = useState(asset.georef?.center?.lat.toString() ?? "");
  const [west, setWest] = useState(asset.georef?.bounds?.west.toString() ?? "");
  const [south, setSouth] = useState(asset.georef?.bounds?.south.toString() ?? "");
  const [east, setEast] = useState(asset.georef?.bounds?.east.toString() ?? "");
  const [north, setNorth] = useState(asset.georef?.bounds?.north.toString() ?? "");
  const [crs, setCrs] = useState(asset.georef?.crs ?? "EPSG:4326");
  const [orientation, setOrientation] = useState(
    asset.georef?.orientation_deg.toString() ?? "0",
  );
  const [resolutionX, setResolutionX] = useState(
    formatOptionalNumber(asset.georef?.pixel_resolution_m?.[0]),
  );
  const [resolutionY, setResolutionY] = useState(
    formatOptionalNumber(asset.georef?.pixel_resolution_m?.[1]),
  );

  const saveGeoreference = async () => {
    try {
      const center = parseOptionalNumbers([longitude, latitude], "center coordinate");
      const bounds = parseOptionalNumbers([west, south, east, north], "bounding box");
      const resolution = parseOptionalNumbers([resolutionX, resolutionY], "pixel resolution");
      const orientationDegrees = Number(orientation);
      if (!Number.isFinite(orientationDegrees)) {
        throw new RangeError("Orientation must be a finite number.");
      }
      if (!crs.trim()) throw new RangeError("CRS cannot be empty.");
      if (crs.trim().length > 128) throw new RangeError("CRS must be 128 characters or fewer.");
      if (
        center &&
        (center[0]! < -180 ||
          center[0]! > 180 ||
          center[1]! < -90 ||
          center[1]! > 90)
      ) {
        throw new RangeError("Center coordinates must be valid longitude and latitude values.");
      }
      if (
        bounds &&
        (bounds[0]! < -180 ||
          bounds[0]! > 180 ||
          bounds[1]! < -90 ||
          bounds[1]! > 90 ||
          bounds[2]! < -180 ||
          bounds[2]! > 180 ||
          bounds[3]! < -90 ||
          bounds[3]! > 90 ||
          bounds[1]! > bounds[3]!)
      ) {
        throw new RangeError("Bounding box coordinates or latitude order are invalid.");
      }
      if (resolution && (resolution[0]! <= 0 || resolution[1]! <= 0)) {
        throw new RangeError("Pixel resolutions must be positive.");
      }
      const georef: GeoReference = {
        bounds: bounds
          ? {
              west: bounds[0]!,
              south: bounds[1]!,
              east: bounds[2]!,
              north: bounds[3]!,
            }
          : null,
        center: center ? { lng: center[0]!, lat: center[1]! } : null,
        crs: crs.trim(),
        orientation_deg: orientationDegrees,
        pixel_resolution_m: resolution ? [resolution[0]!, resolution[1]!] : null,
      };
      const updated = await updateImageAsset(sessionId, asset.id, {
        filename: asset.filename,
        georef,
      });
      onUpdated(updated);
    } catch (reason) {
      onError(messageOf(reason));
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Image viewer"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <div
        ref={frame}
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-surface text-ink shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-white/10 p-3">
          <button type="button" onClick={() => setScale((value) => Math.min(5, value + 0.25))}>Zoom +</button>
          <button type="button" onClick={() => setScale((value) => Math.max(0.25, value - 0.25))}>Zoom −</button>
          <button type="button" onClick={() => setRotation((value) => value + 90)}>Rotate</button>
          <button
            type="button"
            onClick={() => {
              if (!document.fullscreenElement) void frame.current?.requestFullscreen();
              else void document.exitFullscreen();
            }}
          >
            Fullscreen
          </button>
          <button type="button" className="ml-auto" onClick={onClose}>Close</button>
        </div>
        <div
          className="flex min-h-0 flex-1 touch-none items-center justify-center overflow-hidden bg-black/50"
          onPointerDown={(event) => setDragOrigin({ x: event.clientX - offset.x, y: event.clientY - offset.y })}
          onPointerMove={(event) => {
            if (dragOrigin) setOffset({ x: event.clientX - dragOrigin.x, y: event.clientY - dragOrigin.y });
          }}
          onPointerUp={() => setDragOrigin(null)}
          onPointerLeave={() => setDragOrigin(null)}
        >
          <img
            src={imageContentUrl(sessionId, asset.id)}
            alt={asset.filename ?? "Uploaded image"}
            draggable={false}
            style={{
              transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale}) rotate(${rotation}deg)`,
              maxHeight: "65vh",
              maxWidth: "100%",
            }}
          />
        </div>
        <div className="grid gap-3 p-4 text-xs text-ink-dim md:grid-cols-2">
          <dl className="space-y-1">
            <div>{asset.filename ?? "Untitled image"}</div>
            <div>{asset.width} × {asset.height} · {(asset.size_bytes / 1024).toFixed(1)} KiB</div>
            <div>{asset.mime_type} · {new Date(asset.created_at).toLocaleString()}</div>
            <div className="break-all">SHA-256: {asset.sha256}</div>
            <div>
              Georeference: {asset.georef?.center
                ? `${asset.georef.center.lat.toFixed(5)}, ${asset.georef.center.lng.toFixed(5)} (${asset.georef.crs})`
                : "not provided"}
            </div>
          </dl>
          <div className="grid gap-2 sm:grid-cols-2">
            <label>
              Latitude
              <input
                aria-label="Georeference latitude"
                value={latitude}
                onChange={(event) => setLatitude(event.target.value)}
                className="mt-1 block w-28 rounded bg-black/30 px-2 py-1 text-ink"
                inputMode="decimal"
              />
            </label>
            <label>
              Longitude
              <input
                aria-label="Georeference longitude"
                value={longitude}
                onChange={(event) => setLongitude(event.target.value)}
                className="mt-1 block w-28 rounded bg-black/30 px-2 py-1 text-ink"
                inputMode="decimal"
              />
            </label>
            <label>
              West
              <input
                aria-label="Georeference west"
                value={west}
                onChange={(event) => setWest(event.target.value)}
                className="mt-1 block w-full rounded bg-black/30 px-2 py-1 text-ink"
                inputMode="decimal"
              />
            </label>
            <label>
              South
              <input
                aria-label="Georeference south"
                value={south}
                onChange={(event) => setSouth(event.target.value)}
                className="mt-1 block w-full rounded bg-black/30 px-2 py-1 text-ink"
                inputMode="decimal"
              />
            </label>
            <label>
              East
              <input
                aria-label="Georeference east"
                value={east}
                onChange={(event) => setEast(event.target.value)}
                className="mt-1 block w-full rounded bg-black/30 px-2 py-1 text-ink"
                inputMode="decimal"
              />
            </label>
            <label>
              North
              <input
                aria-label="Georeference north"
                value={north}
                onChange={(event) => setNorth(event.target.value)}
                className="mt-1 block w-full rounded bg-black/30 px-2 py-1 text-ink"
                inputMode="decimal"
              />
            </label>
            <label>
              CRS
              <input
                aria-label="Georeference CRS"
                value={crs}
                onChange={(event) => setCrs(event.target.value)}
                className="mt-1 block w-full rounded bg-black/30 px-2 py-1 text-ink"
              />
            </label>
            <label>
              Orientation (°)
              <input
                aria-label="Georeference orientation"
                value={orientation}
                onChange={(event) => setOrientation(event.target.value)}
                className="mt-1 block w-full rounded bg-black/30 px-2 py-1 text-ink"
                inputMode="decimal"
              />
            </label>
            <label>
              Pixel resolution X (m)
              <input
                aria-label="Pixel resolution X"
                value={resolutionX}
                onChange={(event) => setResolutionX(event.target.value)}
                className="mt-1 block w-full rounded bg-black/30 px-2 py-1 text-ink"
                inputMode="decimal"
              />
            </label>
            <label>
              Pixel resolution Y (m)
              <input
                aria-label="Pixel resolution Y"
                value={resolutionY}
                onChange={(event) => setResolutionY(event.target.value)}
                className="mt-1 block w-full rounded bg-black/30 px-2 py-1 text-ink"
                inputMode="decimal"
              />
            </label>
            <button
              type="button"
              onClick={() => void saveGeoreference()}
              className="rounded border border-white/10 px-3 py-1 text-ink"
            >
              Save georeference
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
