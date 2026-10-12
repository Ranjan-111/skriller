import type { components } from "../generated/api";

export type ProgressUpdate = {
  id: string;
  data: components["schemas"]["ProgressEvent"];
};

/** Decode bounded SSE frames while preserving decimal replay cursors exactly. */
export async function* decodeProgress(
  response: Response,
): AsyncGenerator<ProgressUpdate> {
  if (!response.body) throw new Error("Progress stream has no body.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) return;
      pending += decoder.decode(chunk.value, { stream: true });
      while (true) {
        const separator = /\r?\n\r?\n/.exec(pending);
        if (!separator) break;
        const frame = pending.slice(0, separator.index);
        pending = pending.slice(separator.index + separator[0].length);
        if (frame.length > 65_536)
          throw new Error("Progress frame exceeds its limit.");
        let id = "";
        let event = "message";
        const data: string[] = [];
        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith(":")) continue;
          const colon = line.indexOf(":");
          const field = colon < 0 ? line : line.slice(0, colon);
          const raw = colon < 0 ? "" : line.slice(colon + 1);
          const value = raw.startsWith(" ") ? raw.slice(1) : raw;
          if (field === "id") id = value;
          if (field === "event") event = value;
          if (field === "data") data.push(value);
        }
        if (event !== "progress" || !data.length) continue;
        if (!/^[0-9]+$/.test(id) || BigInt(id) > 2n ** 63n - 1n)
          throw new Error("Invalid progress cursor.");
        const payload: unknown = JSON.parse(data.join("\n"));
        if (
          !payload ||
          typeof payload !== "object" ||
          !("kind" in payload) ||
          typeof payload.kind !== "string" ||
          !("details" in payload) ||
          !payload.details ||
          typeof payload.details !== "object" ||
          Array.isArray(payload.details)
        )
          throw new Error("Invalid progress event.");
        yield { id, data: payload as components["schemas"]["ProgressEvent"] };
      }
      if (pending.length > 65_536)
        throw new Error("Progress frame exceeds its limit.");
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
