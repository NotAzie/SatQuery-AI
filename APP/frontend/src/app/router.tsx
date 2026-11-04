import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "./layout/AppShell";
import { WorkspaceRoute } from "./routes/WorkspaceRoute";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <WorkspaceRoute /> },
      { path: "s/:sessionId", element: <WorkspaceRoute /> },
      {
        path: "p/:projectId",
        lazy: async () => {
          const { ProjectRoute } = await import("./routes/ProjectRoute");
          return { Component: ProjectRoute };
        },
      },
      {
        path: "p/:projectId/comparisons/:comparisonId",
        lazy: async () => {
          const { InvestigationComparisonRoute } = await import(
            "./routes/InvestigationComparisonRoute"
          );
          return { Component: InvestigationComparisonRoute };
        },
      },
      {
        path: "p/:projectId/investigations/:sessionId/:investigationId",
        lazy: async () => {
          const { InvestigationRoute } = await import("./routes/InvestigationRoute");
          return { Component: InvestigationRoute };
        },
      },
    ],
  },
]);
