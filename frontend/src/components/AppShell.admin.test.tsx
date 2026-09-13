import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/connectors",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const adminSession = {
  user: {
    user_id: "u1",
    email: "admin@chatwithdocs.com",
    display_name: "Admin",
    role: "admin",
    tenant_id: "t1",
  },
  tenant: {
    tenant_id: "t1",
    tenant_key: "chatwithdocs",
    display_name: "Chatwithdocs",
  },
};

vi.mock("@/lib/auth", () => ({
  readCachedSession: () => adminSession,
  fetchSession: async () => adminSession,
  logoutRequest: async () => undefined,
}));

describe("AppShell on Admin routes", () => {
  it("keeps the GraphRAG workspace chrome instead of swapping to a separate console", () => {
    render(
      <AppShell>
        <div>Connectors panel</div>
      </AppShell>,
    );

    expect(screen.getAllByText("GraphRAG").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Documents").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Chat").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Admin").length).toBeGreaterThan(0);
    expect(screen.getByText("Connectors panel")).toBeInTheDocument();
    expect(screen.queryByText("Back to workspace")).not.toBeInTheDocument();
  });
});
