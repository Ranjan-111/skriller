import type { components } from "../generated/api";

type ExportMetadata = components["schemas"]["ExportOutput"];
type ExportFormat = "csv" | "json";
const uuid = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );

export function createQualifiedExportClient(
  request: (path: string, init: RequestInit) => Promise<Response>,
) {
  return {
    async qualifiedExport(
      workspace: string,
      plan: string,
      entities: string[],
      format: ExportFormat,
      signal?: AbortSignal,
    ): Promise<ExportMetadata> {
      if (
        !uuid(workspace) ||
        !uuid(plan) ||
        entities.length < 1 ||
        entities.length > 100 ||
        !entities.every(uuid) ||
        new Set(entities).size !== entities.length ||
        !["csv", "json"].includes(format)
      )
        throw new Error("Choose 1–100 distinct confirmed records.");
      const response = await request(`/v1/workspaces/${workspace}/exports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: plan, entity_ids: entities, format }),
        signal,
      });
      if (!response.ok)
        throw new Error(
          "Export could not be created. Refresh results and check that these records are still confirmed.",
        );
      const value = (await response.json()) as ExportMetadata;
      if (
        !value ||
        !uuid(value.id) ||
        value.format !== format ||
        !Number.isInteger(value.row_count) ||
        value.row_count < 0 ||
        value.row_count > entities.length ||
        value.schema_version !== "skriller-qualified-v1" ||
        !Number.isFinite(Date.parse(value.expires_at)) ||
        Date.parse(value.expires_at) <= Date.now()
      )
        throw new Error("The service returned an invalid export confirmation.");
      return value;
    },
    async qualifiedExportDownload(
      workspace: string,
      id: string,
      format: ExportFormat,
      signal?: AbortSignal,
    ): Promise<Blob> {
      if (!uuid(workspace) || !uuid(id) || !["csv", "json"].includes(format))
        throw new Error("Export reference is invalid.");
      const response = await request(
        `/v1/workspaces/${workspace}/exports/${id}`,
        { signal },
      );
      if (!response.ok)
        throw new Error(
          "Export is unavailable or expired. Refresh results and create it again.",
        );
      const mime = format === "csv" ? "text/csv" : "application/json";
      if (
        response.headers.get("Content-Type")?.split(";")[0].trim() !== mime ||
        !response.body
      )
        throw new Error("The service returned an invalid export file.");
      const reader = response.body.getReader();
      const chunks: Uint8Array<ArrayBuffer>[] = [];
      let bytes = 0;
      let timedOut = false;
      const cancel = () => {
        void reader.cancel().catch(() => {});
      };
      signal?.addEventListener("abort", cancel, { once: true });
      const timer = setTimeout(() => {
        timedOut = true;
        cancel();
      }, 15000);
      try {
        while (true) {
          if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
          const { done, value } = await reader.read();
          if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
          if (timedOut)
            throw new Error(
              "Export download timed out. Try downloading again.",
            );
          if (done) break;
          bytes += value.byteLength;
          if (bytes > 8 * 1024 * 1024)
            throw new Error("Export exceeds the supported download size.");
          chunks.push(new Uint8Array(value));
        }
        return new Blob(chunks, { type: mime });
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener("abort", cancel);
        await reader.cancel();
        reader.releaseLock();
      }
    },
  };
}

export function saveQualifiedExport(blob: Blob, format: ExportFormat): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `skriller-confirmed-records.${format}`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
