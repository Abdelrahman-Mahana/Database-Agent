"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  TableProperties, 
  Key, 
  Link as LinkIcon, 
  Layers, 
  FileText, 
  Sparkles, 
  CheckCircle2, 
  XCircle, 
  Calendar, 
  ExternalLink,
  ShieldAlert,
  Code
} from "lucide-react";
import { BaseDBObject } from "@/types/api";

interface ObjectDetailPanelProps {
  activeObject: BaseDBObject | null;
  onSelectObject: (name: string, type: string) => void;
  onAskAI: (name: string) => void;
}

export function ObjectDetailPanel({
  activeObject,
  onSelectObject,
  onAskAI,
}: ObjectDetailPanelProps) {
  if (!activeObject) {
    return (
      <Card className="border-border/60 p-12 text-center text-muted-foreground shadow-sm">
        Select a database object from the tree on the left to inspect detailed schema definitions.
      </Card>
    );
  }

  const isCollection = activeObject.object_type === "collection";
  const isView = activeObject.object_type === "view";
  const isProcedure = activeObject.object_type === "procedure";

  return (
    <Card className="border-border/60 shadow-sm">
      {/* Top Inspector Header */}
      <CardHeader className="p-6 border-b border-border/40 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-2xl font-bold tracking-tight">{activeObject.name}</h3>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary/10 text-primary uppercase border border-primary/20">
              {activeObject.object_type}
            </span>
            {activeObject.primary_key && activeObject.primary_key.length > 0 && (
              <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                <Key className="h-3 w-3" />
                PK: {activeObject.primary_key.join(", ")}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1 font-mono">
            {activeObject.qualified_name}
          </p>
        </div>

        <Button
          size="sm"
          onClick={() => onAskAI(activeObject.name)}
          className="gap-2 bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white shadow"
        >
          <Sparkles className="h-3.5 w-3.5" />
          Ask AI About {activeObject.name}
        </Button>
      </CardHeader>

      <CardContent className="p-6">
        <Tabs defaultValue="columns" className="w-full">
          <TabsList className="grid w-full grid-cols-5 mb-6">
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
              Definition / SQL
            </TabsTrigger>
          </TabsList>

          {/* 1. Columns Tab */}
          <TabsContent value="columns" className="space-y-4">
            <div className="rounded-lg border border-border/50 overflow-hidden">
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
                                <span
                                  className="text-[10px] bg-amber-500/10 text-amber-400 px-1.5 py-0.5 rounded flex items-center gap-0.5 border border-amber-500/20"
                                  title={`FK to ${fkMatch.referred_table}`}
                                >
                                  <LinkIcon className="h-2.5 w-2.5" />
                                  FK
                                </span>
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

          {/* 2. Foreign Keys Tab */}
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

          {/* 3. Indexes Tab */}
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

          {/* 4. Constraints Tab */}
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

          {/* 5. Definition / Code Tab */}
          <TabsContent value="definition" className="space-y-3">
            <div className="p-4 rounded-lg bg-black/50 border border-border/50 font-mono text-xs text-sky-300 leading-relaxed overflow-x-auto whitespace-pre-wrap">
              {activeObject.definition || "No custom view or stored procedure SQL definition available."}
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
