import * as Cesium from 'cesium';
import { isPickedWorldPosition } from '../data/scenePick.js';

function trackedTarget(viewer) {
  const entity = viewer.trackedEntity;
  return (
    entity?.gevDisplayPosition?.() ||
    entity?.position?.getValue(viewer.clock?.currentTime)
  );
}

export const OBLIQUE_PITCH = Cesium.Math.toRadians(-35);
export const STRAIGHT_DOWN_PITCH = Cesium.Math.toRadians(-89);
const OBLIQUE_THRESHOLD = Cesium.Math.toRadians(-60);

export function normalizedHeading(heading) {
  const wrapped = Cesium.Math.zeroToTwoPi(
    Number.isFinite(heading) ? heading : 0,
  );
  return Math.abs(wrapped - Cesium.Math.TWO_PI) < Cesium.Math.EPSILON10
    ? 0
    : wrapped;
}

export function formatCoordinates(latDeg, lonDeg) {
  if (!Number.isFinite(latDeg) || !Number.isFinite(lonDeg)) return '--';
  const latHemi = latDeg >= 0 ? 'N' : 'S';
  const lonHemi = lonDeg >= 0 ? 'E' : 'W';
  const absLat = Math.abs(latDeg);
  const absLon = Math.abs(lonDeg);
  const latD = Math.floor(absLat);
  const latM = Math.floor((absLat - latD) * 60);
  const latS = Math.round(((absLat - latD) * 60 - latM) * 60);
  const lonD = Math.floor(absLon);
  const lonM = Math.floor((absLon - lonD) * 60);
  const lonS = Math.round(((absLon - lonD) * 60 - lonM) * 60);
  return `${latD}°${String(latM).padStart(2, '0')}'${String(latS).padStart(2, '0')}"${latHemi} ${lonD}°${String(lonM).padStart(2, '0')}'${String(lonS).padStart(2, '0')}"${lonHemi}`;
}

export function formatAltitude(altMeters) {
  if (!Number.isFinite(altMeters)) return '--';
  if (altMeters >= 1_000_000) {
    return `${(altMeters / 1_000_000).toFixed(1)} Mm`;
  }
  if (altMeters >= 10_000) {
    return `${Math.round(altMeters / 1_000).toLocaleString()} km`;
  }
  return `${Math.round(altMeters).toLocaleString()} m`;
}

export function formatHeadingPitch(headingDeg, pitchDeg) {
  const hdg = Math.round(Number.isFinite(headingDeg) ? headingDeg : 0) % 360;
  const ptc = Math.round(Number.isFinite(pitchDeg) ? pitchDeg : 0);
  return `HDG ${String(hdg >= 0 ? hdg : hdg + 360).padStart(3, '0')}° · ${ptc > 0 ? '+' : ''}${ptc}°`;
}

function updateTelemetry(viewer, telemetry) {
  if (!telemetry || !viewer?.camera) return;
  const pos = viewer.camera.positionCartographic;
  if (!pos) return;

  const latDeg = Cesium.Math.toDegrees(pos.latitude);
  const lonDeg = Cesium.Math.toDegrees(pos.longitude);
  const heightM = pos.height;
  const hdgDeg = Cesium.Math.toDegrees(viewer.camera.heading);
  const pitchDeg = Cesium.Math.toDegrees(viewer.camera.pitch);

  if (telemetry.coords) {
    const text = formatCoordinates(latDeg, lonDeg);
    if (telemetry.coords.textContent !== text) {
      telemetry.coords.textContent = text;
    }
  }

  if (telemetry.altitude) {
    const text = formatAltitude(heightM);
    if (telemetry.altitude.textContent !== text) {
      telemetry.altitude.textContent = text;
    }
  }

  if (telemetry.heading) {
    const text = formatHeadingPitch(hdgDeg, pitchDeg);
    if (telemetry.heading.textContent !== text) {
      telemetry.heading.textContent = text;
    }
  }
}

export function pickViewTarget(viewer) {
  const scene = viewer?.scene;
  const camera = viewer?.camera;
  const canvas = scene?.canvas;
  if (!scene || !camera || !canvas) return null;
  const width = canvas.clientWidth || canvas.width || 0;
  const height = canvas.clientHeight || canvas.height || 0;
  if (!width || !height) return null;
  const center = new Cesium.Cartesian2(width / 2, height / 2);
  let target = null;

  if (scene.pickPositionSupported && typeof scene.pickPosition === 'function') {
    try {
      target = scene.pickPosition(center);
    } catch {
      target = null;
    }
  }
  if (
    !isPickedWorldPosition(target) &&
    typeof camera.getPickRay === 'function'
  ) {
    try {
      target = scene.globe?.pick(camera.getPickRay(center), scene) || null;
    } catch {
      target = null;
    }
  }
  if (
    !isPickedWorldPosition(target) &&
    typeof camera.pickEllipsoid === 'function'
  ) {
    try {
      target = camera.pickEllipsoid(center, Cesium.Ellipsoid.WGS84);
    } catch {
      target = null;
    }
  }
  return isPickedWorldPosition(target) ? target : null;
}

export function readCameraTargetFrame(viewer) {
  const camera = viewer?.camera;
  const target = viewer?.trackedEntity
    ? trackedTarget(viewer)
    : pickViewTarget(viewer);
  if (!camera || !target || !isPickedWorldPosition(camera.positionWC))
    return null;

  const transform = Cesium.Transforms.eastNorthUpToFixedFrame(target);
  const inverse = Cesium.Matrix4.inverseTransformation(
    transform,
    new Cesium.Matrix4(),
  );
  const localOffset = Cesium.Matrix4.multiplyByPoint(
    inverse,
    camera.positionWC,
    new Cesium.Cartesian3(),
  );
  const range = Cesium.Cartesian3.magnitude(localOffset);
  if (!Number.isFinite(range) || range < 1) return null;

  const pitch = -Math.asin(Cesium.Math.clamp(localOffset.z / range, -1, 1));
  const targetHeading = Math.atan2(-localOffset.x, -localOffset.y);
  const heading = normalizedHeading(
    pitch < Cesium.Math.toRadians(-88.5) ? camera.heading : targetHeading,
  );
  return { target, range, heading, pitch };
}

export function setCameraTargetFrame(viewer, frame) {
  const camera = viewer?.camera;
  if (!camera || !frame?.target || !Number.isFinite(frame.range)) return false;
  try {
    const trackedTransform = viewer.trackedEntity
      ? Cesium.Matrix4.clone(camera.transform)
      : null;
    camera.lookAt(
      frame.target,
      new Cesium.HeadingPitchRange(
        normalizedHeading(frame.heading),
        frame.pitch,
        frame.range,
      ),
    );
    if (trackedTransform) {
      camera.lookAtTransform(trackedTransform);
      viewer.scene?.requestRender?.();
      return true;
    }
    const destination = Cesium.Cartesian3.clone(camera.positionWC);
    const direction = Cesium.Cartesian3.clone(camera.directionWC);
    const up = Cesium.Cartesian3.clone(camera.upWC);
    camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    if (destination && direction && up) {
      camera.setView({ destination, orientation: { direction, up } });
    }
    viewer.scene?.requestRender?.();
    return true;
  } catch {
    return false;
  }
}

export function frameIsTilted(frame) {
  return frame ? frame.pitch > OBLIQUE_THRESHOLD : false;
}

export function headingDegrees(camera) {
  return Cesium.Math.toDegrees(normalizedHeading(camera?.heading));
}

export function targetFrameHeadingOffset(currentHeading, targetHeading) {
  let delta = normalizedHeading(targetHeading) - normalizedHeading(currentHeading);
  while (delta > Math.PI) delta -= Cesium.Math.TWO_PI;
  while (delta < -Math.PI) delta += Cesium.Math.TWO_PI;
  return delta;
}

export function toggleCameraTilt(viewer) {
  const frame = readCameraTargetFrame(viewer);
  if (!frame) return false;
  const nextTilted = !frameIsTilted(frame);
  const pitch = nextTilted ? OBLIQUE_PITCH : STRAIGHT_DOWN_PITCH;
  if (!setCameraTargetFrame(viewer, { ...frame, pitch })) return false;
  return { tilted: nextTilted, pitch };
}

export function resetCameraNorth(viewer) {
  const frame = readCameraTargetFrame(viewer);
  if (!frame) return false;
  return setCameraTargetFrame(viewer, { ...frame, heading: 0 });
}

export function createCameraOrientationAnimator(viewer, { now = () => performance.now(), duration = 650 } = {}) {
  let removeListener = null;
  let destination = null;

  function cancel() {
    destination = null;
    if (removeListener) {
      removeListener();
      removeListener = null;
    }
  }

  function animate(frame, { heading, pitch }) {
    if (!frame || !viewer?.camera) return false;
    cancel();

    const startHeading = frame.heading;
    const startPitch = frame.pitch;
    const endHeading = heading ?? startHeading;
    const endPitch = pitch ?? startPitch;
    const headingDelta = targetFrameHeadingOffset(startHeading, endHeading);
    const pitchDelta = endPitch - startPitch;

    destination = { heading: endHeading, pitch: endPitch, range: frame.range };
    const startTime = now();
    const initialTracked = viewer.trackedEntity;

    const onUpdate = () => {
      if (viewer.trackedEntity !== initialTracked) {
        cancel();
        return;
      }
      const elapsed = now() - startTime;
      const progress = Cesium.Math.clamp(elapsed / duration, 0, 1);
      const eased = Cesium.EasingFunction.CUBIC_IN_OUT(progress);

      const currentHeading = normalizedHeading(startHeading + headingDelta * eased);
      const currentPitch = Cesium.Math.lerp(startPitch, endPitch, eased);

      setCameraTargetFrame(viewer, {
        target: viewer.trackedEntity
          ? trackedTarget(viewer)
          : frame.target,
        range: frame.range,
        heading: currentHeading,
        pitch: currentPitch,
      });

      if (progress >= 1) {
        cancel();
      }
    };

    if (!viewer.scene?.preUpdate?.addEventListener) {
      setCameraTargetFrame(viewer, {
        target: viewer.trackedEntity
          ? trackedTarget(viewer)
          : frame.target,
        range: frame.range,
        heading: endHeading,
        pitch: endPitch,
      });
      destination = null;
      return true;
    }

    removeListener = viewer.scene.preUpdate.addEventListener(onUpdate);
    return true;
  }

  return {
    animate,
    cancel,
    get destination() {
      return destination;
    },
  };
}

export function bindCameraOrientationControls({
  viewer,
  elements,
  runNavigation,
  showToast,
}) {
  const tiltButton = elements?.tiltButton;
  const northButton = elements?.northButton;
  const zoomInButton = elements?.zoomInButton;
  const zoomOutButton = elements?.zoomOutButton;
  const myLocationButton = elements?.myLocationButton;
  const orbitButton = elements?.orbitButton;
  const zenButton = elements?.zenButton;
  const splatButton = elements?.splatButton;
  const splatDialog = elements?.splatDialog;
  const orbitController = elements?.orbitController;
  const toggleCleanView = elements?.toggleCleanView;
  const telemetry = elements?.telemetry;
  const removers = [];
  let destroyed = false;
  let applied = null;
  let activeSplatTileset = null;
  let tilted = false;
  const animator = createCameraOrientationAnimator(viewer);

  const refreshTilt = () => {
    if (destroyed) return;
    tilted = frameIsTilted(readCameraTargetFrame(viewer));
    sync();
  };

  function sync() {
    if (destroyed) return;
    if (telemetry) {
      updateTelemetry(viewer, telemetry);
    }
    const next = {
      tilted,
      heading: Math.round(headingDegrees(viewer?.camera)) % 360,
    };
    if (
      applied &&
      applied.tilted === next.tilted &&
      applied.heading === next.heading
    )
      return;
    if (!applied || applied.tilted !== next.tilted) {
      tiltButton?.setAttribute('aria-pressed', String(next.tilted));
      tiltButton?.setAttribute(
        'aria-label',
        next.tilted
          ? 'Return map to straight-down view'
          : 'Tilt map to oblique view',
      );
    }
    if (!applied || applied.heading !== next.heading) {
      northButton?.setAttribute('data-north-up', String(next.heading === 0));
      northButton?.style?.setProperty('--camera-heading', `${next.heading}deg`);
      northButton?.setAttribute(
        'aria-label',
        `Reset map to north up. Current heading ${next.heading} degrees`,
      );
    }
    applied = next;
  }

  const listen = (element, handler) => {
    if (!element) return;
    element.addEventListener('click', handler);
    removers.push(() => element.removeEventListener('click', handler));
  };

  listen(tiltButton, () => {
    const pending = animator.destination;
    const result = runNavigation('camera', () => {
      const frame = readCameraTargetFrame(viewer);
      if (!frame) return false;
      const nextTilted = !frameIsTilted(pending || frame);
      const pitch = nextTilted ? OBLIQUE_PITCH : STRAIGHT_DOWN_PITCH;
      return animator.animate(frame, {
        heading: pending?.heading ?? frame.heading,
        pitch,
      })
        ? { tilted: nextTilted, pitch }
        : false;
    });
    if (result) {
      showToast?.(result.tilted ? 'Tilted view' : 'Straight-down view');
      tilted = result.tilted;
    }
    sync();
  });

  listen(northButton, () => {
    const pending = animator.destination;
    const result = runNavigation('camera', () => {
      const frame = readCameraTargetFrame(viewer);
      return (
        frame &&
        animator.animate(frame, {
          heading: 0,
          pitch: pending?.pitch ?? frame.pitch,
        })
      );
    });
    if (result) showToast?.('North up');
    sync();
  });

  listen(zoomInButton, () => {
    runNavigation('camera', () => {
      const height = viewer?.camera?.positionCartographic?.height || 10000;
      viewer?.camera?.zoomIn?.(height * 0.4);
      return true;
    });
    refreshTilt();
  });

  listen(zoomOutButton, () => {
    runNavigation('camera', () => {
      const height = viewer?.camera?.positionCartographic?.height || 10000;
      viewer?.camera?.zoomOut?.(height * 0.5);
      return true;
    });
    refreshTilt();
  });

  listen(myLocationButton, () => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      showToast?.('Geolocation not supported by browser');
      return;
    }
    showToast?.('Locating position...');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        if (!viewer?.camera) return;
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(longitude, latitude, 2500),
          duration: 2.5,
          easingFunction: Cesium.EasingFunction.CUBIC_IN_OUT,
        });
        showToast?.(`Position: ${latitude.toFixed(4)}°, ${longitude.toFixed(4)}°`);
      },
      (err) => {
        showToast?.(`Location unavailable: ${err?.message || 'Permission denied'}`);
      },
      { timeout: 10000, enableHighAccuracy: true },
    );
  });

  let orbitActive = false;
  const toggleOrbit = () => {
    if (orbitController) {
      orbitController.toggleOrbit();
      return;
    }
    orbitActive = !orbitActive;
    orbitButton?.setAttribute('aria-pressed', String(orbitActive));
    orbitButton?.classList.toggle('active', orbitActive);
    showToast?.(orbitActive ? 'Cinematic Orbit: Active' : 'Cinematic Orbit: Paused');
  };
  listen(orbitButton, toggleOrbit);

  const toggleZen = () => {
    if (typeof toggleCleanView === 'function') {
      const isClean = toggleCleanView();
      zenButton?.setAttribute('aria-pressed', String(isClean));
      zenButton?.classList.toggle('active', isClean);
      showToast?.(isClean ? 'Zen Mode: UI hidden (ESC to return)' : 'Zen Mode deactivated');
    }
  };
  listen(zenButton, toggleZen);

  const splatDialogCloseBtn = splatDialog?.querySelector?.('#splat-dialog-close');
  const splatLoadBtn = splatDialog?.querySelector?.('#splat-load-btn');
  const splatUnloadBtn = splatDialog?.querySelector?.('#splat-unload-btn');
  const splatStatusLabel = splatDialog?.querySelector?.('#splat-status-label');
  const splatCustomUrl = splatDialog?.querySelector?.('#splat-custom-url');
  const splatCoordLat = splatDialog?.querySelector?.('#splat-coord-lat');
  const splatCoordLon = splatDialog?.querySelector?.('#splat-coord-lon');
  const splatCoordAlt = splatDialog?.querySelector?.('#splat-coord-alt');

  const toggleSplatDialog = () => {
    if (!splatDialog) return;
    if (splatDialog.open) {
      splatDialog.close?.() || splatDialog.removeAttribute('open');
      splatButton?.classList.remove('active');
    } else {
      if (typeof splatDialog.showModal === 'function') {
        splatDialog.showModal();
      } else {
        splatDialog.setAttribute('open', '');
      }
      splatButton?.classList.add('active');
    }
  };
  listen(splatButton, toggleSplatDialog);
  listen(splatDialogCloseBtn, () => {
    splatDialog?.close?.() || splatDialog?.removeAttribute('open');
    splatButton?.classList.remove('active');
  });

  const splatPresets = {
    'bhote-koshi': {
      name: 'Bhote Koshi Canyon',
      lat: 28.1885,
      lon: 85.3195,
      alt: 2200,
      heading: 30,
      pitch: -35,
    },
    eiffel: {
      name: 'Eiffel Tower',
      lat: 48.8584,
      lon: 2.2945,
      alt: 500,
      heading: 45,
      pitch: -28,
    },
    'sf-rotunda': {
      name: 'Palace of Fine Arts',
      lat: 37.8029,
      lon: -122.4485,
      alt: 350,
      heading: 120,
      pitch: -30,
    },
  };

  const presetCards = splatDialog?.querySelectorAll?.('[data-splat-id]');
  presetCards?.forEach?.((card) => {
    listen(card, () => {
      const id = card.getAttribute('data-splat-id');
      const preset = splatPresets[id];
      if (!preset || !viewer?.camera) return;
      splatDialog?.close?.() || splatDialog?.removeAttribute('open');
      splatButton?.classList.remove('active');
      showToast?.(`Navigating to 3D Gaussian Splat: ${preset.name}...`);
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(preset.lon, preset.lat, preset.alt),
        orientation: {
          heading: Cesium.Math.toRadians(preset.heading),
          pitch: Cesium.Math.toRadians(preset.pitch),
          roll: 0,
        },
        duration: 3.5,
        easingFunction: Cesium.EasingFunction.CUBIC_IN_OUT,
        complete: () => {
          showToast?.(`3DGS Radiance Field Loaded: ${preset.name}`);
        },
      });
    });
  });

  const unloadSplat = () => {
    if (activeSplatTileset && viewer?.scene?.primitives) {
      try {
        viewer.scene.primitives.remove(activeSplatTileset);
      } catch {
        // Ignored
      }
      activeSplatTileset = null;
    }
    if (splatStatusLabel) splatStatusLabel.textContent = 'READY';
    if (splatUnloadBtn) splatUnloadBtn.hidden = true;
    showToast?.('3D Gaussian Splat unloaded');
  };
  listen(splatUnloadBtn, unloadSplat);

  const loadCustomSplat = async () => {
    const url = splatCustomUrl?.value?.trim();
    if (!url) {
      showToast?.('Please enter a 3D Tileset / Gaussian Splat URL');
      return;
    }
    if (splatStatusLabel) splatStatusLabel.textContent = 'LOADING TILESET...';
    try {
      unloadSplat();
      const lat = parseFloat(splatCoordLat?.value);
      const lon = parseFloat(splatCoordLon?.value);
      const alt = parseFloat(splatCoordAlt?.value) || 0;

      let modelMatrix = Cesium.Matrix4.IDENTITY;
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        modelMatrix = Cesium.Transforms.eastNorthUpToFixedFrame(
          Cesium.Cartesian3.fromDegrees(lon, lat, alt),
        );
      }

      const tileset = await Cesium.Cesium3DTileset.fromUrl(url, {
        modelMatrix,
        maximumScreenSpaceError: 2,
      });

      if (viewer?.scene?.primitives) {
        viewer.scene.primitives.add(tileset);
        activeSplatTileset = tileset;
      }

      if (splatStatusLabel) splatStatusLabel.textContent = '3DGS ACTIVE';
      if (splatUnloadBtn) splatUnloadBtn.hidden = false;
      splatDialog?.close?.() || splatDialog?.removeAttribute('open');
      splatButton?.classList.remove('active');
      showToast?.('3D Gaussian Splatting loaded successfully');

      if (viewer?.camera) {
        if (Number.isFinite(lat) && Number.isFinite(lon)) {
          viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(lon, lat, alt + 300),
            orientation: {
              heading: 0,
              pitch: Cesium.Math.toRadians(-35),
              roll: 0,
            },
            duration: 3.0,
          });
        } else if (tileset.boundingSphere) {
          viewer.camera.flyToBoundingSphere(tileset.boundingSphere, { duration: 3.0 });
        }
      }
    } catch (err) {
      if (splatStatusLabel) splatStatusLabel.textContent = 'LOAD ERROR';
      showToast?.(`Failed to load 3DGS: ${err?.message || err}`);
    }
  };
  listen(splatLoadBtn, loadCustomSplat);

  const handleKeydown = (event) => {
    if (destroyed) return;
    const tag = event.target?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || event.target?.isContentEditable) {
      return;
    }
    if (event.altKey || event.ctrlKey || event.metaKey) return;

    if (event.key === 'n' || event.key === 'N') {
      northButton?.click();
    } else if (event.key === 'u' || event.key === 'U') {
      tiltButton?.click();
    } else if (event.key === 'o' || event.key === 'O') {
      toggleOrbit();
    } else if (event.key === 'z' || event.key === 'Z') {
      toggleZen();
    } else if (event.key === 'g' || event.key === 'G') {
      toggleSplatDialog();
    } else if (event.key === '+' || event.key === '=') {
      zoomInButton?.click();
    } else if (event.key === '-' || event.key === '_') {
      zoomOutButton?.click();
    }
  };
  if (typeof window !== 'undefined') {
    window.addEventListener('keydown', handleKeydown);
    removers.push(() => window.removeEventListener('keydown', handleKeydown));
  }

  const subscribe = (event, handler) => {
    const remove = event?.addEventListener?.(handler);
    if (typeof remove === 'function') removers.push(remove);
  };
  subscribe(viewer?.scene?.preRender, sync);
  subscribe(viewer?.camera?.moveEnd, refreshTilt);
  subscribe(viewer?.trackedEntityChanged, animator.cancel);
  for (const type of ['pointerdown', 'wheel']) {
    const canvas = viewer?.scene?.canvas;
    canvas?.addEventListener?.(type, animator.cancel, { passive: true });
    removers.push(() => canvas?.removeEventListener?.(type, animator.cancel));
  }
  refreshTilt();

  return {
    sync,
    refreshTilt,
    cancel: animator.cancel,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      animator.cancel();
      if (activeSplatTileset && viewer?.scene?.primitives) {
        try {
          viewer.scene.primitives.remove(activeSplatTileset);
        } catch {
          // Ignored
        }
        activeSplatTileset = null;
      }
      for (const remove of removers.splice(0)) remove();
    },
  };
}
