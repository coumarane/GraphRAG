"use client";

import type { ReactNode } from "react";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type UserPermissionValues = {
  displayName: string;
  role: "member" | "admin";
  status: "active" | "disabled" | "suspended";
  canIngest: boolean;
  clearanceLevel: string;
  country: string;
  department: string;
  businessUnit: string;
  jobLevel: string;
  costCenter: string;
  employmentType: string;
  groups: string;
};

export const EMPTY_PERMISSIONS: UserPermissionValues = {
  displayName: "",
  role: "member",
  status: "active",
  canIngest: true,
  clearanceLevel: "1",
  country: "",
  department: "",
  businessUnit: "",
  jobLevel: "",
  costCenter: "",
  employmentType: "",
  groups: "",
};

export function permissionsFromAttributes(
  user: {
    display_name: string | null;
    role: string;
    status: string;
    attributes?: Record<string, unknown>;
  },
): UserPermissionValues {
  const attrs = user.attributes || {};
  const groups = Array.isArray(attrs.groups)
    ? attrs.groups.map(String).join(", ")
    : typeof attrs.groups === "string"
      ? attrs.groups
      : "";
  return {
    displayName: user.display_name || "",
    role: user.role === "admin" ? "admin" : "member",
    status:
      user.status === "disabled" || user.status === "suspended"
        ? user.status
        : "active",
    canIngest: attrs.can_ingest !== false,
    clearanceLevel:
      attrs.clearance_level == null ? "1" : String(attrs.clearance_level),
    country: attrs.country == null ? "" : String(attrs.country),
    department: attrs.department == null ? "" : String(attrs.department),
    businessUnit: attrs.business_unit == null ? "" : String(attrs.business_unit),
    jobLevel: attrs.job_level == null ? "" : String(attrs.job_level),
    costCenter: attrs.cost_center == null ? "" : String(attrs.cost_center),
    employmentType:
      attrs.employment_type == null ? "" : String(attrs.employment_type),
    groups,
  };
}

export function permissionPayload(values: UserPermissionValues) {
  const clearance = Number.parseInt(values.clearanceLevel, 10);
  return {
    display_name: values.displayName.trim() || null,
    role: values.role,
    status: values.status,
    attributes: {
      admin: values.role === "admin",
      can_ingest: values.canIngest,
      clearance_level: Number.isFinite(clearance) ? clearance : 1,
      country: values.country.trim(),
      department: values.department.trim(),
      business_unit: values.businessUnit.trim(),
      job_level: values.jobLevel.trim(),
      cost_center: values.costCenter.trim(),
      employment_type: values.employmentType.trim(),
      groups: values.groups,
    },
  };
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <Label className="text-xs uppercase tracking-wide">{label}</Label>
      {children}
    </label>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors",
        checked
          ? "border-accent/50 bg-accent-soft"
          : "border-border bg-surface-elevated/40 hover:border-accent/40",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
          checked
            ? "border-accent bg-accent text-[10px] text-white"
            : "border-border bg-background",
        )}
        aria-hidden
      >
        {checked ? "✓" : ""}
      </span>
      <span>
        <span className="block text-sm font-medium text-foreground">{label}</span>
        <span className="block text-xs text-muted">{hint}</span>
      </span>
    </button>
  );
}

const selectClass =
  "h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function UserPermissionFields({
  values,
  onChange,
  showStatus,
  lockAdmin,
}: {
  values: UserPermissionValues;
  onChange: (next: UserPermissionValues) => void;
  showStatus?: boolean;
  lockAdmin?: boolean;
}) {
  function patch(partial: Partial<UserPermissionValues>) {
    onChange({ ...values, ...partial });
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Display name">
          <Input
            value={values.displayName}
            onChange={(event) => patch({ displayName: event.target.value })}
            placeholder="Optional"
          />
        </Field>
        <Field label="Workspace role">
          <select
            className={selectClass}
            value={values.role}
            disabled={lockAdmin}
            onChange={(event) => {
              const role = event.target.value === "admin" ? "admin" : "member";
              patch({ role });
            }}
          >
            <option value="member">member</option>
            <option value="admin">admin</option>
          </select>
        </Field>
        {showStatus ? (
          <Field label="Account status">
            <select
              className={selectClass}
              value={values.status}
              disabled={lockAdmin}
              onChange={(event) =>
                patch({
                  status: event.target.value as UserPermissionValues["status"],
                })
              }
            >
              <option value="active">active — can sign in and query</option>
              <option value="disabled">disabled — blocked</option>
              <option value="suspended">suspended — blocked</option>
            </select>
          </Field>
        ) : null}
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">
          Capabilities
        </p>
        <Toggle
          checked={values.role === "admin"}
          disabled={lockAdmin}
          onChange={(checked) => patch({ role: checked ? "admin" : "member" })}
          label="Workspace admin"
          hint="Manage users, policies, and quotas (ABAC admin attribute)"
        />
        <Toggle
          checked={values.canIngest}
          onChange={(checked) => patch({ canIngest: checked })}
          label="Ingest documents"
          hint="Upload, delete, and reindex documents (can_ingest)"
        />
        {showStatus ? (
          <Toggle
            checked={values.status === "active"}
            disabled={lockAdmin}
            onChange={(checked) =>
              patch({ status: checked ? "active" : "disabled" })
            }
            label="Query access"
            hint="Chat, cross-document, and graph queries require an active account"
          />
        ) : null}
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">
          Document access attributes
        </p>
        <p className="text-xs text-muted">
          Used by ABAC policies for document.read (clearance, country, groups).
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Clearance level">
            <Input
              type="number"
              min={0}
              value={values.clearanceLevel}
              onChange={(event) => patch({ clearanceLevel: event.target.value })}
            />
          </Field>
          <Field label="Country">
            <Input
              value={values.country}
              onChange={(event) => patch({ country: event.target.value })}
              placeholder="FR"
            />
          </Field>
          <Field label="Department">
            <Input
              value={values.department}
              onChange={(event) => patch({ department: event.target.value })}
              placeholder="R&D"
            />
          </Field>
          <Field label="Business unit">
            <Input
              value={values.businessUnit}
              onChange={(event) => patch({ businessUnit: event.target.value })}
            />
          </Field>
          <Field label="Job level">
            <Input
              value={values.jobLevel}
              onChange={(event) => patch({ jobLevel: event.target.value })}
            />
          </Field>
          <Field label="Cost center">
            <Input
              value={values.costCenter}
              onChange={(event) => patch({ costCenter: event.target.value })}
            />
          </Field>
          <Field label="Employment type">
            <Input
              value={values.employmentType}
              onChange={(event) => patch({ employmentType: event.target.value })}
              placeholder="full-time"
            />
          </Field>
          <Field label="Groups">
            <Input
              value={values.groups}
              onChange={(event) => patch({ groups: event.target.value })}
              placeholder="research, finance"
            />
          </Field>
        </div>
      </div>
    </div>
  );
}
