"use client";

import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { apiClient } from "@/services/api";
import { SchemaResponse, BaseDBObject } from "@/types/api";
import { useAppStore } from "@/store/useAppStore";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SchemaTreeView } from "@/components/explorer/SchemaTreeView";
import { ObjectDetailPanel } from "@/components/explorer/ObjectDetailPanel";
import { 
  Database, 
  TableProperties, 
  Search, 
  Hash, 
  Link as LinkIcon, 
  RotateCw, 
  Zap, 
  Layers, 
  FileCode2,
  ChevronRight
} from "lucide-react";

export default function DatabaseExplorer() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { activeDatabase } = useAppStore();
  
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedObjectName, setSelectedObjectName] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Fetch schema data
  const { data: schemaData, isLoading, isError, refetch } = useQuery<SchemaResponse>({
    queryKey: ["schema", activeDatabase],
    queryFn: async () => {
      const res = await apiClient.get("/schema");
      return res.data;
    },
  });

  const handleRefreshSchema = async () => {
    setIsRefreshing(true);
    try {
      const res = await apiClient.get("/schema?force_refresh=true");
      queryClient.setQueryData(["schema", activeDatabase], res.data);
    } catch (err) {
      console.error("Schema refresh error:", err);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Combine all database objects (tables, views, procedures, collections)
  const allObjects = useMemo<BaseDBObject[]>(() => {
    if (!schemaData) return [];
    const list: BaseDBObject[] = [];

    if (schemaData.tables) list.push(...schemaData.tables);
    if (schemaData.views) list.push(...schemaData.views);
    if (schemaData.procedures) list.push(...schemaData.procedures);
    if (schemaData.collections) list.push(...schemaData.collections);

    // Fall back to database_schema dictionary if tables array is not populated
    if (list.length === 0 && schemaData.database_schema) {
      Object.entries(schemaData.database_schema).forEach(([name, info]: [string, any]) => {
        list.push({
          name,
          qualified_name: name,
          catalog: schemaData.database_name || "main",
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
  }, [schemaData]);

  // Determine active object for detail panel
  const activeObject = useMemo(() => {
    if (!allObjects.length) return null;
    if (selectedObjectName) {
      const found = allObjects.find((obj) => obj.name.toLowerCase() === selectedObjectName.toLowerCase());
      if (found) return found;
    }
    return allObjects[0];
  }, [allObjects, selectedObjectName]);

  const handleSelectObject = (objectName: string, _objectType: string) => {
    setSelectedObjectName(objectName);
  };

  const handleAskAI = (tableName: string) => {
    const prompt = encodeURIComponent(`Summarize structure and query examples from ${tableName}`);
    router.push(`/chat?prompt=${prompt}`);
  };

  if (isLoading) {
    return (
      <div className="flex-1 space-y-6 animate-pulse p-2">
        <div className="h-10 bg-muted/40 rounded-lg w-1/3" />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 bg-muted/30 rounded-xl border border-border/40" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 h-96">
          <div className="lg:col-span-4 bg-muted/20 rounded-xl border border-border/40" />
          <div className="lg:col-span-8 bg-muted/20 rounded-xl border border-border/40" />
        </div>
      </div>
    );
  }

  if (isError || !allObjects.length) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-12 text-center space-y-4">
        <div className="h-16 w-16 rounded-full bg-destructive/10 text-destructive flex items-center justify-center">
          <Database className="h-8 w-8" />
        </div>
        <h2 className="text-2xl font-bold tracking-tight">No Active Schema Discovered</h2>
        <p className="text-muted-foreground max-w-md">
          Connect to a database (PostgreSQL, MySQL, SQL Server, SQLite, MongoDB) to inspect hierarchical schemas, columns, indexes, and relationships.
        </p>
        <Button onClick={() => router.push("/connect")} className="gap-2 shadow">
          <Database className="h-4 w-4" />
          Connect Database
        </Button>
      </div>
    );
  }

  const summary = schemaData?.summary;
  const totalCols = summary?.columns ?? allObjects.reduce((acc, obj) => acc + (obj.columns?.length || 0), 0);
  const totalFKs = summary?.foreign_keys ?? allObjects.reduce((acc, obj) => acc + (obj.foreign_keys?.length || 0), 0);

  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-full space-y-6 overflow-y-auto pr-1">
      {/* Top Banner Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/40 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-3xl font-bold tracking-tight">Database Explorer</h2>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary/10 text-primary border border-primary/20 uppercase">
              {schemaData?.database_type || "SQL"}
            </span>
            {schemaData?.cache_hit ? (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                <Zap className="h-3 w-3" /> Cache Hit
              </span>
            ) : (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                Live Introspection
              </span>
            )}
          </div>
          <p className="text-muted-foreground text-sm mt-1">
            Hierarchical schema introspection, column definitions, foreign keys, indexes, and constraints.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshSchema}
            disabled={isRefreshing}
            className="gap-2 text-xs"
          >
            <RotateCw className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`} />
            Refresh Schema
          </Button>

          <Button variant="secondary" size="sm" onClick={() => router.push("/connect")} className="gap-2 text-xs">
            <Database className="h-3.5 w-3.5" />
            {schemaData?.database_name || "Active DB"}
          </Button>
        </div>
      </div>

      {/* KPI Metrics Bar */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Database</CardTitle>
            <Database className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold truncate">{schemaData?.database_name || "Connected"}</div>
            <p className="text-xs text-muted-foreground mt-0.5 truncate">{schemaData?.database_url}</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Objects</CardTitle>
            <TableProperties className="h-4 w-4 text-sky-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">{allObjects.length}</div>
            <p className="text-xs text-muted-foreground mt-0.5">Tables, views & collections</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Columns / Fields</CardTitle>
            <Hash className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">{totalCols}</div>
            <p className="text-xs text-muted-foreground mt-0.5">Across all schema objects</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Relationships</CardTitle>
            <LinkIcon className="h-4 w-4 text-amber-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">{totalFKs}</div>
            <p className="text-xs text-muted-foreground mt-0.5">Foreign key constraints</p>
          </CardContent>
        </Card>
      </div>

      {/* Master-Detail Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Schema Hierarchy Tree */}
        <Card className="lg:col-span-4 border-border/60 shadow-sm flex flex-col max-h-[780px]">
          <CardHeader className="p-4 border-b border-border/40 space-y-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Layers className="h-4 w-4 text-primary" />
                Schema Objects Hierarchy
              </CardTitle>
              <span className="text-xs text-muted-foreground font-mono bg-muted px-2 py-0.5 rounded-full">
                {allObjects.length}
              </span>
            </div>

            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Search objects or columns..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 h-9 text-xs"
              />
            </div>
          </CardHeader>

          <CardContent className="p-2 overflow-y-auto flex-1">
            <SchemaTreeView
              tree={schemaData?.schema_tree || []}
              allObjects={allObjects}
              selectedObjectName={activeObject?.name || null}
              onSelectObject={handleSelectObject}
              searchQuery={searchQuery}
            />
          </CardContent>
        </Card>

        {/* Right Column: Detailed Inspector Workspace */}
        <div className="lg:col-span-8">
          <ObjectDetailPanel
            activeObject={activeObject}
            onSelectObject={handleSelectObject}
            onAskAI={handleAskAI}
          />
        </div>
      </div>
    </div>
  );
}
