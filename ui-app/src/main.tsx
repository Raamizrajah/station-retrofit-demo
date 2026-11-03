import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@lego/connect-core-tokens";
import "@lego/connect-theme-enterprise";
import { ErrorBoundary } from "./ErrorBoundary";
import App from "./App";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element #root not found");

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
