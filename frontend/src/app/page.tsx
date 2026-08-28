"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { apiClient } from "@/services/api";
import { SchemaResponse, BaseDBObject } from "@/types/api";
import { useAppStore } from "@/store/useAppStore";
import { Button } from "@/components/ui/button";
import { Database, Layers } from "lucide-react";

import { DashboardKpiCards } from "@/components/features/dashboard/DashboardKpiCards";
import { DashboardSchemaExplorer } from "@/components/features/dashboard/DashboardSchemaExplorer";
import { DashboardSidebar } from "@/components/features/dashboard/DashboardSidebar";

/**
 * Main Dashboard Page Component
 * 
 * Assembles the dashboard view containing:
 * - High-level KPI Cards (Active DB, Objects, Columns, AI Status)
 * - Schema Explorer (Searchable grid of tables, views, etc.)
 * - Sidebar (AI Recommended Questions and Query Telemetry)
 * 
 * Data fetching is handled via React Query for optimal caching and polling.
 */
export default function Dashboard() {
  const router = useRouter();
  const { activeDatabase } = useAppStore();

  // Fetch schema metadata
  const { data: schema } = useQuery<SchemaResponse>({
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
      } catch {
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

  const summary = schema?.summary;
  const tablesCount = summary?.tables ?? schema?.tables?.length ?? allObjects.filter((o) => o.object_type === 'table').length;
  const viewsCount = summary?.views ?? schema?.views?.length ?? allObjects.filter((o) => o.object_type === 'view').length;
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

      <DashboardKpiCards 
        dbName={dbName}
        schema={schema}
        allObjects={allObjects}
        tablesCount={tablesCount}
        viewsCount={viewsCount}
        collectionsCount={collectionsCount}
        totalColumns={totalColumns}
        totalForeignKeys={totalForeignKeys}
        totalIndexes={totalIndexes}
        totalConstraints={totalConstraints}
        health={health}
      />

      {/* Main Dashboard Content Grid */}
      <div className="grid gap-6 grid-cols-1 lg:grid-cols-12 items-start">
        <DashboardSchemaExplorer allObjects={allObjects} />
        <DashboardSidebar schema={schema} activityTrendData={activityTrendData} />
      </div>
    </div>
  );
}
