"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  FileSearch,
  FlaskConical,
  Layers,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Settings,
} from "lucide-react";
import {
  ApiError,
  createApi,
  type Health,
  type ResearchJob,
  type Source,
} from "../lib/api";

import { WorkspaceDialog } from "./workspace-dialog";
import { IdentityControls, useIdentity } from "./identity";
import { ResearchResultsPanel } from "./research-results";
import { WorkspaceAllowancePanel } from "./workspace-allowance";
import { YouTubeAnalyticsPanel } from "./youtube-analytics";
import { SalesforcePanel } from "./salesforce-panel";
import { BillingPanel } from "./billing-panel";
import { RedditConnectionPanel } from "./reddit-connection-panel";
import { XConnectionPanel } from "./x-connection-panel";
const sources = [
  { id: "linkedin", name: "LinkedIn", detail: "Professional discovery" },
  { id: "reddit", name: "Reddit", detail: "Discussions & demand" },
  { id: "web", name: "Web", detail: "Company websites & search" },
  {
    id: "instagram",
    name: "Instagram",
    detail: "Public profile references; connected reads when configured",
  },
  {
    id: "facebook",
    name: "Facebook",
    detail: "Page references; connected headers when configured",
  },
  { id: "youtube", name: "YouTube", detail: "Public video references" },
  {
    id: "x",
    name: "X",
    detail: "Direct public posts (owner connection required)",
  },
] as const;
const examples = {
  leads: [
    "Find fintech founders in Bengaluru. Prioritise companies hiring engineers.",
    "Find B2B agencies in London with a public portfolio of healthcare clients.",
  ],
  research: [
    "Research how small teams discuss CRM migration on Reddit. Cite the original discussions.",
    "Compare the public positioning of three companies and explain the differences.",
  ],
};

export function Workbench() {
  const identity = useIdentity();
  const accountId = identity.user?.uid;
  const currentAccount = useRef(accountId);
  currentAccount.current = accountId;
  const tokenProvider = useRef(identity.getToken);
  tokenProvider.current = identity.getToken;
  const billingToken = useCallback(
    (force?: boolean) => tokenProvider.current(force),
    [],
  );
  const api = useMemo(
    () =>
      createApi(undefined, undefined, (force) => tokenProvider.current(force)),
    [],
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [connectionPrompt, setConnectionPrompt] = useState(false);
  const xSettings = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<"leads" | "research">("leads");
  const [prompt, setPrompt] = useState("");
  const [selected, setSelected] = useState<Source[]>([
    "linkedin",
    "reddit",
    "web",
  ]);
  const [limit, setLimit] = useState(25);
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(true);
  const [healthError, setHealthError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<ResearchJob | null>(null);
  const [jobAccount, setJobAccount] = useState<string | undefined>();
  const [showSources, setShowSources] = useState(false);
  const [xConnected, setXConnected] = useState(false);
  const [redditRefreshKey, setRedditRefreshKey] = useState(0);
  const reportRedditRefresh = useCallback(() => {
    setRedditRefreshKey((value) => value + 1);
  }, []);
  const reportXConnection = useCallback((connected: boolean) => {
    setXConnected(connected);
    if (!connected)
      setSelected((current) => current.filter((source) => source !== "x"));
  }, []);
  const mounted = useRef(true);
  const composer = useRef<HTMLTextAreaElement>(null);
  const checkHealth = useCallback(async () => {
    setChecking(true);
    setHealthError("");
    try {
      const result = await api.health();
      if (mounted.current) setHealth(result);
    } catch (e) {
      if (mounted.current) {
        setHealth(null);
        setHealthError(e instanceof Error ? e.message : "Service unavailable.");
      }
    } finally {
      if (mounted.current) setChecking(false);
    }
  }, [api]);
  useEffect(() => {
    mounted.current = true;
    void checkHealth();
    return () => {
      mounted.current = false;
    };
  }, [checkHealth]);

  useEffect(() => {
    setJob(null);
    setError("");
  }, [identity.status, accountId]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (!prompt.trim()) {
      setError("Describe who or what you want to research.");
      composer.current?.focus();
      return;
    }
    if (!selected.length) {
      setError("Choose at least one source to search.");
      return;
    }
    if (identity.status !== "signed_in") {
      setError(
        "Sign in to your app account to start research. Your prompt is kept here.",
      );
      return;
    }
    setBusy(true);
    setJob(null);
    const submittedAccount = currentAccount.current;
    try {
      const result = await api.submit({
        prompt: prompt.trim(),
        mode,
        sources: selected,
        result_limit: limit,
      });
      if (mounted.current && currentAccount.current === submittedAccount) {
        setJobAccount(submittedAccount);
        setJob(result);
      }
    } catch (e) {
      if (mounted.current)
        setError(
          e instanceof ApiError
            ? e.message
            : "The request could not be started. Try again.",
        );
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  function newResearch() {
    setPrompt("");
    setJob(null);
    setError("");
    composer.current?.focus();
  }
  const serviceLabel = checking
    ? "Checking service"
    : health?.ready
      ? "Service ready"
      : health?.live
        ? "Service starting"
        : "Service offline";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#research">
        Skip to research
      </a>
      <aside className="sidebar" aria-label="Workspace">
        <a className="brand" href="/" aria-label="Skriller home">
          <span className="brand-mark">
            <Layers size={19} aria-hidden="true" />
          </span>
          Skriller<span className="pilot">Pilot</span>
        </a>
        <button className="new-button" onClick={newResearch} disabled={busy}>
          <Plus size={17} aria-hidden="true" /> New research
        </button>
        <nav aria-label="Research mode">
          <button
            className={mode === "leads" ? "nav-item active" : "nav-item"}
            onClick={() => setMode("leads")}
            disabled={busy}
            aria-pressed={mode === "leads"}
          >
            <Search size={17} aria-hidden="true" /> Lead discovery
          </button>
          <button
            className={mode === "research" ? "nav-item active" : "nav-item"}
            onClick={() => setMode("research")}
            disabled={busy}
            aria-pressed={mode === "research"}
          >
            <FileSearch size={17} aria-hidden="true" /> Research assistant
          </button>
        </nav>
        <div className="history">
          <h2>Recent research</h2>
          <p>Your research conversations will appear here.</p>
        </div>
        <div className="workspace-note">
          <FlaskConical size={18} aria-hidden="true" />
          <div>
            <strong>Local workspace</strong>
            <span>Development scaffold</span>
          </div>
        </div>
      </aside>
      <WorkspaceDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        title="Workspace settings"
        id="workspace-settings"
        wide
      >
        <p className="settings-description">
          Manage your allowance, billing and connected accounts.
        </p>
        {identity.status === "signed_in" && accountId && (
          <WorkspaceAllowancePanel
            key={`allowance:${accountId}`}
            api={api}
            refreshKey={job?.id}
          />
        )}
        <BillingPanel
          key={`billing:${accountId || "signed-out"}`}
          api={api}
          userId={accountId}
          identityStatus={identity.status}
          getToken={billingToken}
        />
        <YouTubeAnalyticsPanel
          api={api}
          userId={accountId}
          identityStatus={identity.status}
        />
        <SalesforcePanel
          api={api}
          userId={identity.user?.uid}
          identityStatus={identity.status}
        />
        <div ref={xSettings}>
          <XConnectionPanel
            api={api}
            userId={identity.user?.uid}
            identityStatus={identity.status}
            onConnectedChange={reportXConnection}
          />
        </div>
        <RedditConnectionPanel
          api={api}
          userId={identity.user?.uid}
          identityStatus={identity.status}
          refreshKey={redditRefreshKey}
        />
      </WorkspaceDialog>
      <WorkspaceDialog
        open={connectionPrompt}
        onClose={() => setConnectionPrompt(false)}
        title="Connect X to include posts"
        id="source-connection"
      >
        <p>
          X post search needs an active workspace owner connection. Public
          indexed Instagram, Facebook and YouTube searches do not need a
          platform login.
        </p>
        <p>
          Connect X in workspace settings, then select X again. Only the
          workspace owner can connect an account; availability depends on the
          configured X service.
        </p>
        <div className="dialog-actions">
          <button
            type="button"
            className="text-button"
            onClick={() => setConnectionPrompt(false)}
          >
            Keep current sources
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => {
              setConnectionPrompt(false);
              const detail = xSettings.current?.querySelector("details");
              if (detail) detail.open = true;
              setSettingsOpen(true);
            }}
          >
            Open X connection settings
          </button>
        </div>
      </WorkspaceDialog>
      <div className="workspace">
        <header className="topbar">
          <span>
            {mode === "leads" ? "Lead discovery" : "Research assistant"}
          </span>
          <div className="topbar-controls">
            <IdentityControls disabled={busy} />
            <button
              className="settings-button"
              type="button"
              onClick={() => setSettingsOpen(true)}
              aria-haspopup="dialog"
            >
              <Settings size={17} aria-hidden="true" /> Workspace settings
            </button>
            <button
              className="service-state"
              onClick={() => void checkHealth()}
              disabled={checking}
              aria-label={`${serviceLabel}. Check connection`}
            >
              <span className={`status-dot ${health?.ready ? "ready" : ""}`} />
              <span>{serviceLabel}</span>
              <RefreshCw
                size={13}
                className={checking ? "checking" : ""}
                aria-hidden="true"
              />
            </button>
          </div>
        </header>
        <main id="research" className="research" tabIndex={-1}>
          <div className="intro">
            <h1>
              {mode === "leads"
                ? "Find the people behind\nyour next opportunity."
                : "Follow the question.\nFind the evidence."}
            </h1>
            <p>
              {mode === "leads"
                ? "Describe your ideal prospects. Research across sources, understand the fit, and review the evidence."
                : "Explore companies, conversations, and markets. Build a clear answer from source evidence."}
            </p>
          </div>
          <p className="mode-description" id="mode-description">
            {mode === "leads"
              ? "Lead discovery looks for people and potential customers who match your criteria."
              : "Research assistant explores discussions, companies and topics to help you review the evidence."}{" "}
            Both search the sources you choose.
          </p>
          <form
            className="composer"
            onSubmit={submit}
            aria-label="Research request"
          >
            <label htmlFor="prompt" className="sr-only">
              Research prompt
            </label>
            <textarea
              ref={composer}
              id="prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              maxLength={10000}
              placeholder={
                mode === "leads"
                  ? "Who are you looking for, and what makes them a good fit?"
                  : "What would you like to understand?"
              }
              rows={4}
              aria-describedby={error ? "request-error" : "prompt-help"}
              disabled={busy}
            />
            <div className="composer-toolbar">
              <button
                type="button"
                className="source-toggle"
                onClick={() => setShowSources(!showSources)}
                disabled={busy}
                aria-expanded={showSources}
                aria-controls="source-options"
              >
                <Layers size={15} aria-hidden="true" />
                {selected.length} sources
                <ChevronDown size={13} aria-hidden="true" />
              </button>
              <label className="limit-control">
                Results{" "}
                <select
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  disabled={busy}
                >
                  {[10, 25, 50].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="primary"
                type="submit"
                disabled={busy || checking || !health?.ready}
              >
                {busy ? "Starting…" : "Start research"}
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            </div>
            {showSources && (
              <fieldset id="source-options" className="source-options">
                <legend>Sources to include</legend>
                {sources.map((source) => (
                  <label key={source.id}>
                    <input
                      type="checkbox"
                      aria-label={source.name}
                      aria-describedby={`source-${source.id}-detail`}
                      checked={selected.includes(source.id)}
                      disabled={busy}
                      onChange={(e) => {
                        if (
                          source.id === "x" &&
                          e.target.checked &&
                          !xConnected
                        ) {
                          setConnectionPrompt(true);
                          return;
                        }
                        setSelected(
                          e.target.checked
                            ? [...selected, source.id]
                            : selected.filter((s) => s !== source.id),
                        );
                      }}
                    />
                    <span>
                      {source.name}
                      <small id={`source-${source.id}-detail`}>
                        {source.detail}
                      </small>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
          </form>
          <section className="examples" aria-labelledby="examples-title">
            <h2 id="examples-title">Start with a question</h2>
            {examples[mode].map((example) => (
              <button
                key={example}
                disabled={busy}
                onClick={() => {
                  setPrompt(example);
                  setError("");
                  composer.current?.focus();
                }}
              >
                <span>{example}</span>
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            ))}
          </section>
          <div className="composer-help">
            <span id="prompt-help">
              Every result should lead back to its source.
            </span>
            <span>
              Optional controls. One prompt. Search prompts go to Exa; avoid
              confidential information and private personal details.{" "}
              <a
                href="https://exa.ai/privacy-policy"
                target="_blank"
                rel="noopener noreferrer"
              >
                Exa privacy policy
              </a>
            </span>
          </div>
          {busy && (
            <div className="research-activity" role="status" aria-live="polite">
              <RefreshCw size={18} className="checking" aria-hidden="true" />
              <div>
                <strong>Starting your research</strong>
                <p>Submitting your prompt and checking workspace limits…</p>
              </div>
            </div>
          )}
          {error && (
            <div id="request-error" className="notice error" role="alert">
              {error}
            </div>
          )}
          {!checking && (!health?.ready || healthError) && (
            <div className="notice" role="status">
              <strong>
                {health?.live
                  ? "The research service is not ready."
                  : "Connect the research service to begin."}
              </strong>
              <p>
                {healthError ||
                  "The API is running but its dependencies are not ready. Check the service, then retry."}
              </p>
              <button
                onClick={() => void checkHealth()}
                className="text-button"
              >
                Check connection <RefreshCw size={13} aria-hidden="true" />
              </button>
            </div>
          )}
          {job &&
            identity.status === "signed_in" &&
            jobAccount === accountId && (
              <ResearchResultsPanel
                key={`research:${job.id}`}
                api={api}
                job={job}
                onRedditRefresh={reportRedditRefresh}
                onExpanded={(next, nextPrompt) => {
                  setPrompt(nextPrompt);
                  setJob(next);
                  setJobAccount(accountId);
                }}
                onClarification={(next) => {
                  setJob(next);
                  setJobAccount(accountId);
                }}
                onEditPrompt={() => {
                  composer.current?.focus();
                }}
              />
            )}
          {!job && (
            <section className="results-empty" aria-labelledby="results-title">
              <div className="empty-symbol">
                <FileSearch size={25} strokeWidth={1.4} aria-hidden="true" />
              </div>
              <h2 id="results-title">
                A clear trail, from question to evidence.
              </h2>
              <p>
                Start a research run to discover sources. Review their original
                content before deciding whether a prospect meets your criteria.
              </p>
              <div className="evidence-principles">
                <span>
                  <Check size={13} aria-hidden="true" />
                  Source evidence
                </span>
                <span>
                  <Check size={13} aria-hidden="true" />
                  Explicit unknowns
                </span>
                <span>
                  <Check size={13} aria-hidden="true" />
                  Review original sources
                </span>
              </div>
            </section>
          )}
          <footer>
            <Sparkles size={13} aria-hidden="true" />
            <span>
              Early development build. Source access and research execution
              depend on configured backend services.
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
