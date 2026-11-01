import type { Viewer } from "cesium";

/** Renders one frame and returns it as PNG: feeds the vision pipeline ("what am I looking at?"). */
export function captureViewer(viewer: Viewer): Promise<Blob> {
  viewer.render(); // draw immediately so the WebGL buffer is valid when read
  return new Promise((resolve, reject) => {
    viewer.canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Earth capture failed"))),
      "image/png",
    );
  });
}

export interface CaptureController {
  captureEarth(): Promise<Blob>;
}
