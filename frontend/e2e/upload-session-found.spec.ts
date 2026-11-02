import { expect, test } from "@playwright/test";

const uploadId = "01a19b58-4a71-76b4-bbf0-e63b769d5a1c";
const session = {
  user: {
    user_id: "00000000-0000-7000-8000-000000000001",
    email: "admin@example.com",
    display_name: "Admin",
    role: "admin",
    tenant_id: "00000000-0000-7000-8000-000000000002",
  },
  tenant: {
    tenant_id: "00000000-0000-7000-8000-000000000002",
    tenant_key: "demo",
    display_name: "Demo",
  },
};

test("Azure PUT is followed by complete for the same upload session", async ({
  page,
  context,
}) => {
  const unexpected: string[] = [];
  page.on("response", (response) => {
    const status = response.status();
    if (status !== 401 && status !== 404) return;
    const url = new URL(response.url());
    unexpected.push(`${response.request().method()} ${status} ${url.host}${url.pathname}`);
  });

  await context.addCookies([
    {
      name: "erag_session",
      value: "dev-session",
      url: "http://localhost:3010",
    },
  ]);
  await page.route(/\/api\/auth\/me$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(session),
    });
  });
  await page.route(/\/api\/documents\/uploads$/, async (route) => {
    expect(route.request().method()).toBe("POST");
    const body = route.request().postDataJSON() as { filename: string; byte_size: number };
    expect(body.filename).toBe("notes.pdf");
    expect(body.byte_size).toBeGreaterThan(0);
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        upload_id: uploadId,
        expires_at: "2026-11-02T10:00:00Z",
        upload: {
          method: "PUT",
          url: "https://graphragdocsdevbmo9.blob.core.windows.net/documents/staging/notes.pdf?sig=redacted",
          expires_at: "2026-11-02T10:00:00Z",
          headers: {
            "x-ms-blob-type": "BlockBlob",
            "content-type": "application/pdf",
          },
        },
      }),
    });
  });
  await page.route(/blob\.core\.windows\.net/, async (route) => {
    expect(route.request().method()).toBe("PUT");
    expect(route.request().headers()["x-ms-blob-type"]).toBe("BlockBlob");
    await route.fulfill({ status: 201, body: "" });
  });
  await page.route(
    new RegExp(`/api/documents/uploads/${uploadId}/complete$`),
    async (route) => {
      expect(route.request().method()).toBe("POST");
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          ingestion_run_id: "01a19b58-4a71-76b4-bbf0-e63b769d5a1d",
          document_id: "01a19b58-4a71-76b4-bbf0-e63b769d5a1e",
          version_id: "01a19b58-4a71-76b4-bbf0-e63b769d5a1f",
          status: "accepted",
        }),
      });
    },
  );
  await page.route(/\/api\/ingestion-runs\//, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "pending",
        progress_state: "running",
        stages: [],
      }),
    });
  });

  await page.goto("/upload");
  await expect(page.getByRole("heading", { name: "Upload" })).toBeVisible();
  await page.locator("input[type=file]").setInputFiles({
    name: "notes.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\nHi\n"),
  });
  await page.getByRole("button", { name: "Upload & register" }).click();
  await expect(page.getByText("Upload session not found")).toHaveCount(0);
  await expect(page.getByText("status accepted")).toBeVisible();
  expect(unexpected).toEqual([]);
});
