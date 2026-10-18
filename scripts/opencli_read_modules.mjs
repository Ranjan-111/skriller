/** Closed loader for trusted build/fixture execution, not a production sandbox. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import vm from "node:vm";

const allowed = new Set([
  "clis/instagram/search.js",
  "clis/instagram/profile.js",
  "clis/instagram/_shared/read-response.js",
  "clis/facebook/search.js",
  "clis/facebook/profile.js",
]);

export async function loadReadCommand(sourceRoot, site, operation) {
  const definitions = [];
  const context = vm.createContext({ URL, JSON });
  const registry = new vm.SyntheticModule(
    ["cli", "Strategy"],
    function () {
      this.setExport("cli", (definition) => definitions.push(definition));
      this.setExport("Strategy", { COOKIE: "cookie" });
    },
    { context },
  );
  const names = [
    "ArgumentError",
    "AuthRequiredError",
    "CommandExecutionError",
    "EmptyResultError",
  ];
  const errors = new vm.SyntheticModule(
    names,
    function () {
      for (const name of names) {
        this.setExport(
          name,
          class extends Error {
            constructor(...args) {
              super(args.join(": "));
              this.name = name;
            }
          },
        );
      }
    },
    { context },
  );
  const cache = new Map();
  async function load(relative) {
    if (!allowed.has(relative))
      throw new Error("Module outside read-only fixture allowlist");
    if (cache.has(relative)) return cache.get(relative);
    const module = new vm.SourceTextModule(
      await readFile(path.join(sourceRoot, relative), "utf8"),
      {
        context,
        identifier: relative,
      },
    );
    cache.set(relative, module);
    await module.link(async (specifier, parent) => {
      if (specifier === "@jackwener/opencli/registry") return registry;
      if (specifier === "@jackwener/opencli/errors") return errors;
      if (!specifier.startsWith("./"))
        throw new Error("Unexpected upstream dependency");
      return load(
        path.posix.normalize(
          path.posix.join(path.posix.dirname(parent.identifier), specifier),
        ),
      );
    });
    return module;
  }
  const module = await load(`clis/${site}/${operation}.js`);
  await module.evaluate({ timeout: 1000 });
  assert.equal(definitions.length, 1);
  const definition = definitions[0];
  assert.equal(definition.site, site);
  assert.equal(definition.name, operation);
  assert.equal(definition.access, "read");
  return definition;
}
