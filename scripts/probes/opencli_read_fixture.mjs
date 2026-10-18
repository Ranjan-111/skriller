/** Execute only selected, unmodified upstream read modules on synthetic data.
 * This is an offline compatibility probe, not a production sandbox or worker.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { loadReadCommand } from "../opencli_read_modules.mjs";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const require = createRequire(path.join(root, "apps/web/package.json"));
const { JSDOM } = require("jsdom");
const adapted = process.argv[2] === "--adapted";
assert.ok(process.argv.length === 2 || (process.argv.length === 3 && adapted));
const sourceRoot = path.join(
  root,
  adapted ? "src/skriller/_vendor/opencli" : "third_party/external/opencli",
);

function pageFixture(url, html = "", responses = []) {
  const dom = new JSDOM(html, { url, runScripts: "outside-only" });
  const navigations = [];
  const requests = [];
  const context = dom.getInternalVMContext();
  // No resource loader or live fetch is installed. Every request consumes one
  // explicit fixture response and must match its exact intended URL.
  context.fetch = async (url, options) => {
    const response = responses[requests.length];
    assert.ok(response, "Unexpected request or hidden retry");
    assert.equal(url, response.url);
    assert.equal(options.credentials, "include");
    requests.push(url);
    return {
      status: response.status ?? 200,
      ok: (response.status ?? 200) >= 200 && (response.status ?? 200) < 300,
      text: async () =>
        typeof response.body === "string"
          ? response.body
          : JSON.stringify(response.body),
    };
  };
  return {
    navigations,
    requests,
    goto: async (target) => {
      const parsed = new URL(target);
      assert.equal(parsed.protocol, "https:");
      assert.ok(
        ["www.instagram.com", "www.facebook.com"].includes(parsed.hostname),
      );
      navigations.push(target);
      dom.reconfigure({ url: target });
    },
    evaluate: async (script) =>
      vm.runInContext(script, context, { timeout: 1000 }),
    close: () => dom.window.close(),
  };
}

const igSearchUrl =
  "https://www.instagram.com/web/search/topsearch/?query=synthetic&context=user";
const igProfileUrl =
  "https://www.instagram.com/api/v1/users/web_profile_info/?username=synthetic";
const rows = [];
async function check(id, site, operation, exercise) {
  const definition = await loadReadCommand(sourceRoot, site, operation);
  const metrics = await exercise(definition);
  rows.push({ id, source: site, operation, outcome: "passed", ...metrics });
}

await check(
  "instagram-search-public-private",
  "instagram",
  "search",
  async (cmd) => {
    const page = pageFixture("https://www.instagram.com/", "", [
      {
        url: igSearchUrl,
        body: {
          users: [
            {
              user: {
                username: "public_fixture",
                full_name: "Synthetic Public",
                is_private: false,
              },
            },
            {
              user: {
                username: "private_fixture",
                full_name: "Synthetic Private",
                is_private: true,
              },
            },
            {
              user: {
                username: "unknown_fixture",
                full_name: "Unknown Visibility",
              },
            },
          ],
        },
      },
    ]);
    try {
      const output = await cmd.func(page, { query: "synthetic", limit: 3 });
      assert.equal(output.length, adapted ? 1 : 3);
      if (adapted) {
        assert.equal(output[0].private, false);
        assert.equal(output[0].verified, null);
      } else {
        assert.equal(output[0].private, "No");
        assert.equal(output[1].private, "Yes");
        assert.equal(output[2].private, "No"); // missing upstream flag is misleading
      }
      return {
        requests: page.requests.length,
        navigations: page.navigations.length,
        sample: output,
      };
    } finally {
      page.close();
    }
  },
);

await check(
  "instagram-profile-missing-counts",
  "instagram",
  "profile",
  async (cmd) => {
    const page = pageFixture("https://www.instagram.com/", "", [
      {
        url: igProfileUrl,
        body: {
          data: {
            user: {
              username: "synthetic",
              is_private: false,
              full_name: "Synthetic",
              biography: "First\nSecond",
            },
          },
        },
      },
    ]);
    try {
      const output = await cmd.func(page, { username: "synthetic" });
      // Document the upstream uncertainty: zeros are defaults, not verified counts.
      assert.equal(output[0].followers, adapted ? null : 0);
      assert.equal(output[0].following, adapted ? null : 0);
      assert.equal(output[0].posts, adapted ? null : 0);
      assert.equal(output[0].bio, "First Second");
      assert.equal("private" in output[0], adapted);
      return {
        requests: page.requests.length,
        default_zero_is_not_fact: true,
        sample: output,
      };
    } finally {
      page.close();
    }
  },
);

await check(
  "instagram-profile-business-fallback",
  "instagram",
  "profile",
  async (cmd) => {
    const page = pageFixture("https://www.instagram.com/", "", [
      { url: igProfileUrl, status: 400, body: {} },
      {
        url: "https://www.instagram.com/api/v1/feed/user/synthetic/username/?count=1",
        body: { user: { pk: "1234" } },
      },
      {
        url: "https://www.instagram.com/api/v1/users/1234/info/",
        body: {
          user: {
            username: "synthetic",
            is_private: false,
            follower_count: 12,
            following_count: 3,
            media_count: 2,
          },
        },
      },
    ]);
    try {
      const output = await cmd.func(page, { username: "synthetic" });
      assert.equal(output[0].followers, 12);
      assert.equal(page.requests.length, 3);
      return { requests: page.requests.length, sample: output };
    } finally {
      page.close();
    }
  },
);

for (const [id, status, body, error] of [
  ["rate-limit", 429, {}, "CommandExecutionError"],
  ["login", 403, {}, "AuthRequiredError"],
  ["challenge", 200, "<html>checkpoint captcha</html>", "AuthRequiredError"],
  ["malformed", 200, "not JSON", "CommandExecutionError"],
]) {
  await check(
    `instagram-profile-${id}`,
    "instagram",
    "profile",
    async (cmd) => {
      const page = pageFixture("https://www.instagram.com/", "", [
        { url: igProfileUrl, status, body },
      ]);
      try {
        await assert.rejects(
          cmd.func(page, { username: "synthetic" }),
          (failure) => failure.name === error,
        );
        assert.equal(page.requests.length, 1);
        return { requests: 1, no_retry: true };
      } finally {
        page.close();
      }
    },
  );
}

if (adapted) {
  for (const [id, user] of [
    ["private", { username: "synthetic", is_private: true }],
    ["unknown", { username: "synthetic" }],
    ["mismatched", { username: "different", is_private: false }],
  ]) {
    await check(
      `instagram-profile-rejects-${id}`,
      "instagram",
      "profile",
      async (cmd) => {
        const page = pageFixture("https://www.instagram.com/", "", [
          { url: igProfileUrl, body: { data: { user } } },
        ]);
        try {
          await assert.rejects(
            cmd.func(page, { username: "synthetic" }),
            (failure) => failure.name === "CommandExecutionError",
          );
          assert.equal(page.requests.length, 1);
          return { requests: 1, no_retry: true };
        } finally {
          page.close();
        }
      },
    );
  }
}

await check(
  "facebook-search-identity-and-decoys",
  "facebook",
  "search",
  async (cmd) => {
    const page = pageFixture(
      "https://www.facebook.com/",
      `<main role="main"><div role="feed">
    <div><a href="/story.php?story_fbid=1&id=9&ref=one">First source</a> First synthetic post text.</div>
    <div><a href="/story.php?story_fbid=1&id=9&ref=two">First source</a> Duplicate tracking URL.</div>
    <div><a href="/story.php?story_fbid=2&id=9">Second source</a> Second synthetic post text.</div>
    <a href="/search/top?q=noise">Search decoy</a><a href="/checkpoint/">Checkpoint</a>
    <a href="https://facebook.com.evil.example/thing">External decoy</a>
  </div></main>`,
    );
    try {
      const output = await cmd.func(page, { query: "synthetic", limit: 10 });
      assert.equal(output.length, 2);
      assert.equal(
        output[0].url,
        "https://www.facebook.com/story.php?story_fbid=1&id=9",
      );
      assert.equal(
        output[1].url,
        "https://www.facebook.com/story.php?story_fbid=2&id=9",
      );
      assert.equal(page.navigations.length, 2);
      return { requests: 0, navigations: 2, sample: output };
    } finally {
      page.close();
    }
  },
);

await check("facebook-search-login", "facebook", "search", async (cmd) => {
  const page = pageFixture(
    "https://www.facebook.com/",
    "<body>You must log in to continue</body>",
  );
  try {
    await assert.rejects(
      cmd.func(page, { query: "synthetic", limit: 10 }),
      (failure) => failure.name === "AuthRequiredError",
    );
    return {
      requests: 0,
      navigations: page.navigations.length,
      no_retry: true,
    };
  } finally {
    page.close();
  }
});

await check(
  "facebook-profile-scoped-header-and-display-count",
  "facebook",
  "profile",
  async (cmd) => {
    const page = pageFixture(
      "https://www.facebook.com/synthetic",
      `
    <nav><a href="/synthetic/followers">999 followers</a></nav>
    <main role="main"><a aria-label="Synthetic Profile" href="/synthetic/photo/">
      <span role="img" aria-label="Synthetic Profile"></span></a>
      <a href="/other/friends">Wrong profile count</a>
      <a href="/synthetic/followers">1.2K followers</a></main>`,
    );
    try {
      assert.equal(cmd.pipeline.length, 2);
      const script = cmd.pipeline[1].evaluate.replaceAll(
        "${{ args.username | json }}",
        JSON.stringify("synthetic"),
      );
      assert.equal(script.includes("${{"), false);
      const output = await page.evaluate(script);
      assert.equal(output[0].name, "Synthetic Profile");
      assert.equal(output[0].followers, "1.2K followers");
      assert.equal(output[0].friends, "-");
      return {
        requests: 0,
        count_preserved_as_display_text: true,
        sample: output,
      };
    } finally {
      page.close();
    }
  },
);

console.log(
  JSON.stringify({
    mode: "offline_synthetic_fixture",
    adapted,
    source_calls: 0,
    platform_enabled: false,
    cases: rows,
  }),
);
