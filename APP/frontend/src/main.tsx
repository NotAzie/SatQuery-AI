import "../../earth-view/src/main.js";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/app/App";
import "@/styles/globals.css";
import "../../earth-view/style.css";
import "@/earth/integration/godsEyeIntegration.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
