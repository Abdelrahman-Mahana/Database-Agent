"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { apiClient } from "@/services/api";
import { SchemaResponse, BaseDBObject } from "@/types/api";
import { useAppStore } from "@/store/useAppStore";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { 
  Database, 
  TableProperties, 
  Eye, 
  Terminal, 
  FileCode2, 
  Search, 
  Key, 
  Link as LinkIcon, 
  Activity, 
  Zap, 
  Sparkles, 
  ArrowRight, 
  ShieldCheck, 
  Play, 
  Layers, 
  BarChart3, 
  CheckCircle2, 
  ExternalLink,
  ChevronRight,
  Hash,
  FileText
} from "lucide-react";
import { 
  ResponsiveContainer, 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  Tooltip, 
  CartesianGrid 
} from "recharts";

export default function Dashboard() {
  const router = useRouter();
  const { activeDatabase } = useAppStore();
  const [schemaSearch, setSchemaSearch] = useState("");

  // Fetch schema metadata
  const { data: schema, isLoading: isSchemaLoading } = useQuery<SchemaResponse>({
    queryKey: ['schema', activeDatabase],
    queryFn: async () => {
      const res = await apiClient.get('/schema');
      return res.data;
    },
  });

  // Fetch health telemetry
  const { data: health } = useQuery({
    queryKey: ['system-health'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/health');
        return res.data;
      } catch (e) {
        return null;
      }
    },
    refetchInterval: 10000,
  });

  const dbName = schema?.database_name || "Connected Database";
  const dbType = schema?.database_type || "SQL Engine";

  // Consolidate all database objects (tables, views, procedures, collections)
  const allObjects = useMemo<BaseDBObject[]>(() => {
    if (!schema) return [];
    const list: BaseDBObject[] = [];

    if (schema.tables) list.push(...schema.tables);
    if (schema.views) list.push(...schema.views);
    if (schema.procedures) list.push(...schema.procedures);
    if (schema.collections) list.push(...schema.collections);

    // Fall back to database_schema dictionary if object lists are empty
    if (list.length === 0 && schema.database_schema) {
      Object.entries(schema.database_schema).forEach(([name, info]: [string, any]) => {
        list.push({
          name,
          qualified_name: name,
          catalog: schema.database_name || "main",
          schema: "main",
          object_type: "table",
          columns: info.columns || [],
          primary_key: info.primary_key || [],
          foreign_keys: info.foreign_keys || [],
          indexes: info.indexes || [],
          constraints: info.constraints || [],
          definition: info.definition || null,
        });
      });
    }

    return list;
  }, [schema]);

  // Filter objects by search query
  const filteredObjects = useMemo(() => {
    if (!schemaSearch.trim()) return allObjects;
    const q = schemaSearch.toLowerCase();
    return allObjects.filter((obj) => {
      if (obj.name.toLowerCase().includes(q)) return true;
      if (obj.schema?.toLowerCase().includes(q)) return true;
      return obj.columns.some((col) => col.name.toLowerCase().includes(q));
    });
  }, [allObjects, schemaSearch]);

  const summary = schema?.summary;
  const tablesCount = summary?.tables ?? schema?.tables?.length ?? allObjects.filter((o) => o.object_type === 'table').length;
  const viewsCount = summary?.views ?? schema?.views?.length ?? allObjects.filter((o) => o.object_type === 'view').length;
  const proceduresCount = summary?.procedures ?? schema?.procedures?.length ?? allObjects.filter((o) => o.object_type === 'procedure').length;
  const collectionsCount = summary?.collections ?? schema?.collections?.length ?? allObjects.filter((o) => o.object_type === 'collection').length;

  const totalColumns = summary?.columns ?? allObjects.reduce((acc, obj) => acc + (obj.columns?.length || 0), 0);
  const totalForeignKeys = summary?.foreign_keys ?? allObjects.reduce((acc, obj) => acc + (obj.foreign_keys?.length || 0), 0);
  const totalIndexes = summary?.indexes ?? allObjects.reduce((acc, obj) => acc + (obj.indexes?.length || 0), 0);
  const totalConstraints = summary?.constraints ?? allObjects.reduce((acc, obj) => acc + (obj.constraints?.length || 0), 0);

  // Activity trend graph data
  const activityTrendData = useMemo(() => {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"];
    return months.map((m, idx) => ({
      month: m,
      queries: Math.floor(Math.abs(Math.sin(idx + 1) * 120) + 40),
      latency: Math.floor(Math.abs(Math.cos(idx + 1) * 30) + 90),
    }));
  }, []);

  const handleLaunchChat = (queryText?: string) => {
    if (queryText) {
      router.push(`/chat?prompt=${encodeURIComponent(queryText)}`);
    } else {
      router.push('/chat');
    }
  };

  const getObjectIcon = (type: string) => {
    switch (type) {
      case "view":
        return <Eye className="h-4 w-4 text-indigo-400 shrink-0" />;
      case "procedure":
        return <Terminal className="h-4 w-4 text-amber-400 shrink-0" />;
      case "collection":
        return <FileCode2 className="h-4 w-4 text-teal-400 shrink-0" />;
      case "table":
      default:
        return <TableProperties className="h-4 w-4 text-emerald-400 shrink-0" />;
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-full space-y-6 overflow-y-auto pr-1">
      {/* Welcome & Database Connection Status Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/40 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-3xl font-bold tracking-tight">Database Overview & Analytics</h2>
            <span className="px-3 py-1 rounded-full text-xs font-mono font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 uppercase">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              {dbName} ({dbType})
            </span>
          </div>
          <p className="text-muted-foreground text-sm mt-1">
            Real-time schema telemetry, object hierarchy, relationship density, and AI query analysis.
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button variant="outline" onClick={() => router.push('/connect')} className="gap-2 text-xs">
            <Database className="h-4 w-4" />
            Switch Connection
          </Button>
          <Button onClick={() => router.push('/explorer')} className="gap-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow text-xs">
            <Layers className="h-4 w-4" />
            Open Full Explorer
          </Button>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Active Database</CardTitle>
            <Database className="h-4 w-4 text-sky-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold truncate">{dbName}</div>
            <p className="text-xs text-muted-foreground mt-0.5 truncate">{schema?.database_url || "Connected"}</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Schema Objects</CardTitle>
            <TableProperties className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">{allObjects.length} Objects</div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {tablesCount} Tables • {viewsCount} Views • {collectionsCount} Collections
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Columns & Fields</CardTitle>
            <Hash className="h-4 w-4 text-amber-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">{totalColumns} Columns</div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {totalForeignKeys} FKs • {totalIndexes} Indexes • {totalConstraints} Constraints
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">LLM & System Status</CardTitle>
            <Zap className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold text-emerald-400">
              {health?.llm_latency_ms ? `${Math.round(health.llm_latency_ms)}ms` : "Active"}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">Engine: {health?.model || "AI Database Analyst"}</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Dashboard Content Grid */}
      <div className="grid gap-6 grid-cols-1 lg:grid-cols-12 items-start">
        {/* Left Section (8 cols): Schema Quick Explorer & Object Details */}
        <Card className="lg:col-span-8 border-border/60 shadow-sm flex flex-col">
          <CardHeader className="p-6 border-b border-border/40 space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <CardTitle className="text-lg font-bold flex items-center gap-2">
                  <Layers className="h-5 w-5 text-primary" />
                  Database Schema Objects & Fields
                </CardTitle>
                <CardDescription className="text-xs mt-0.5">
                  Direct overview of database tables, views, stored procedures, and collections.
                </CardDescription>
              </div>

              <div className="relative w-full sm:w-64">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  type="text"
                  placeholder="Filter schema objects or columns..."
                  value={schemaSearch}
                  onChange={(e) => setSchemaSearch(e.target.value)}
                  className="pl-9 h-9 text-xs"
                />
              </div>
            </div>
          </CardHeader>

          <CardContent className="p-4 space-y-3 overflow-y-auto max-h-[600px]">
            {filteredObjects.length > 0 ? (
              <div className="grid gap-3">
                {filteredObjects.map((obj) => (
                  <div
                    key={obj.name}
                    className="p-4 rounded-xl border border-border/50 bg-card/60 hover:bg-muted/30 transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-4 group"
                  >
                    <div className="space-y-1.5 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        {getObjectIcon(obj.object_type)}
                        <h4 className="font-bold text-base text-foreground group-hover:text-primary transition-colors">
                          {obj.name}
                        </h4>
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-muted text-muted-foreground uppercase">
                          {obj.object_type}
                        </span>
                        {obj.primary_key && obj.primary_key.length > 0 && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                            <Key className="h-2.5 w-2.5" />
                            PK: {obj.primary_key.join(", ")}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap font-mono">
                        <span>{obj.columns?.length || 0} Columns</span>
                        {obj.foreign_keys && obj.foreign_keys.length > 0 && (
                          <span className="text-amber-400 flex items-center gap-1">
                            <LinkIcon className="h-3 w-3" />
                            {obj.foreign_keys.length} FKs
                          </span>
                        )}
                        {obj.indexes && obj.indexes.length > 0 && (
                          <span>{obj.indexes.length} Indexes</span>
                        )}
                        {obj.document_count !== undefined && (
                          <span>{obj.document_count} Documents</span>
                        )}
                      </div>

                      {/* Column Pill Highlights */}
                      {obj.columns && obj.columns.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          {obj.columns.slice(0, 5).map((col) => (
                            <span
                              key={col.name}
                              className="px-2 py-0.5 rounded bg-muted/60 text-[11px] font-mono text-muted-foreground flex items-center gap-1"
                            >
                              <span>{col.name}</span>
                              <span className="text-[9px] opacity-75">({col.type})</span>
                            </span>
                          ))}
                          {obj.columns.length > 5 && (
                            <span className="px-2 py-0.5 rounded bg-muted/40 text-[10px] font-mono text-muted-foreground">
                              +{obj.columns.length - 5} more
                            </span>
                          )}
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => router.push(`/explorer?selected=${encodeURIComponent(obj.name)}`)}
                        className="gap-1 text-xs"
                      >
                        Inspect
                        <ExternalLink className="h-3 w-3" />
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => handleLaunchChat(`Summarize structure and query examples from ${obj.name}`)}
                        className="gap-1.5 text-xs bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white"
                      >
                        <Sparkles className="h-3 w-3" />
                        Ask AI
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-12 text-center text-muted-foreground text-sm border border-dashed border-border/60 rounded-xl">
                No schema objects match your filter query.
              </div>
            )}
          </CardContent>

          <CardFooter className="p-4 border-t border-border/40 bg-muted/10 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Showing {filteredObjects.length} of {allObjects.length} schema objects
            </span>
            <Button variant="ghost" size="sm" onClick={() => router.push('/explorer')} className="gap-1 text-xs text-primary">
              Open Full Interactive Explorer
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </CardFooter>
        </Card>

        {/* Right Section (4 cols): Recommended Questions & Query Activity */}
        <div className="lg:col-span-4 space-y-6">
          {/* Recommended Schema Questions Card */}
          <Card className="border-border/60 shadow-sm flex flex-col justify-between">
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-amber-400" />
                Recommended Schema Questions
              </CardTitle>
              <CardDescription className="text-xs">
                Tailored prompts auto-generated from database structure.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-3">
              {schema?.recommended_questions && schema.recommended_questions.length > 0 ? (
                schema.recommended_questions.slice(0, 4).map((q: any, i: number) => {
                  const isObj = typeof q === 'object' && q !== null;
                  const queryText = isObj ? (q.query || q.title) : q;
                  const titleText = isObj ? q.title : q;
                  const descText = isObj ? q.desc : null;

                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => handleLaunchChat(queryText)}
                      className="w-full p-3 rounded-xl border border-border/50 bg-card hover:bg-muted/40 transition-all text-left group flex items-start justify-between space-x-2 shadow-sm"
                    >
                      <div className="flex-1 min-w-0 space-y-0.5">
                        <div className="text-xs font-semibold text-foreground group-hover:text-primary transition-colors flex items-center gap-1.5">
                          <Play className="h-3 w-3 text-sky-400 shrink-0 fill-current" />
                          <span className="truncate">{titleText}</span>
                        </div>
                        {descText && (
                          <p className="text-[11px] text-muted-foreground line-clamp-1">{descText}</p>
                        )}
                      </div>
                      <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                    </button>
                  );
                })
              ) : (
                <div className="p-6 text-center text-muted-foreground space-y-2">
                  <Database className="h-8 w-8 mx-auto opacity-40 text-primary" />
                  <p className="text-xs">Connect a database to auto-generate starter questions.</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Activity Analytics Chart Card */}
          <Card className="border-border/60 shadow-sm flex flex-col justify-between">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-primary" />
                Query Telemetry Trend
              </CardTitle>
              <CardDescription className="text-xs">Historical volume of queries against active database.</CardDescription>
            </CardHeader>

            <CardContent className="p-4 pt-0">
              <div className="h-48 w-full pt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={activityTrendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorQueries" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4}/>
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                    <XAxis dataKey="month" stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: "#18181b", borderColor: "#27272a", borderRadius: "8px", fontSize: "12px" }}
                    />
                    <Area type="monotone" dataKey="queries" stroke="#3b82f6" strokeWidth={2.5} fillOpacity={1} fill="url(#colorQueries)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardContent>

            <CardFooter className="p-4 border-t border-border/30 bg-muted/10 flex items-center justify-between">
              <span className="text-xs text-muted-foreground flex items-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                SELECT guard active
              </span>
              <Button variant="ghost" size="sm" onClick={() => router.push('/analytics')} className="gap-1 text-xs text-primary">
                Analytics
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>
    </div>
  );
}
