/* eslint-disable @typescript-eslint/no-explicit-any */

import { Database, TableProperties, Hash, Zap } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SchemaResponse, BaseDBObject } from "@/types/api";

interface DashboardKpiCardsProps {
  dbName: string;
  schema?: SchemaResponse;
  allObjects: BaseDBObject[];
  tablesCount: number;
  viewsCount: number;
  collectionsCount: number;
  totalColumns: number;
  totalForeignKeys: number;
  totalIndexes: number;
  totalConstraints: number;
  health?: any;
}

/**
 * Dashboard KPI Cards Component
 * 
 * Displays 4 critical KPI metrics at the top of the main dashboard:
 * 1. Active Database Info
 * 2. Total Schema Objects (Tables, Views, etc.)
 * 3. Total Columns & Constraints
 * 4. LLM & System Health Status
 */
export function DashboardKpiCards({
  dbName,
  schema,
  allObjects,
  tablesCount,
  viewsCount,
  collectionsCount,
  totalColumns,
  totalForeignKeys,
  totalIndexes,
  totalConstraints,
  health
}: DashboardKpiCardsProps) {
  return (
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
  );
}
