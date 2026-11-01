import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "./layout/AppShell";
import { WorkspaceRoute } from "./routes/WorkspaceRoute";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <WorkspaceRoute /> },
      { path: "s/:sessionId", element: <WorkspaceRoute /> },
    ],
  },
]);
