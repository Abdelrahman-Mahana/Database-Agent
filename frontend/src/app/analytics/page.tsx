"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BarChart3, Database, Sparkles, TrendingUp, Activity, RefreshCw } from "lucide-react";
import { useAnalytics } from "@/components/features/analytics/useAnalytics";
import { AnalyticsKpiCards } from "@/components/features/analytics/AnalyticsKpiCards";
import { AnalyticsDataProfilingTab } from "@/components/features/analytics/AnalyticsDataProfilingTab";
import { AnalyticsTelemetryTab } from "@/components/features/analytics/AnalyticsTelemetryTab";
import { AnalyticsTableProfilerTab } from "@/components/features/analytics/AnalyticsTableProfilerTab";

export default function AnalyticsPage() {
  const analytics = useAnalytics();
  const {
    schemaData,
    evalStats,
    evalHistory,
    tables,
    currentTable,
    columnTypeDistribution,
    totalColumns,
    totalForeignKeys,
    setSelectedTableName,
    chartType,
    setChartType,
    profileSuccessMsg,
    profileTableMutation,
    handleAskInChat,
    handleProfileTable
  } = analytics;

  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-full space-y-6 overflow-y-auto pr-1">
      {/* Top Banner Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/40 pb-5">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2.5">
            <BarChart3 className="h-7 w-7 text-primary" />
            Database Analytics & AI Evaluation
          </h2>
          <p className="text-muted-foreground text-sm mt-1">
            Real-time schema telemetry, AI model quality scoring, latency distributions, and live table data profiling for <strong>{schemaData?.database_name || "Connected Database"}</strong>.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button 
            onClick={() => handleAskInChat(`Provide a comprehensive statistical summary and data quality audit of ${currentTable?.name || 'the database'}`)}
            className="gap-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow"
          >
            <Sparkles className="h-4 w-4" />
            Ask AI for Deep Insights
          </Button>
        </div>
      </div>

      {/* AI Evaluation Framework Metrics Bar */}
      <AnalyticsKpiCards evalStats={evalStats} />

      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        {/* We can put other small cards here if needed, but Total Schema Footprint is standalone */}
        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Total Schema Footprint</CardTitle>
            <Database className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{tables.length} Tables</div>
            <p className="text-xs text-muted-foreground mt-1">{totalColumns} Columns • {totalForeignKeys} FKs</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Tabs Navigation */}
      <Tabs defaultValue="visualizer" className="w-full">
        <TabsList className="grid w-full grid-cols-3 max-w-2xl mb-6 h-10">
          <TabsTrigger value="visualizer" className="flex items-center gap-2 text-xs">
            <TrendingUp className="h-4 w-4 text-primary" />
            Data Profiling
          </TabsTrigger>
          <TabsTrigger value="evaluation-stream" className="flex items-center gap-2 text-xs">
            <Activity className="h-4 w-4 text-sky-400" />
            AI Telemetry
          </TabsTrigger>
          <TabsTrigger value="table-profiler" className="flex items-center gap-2 text-xs">
            <RefreshCw className="h-4 w-4 text-emerald-400" />
            Table Profiler
          </TabsTrigger>
        </TabsList>

        <TabsContent value="visualizer" className="space-y-6">
          <AnalyticsDataProfilingTab 
            tables={tables}
            currentTable={currentTable}
            setSelectedTableName={setSelectedTableName}
            handleProfileTable={handleProfileTable}
            profileTableMutation={profileTableMutation}
            profileSuccessMsg={profileSuccessMsg}
            schemaData={schemaData}
            chartType={chartType}
            setChartType={setChartType}
            columnTypeDistribution={columnTypeDistribution}
            handleAskInChat={handleAskInChat}
          />
        </TabsContent>

        <TabsContent value="evaluation-stream" className="space-y-4">
          <AnalyticsTelemetryTab evalHistory={evalHistory} />
        </TabsContent>

        <TabsContent value="table-profiler" className="space-y-4">
          <AnalyticsTableProfilerTab 
            tables={tables}
            handleProfileTable={handleProfileTable}
            profileTableMutation={profileTableMutation}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
