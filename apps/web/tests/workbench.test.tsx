import userEvent from "@testing-library/user-event";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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
  mock.job.mockReturnValue(new Promise(() => {}));
});
describe("research workbench", () => {
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
