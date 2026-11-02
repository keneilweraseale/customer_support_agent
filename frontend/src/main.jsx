import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import AdminDashboard from "./components/AdminDashboard.jsx";
import "./styles.css";
import "./admin.css";

const Page = window.location.pathname.startsWith("/admin")
  ? AdminDashboard
  : App;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Page />
  </React.StrictMode>,
);
