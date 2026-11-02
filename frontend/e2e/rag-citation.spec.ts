import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import os from "node:os";
import path from "node:path";

function credential(name: string, localDefault: string): string {
  const value = process.env[name];
  if (process.env.E2E_TARGET === "dev") {
    if (!value) {
      throw new Error(`${name} is required when E2E_TARGET=dev`);
    }
    return value;
  }
  return value ?? localDefault;
}

const adminEmail = credential("E2E_ADMIN_EMAIL", "admin@example.com");
const adminPassword = credential("E2E_ADMIN_PASSWORD", "change-me-now-12");
const tenantKey = credential("E2E_TENANT_KEY", "demo");

function fourPagePdf(stamp: string): string {
  const file = path.join(os.tmpdir(), `rag-citation-${stamp}.pdf`);
  const script = path.join(__dirname, "generate_four_page_pdf.py");
  execFileSync(
    "uv",
    ["run", "--with", "fpdf2", "python", script, file],
    { cwd: path.join(__dirname, "..", ".."), stdio: "inherit" },
  );
  return file;
}

test("uploaded four-page PDF cites page 2 of that document only", async ({ page }) => {
  const stamp = `${Date.now()}`;
  const title = `citrine-serum-${stamp}`;
  const pdf = fourPagePdf(stamp);

  await page.goto("/login");
  await page.getByLabel("Email").fill(adminEmail);
  await page.getByLabel("Password").fill(adminPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));

  await page.goto("/upload");
  await page.locator("input[type=file]").setInputFiles(pdf);
  await page.getByLabel("Title (optional)").fill(title);
  const putPromise = page.waitForRequest((request) => request.method() === "PUT");
  await page.getByRole("button", { name: "Upload & register" }).click();
  const put = await putPromise;
  expect(put.url()).toContain("/staging/");
  await expect(page.getByText("status accepted")).toBeVisible();
  const documentLine = page.locator("p", { hasText: "document_id" });
  const documentId = (await documentLine.innerText()).replace("document_id", "").trim();
  expect(documentId).toMatch(/[0-9a-f-]{36}/i);
  await expect(page.getByText(/run completed/)).toBeVisible({ timeout: 90_000 });

  await page.goto("/query");
  await page.getByPlaceholder("Usually leave empty").fill(documentId);
  await page.getByRole("textbox").fill("What does page two say about ceramide?");
  const queryResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/query") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Send" }).click();
  const response = await queryResponse;
  if (response.status() === 403 && (await response.text()).includes("1010")) {
    throw new Error("Cloudflare 1010 is a failed browser job, not an API success");
  }
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  const citations = (body.citations ?? []) as Array<{
    document_id?: string;
    page_start?: number;
    page_end?: number;
  }>;
  expect(citations.length).toBeGreaterThan(0);
  expect(citations.every((citation) => citation.document_id === documentId)).toBeTruthy();
  expect(
    citations.some(
      (citation) =>
        typeof citation.page_start === "number" &&
        typeof citation.page_end === "number" &&
        citation.page_start <= 2 &&
        citation.page_end >= 2,
    ),
  ).toBeTruthy();
  await expect(page.getByText(/Page 2/)).toBeVisible();
  await expect(page.getByText(title)).toBeVisible();
});
