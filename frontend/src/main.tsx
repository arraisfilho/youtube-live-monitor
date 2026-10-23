import "@fontsource-variable/inter";
import "./design-kit/base.css";
import "./design-kit/layout.css";
import "./design-kit/auth.css";
import "./design-kit/glass.css";
import "./app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
