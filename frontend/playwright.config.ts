import { defineConfig } from "@playwright/test";
import { assertDevTargetEnv } from "./src/e2e/devTarget";

assertDevTargetEnv(process.env);

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3010";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  retries: 0,
  use: {
    baseURL,
    trace: "on-first-retry",
  },
});
