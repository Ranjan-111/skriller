import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { safeSourceUrl } from "../lib/api";

/** Source content is untrusted: never enable raw HTML or remote image loading. */
export function SourceMarkdown({ children }: { children: string }) {
  return (
    <div className="source-markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const url = href && safeSourceUrl(href);
            return url ? (
              <a href={url} target="_blank" rel="noopener noreferrer">
                {children}
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            ) : (
              <span>{children}</span>
            );
          },
          img: ({ alt }) => <span>{alt || "Source image"}</span>,
          h1: ({ children }) => <h5>{children}</h5>,
          h2: ({ children }) => <h5>{children}</h5>,
          h3: ({ children }) => <h5>{children}</h5>,
          table: ({ children }) => (
            <div className="markdown-table">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {children}
      </Markdown>
    </div>
  );
}
