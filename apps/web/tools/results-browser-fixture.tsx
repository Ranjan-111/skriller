// Isolated test harness: synthetic tenant API, never the user's Firebase session.
import React from "react";
import { createRoot } from "react-dom/client";
import { ResearchResultsPanel } from "../src/components/research-results";
import { createApi, type ResearchJob } from "../src/lib/api";
import "../src/app/globals.css";

declare global {
  interface Window {
    fixtureJob: ResearchJob;
  }
}

const api = createApi("/api");
createRoot(document.getElementById("root")!).render(
  <main>
    <ResearchResultsPanel api={api} job={window.fixtureJob} />
  </main>,
);
