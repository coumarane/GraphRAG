import { expect, test } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const adminEmail = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const adminPassword = process.env.E2E_ADMIN_PASSWORD ?? "change-me-now-12";
const tenantKey = process.env.E2E_TENANT_KEY ?? "demo";

function isolatedPdf(stamp: string): string {
  const body = [
    "%PDF-1.4",
    "1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj",
    "2 0 obj<< /Type /Pages /Count 1 /Kids [3 0 R] >>endobj",
    "3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>endobj",
    `% e2e ${stamp}`,
    "trailer<< /Root 1 0 R >>",
    "%%EOF",
    "",
  ].join("\n");
  const file = path.join(os.tmpdir(), `e2e-${stamp}.pdf`);
  fs.writeFileSync(file, body);
  return file;
}

test("isolated member uploads through object storage and sees the document", async ({
  page,
}) => {
  const stamp = `${Date.now()}`;
  const memberEmail = `e2e-${stamp}@example.com`;
  const memberPassword = `E2e-isolated-${stamp}`;
  const title = `e2e-${stamp}`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(adminEmail);
  await page.getByLabel("Password").fill(adminPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  const created = await page.request.post("/api/admin/users", {
    data: {
      email: memberEmail,
      password: memberPassword,
      display_name: title,
      role: "member",
      attributes: { can_ingest: true },
    },
    headers: {
      "Content-Type": "application/json",
      "X-Tenant-Key": tenantKey,
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/\/login/);
  await page.getByLabel("Email").fill(memberEmail);
  await page.getByLabel("Password").fill(memberPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Operations Dashboard" })).toBeVisible();
  await page.goto("/upload");
  await expect(page).toHaveURL(/\/upload$/);
  await expect(page.getByRole("heading", { name: "Upload" })).toBeVisible();
  await page.locator("input[type=file]").setInputFiles(isolatedPdf(stamp));
  await page.getByLabel("Title (optional)").fill(title);
  const putPromise = page.waitForRequest(
    (request) => request.method() === "PUT",
  );
  await page.getByRole("button", { name: "Upload & register" }).click();
  const put = await putPromise;
  expect(put.url()).toContain("/staging/");
  expect(put.url()).not.toContain("/api/ingest");
  expect(new URL(put.url()).host).toBe(
    process.env.E2E_OBJECT_HOST ?? "127.0.0.1:9000",
  );

  await expect(page.getByText("status accepted")).toBeVisible();
  await expect(
    page.getByText(/run (pending|running|stalled|completed|failed|partial)/),
  ).toBeVisible();
  await page.goto("/documents");
  await expect(page.getByRole("link", { name: title })).toBeVisible();
});
