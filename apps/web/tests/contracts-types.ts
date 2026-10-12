/** Compile-time regression checks against the generated API contracts. */
import type { Capability, Failure, SearchPlan, Source } from "../src/lib/api";

const minimalPlan: SearchPlan = {
  workspace_id: "workspace-uuid",
  conversation_id: "conversation-uuid",
  revision: 1,
  schema_version: 1,
  clarification: null,
  freshness_days: null,
  entity_type: "company",
};
const source: Source = "linkedin";
const failure: Failure = {
  code: "access_denied",
  message: "Unavailable",
  retry_after_seconds: null,
};
// @ts-expect-error Generated source unions reject unsupported platforms.
const invalidSource: Source = "unsupported-platform";
// @ts-expect-error Generated failures reject invented success/failure codes.
const invalidFailure: Failure["code"] = "magic_bypass";
// @ts-expect-error Arbitrary backend operations are outside the generated enum.
const invalidOperation: Capability["operation"] = "execute_shell";
// @ts-expect-error Required plan identity cannot disappear unnoticed.
const missingIdentity: SearchPlan = { revision: 1, entity_type: "company" };
export {
  minimalPlan,
  source,
  failure,
  invalidSource,
  invalidFailure,
  invalidOperation,
  missingIdentity,
};
