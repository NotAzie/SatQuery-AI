import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "./layout/AppShell";
import { InvestigationComparisonRoute } from "./routes/InvestigationComparisonRoute";
import { InvestigationRoute } from "./routes/InvestigationRoute";
import { ProjectRoute } from "./routes/ProjectRoute";
import { WorkspaceRoute } from "./routes/WorkspaceRoute";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <WorkspaceRoute /> },
      { path: "s/:sessionId", element: <WorkspaceRoute /> },
      { path: "p/:projectId", element: <ProjectRoute /> },
      {
        path: "p/:projectId/comparisons/:comparisonId",
        element: <InvestigationComparisonRoute />,
      },
      {
        path: "p/:projectId/investigations/:sessionId/:investigationId",
        element: <InvestigationRoute />,
      },
    ],
  },
]);
