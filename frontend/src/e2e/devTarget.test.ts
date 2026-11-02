import { describe, expect, it } from "vitest";
import { assertDevTargetEnv, missingDevTargetEnv } from "./devTarget";

describe("dev target credentials", () => {
  it("requires the four DEV values and does not accept the local demo login", () => {
    const missing = missingDevTargetEnv({ E2E_TARGET: "dev" });
    expect(missing).toEqual([
      "E2E_BASE_URL",
      "E2E_ADMIN_EMAIL",
      "E2E_ADMIN_PASSWORD",
      "E2E_TENANT_KEY",
    ]);
    expect(() => assertDevTargetEnv({ E2E_TARGET: "dev" })).toThrow(/E2E_ADMIN_PASSWORD/);
  });

  it("leaves a local run alone when E2E_TARGET is unset", () => {
    expect(missingDevTargetEnv({})).toEqual([]);
    expect(() => assertDevTargetEnv({})).not.toThrow();
  });
});
