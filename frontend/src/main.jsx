import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import AdminDashboard from "./components/AdminDashboard.jsx";
import ArchitectureDiagram from "./components/ArchitectureDiagram.jsx";
import "./styles.css";
import "./admin.css";

const path = window.location.pathname;
const Page = path.startsWith("/admin")
  ? AdminDashboard
  : path.startsWith("/architecture")
    ? ArchitectureDiagram
    : App;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Page />
  </React.StrictMode>,
);
