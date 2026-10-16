import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CrmDeliveryPanel } from "../src/components/crm-delivery-panel";
import { createApi, type ResearchCandidate } from "../src/lib/api";
const workspace = "22222222-2222-4222-8222-222222222222";
const id = "11111111-1111-4111-8111-111111111111";
const destination = { id, instance_url: "https://acme.my.salesforce.com", enabled: true, expires_at: "2099-01-01T00:00:00Z", generation: 1 };
const candidate = (candidateId: string, title: string): ResearchCandidate => ({ id: candidateId, title, url: "https://example.com", snippet: "source", source: "web", provider: "exa_keyless", evidence_kind: "search_snippet", qualification: "unverified", observed_at: "2026-01-01T00:00:00Z", provenance: [] });
describe("Salesforce CRM delivery controls", () => {
  it("only selects current qualification groups and requires explicit near-match and send consent", async () => {
    const api = { ...createApi(), allowance: vi.fn().mockResolvedValue({ workspace_id: workspace, can_manage: true }), crmDestinations: vi.fn().mockResolvedValue([destination]), crmDeliveries: vi.fn().mockResolvedValue([]), crmDeliver: vi.fn().mockResolvedValue({ id, entity_id: id, destination_id: id, state: "pending", attempts: 0, last_code: null }), crmCancelDelivery: vi.fn() };
    render(<CrmDeliveryPanel api={api} workspaceId={workspace} planId={id} candidates={[candidate(id, "Review this company"), candidate("33333333-3333-4333-8333-333333333333", "Unverified search result")]} confirmed={[]} near={[id]} />);
    await screen.findByLabelText("Qualified record");
    fireEvent.change(screen.getByLabelText("Qualified record"), { target: { value: id } });
    expect(screen.queryByRole("option", { name: /Unverified search result/ })).not.toBeInTheDocument();
    const authorize = screen.getByLabelText(/authorize sending/i);
    expect(authorize).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/keep its near-match status/i));
    expect(authorize).toBeEnabled();
    fireEvent.click(authorize);
    fireEvent.click(screen.getByRole("button", { name: "Queue Salesforce delivery" }));
    await waitFor(() => expect(api.crmDeliver).toHaveBeenCalledWith(workspace, expect.objectContaining({ destination_id: id, plan_id: id, entity_id: id, field_map: { last_name: "LastName", company_name: "Company" }, selected_near: true, opt_in: true })));
  });
});
