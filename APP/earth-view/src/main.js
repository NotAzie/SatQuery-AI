import { createStandaloneApplication } from './standalone/application.js';
import { describeError } from './standalone/errors.js';

const application = createStandaloneApplication({
  googleApiKey: import.meta.env.GOOGLE_MAPS_API_KEY,
  cesiumToken: import.meta.env.CESIUM_ION_TOKEN,
  allowQaRegistration: import.meta.env.DEV,
});

export const applicationReady = application.start().then(() => {
  const runtime = window.__godsEyeView;
  if (!runtime?.viewer || !runtime?.dataManager) {
    throw new Error('Earth View started without exposing its runtime');
  }
  return runtime;
});

applicationReady.catch((error) => {
  console.error("Earth View initialization failed:", error);
  const message = describeError(error);
  const loaderStatus = document.querySelector('#loading-screen .loader-status');
  if (loaderStatus) {
    loaderStatus.textContent = `Error: ${message}`;
    loaderStatus.style.color = '#ff4444';
  }
});

export { application };
