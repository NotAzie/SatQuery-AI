import { Color, Ion, Viewer } from "cesium";

import { CESIUM_ION_TOKEN } from "@/shared/constants";

/**
 * Creates a chrome-free Cesium viewer: the Earth is the workspace, so every built-in widget is
 * off. Without an ion token there is no default imagery; base imagery is then supplied through
 * the layer catalogue (earth/layers) instead of silently failing.
 */
export function createViewer(container: HTMLElement): Viewer {
  if (CESIUM_ION_TOKEN) Ion.defaultAccessToken = CESIUM_ION_TOKEN;

  const viewer = new Viewer(container, {
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    baseLayer: CESIUM_ION_TOKEN ? undefined : false,
  });
  viewer.scene.globe.baseColor = Color.fromCssColorString("#0a1220");
  viewer.scene.backgroundColor = Color.fromCssColorString("#04060a");
  return viewer;
}
