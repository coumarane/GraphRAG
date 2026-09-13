"use client";

import type { JSX } from "react";
import { notFound, useParams } from "next/navigation";
import {
  CategoriesPanel,
  ChatContextsPanel,
  ConnectorsPanel,
  LogsPanel,
} from "@/components/admin/OperationsPanels";
import {
  BenchmarksPanel,
  DocumentHealthPanel,
  FeedbackPanel,
  IngestionAuditPanel,
  KnowledgeGraphPanel,
  ProcessingPanel,
  RetrievalAuditPanel,
} from "@/components/admin/InsightsPanels";
import {
  BillingPanel,
  CloudCostsPanel,
  InfrastructurePanel,
  ProvidersPanel,
  SettingsPanel,
} from "@/components/admin/PlatformPanels";
import { UsersPanel } from "@/components/admin/UsersPanel";

const PANELS: Record<string, () => JSX.Element> = {
  connectors: ConnectorsPanel,
  categories: CategoriesPanel,
  "chat-contexts": ChatContextsPanel,
  logs: LogsPanel,
  users: UsersPanel,
  "document-health": DocumentHealthPanel,
  processing: ProcessingPanel,
  "knowledge-graph": KnowledgeGraphPanel,
  feedback: FeedbackPanel,
  benchmarks: BenchmarksPanel,
  "ingestion-audit": IngestionAuditPanel,
  "retrieval-audit": RetrievalAuditPanel,
  providers: ProvidersPanel,
  infrastructure: InfrastructurePanel,
  billing: BillingPanel,
  "cloud-costs": CloudCostsPanel,
  settings: SettingsPanel,
};

export default function AdminSectionPage() {
  const params = useParams<{ section: string }>();
  const Panel = PANELS[params.section];
  if (!Panel) notFound();
  return <Panel />;
}
