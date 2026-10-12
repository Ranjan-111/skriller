import type { ResearchCandidate } from "./api";

export const SOURCE_EXPORT_LIMIT = 100;
const columns = [
  "title",
  "url",
  "snippet",
  "source",
  "evidence_kind",
  "qualification",
  "observed_at",
] as const;
export type SourceExportFormat = "json" | "csv";

function csvCell(value: string): string {
  // Spreadsheet programs can execute formula cells even after whitespace.
  const safe = /^[=+\-@]/.test(value.trimStart()) ? `'${value}` : value;
  return `"${safe.replaceAll('"', '""')}"`;
}

export function serializeSources(
  results: ResearchCandidate[],
  format: SourceExportFormat,
): string {
  const rows = results
    .slice(0, SOURCE_EXPORT_LIMIT)
    .map((candidate) =>
      Object.fromEntries(columns.map((key) => [key, candidate[key]])),
    );
  if (format === "json") return JSON.stringify(rows, null, 2);
  return [
    columns.map(csvCell).join(","),
    ...rows.map((row) => columns.map((key) => csvCell(row[key])).join(",")),
  ].join("\r\n");
}

export function downloadSources(
  results: ResearchCandidate[],
  format: SourceExportFormat,
): void {
  const blob = new Blob([serializeSources(results, format)], {
    type:
      format === "csv"
        ? "text/csv;charset=utf-8"
        : "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  // A constant name keeps prompts, IDs and source-provided text out of filenames.
  anchor.download = `skriller-search-snippets.${format}`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
