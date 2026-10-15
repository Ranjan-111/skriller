// Use the pinned Vite dependency already installed with Vitest; no downloads.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const vitest = createRequire(require.resolve("vitest/package.json"));
const { build } = await import(vitest.resolve("vite"));
const outDir = process.argv[2];
if (!outDir) throw new Error("An owned temporary output directory is required");
await build({
  configFile: false,
  root: fileURLToPath(new URL("../", import.meta.url)),
  envDir: false,
  logLevel: "error",
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir,
    emptyOutDir: true,
    lib: {
      entry: fileURLToPath(
        new URL("results-browser-fixture.tsx", import.meta.url),
      ),
      name: "ResultsFixture",
      formats: ["iife"],
      fileName: () => "fixture.js",
    },
  },
});
