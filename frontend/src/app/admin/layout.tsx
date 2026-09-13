import type { ReactNode } from "react";
import { AdminShell } from "@/components/admin/AdminShell";
import "./admin.css";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <div className="admin-console">
      <AdminShell>{children}</AdminShell>
    </div>
  );
}
