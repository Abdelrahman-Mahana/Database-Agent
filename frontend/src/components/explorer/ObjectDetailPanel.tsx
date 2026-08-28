"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import React, { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { apiClient } from "@/services/api";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  TableProperties, 
  Key, 
  Link as LinkIcon, 
  Layers, 
  Sparkles, 
  CheckCircle2, 
  XCircle, 
  Calendar, 
  ExternalLink,
  ShieldAlert,
  Code,
  Download,
  Check,
  Eye,
  RefreshCw
} from "lucide-react";
import { BaseDBObject } from "@/types/api";

interface ObjectDetailPanelProps {
  activeObject: BaseDBObject | null;
  onSelectObject: (name: string, type: string) => void;
  onAskAI: (name: string) => void;
}

interface TablePreviewData {
  status: string;
  table_name: string;
  schema_name: string;
  columns: string[];
  rows: Record<string, any>[];
  row_count: number;
  limit: number;
}

export function ObjectDetailPanel({
  activeObject,
  onSelectObject,
  onAskAI,
}: ObjectDetailPanelProps) {
  const [copiedSchema, setCopiedSchema] = useState(false);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);

  // Fetch live table sample preview
  const { data: previewData, isLoading: isPreviewLoading, refetch: refetchPreview } = useQuery<TablePreviewData>({
    queryKey: ['table-preview', activeObject?.name, activeObject?.schema],
    queryFn: async () => {
      if (!activeObject?.name) return null;
      const res = await apiClient.get(`/schema/preview/${encodeURIComponent(activeObject.name)}?schema_name=${encodeURIComponent(activeObject.schema || 'public')}&limit=10`);
      return res.data;
    },
    enabled: Boolean(activeObject?.name),
  });

  // Table profiling mutation
  const profileMutation = useMutation({
    mutationFn: async () => {
      if (!activeObject?.name) return;
      const res = await apiClient.post(`/schema/refresh/${encodeURIComponent(activeObject.name)}?schema_name=${encodeURIComponent(activeObject.schema || 'public')}`);
      return res.data;
    },
    onSuccess: (data) => {
      setProfileMessage(data?.message || "Profile refreshed successfully");
      refetchPreview();
      setTimeout(() => setProfileMessage(null), 3000);
    },
    onError: (err: any) => {
      setProfileMessage(err?.response?.data?.detail || "Profiling error");
      setTimeout(() => setProfileMessage(null), 4000);
    }
  });

  if (!activeObject) {
    return (
      <Card className="border-border/60 p-12 text-center text-muted-foreground shadow-sm bg-card/50">
        Select a database object from the tree on the left to inspect detailed schema definitions and live data.
      </Card>
    );
  }

  const exportSchemaAsJson = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(activeObject, null, 2));
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `${activeObject.name}_schema.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const exportColumnsAsCsv = () => {
    if (!activeObject.columns || activeObject.columns.length === 0) return;
    const headers = ["Column Name", "Data Type", "Nullable", "Default", "Primary Key", "Samples"];
    const rows = activeObject.columns.map((c) => [
      c.name,
      c.type,
      c.nullable ? "YES" : "NO",
      c.default || "",
      c.primary_key ? "YES" : "NO",
      (c.samples || []).join(" | ")
    ]);
    const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(e => e.map(val => `"${String(val).replace(/"/g, '""')}"`).join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `${activeObject.name}_columns.csv`);
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const copySqlDefinition = () => {
    const sql = activeObject.definition || `-- Table: ${activeObject.name}\n-- Columns: ${activeObject.columns.map(c => `${c.name} ${c.type}`).join(', ')}`;
    navigator.clipboard.writeText(sql);
    setCopiedSchema(true);
    setTimeout(() => setCopiedSchema(false), 2000);
  };

  return (
    <Card className="border-border/60 shadow-sm bg-card/60 backdrop-blur">
      {/* Top Inspector Header */}
      <CardHeader className="p-6 border-b border-border/40 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-2xl font-bold tracking-tight">{activeObject.name}</h3>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary/10 text-primary uppercase border border-primary/20">
              {activeObject.object_type}
            </span>
            {activeObject.primary_key && activeObject.primary_key.length > 0 && (
              <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1 font-mono">
                <Key className="h-3 w-3" />
                PK: {activeObject.primary_key.join(", ")}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1 font-mono">
            {activeObject.qualified_name}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Profile Table Button */}
          <Button
            size="sm"
            variant="outline"
            onClick={() => profileMutation.mutate()}
            disabled={profileMutation.isPending}
            className="gap-1.5 text-xs font-semibold"
            title="Incrementally refresh sample values and column statistics"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${profileMutation.isPending ? "animate-spin" : ""}`} />
            {profileMutation.isPending ? "Profiling..." : "Refresh Profile"}
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={exportColumnsAsCsv}
            className="gap-1 text-xs"
            title="Download columns definition as CSV"
          >
            <Download className="h-3.5 w-3.5" />
            CSV
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={exportSchemaAsJson}
            className="gap-1 text-xs"
            title="Export full object metadata as JSON"
          >
            <Download className="h-3.5 w-3.5" />
            JSON
          </Button>
          <Button
            size="sm"
            onClick={() => onAskAI(activeObject.name)}
            className="gap-2 bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white shadow font-semibold"
          >
            <Sparkles className="h-3.5 w-3.5" />
            Ask AI About {activeObject.name}
          </Button>
        </div>
      </CardHeader>

      {/* Profile Toast Message */}
      {profileMessage && (
        <div className="px-6 py-2 bg-primary/10 border-b border-primary/20 text-xs font-semibold text-primary flex items-center gap-2">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
          {profileMessage}
        </div>
      )}

      <CardContent className="p-6">
        <Tabs defaultValue="preview" className="w-full">
          <TabsList className="grid w-full grid-cols-6 mb-6">
            <TabsTrigger value="preview" className="flex items-center gap-1.5 text-xs">
              <Eye className="h-3.5 w-3.5 text-primary" />
              Live Preview
            </TabsTrigger>
            <TabsTrigger value="columns" className="flex items-center gap-1.5 text-xs">
              <TableProperties className="h-3.5 w-3.5" />
              Fields ({activeObject.columns?.length || 0})
            </TabsTrigger>
            <TabsTrigger value="foreign-keys" className="flex items-center gap-1.5 text-xs">
              <LinkIcon className="h-3.5 w-3.5" />
              FKs ({activeObject.foreign_keys?.length || 0})
            </TabsTrigger>
            <TabsTrigger value="indexes" className="flex items-center gap-1.5 text-xs">
              <Layers className="h-3.5 w-3.5" />
              Indexes ({activeObject.indexes?.length || 0})
            </TabsTrigger>
            <TabsTrigger value="constraints" className="flex items-center gap-1.5 text-xs">
              <ShieldAlert className="h-3.5 w-3.5" />
              Constraints ({activeObject.constraints?.length || 0})
            </TabsTrigger>
            <TabsTrigger value="definition" className="flex items-center gap-1.5 text-xs">
              <Code className="h-3.5 w-3.5" />
              Definition
            </TabsTrigger>
          </TabsList>

          {/* 1. Live Data Preview Tab (NEW FEATURE) */}
          <TabsContent value="preview" className="space-y-4">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                Showing top {previewData?.row_count || 10} live sample records from <strong>{activeObject.name}</strong>.
              </p>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => refetchPreview()}
                disabled={isPreviewLoading}
                className="h-7 text-xs gap-1 text-muted-foreground"
              >
                <RefreshCw className={`h-3 w-3 ${isPreviewLoading ? "animate-spin" : ""}`} />
                Reload Data
              </Button>
            </div>

            <div className="rounded-lg border border-border/50 overflow-hidden shadow-sm">
              {isPreviewLoading ? (
                <div className="p-12 text-center text-xs text-muted-foreground flex flex-col items-center gap-2">
                  <RefreshCw className="h-6 w-6 animate-spin text-primary" />
                  Fetching live table records...
                </div>
              ) : previewData?.rows && previewData.rows.length > 0 ? (
                <div className="overflow-x-auto max-h-96">
                  <table className="w-full text-left text-xs border-collapse font-mono">
                    <thead className="sticky top-0 bg-muted/90 backdrop-blur z-10">
                      <tr className="border-b border-border/60 text-muted-foreground uppercase font-semibold">
                        <th className="py-2.5 px-3 w-10 text-center text-muted-foreground/60">#</th>
                        {previewData.columns.map((col) => (
                          <th key={col} className="py-2.5 px-3 whitespace-nowrap">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/30">
                      {previewData.rows.map((row, rIdx) => (
                        <tr key={rIdx} className="hover:bg-muted/20 transition-colors">
                          <td className="py-2 px-3 text-center text-muted-foreground/50 text-[10px]">
                            {rIdx + 1}
                          </td>
                          {previewData.columns.map((col) => (
                            <td key={col} className="py-2 px-3 whitespace-nowrap max-w-xs truncate text-foreground">
                              {row[col] === null ? (
                                <span className="text-muted-foreground/40 italic">null</span>
                              ) : (
                                String(row[col])
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="p-8 text-center text-muted-foreground text-xs">
                  No sample records returned for this table (table may be empty).
                </div>
              )}
            </div>
          </TabsContent>

          {/* 2. Columns Tab */}
          <TabsContent value="columns" className="space-y-4">
            <div className="rounded-lg border border-border/50 overflow-hidden shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm border-collapse">
                  <thead>
                    <tr className="border-b border-border/60 bg-muted/40 text-muted-foreground text-xs uppercase font-semibold">
                      <th className="py-3 px-4">Field / Column</th>
                      <th className="py-3 px-4">Data Type</th>
                      <th className="py-3 px-4">Nullable</th>
                      <th className="py-3 px-4">Default</th>
                      <th className="py-3 px-4">Samples / Preview</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/30">
                    {activeObject.columns?.map((col) => {
                      const isPK = col.primary_key;
                      const fkMatch = activeObject.foreign_keys?.find((fk) =>
                        fk.constrained_columns?.includes(col.name)
                      );

                      return (
                        <tr key={col.name} className="hover:bg-muted/20 transition-colors">
                          <td className="py-3 px-4 font-mono text-xs font-semibold">
                            <div className="flex items-center gap-2">
                              {col.name}
                              {isPK && (
                                <span
                                  className="text-[10px] bg-emerald-500/10 text-emerald-400 px-1.5 py-0.5 rounded flex items-center gap-0.5 border border-emerald-500/20"
                                  title="Primary Key"
                                >
                                  <Key className="h-2.5 w-2.5" />
                                  PK
                                </span>
                              )}
                              {fkMatch && (
                                <button
                                  type="button"
                                  onClick={() => onSelectObject(fkMatch.referred_table, "table")}
                                  className="text-[10px] bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded flex items-center gap-0.5 border border-amber-500/20 transition-colors"
                                  title={`Jump to ${fkMatch.referred_table}`}
                                >
                                  <LinkIcon className="h-2.5 w-2.5" />
                                  FK → {fkMatch.referred_table}
                                </button>
                              )}
                            </div>
                          </td>
                          <td className="py-3 px-4 font-mono text-xs text-muted-foreground">
                            <span className="bg-muted px-2 py-0.5 rounded text-[11px]">
                              {col.type}
                            </span>
                          </td>
                          <td className="py-3 px-4 text-xs">
                            {col.nullable ? (
                              <span className="text-muted-foreground flex items-center gap-1">
                                <CheckCircle2 className="h-3 w-3 text-emerald-500/70" />
                                Nullable
                              </span>
                            ) : (
                              <span className="text-foreground font-medium flex items-center gap-1">
                                <XCircle className="h-3 w-3 text-amber-500/70" />
                                NOT NULL
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-xs font-mono text-muted-foreground">
                            {col.default || "—"}
                          </td>
                          <td className="py-3 px-4 text-xs space-y-1">
                            {col.date_range && (
                              <div className="flex items-center gap-1 text-sky-400 font-mono text-[11px]">
                                <Calendar className="h-3 w-3" />
                                {col.date_range}
                              </div>
                            )}
                            {col.samples && col.samples.length > 0 && (
                              <div className="flex flex-wrap gap-1">
                                {col.samples.map((s, idx) => (
                                  <span
                                    key={idx}
                                    className="bg-secondary text-secondary-foreground px-1.5 py-0.5 rounded font-mono text-[10px] truncate max-w-[140px]"
                                  >
                                    {s}
                                  </span>
                                ))}
                              </div>
                            )}
                            {!col.date_range && (!col.samples || col.samples.length === 0) && (
                              <span className="text-muted-foreground/50 text-[11px]">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </TabsContent>

          {/* 3. Foreign Keys Tab */}
          <TabsContent value="foreign-keys" className="space-y-3">
            {activeObject.foreign_keys?.length > 0 ? (
              <div className="grid gap-3">
                {activeObject.foreign_keys.map((fk, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-lg border border-border/50 bg-muted/10 flex items-center justify-between"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 font-mono text-sm font-medium">
                        <span>{fk.constrained_columns?.join(", ")}</span>
                        <span className="text-muted-foreground">→</span>
                        <span className="text-amber-400 font-bold">{fk.referred_table}</span>
                        <span className="text-muted-foreground">({fk.referred_columns?.join(", ")})</span>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Relational reference mapping to target primary keys.
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => onSelectObject(fk.referred_table, "table")}
                      className="gap-1 text-xs text-primary"
                    >
                      Inspect Table
                      <ExternalLink className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 text-center border border-dashed border-border/60 rounded-lg text-muted-foreground text-sm">
                No foreign key constraints mapped for <strong>{activeObject.name}</strong>.
              </div>
            )}
          </TabsContent>

          {/* 4. Indexes Tab */}
          <TabsContent value="indexes" className="space-y-3">
            {activeObject.indexes?.length > 0 ? (
              <div className="grid gap-3">
                {activeObject.indexes.map((idx, i) => (
                  <div
                    key={i}
                    className="p-4 rounded-lg border border-border/50 bg-muted/10 flex items-center justify-between"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-semibold">{idx.name || `Index #${i + 1}`}</span>
                        {idx.unique && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                            UNIQUE
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground font-mono">
                        Indexed Columns: [{idx.columns?.join(", ")}]
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 text-center border border-dashed border-border/60 rounded-lg text-muted-foreground text-sm">
                No secondary indexes mapped for <strong>{activeObject.name}</strong>.
              </div>
            )}
          </TabsContent>

          {/* 5. Constraints Tab */}
          <TabsContent value="constraints" className="space-y-3">
            {activeObject.constraints?.length > 0 ? (
              <div className="grid gap-3">
                {activeObject.constraints.map((c, i) => (
                  <div
                    key={i}
                    className="p-4 rounded-lg border border-border/50 bg-muted/10 space-y-1"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-semibold">{c.name || `Constraint #${i + 1}`}</span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 uppercase">
                        {c.type}
                      </span>
                    </div>
                    {c.columns?.length > 0 && (
                      <p className="text-xs text-muted-foreground font-mono">
                        Target Columns: [{c.columns.join(", ")}]
                      </p>
                    )}
                    {c.definition && (
                      <p className="text-xs font-mono text-sky-300 mt-1 bg-black/30 p-2 rounded">
                        {c.definition}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 text-center border border-dashed border-border/60 rounded-lg text-muted-foreground text-sm">
                No explicit Check or Unique constraints declared for <strong>{activeObject.name}</strong>.
              </div>
            )}
          </TabsContent>

          {/* 6. Definition / Code Tab */}
          <TabsContent value="definition" className="space-y-3">
            <div className="flex justify-end mb-2">
              <Button size="sm" variant="outline" onClick={copySqlDefinition} className="gap-1.5 text-xs">
                {copiedSchema ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Code className="h-3.5 w-3.5" />}
                {copiedSchema ? "Copied SQL" : "Copy SQL Definition"}
              </Button>
            </div>
            <div className="p-4 rounded-lg bg-black/50 border border-border/50 font-mono text-xs text-sky-300 leading-relaxed overflow-x-auto whitespace-pre-wrap">
              {activeObject.definition || `-- Table: ${activeObject.name}\n-- Total Columns: ${activeObject.columns?.length || 0}\n\nSELECT * FROM ${activeObject.name} LIMIT 100;`}
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
