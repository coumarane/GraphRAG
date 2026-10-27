export function shouldStopWaiting(
  httpOk: boolean,
  progressState: string | null | undefined,
  runStatus: string | null | undefined,
): { stop: boolean; error: boolean } {
  if (!httpOk) {
    return { stop: true, error: true };
  }
  const terminal = new Set([
    "completed",
    "completed_with_warnings",
    "partial",
    "failed",
    "cancelled",
    "ready",
    "stalled",
  ]);
  if (progressState === "stalled" || progressState === "failed") {
    return { stop: true, error: false };
  }
  if (runStatus && terminal.has(runStatus)) {
    return { stop: true, error: false };
  }
  if (progressState && terminal.has(progressState)) {
    return { stop: true, error: false };
  }
  return { stop: false, error: false };
}
