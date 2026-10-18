import userEvent from "@testing-library/user-event";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Workbench } from "../src/components/workbench";
import { ApiError } from "../src/lib/api";
const mock = vi.hoisted(() => ({
  health: vi.fn(),
  submit: vi.fn(),
  job: vi.fn(),
  results: vi.fn(),
  allowance: vi.fn(),
  identityReviews: vi.fn(),
  plan: vi.fn(),
  xConsents: vi.fn(),
  xStart: vi.fn(),
  xComplete: vi.fn(),
  xRefresh: vi.fn(),
  xRevoke: vi.fn(),
  redditConsents: vi.fn(),
  redditStart: vi.fn(),
  redditComplete: vi.fn(),
  redditRefresh: vi.fn(),
  redditRevoke: vi.fn(),
  authStatus: "signed_in",
  authUid: "account-one",
}));
vi.mock("../src/components/identity", () => ({
  IdentityControls: () => null,
  useIdentity: () => ({
    status: mock.authStatus,
    user:
      mock.authStatus === "signed_in"
        ? { uid: mock.authUid, email: null }
        : null,
    getToken: async () => "test-app-token",
  }),
}));
vi.mock("../src/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/lib/api")>()),
  createApi: () => mock,
}));
beforeEach(() => {
  vi.clearAllMocks();
  mock.authStatus = "signed_in";
  mock.authUid = "account-one";
  mock.health.mockResolvedValue({ live: true, ready: true });
  mock.allowance.mockResolvedValue({
    workspace_id: "w1",
    tier: "trial",
    enabled: true,
    can_manage: false,
    run_limit: 25,
    result_cap: 25,
    source_cap: 3,
    result_limit: 25,
    source_limit: 3,
    used_runs: 0,
    remaining_runs: 25,
  });
  mock.xConsents.mockResolvedValue([]);
  mock.redditConsents.mockResolvedValue([]);
  mock.job.mockReturnValue(new Promise(() => {}));
  mock.plan.mockReturnValue(new Promise(() => {}));
  mock.identityReviews.mockResolvedValue([]);
});
describe("research workbench", () => {
  it("keeps utilities in the profile settings drawer and closes it with Escape", async () => {
    render(<Workbench />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Workspace settings" }));
    const settings = await screen.findByRole("dialog", {
      name: "Workspace settings",
    });
    for (const title of [
      "Workspace allowance",
      "Plans and billing",
      "YouTube owner analytics",
      "Salesforce CRM",
      "X connection",
      "Reddit direct access",
    ]) {
      expect(within(settings).getByText(new RegExp(title))).toBeInTheDocument();
    }
    expect(settings.closest("main")).toBeNull();
    fireEvent(
      settings,
      new Event("cancel", { bubbles: false, cancelable: true }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
  it("places examples immediately after the prompt form and explains both modes", async () => {
    render(<Workbench />);
    const form = screen.getByRole("form", { name: "Research request" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start research" }),
      ).toBeEnabled(),
    );
    expect(form.nextElementSibling).toHaveClass("examples");
    expect(screen.getByText(/Lead discovery looks for people/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Research assistant" }));
    expect(
      screen.getByText(/Research assistant explores discussions/),
    ).toHaveTextContent("Both search the sources you choose");
  });
  it("clears the sign-in alert after authentication while preserving the prompt", async () => {
    mock.authStatus = "signed_out";
    const view = render(<Workbench />);
    const start = screen.getByRole("button", { name: "Start research" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.change(screen.getByRole("textbox", { name: "Research prompt" }), {
      target: { value: "Find fintech founders" },
    });
    fireEvent.click(start);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign in to your app account",
    );
    mock.authStatus = "signed_in";
    view.rerender(<Workbench />);
    await waitFor(() =>
      expect(
        screen.queryByText(/Sign in to your app account to start research/),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("textbox", { name: "Research prompt" }),
    ).toHaveValue("Find fintech founders");
  });
  it("shows submission feedback, then the real research stage", async () => {
    let accept!: (value: unknown) => void;
    mock.submit.mockReturnValue(
      new Promise((resolve) => {
        accept = resolve;
      }),
    );
    mock.job.mockResolvedValue({
      id: "run-stage",
      state: "running",
      stage: "discovering",
      result_count: 0,
    });
    mock.results.mockResolvedValue({
      job_id: "run-stage",
      state: "running",
      results: [],
      limitations: [],
    });
    render(<Workbench />);
    const start = screen.getByRole("button", { name: "Start research" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.change(screen.getByRole("textbox", { name: "Research prompt" }), {
      target: { value: "Find founders" },
    });
    fireEvent.click(start);
    expect(await screen.findByText("Starting your research")).toBeVisible();
    expect(screen.getByRole("button", { name: /Starting/ })).toBeDisabled();
    await act(async () => accept({ id: "run-stage", status: "accepted" }));
    expect(await screen.findByText("Current stage: discovering")).toBeVisible();
    expect(
      screen.getByText(
        "Searching your selected sources for matching references.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByText("Starting your research"),
    ).not.toBeInTheDocument();
  });
  it("prompts for unconnected X only and preserves public indexed source choices", async () => {
    render(<Workbench />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start research" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "3 sources" }));
    for (const name of [/Instagram/, /Facebook/, /YouTube/]) {
      const source = screen.getByRole("checkbox", { name });
      fireEvent.click(source);
      expect(source).toBeChecked();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    }
    const x = screen.getByRole("checkbox", { name: "X" });
    fireEvent.click(x);
    expect(x).not.toBeChecked();
    const prompt = await screen.findByRole("dialog", {
      name: "Connect X to include posts",
    });
    fireEvent.click(
      within(prompt).getByRole("button", { name: "Keep current sources" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    fireEvent.click(x);
    fireEvent.click(
      screen.getByRole("button", { name: "Open X connection settings" }),
    );
    const settings = await screen.findByRole("dialog", {
      name: "Workspace settings",
    });
    expect(
      within(settings).getByText("X connection").closest("details"),
    ).toHaveAttribute("open");
  });
  it("keeps account panels distinct when submitting the reported founder prompt", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    mock.submit.mockResolvedValue({
      id: "run-founder",
      status: "accepted",
      workspace_id: "w1",
    });
    mock.job.mockResolvedValue({
      id: "run-founder",
      workspace_id: "w1",
      state: "completed",
      stage: null,
      version: 2,
      terminal_reason: null,
      result_count: 1,
    });
    mock.results.mockResolvedValue({
      job_id: "run-founder",
      workspace_id: "w1",
      state: "completed",
      limitations: [],
      results: [
        {
          id: "source-founder",
          title: "Synthetic founder source",
          url: "https://example.org/founder",
          snippet: "Synthetic indexed reference",
          source: "web",
          provider: "exa_keyless",
          evidence_kind: "search_snippet",
          qualification: "unverified",
          observed_at: "2026-10-18T00:00:00Z",
          provenance: [],
        },
      ],
    });
    try {
      render(<Workbench />);
      const start = screen.getByRole("button", { name: "Start research" });
      await waitFor(() => expect(start).toBeEnabled());
      fireEvent.change(
        screen.getByRole("textbox", { name: "Research prompt" }),
        {
          target: {
            value:
              "Find fintech founders in Bengaluru. Prioritise companies hiring engineers.",
          },
        },
      );
      fireEvent.click(start);
      expect(await screen.findByText("Research complete")).toBeVisible();
      expect(await screen.findByText("Synthetic founder source")).toBeVisible();
      expect(
        screen.getByRole("button", { name: "Download sources as CSV" }),
      ).toBeVisible();
      expect(
        screen.getByRole("button", { name: "Download sources as JSON" }),
      ).toBeVisible();
      expect(mock.submit).toHaveBeenCalledTimes(1);
      expect(
        errors.mock.calls.filter((call) =>
          String(call[0]).includes("same key"),
        ),
      ).toEqual([]);
    } finally {
      errors.mockRestore();
    }
  });
  it("offers prompt-first empty state without fake results", async () => {
    render(<Workbench />);
    expect(
      screen.getByRole("textbox", { name: "Research prompt" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", {
        name: "A clear trail, from question to evidence.",
      }),
    ).toBeVisible();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start research" }),
      ).toBeEnabled(),
    );
    expect(mock.submit).not.toHaveBeenCalled();
    expect(screen.getByText(/Search prompts go to Exa/)).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Exa privacy policy" }),
    ).toHaveAttribute("href", "https://exa.ai/privacy-policy");
    expect(
      screen.getByText(/Start a research run to discover sources/),
    ).toBeVisible();
  });
  it("offers direct X as an optional source only after the owner connection is active", async () => {
    mock.allowance.mockResolvedValue({
      workspace_id: "w1",
      tier: "trial",
      enabled: true,
      can_manage: true,
      run_limit: 25,
      result_cap: 25,
      source_cap: 3,
      result_limit: 25,
      source_limit: 3,
      used_runs: 0,
      remaining_runs: 25,
    });
    mock.xConsents.mockResolvedValue([
      {
        consent_id: "11111111-1111-4111-8111-111111111111",
        connection_id: "33333333-3333-4333-8333-333333333333",
        state: "active",
        expires_at: "2099-01-01T00:00:00Z",
        access_expires_at: "2099-01-01T00:00:00Z",
        access_state: "active",
        remote_revocation: "not_performed",
      },
    ]);
    render(<Workbench />);
    await waitFor(() => expect(mock.xConsents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "3 sources" }));
    const x = screen.getByRole("checkbox", { name: "X" });
    expect(x).toBeEnabled();
    fireEvent.click(x);
    expect(x).toBeChecked();
  });
  it("keeps indexed Reddit enabled when no direct Reddit account is connected", async () => {
    render(<Workbench />);
    await waitFor(() => expect(mock.redditConsents).not.toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "3 sources" }));
    const reddit = screen.getByRole("checkbox", { name: /Reddit/ });
    expect(reddit).toBeEnabled();
    expect(reddit).toBeChecked();
  });
  it("uses examples, optional sources and result controls in actual request", async () => {
    mock.submit.mockResolvedValue({ id: "run-1", status: "accepted" });
    render(<Workbench />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start research" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Find fintech founders/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "3 sources" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Reddit/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "Results" }), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start research" }));
    await waitFor(() =>
      expect(mock.submit).toHaveBeenCalledWith({
        prompt: expect.stringContaining("fintech founders"),
        mode: "leads",
        sources: ["linkedin", "web"],
        result_limit: 10,
      }),
    );
    expect(await screen.findByText("Run accepted")).toBeVisible();
  });
  it("retains prompt on execution failure and exposes recovery", async () => {
    mock.submit.mockRejectedValue(
      new ApiError("Research execution is not available yet."),
    );
    render(<Workbench />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start research" }),
      ).toBeEnabled(),
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Find founders" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start research" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "not available yet",
    );
    expect(screen.getByRole("textbox")).toHaveValue("Find founders");
    expect(screen.queryByText("Run accepted")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New research" })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Research assistant" }),
    ).toBeEnabled();
  });
  it("disables submission when service cannot be reached and retries", async () => {
    mock.health.mockRejectedValueOnce(
      new ApiError("Cannot reach the research service."),
    );
    render(<Workbench />);
    expect(
      await screen.findByText("Connect the research service to begin."),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Start research" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start research" }),
      ).toBeEnabled(),
    );
  });
  it("prevents empty prompt and changes research mode", async () => {
    render(<Workbench />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start research" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Start research" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Describe who or what",
    );
    expect(mock.submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Research assistant" }));
    expect(
      screen.getByRole("heading", { name: /Follow the question/ }),
    ).toBeVisible();
  });
  it("holds submitted intent stable until a delayed request completes", async () => {
    let resolveRun!: (job: { id: string; status: string }) => void;
    mock.submit.mockReturnValue(
      new Promise((resolve) => {
        resolveRun = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<Workbench />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start research" }),
      ).toBeEnabled(),
    );
    await user.type(screen.getByRole("textbox"), "Find founders");
    await user.click(screen.getByRole("button", { name: "3 sources" }));
    await user.click(screen.getByRole("button", { name: "Start research" }));
    const newResearch = screen.getByRole("button", { name: "New research" });
    const researchMode = screen.getByRole("button", {
      name: "Research assistant",
    });
    const example = screen.getByRole("button", {
      name: /Find fintech founders/,
    });
    const sourceToggle = screen.getByRole("button", { name: "3 sources" });
    const reddit = screen.getByRole("checkbox", { name: /Reddit/ });
    const resultLimit = screen.getByRole("combobox", { name: "Results" });
    for (const control of [
      newResearch,
      researchMode,
      example,
      sourceToggle,
      reddit,
      resultLimit,
      screen.getByRole("textbox"),
    ])
      expect(control).toBeDisabled();
    await user.click(newResearch);
    await user.click(researchMode);
    await user.click(example);
    await user.click(sourceToggle);
    await user.click(reddit);
    await user.selectOptions(resultLimit, "10");
    expect(screen.getByRole("textbox")).toHaveValue("Find founders");
    expect(
      screen.getByRole("button", { name: "Lead discovery" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(reddit).toBeChecked();
    expect(resultLimit).toHaveValue("25");
    expect(mock.submit).toHaveBeenCalledTimes(1);
    expect(mock.submit).toHaveBeenCalledWith({
      prompt: "Find founders",
      mode: "leads",
      sources: ["linkedin", "reddit", "web"],
      result_limit: 25,
    });
    await act(async () =>
      resolveRun({ id: "run-delayed", status: "accepted" }),
    );
    expect(await screen.findByText("Run accepted")).toBeVisible();
    for (const control of [
      newResearch,
      researchMode,
      example,
      sourceToggle,
      reddit,
      resultLimit,
      screen.getByRole("textbox"),
    ])
      expect(control).toBeEnabled();
    await user.click(newResearch);
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.queryByText("Run accepted")).not.toBeInTheDocument();
  });
});

it("preserves the prompt through required app sign-in without sending a job", async () => {
  mock.authStatus = "signed_out";
  const view = render(<Workbench />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Start research" }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Research prompt" }), {
    target: { value: "Find fintech founders" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Start research" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Sign in to your app account",
  );
  expect(mock.submit).not.toHaveBeenCalled();
  mock.authStatus = "signed_in";
  view.rerender(<Workbench />);
  expect(screen.getByRole("textbox", { name: "Research prompt" })).toHaveValue(
    "Find fintech founders",
  );
});

it("removes accepted run output when the app account signs out", async () => {
  mock.submit.mockResolvedValue({ id: "run-private", status: "accepted" });
  const view = render(<Workbench />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Start research" }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Private research" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Start research" }));
  expect(await screen.findByText("Run accepted")).toBeVisible();
  mock.authStatus = "signed_out";
  view.rerender(<Workbench />);
  expect(screen.queryByText("Run accepted")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue("Private research");
});

it("hides a prior account's run immediately when the signed-in account changes", async () => {
  mock.submit.mockResolvedValue({
    id: "run-first-account",
    status: "accepted",
  });
  const view = render(<Workbench />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Start research" }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Find companies" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Start research" }));
  expect(await screen.findByText("Run accepted")).toBeVisible();
  mock.authUid = "account-two";
  view.rerender(<Workbench />);
  expect(screen.queryByText("Run accepted")).not.toBeInTheDocument();
});
