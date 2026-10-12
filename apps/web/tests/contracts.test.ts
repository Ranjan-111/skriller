// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "vitest";

const generator = "tools/contracts-generator/generate.mjs";
test("committed frontend types match the exported API schema exactly", () => {
  const result = spawnSync(process.execPath, [generator, "--check"], {
    encoding: "utf8",
  });
  expect(result.status, result.stdout + result.stderr).toBe(0);
});

test("check fails when API schema changes without generated client types", () => {
  const directory = mkdtempSync(join(tmpdir(), "skriller-contract-drift-"));
  try {
    const schema = JSON.parse(readFileSync("contracts/openapi.json", "utf8"));
    schema.components.schemas.SearchPlan.required.push("drift_probe");
    schema.components.schemas.SearchPlan.properties.drift_probe = {
      type: "string",
    };
    const file = join(directory, "changed.json");
    writeFileSync(file, JSON.stringify(schema));
    const result = spawnSync(
      process.execPath,
      [generator, "--schema", file, "--check"],
      { encoding: "utf8" },
    );
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("Generated client types differ");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
