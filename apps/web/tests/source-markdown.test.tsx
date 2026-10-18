import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceMarkdown } from "../src/components/source-markdown";

describe("untrusted source Markdown", () => {
  it("renders headings, emphasis, lists and tables as semantic content", () => {
    const { container } = render(
      <SourceMarkdown>
        {
          "## Hiring signals\n\n**Engineering** team\n\n- Public role\n- Founder post\n\n| Role | Location |\n| --- | --- |\n| Engineer | Bengaluru |"
        }
      </SourceMarkdown>,
    );
    expect(
      screen.getByRole("heading", { name: "Hiring signals" }),
    ).toBeVisible();
    expect(container.querySelector("strong")).toHaveTextContent("Engineering");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("table")).toBeVisible();
  });
  it("keeps HTML inert, blocks unsafe links and never loads source images", () => {
    const { container } = render(
      <SourceMarkdown>
        {
          '<script>alert(1)</script>\n\n<img src="https://example.org/track" onerror="alert(2)">\n\n[Unsafe](javascript:alert%281%29)\n\n![Tracking image](https://example.org/pixel)\n\n[Original source](https://example.org/source)'
        }
      </SourceMarkdown>,
    );
    expect(container.querySelector("script, img")).toBeNull();
    expect(
      screen.queryByRole("link", { name: /Unsafe/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Original source/ }),
    ).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("Tracking image")).toBeVisible();
  });
});
