export const DEV_TARGET_ENV_KEYS = [
  "E2E_BASE_URL",
  "E2E_ADMIN_EMAIL",
  "E2E_ADMIN_PASSWORD",
  "E2E_TENANT_KEY",
] as const;

export function missingDevTargetEnv(env: Record<string, string | undefined>): string[] {
  if (env.E2E_TARGET !== "dev") return [];
  return DEV_TARGET_ENV_KEYS.filter((key) => !env[key]);
}

export function assertDevTargetEnv(env: Record<string, string | undefined>): void {
  const missing = missingDevTargetEnv(env);
  if (missing.length > 0) {
    throw new Error(`E2E_TARGET=dev requires ${missing.join(", ")}`);
  }
}
