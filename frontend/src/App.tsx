import { createBrowserRouter, Navigate } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { Dashboard } from "@/pages/Dashboard";
import { Timeline } from "@/pages/Timeline";
import { GraphView } from "@/pages/GraphView";
import { Evidence } from "@/pages/Evidence";
import { CaseManager } from "@/pages/CaseManager";
import { Reports } from "@/pages/Reports";
import { Settings } from "@/pages/Settings";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "timeline", element: <Timeline /> },
      { path: "graph", element: <GraphView /> },
      { path: "evidence", element: <Evidence /> },
      { path: "cases", element: <CaseManager /> },
      { path: "cases/:investigationId", element: <CaseManager /> },
      { path: "reports", element: <Reports /> },
      { path: "settings", element: <Settings /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
