/* eslint-disable @typescript-eslint/no-explicit-any */

import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Filter, Table as TableIcon, RefreshCw, TrendingUp, BarChart3, LineChart as LineIcon, PieChart as PieIcon, CheckCircle2, ArrowRight } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, XAxis, YAxis, Tooltip, Legend, CartesianGrid } from "recharts";
import { SchemaResponse } from "@/types/api";

const CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#6366f1'];

interface AnalyticsDataProfilingTabProps {
  tables: any[];
  currentTable: any;
  setSelectedTableName: (name: string) => void;
  handleProfileTable: (name: string) => void;
  profileTableMutation: any;
  profileSuccessMsg: string | null;
  schemaData?: SchemaResponse;
  chartType: "bar" | "line" | "pie";
  setChartType: (type: "bar" | "line" | "pie") => void;
  columnTypeDistribution: any[];
  handleAskInChat: (prompt: string) => void;
}

/**
 * Data Profiling Tab Component
 * 
 * Renders the table selection list, column breakdown, and a dynamic chart (Bar/Line/Pie)
 * showing the distribution of column types across the database.
 */
export function AnalyticsDataProfilingTab({
  tables,
  currentTable,
  setSelectedTableName,
  handleProfileTable,
  profileTableMutation,
  profileSuccessMsg,
  schemaData,
  chartType,
  setChartType,
  columnTypeDistribution,
  handleAskInChat
}: AnalyticsDataProfilingTabProps) {
  return (
    <div className="grid gap-6 grid-cols-1 lg:grid-cols-3">
      {/* Table Selector */}
      <Card className="lg:col-span-1 border-border/60 flex flex-col justify-between">
        <CardHeader>
          <CardTitle className="text-base font-bold flex items-center gap-2">
            <Filter className="h-4 w-4 text-primary" />
            Select Table to Inspect
          </CardTitle>
          <CardDescription>Choose a table to inspect column metrics and types.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 flex-1">
          <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
            {tables.map((t) => (
              <button
                key={t.name}
                type="button"
                onClick={() => setSelectedTableName(t.name)}
                className={`w-full p-3 rounded-xl border text-left transition-all flex items-center justify-between ${
                  (currentTable?.name === t.name)
                    ? "border-primary bg-primary/10 text-foreground font-semibold shadow-sm"
                    : "border-border/50 bg-card/40 hover:bg-muted/30 text-muted-foreground"
                }`}
              >
                <div className="flex items-center gap-2.5 truncate">
                  <TableIcon className="h-4 w-4 text-primary shrink-0" />
                  <span className="truncate text-xs font-mono">{t.name}</span>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-muted font-mono shrink-0">
                  {t.columns?.length || 0} cols
                </span>
              </button>
            ))}
          </div>

          {currentTable && (
            <div className="pt-4 border-t border-border/40 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Columns Breakdown</h4>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleProfileTable(currentTable.name)}
                  disabled={profileTableMutation.isPending}
                  className="h-7 px-2 text-[11px] gap-1 text-primary border-primary/30 hover:bg-primary/10"
                >
                  <RefreshCw className={`h-3 w-3 ${profileTableMutation.isPending ? "animate-spin" : ""}`} />
                  Profile Table
                </Button>
              </div>
              {profileSuccessMsg && (
                <p className="text-[11px] text-emerald-400 bg-emerald-500/10 p-2 rounded border border-emerald-500/20">{profileSuccessMsg}</p>
              )}
              <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                {currentTable.columns?.map((c: any) => (
                  <div key={c.name} className="flex items-center justify-between text-xs p-2 rounded-lg bg-muted/20 border border-border/30">
                    <span className="font-mono text-foreground font-medium truncate">{c.name}</span>
                    <span className="text-[10px] font-mono text-muted-foreground uppercase">{c.type}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dynamic Visualizations */}
      <Card className="lg:col-span-2 border-border/60 flex flex-col justify-between">
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <div>
            <CardTitle className="text-base font-bold flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-emerald-500" />
              Schema Column Type Distribution
            </CardTitle>
            <CardDescription>
              Aggregated data types count across all {tables.length} tables in {schemaData?.database_name || "database"}.
            </CardDescription>
          </div>
          
          <div className="flex items-center gap-1 bg-muted/40 p-1 rounded-lg border border-border/40">
            <button
              type="button"
              onClick={() => setChartType("bar")}
              className={`p-1.5 rounded-md text-xs transition-colors ${chartType === "bar" ? "bg-primary text-primary-foreground shadow" : "text-muted-foreground hover:text-foreground"}`}
              title="Bar Chart"
            >
              <BarChart3 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setChartType("line")}
              className={`p-1.5 rounded-md text-xs transition-colors ${chartType === "line" ? "bg-primary text-primary-foreground shadow" : "text-muted-foreground hover:text-foreground"}`}
              title="Line Chart"
            >
              <LineIcon className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setChartType("pie")}
              className={`p-1.5 rounded-md text-xs transition-colors ${chartType === "pie" ? "bg-primary text-primary-foreground shadow" : "text-muted-foreground hover:text-foreground"}`}
              title="Pie Chart"
            >
              <PieIcon className="h-4 w-4" />
            </button>
          </div>
        </CardHeader>

        <CardContent className="p-4 pt-0 flex-1">
          <div className="h-72 w-full pt-4">
            <ResponsiveContainer width="100%" height="100%">
              {chartType === "bar" ? (
                <BarChart data={columnTypeDistribution} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                  <XAxis dataKey="name" stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
                  <Tooltip 
                    contentStyle={{ backgroundColor: "#18181b", borderColor: "#27272a", borderRadius: "8px", fontSize: "12px", color: "#fff" }}
                  />
                  <Bar dataKey="count" fill="#3b82f6" radius={[6, 6, 0, 0]}>
                    {columnTypeDistribution.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              ) : chartType === "line" ? (
                <LineChart data={columnTypeDistribution} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                  <XAxis dataKey="name" stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
                  <Tooltip 
                    contentStyle={{ backgroundColor: "#18181b", borderColor: "#27272a", borderRadius: "8px", fontSize: "12px", color: "#fff" }}
                  />
                  <Line type="monotone" dataKey="count" stroke="#10b981" strokeWidth={2.5} dot={{ r: 4 }} />
                </LineChart>
              ) : (
                <PieChart>
                  <Pie
                    data={columnTypeDistribution}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={90}
                    paddingAngle={4}
                    dataKey="count"
                  >
                    {columnTypeDistribution.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip 
                    contentStyle={{ backgroundColor: "#18181b", borderColor: "#27272a", borderRadius: "8px", fontSize: "12px", color: "#fff" }}
                  />
                  <Legend wrapperStyle={{ fontSize: "11px" }} />
                </PieChart>
              )}
            </ResponsiveContainer>
          </div>
        </CardContent>

        <CardFooter className="p-4 border-t border-border/30 flex items-center justify-between bg-muted/10">
          <span className="text-xs text-muted-foreground flex items-center gap-1.5">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
            Showing {columnTypeDistribution.length} distinct column types
          </span>
          <Button 
            size="sm" 
            variant="secondary"
            onClick={() => handleAskInChat(`Show detailed breakdown and distribution for table ${currentTable?.name}`)}
            className="gap-1.5 text-xs text-primary"
          >
            Analyze in Chat
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
