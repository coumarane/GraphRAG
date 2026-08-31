"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { readTenantKey } from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type FieldFilterOperator = "eq" | "contains" | "gt" | "gte" | "lt" | "lte" | "between";

const OPERATORS: { value: FieldFilterOperator; label: string }[] = [
  { value: "eq", label: "= equals" },
  { value: "contains", label: "contains" },
  { value: "gt", label: "> greater than" },
  { value: "gte", label: "≥ at least" },
  { value: "lt", label: "< less than" },
  { value: "lte", label: "≤ at most" },
  { value: "between", label: "between" },
];

type FieldFilterDraft = {
  id: string;
  name: string;
  operator: FieldFilterOperator;
  value: string;
  valueTo: string;
};

type DocumentItem = {
  document_id: string;
  title: string | null;
  document_type: string | null;
  status: string;
  tags: string[];
};

type MatchedField = {
  name: string;
  value: unknown;
  confidence_band: string;
};

type SearchHit = {
  document: DocumentItem;
  matched_fields: MatchedField[];
};

type SearchResponse = {
  items: SearchHit[];
  total: number;
  offset: number;
  limit: number;
};

function newFilterId(): string {
  return `f_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

/** Parse a numeric-looking filter value to a number so gt/gte/lt/lte/between
 * compare numerically server-side; anything else (including dates) stays a
 * plain string, which the backend also handles for ISO date comparisons. */
function coerceFilterValue(raw: string): string | number {
  const trimmed = raw.trim();
  if (trimmed !== "" && !Number.isNaN(Number(trimmed))) {
    return Number(trimmed);
  }
  return trimmed;
}

function SearchPageContent() {
  const searchParams = useSearchParams();
  const [text, setText] = useState(searchParams.get("q") || "");
  const [documentType, setDocumentType] = useState("");
  const [status, setStatus] = useState("");
  const [tags, setTags] = useState("");
  const [department, setDepartment] = useState("");
  const [country, setCountry] = useState("");
  const [businessUnit, setBusinessUnit] = useState("");
  const [classification, setClassification] = useState("");
  const [createdAfter, setCreatedAfter] = useState("");
  const [createdBefore, setCreatedBefore] = useState("");
  const [fieldFilters, setFieldFilters] = useState<FieldFilterDraft[]>([]);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runSearch = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/documents/search", {
        credentials: "include",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-Key": readTenantKey(),
        },
        body: JSON.stringify({
          text: text.trim() || null,
          document_type: documentType.trim() || null,
          status: status.trim() || null,
          tags: tags
            .split(",")
            .map((tag) => tag.trim())
            .filter(Boolean),
          department: department.trim() || null,
          country: country.trim() || null,
          business_unit: businessUnit.trim() || null,
          classification: classification.trim() || null,
          created_after: createdAfter ? new Date(createdAfter).toISOString() : null,
          created_before: createdBefore ? new Date(createdBefore).toISOString() : null,
          field_filters: fieldFilters
            .filter((filter) => filter.name.trim() && filter.value.trim())
            .map((filter) => ({
              name: filter.name.trim(),
              operator: filter.operator,
              value: coerceFilterValue(filter.value),
              value_to:
                filter.operator === "between" && filter.valueTo.trim()
                  ? coerceFilterValue(filter.valueTo)
                  : null,
            })),
          offset: 0,
          limit: 50,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : body.message || response.statusText,
        );
      }
      setResult(body as SearchResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResult(null);
    } finally {
      setBusy(false);
    }
  }, [
    text,
    documentType,
    status,
    tags,
    department,
    country,
    businessUnit,
    classification,
    createdAfter,
    createdBefore,
    fieldFilters,
  ]);

  useEffect(() => {
    void runSearch();
    // Only re-run automatically for the initial ?q= from the URL; further
    // searches are explicit via the Search button/form submit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function addFieldFilter() {
    setFieldFilters((prev) => [
      ...prev,
      { id: newFilterId(), name: "", operator: "eq", value: "", valueTo: "" },
    ]);
  }

  function updateFieldFilter(id: string, patch: Partial<FieldFilterDraft>) {
    setFieldFilters((prev) =>
      prev.map((filter) => (filter.id === id ? { ...filter, ...patch } : filter)),
    );
  }

  function removeFieldFilter(id: string) {
    setFieldFilters((prev) => prev.filter((filter) => filter.id !== id));
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    void runSearch();
  }

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Search</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Search documents by title, metadata, and extracted structured fields.
        </p>
      </div>

      <form onSubmit={onSubmit} className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Filters</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="search-text">Text</Label>
              <Input
                id="search-text"
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="Title contains…"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="search-type">Document type</Label>
              <Input
                id="search-type"
                value={documentType}
                onChange={(event) => setDocumentType(event.target.value)}
                placeholder="sds, datasheet…"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="search-status">Status</Label>
              <Input
                id="search-status"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                placeholder="ready, failed…"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="search-tags">Tags</Label>
              <Input
                id="search-tags"
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="comma, separated"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="search-department">Department</Label>
              <Input
                id="search-department"
                value={department}
                onChange={(event) => setDepartment(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="search-country">Country</Label>
              <Input
                id="search-country"
                value={country}
                onChange={(event) => setCountry(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="search-business-unit">Business unit</Label>
              <Input
                id="search-business-unit"
                value={businessUnit}
                onChange={(event) => setBusinessUnit(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="search-classification">Classification</Label>
              <Input
                id="search-classification"
                value={classification}
                onChange={(event) => setClassification(event.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1.5">
                <Label htmlFor="search-created-after">Created after</Label>
                <Input
                  id="search-created-after"
                  type="date"
                  value={createdAfter}
                  onChange={(event) => setCreatedAfter(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="search-created-before">Created before</Label>
                <Input
                  id="search-created-before"
                  type="date"
                  value={createdBefore}
                  onChange={(event) => setCreatedBefore(event.target.value)}
                />
              </div>
            </div>

            <div className="space-y-2 border-t border-border pt-4">
              <div className="flex items-center justify-between">
                <Label>Extracted fields</Label>
                <Button type="button" variant="ghost" size="sm" onClick={addFieldFilter}>
                  + Add
                </Button>
              </div>
              {fieldFilters.length === 0 ? (
                <p className="text-xs text-muted">
                  Filter by fields extracted from documents, e.g. lot_number = LOT-42.
                </p>
              ) : null}
              {fieldFilters.map((filter) => (
                <div
                  key={filter.id}
                  className="space-y-1.5 rounded-lg border border-border p-2"
                >
                  <div className="flex items-center gap-1">
                    <Input
                      value={filter.name}
                      onChange={(event) =>
                        updateFieldFilter(filter.id, { name: event.target.value })
                      }
                      placeholder="field name"
                      className="h-8 text-xs"
                    />
                    <button
                      type="button"
                      onClick={() => removeFieldFilter(filter.id)}
                      className="shrink-0 rounded p-1 text-xs text-muted hover:text-danger"
                      aria-label="Remove filter"
                    >
                      ✕
                    </button>
                  </div>
                  <select
                    value={filter.operator}
                    onChange={(event) =>
                      updateFieldFilter(filter.id, {
                        operator: event.target.value as FieldFilterOperator,
                      })
                    }
                    className="h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {OPERATORS.map((op) => (
                      <option key={op.value} value={op.value}>
                        {op.label}
                      </option>
                    ))}
                  </select>
                  <div className="flex items-center gap-1">
                    <Input
                      value={filter.value}
                      onChange={(event) =>
                        updateFieldFilter(filter.id, { value: event.target.value })
                      }
                      placeholder="value"
                      className="h-8 text-xs"
                    />
                    {filter.operator === "between" ? (
                      <Input
                        value={filter.valueTo}
                        onChange={(event) =>
                          updateFieldFilter(filter.id, { valueTo: event.target.value })
                        }
                        placeholder="and…"
                        className="h-8 text-xs"
                      />
                    ) : null}
                  </div>
                </div>
              ))}
            </div>

            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "Searching…" : "Search"}
            </Button>
          </CardContent>
        </Card>

        <div className="space-y-3">
          {error ? (
            <p className="rounded border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
              {error}
            </p>
          ) : null}

          {!error && result ? (
            <p className="text-sm text-muted">
              {result.total} document{result.total === 1 ? "" : "s"} found
            </p>
          ) : null}

          {result?.items.map((hit) => (
            <Card key={hit.document.document_id}>
              <CardContent className="space-y-2 py-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Link
                    href={`/documents/${hit.document.document_id}`}
                    className="font-medium text-foreground hover:text-accent hover:underline"
                  >
                    {hit.document.title || "Untitled"}
                  </Link>
                  <Badge variant="muted">{hit.document.status}</Badge>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {hit.document.document_type ? (
                    <Badge variant="default">{hit.document.document_type}</Badge>
                  ) : null}
                  {hit.document.tags.map((tag) => (
                    <Badge key={tag} variant="muted">
                      {tag}
                    </Badge>
                  ))}
                </div>
                {hit.matched_fields.length ? (
                  <div className="flex flex-wrap gap-1.5 border-t border-border pt-2">
                    {hit.matched_fields.map((field) => (
                      <span
                        key={field.name}
                        className={cn(
                          "rounded-md border border-border bg-surface-elevated px-2 py-0.5 text-xs text-foreground/90",
                        )}
                      >
                        <span className="text-muted">{field.name}:</span>{" "}
                        {String(field.value)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ))}

          {result && result.items.length === 0 && !error ? (
            <p className="rounded-lg border border-border bg-surface px-4 py-6 text-center text-sm text-muted">
              No documents match these filters.
            </p>
          ) : null}
        </div>
      </form>
    </section>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
      <SearchPageContent />
    </Suspense>
  );
}
