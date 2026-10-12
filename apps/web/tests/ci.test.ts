// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { expect, test } from "vitest";

const require = createRequire(import.meta.url);

test("the configured TypeScript checker rejects an invalid request contract", () => {
  const directory = mkdtempSync(join(tmpdir(), "skriller-contract-"));
  try {
    const file = join(directory, "broken.ts");
    writeFileSync(
      file,
      'type Request = { result_limit: number };\nconst request: Request = { result_limit: "twenty" };\nexport { request };\n',
    );
    const result = spawnSync(
      process.execPath,
      [
        join(dirname(require.resolve("typescript/package.json")), "bin/tsc"),
        "--noEmit",
        "--ignoreConfig",
        "--strict",
        "--skipLibCheck",
        "--types",
        "node",
        "--typeRoots",
        join(process.cwd(), "node_modules/@types"),
        file,
      ],
      { encoding: "utf8" },
    );
    expect(result.status, result.stdout + result.stderr).toBe(1);
    expect(result.stdout).toContain("TS2322");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}, 15000);
