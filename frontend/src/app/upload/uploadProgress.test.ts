import { describe, expect, it } from "vitest";
import { buildUploadSessionBody } from "./uploadPayload";
import { shouldStopWaiting } from "./uploadProgress";

describe("upload session body", () => {
  it("sends JSON metadata and does not include file bytes", () => {
    const file = new File(["payload-bytes"], "hello.pdf", { type: "application/pdf" });
    const body = buildUploadSessionBody(file, "Notes", { enabled: false, payload: null });
    expect(body).toEqual({ filename: "hello.pdf", byte_size: 13, title: "Notes" });
    expect(JSON.stringify(body)).not.toContain("payload-bytes");
  });
});

describe("upload progress", () => {
  it("stops the spinner on a failed poll", () => {
    expect(shouldStopWaiting(false, null, null)).toEqual({ stop: true, error: true });
  });

  it("stops the spinner when progress is stalled or failed", () => {
    expect(shouldStopWaiting(true, "stalled", "running").stop).toBe(true);
    expect(shouldStopWaiting(true, "failed", "failed").stop).toBe(true);
    expect(shouldStopWaiting(true, "running", "running")).toEqual({ stop: false, error: false });
  });
});
