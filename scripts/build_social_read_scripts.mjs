/** Generate a fixed script bundle from the copied read modules; no network/browser. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadReadCommand } from "./opencli_read_modules.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const subset = path.join(root, "src/skriller/_vendor/opencli");
const target = path.join(subset, "READ_SCRIPTS.json");
const username = "SKRILLER_PROFILE_ARGUMENT_89f4";
const query = "SKRILLER_QUERY_ARGUMENT_89f4";
const limit = 987654321;
const commands = {};
for (const site of ["instagram", "facebook"]) {
  for (const operation of ["search", "profile"]) {
    const definition = await loadReadCommand(subset, site, operation);
    const scripts = [];
    if (definition.func) {
      await definition.func(
        {
          goto: async () => {},
          evaluate: async (script) => {
            scripts.push(script);
            return site === "instagram"
              ? { rows: [] }
              : { status: "ok", rows: [{ synthetic: true }] };
          },
        },
        { username, query, limit: site === "facebook" ? 50 : limit },
      );
    } else {
      assert.equal(site, "facebook");
      assert.equal(operation, "profile");
      scripts.push(
        definition.pipeline[1].evaluate.replaceAll(
          "${{ args.username | json }}",
          JSON.stringify(username),
        ),
      );
    }
    assert.equal(scripts.length, 1);
    const tokens =
      operation === "profile"
        ? { username: JSON.stringify(username) }
        : site === "instagram"
          ? { query: JSON.stringify(query), limit: String(limit) }
          : { limit: "const limit = 50;" };
    for (const token of Object.values(tokens)) {
      assert.equal(
        scripts[0].split(token).length - 1,
        1,
        "Each parameter must have one bounded replacement site",
      );
    }
    commands[`${site}_${operation}`] = { script: scripts[0], tokens };
  }
}
const names = [
  "scripts/build_social_read_scripts.mjs",
  "scripts/opencli_read_modules.mjs",
  "src/skriller/_vendor/opencli/PROVENANCE.json",
];
const provenance = JSON.parse(
  await readFile(path.join(subset, "PROVENANCE.json"), "utf8"),
);
for (const name of Object.keys(provenance.files))
  names.push("src/skriller/_vendor/opencli/" + name);
const hashes = {};
for (const name of names)
  hashes[name] = createHash("sha256")
    .update(await readFile(path.join(root, name)))
    .digest("hex");
const result =
  JSON.stringify(
    {
      schema_version: 1,
      source_commit: provenance.commit,
      implementation_sha256: hashes,
      commands,
    },
    null,
    2,
  ) + "\n";
if (process.argv[2] === "--check") {
  assert.equal(
    await readFile(target, "utf8"),
    result,
    "Copied social read script bundle has drifted",
  );
} else {
  assert.equal(process.argv.length, 2);
  await writeFile(target, result);
}
