import { describe, expect, it } from "vitest";
import {
  captureCallback,
  CONSENT_KEY,
  consumeConsent,
} from "../src/lib/analytics-consent";

const state = "a".repeat(43);
const grant = "11111111-1111-4111-8111-111111111111";
describe("owner analytics consent", () => {
  it("cleans code/state immediately while preserving unrelated URL state", () => {
    const result = captureCallback(
      `http://localhost/?q=keep&code=private-code&state=${state}&scope=private#section`,
    )!;
    expect(result.cleanUrl).toBe("/?q=keep#section");
    expect(result.callback.code).toBe("private-code");
  });
  it.each(["account", "workspace", "state", "expired", "denied", "duplicate"])(
    "rejects %s and consumes the tab-local intent",
    (kind) => {
      sessionStorage.setItem(
        CONSENT_KEY,
        JSON.stringify({
          uid: "owner",
          workspace: "workspace",
          grant,
          state,
          expires: kind === "expired" ? 0 : Date.now() + 100000,
        }),
      );
      const callback = captureCallback(
        `http://localhost/?code=private&state=${kind === "state" ? "b".repeat(43) : state}${kind === "duplicate" ? "&code=other" : ""}${kind === "denied" ? "&error=access_denied" : ""}`,
      )!.callback;
      expect(() =>
        consumeConsent(
          sessionStorage,
          callback,
          kind === "account" ? "other" : "owner",
          kind === "workspace" ? "other" : "workspace",
        ),
      ).toThrow(/Connect again/);
      expect(sessionStorage.getItem(CONSENT_KEY)).toBeNull();
    },
  );
});
