"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/services/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  CodeXml, 
  Activity, 
  Cpu, 
  Zap, 
  ShieldCheck, 
  Layers, 
  BarChart3, 
  DollarSign, 
  RefreshCw, 
  CheckCircle2, 
  Play, 
  AlertCircle, 
  Sparkles, 
  Award, 
  Terminal,
  Download,
  Copy,
  Check,
  Search,
  Gauge
} from "lucide-react";

interface HealthData {
  status: string;
  llm_available: boolean;
  llm_configured?: boolean;
  llm_provider: string;
  ollama_available: boolean;
  model: string;
  llm_latency_ms?: number;
  pricing?: {
    prompt?: number;
    completion?: number;
  };
}

interface CostSummary {
  total_prompt_tokens?: number;
  total_completion_tokens?: number;
  total_tokens?: number;
  estimated_cost_usd?: number;
  requests_count?: number;
  by_analysis_type?: Record<string, number>;
}

interface RecentUsageRecord {
  timestamp?: number | string;
  model?: string;
  analysis_type?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  estimated_cost_usd?: number;
  session_id?: string;
}

interface DirectExecutionResult {
  success: boolean;
  sql: string;
  sanitized_sql?: string;
  columns?: string[];
  rows?: Record<string, any>[];
  row_count?: number;
  execution_time_ms?: number;
  plan?: string | null;
  dialect?: string;
  error?: string | null;
}

export default function ExecutionDetailsPage() {
  const [testSql, setTestSql] = useState("SELECT 1 AS id, 'Database Agent' AS tool_name, 100 AS accuracy_score;");
  const [guardResult, setGuardResult] = useState<any>(null);
  const [isGuarding, setIsGuarding] = useState(false);
  const [executionResult, setExecutionResult] = useState<DirectExecutionResult | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [resultFilter, setResultFilter] = useState("");
  const [copiedResults, setCopiedResults] = useState(false);
  const [copiedSql, setCopiedSql] = useState(false);
  const [maxRowsLimit, setMaxRowsLimit] = useState(100);

  // Quick SQL Templates
  const SQL_TEMPLATES = [
    { label: "Sample 10 Rows", query: "SELECT * FROM public.res_partner LIMIT 10;" },
    { label: "Count All Records", query: "SELECT COUNT(*) AS total_count FROM public.res_partner;" },
    { label: "Group & Aggregate", query: "SELECT state, COUNT(*) AS count FROM public.account_move GROUP BY state ORDER BY count DESC LIMIT 10;" },
    { label: "Safety Test (DROP)", query: "DROP TABLE public.account_move;" },
  ];

  const handleTestGuard = async () => {
    if (!testSql.trim()) return;
    setIsGuarding(true);
    try {
      const res = await apiClient.post('/stats/validate-sql', { query: testSql });
      setGuardResult(res.data);
    } catch (err: any) {
      setGuardResult({ valid: false, reason: err.message || "Error validating SQL", query_type: "error" });
    } finally {
      setIsGuarding(false);
    }
  };

  const handleRunInSandbox = async () => {
    if (!testSql.trim()) return;
    setIsExecuting(true);
    try {
      const res = await apiClient.post('/stats/execute-sql', {
        query: testSql,
        max_rows: maxRowsLimit,
        explain: true,
      });
      setExecutionResult(res.data);
    } catch (err: any) {
      setExecutionResult({
        success: false,
        sql: testSql,
        error: err.response?.data?.detail || err.message || "Execution error",
      });
    } finally {
      setIsExecuting(false);
    }
  };

  const handleCopyResults = () => {
    if (!executionResult?.rows) return;
    navigator.clipboard.writeText(JSON.stringify(executionResult.rows, null, 2));
    setCopiedResults(true);
    setTimeout(() => setCopiedResults(false), 2000);
  };

  const handleCopySql = (sqlText: string) => {
    navigator.clipboard.writeText(sqlText);
    setCopiedSql(true);
    setTimeout(() => setCopiedSql(false), 2000);
  };

  const exportResultsAsCsv = () => {
    if (!executionResult?.rows || executionResult.rows.length === 0) return;
    const cols = executionResult.columns || Object.keys(executionResult.rows[0]);
    const csvRows = [
      cols.join(","),
      ...executionResult.rows.map(row => 
        cols.map(c => `"${String(row[c] ?? "").replace(/"/g, '""')}"`).join(",")
      )
    ];
    const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `query_result_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const formatTimestamp = (ts?: number | string) => {
    if (!ts) return "Just now";
    const date = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
    return isNaN(date.getTime()) ? "Recent" : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  // Fetch health telemetry
  const { data: healthData, refetch: refetchHealth } = useQuery<HealthData>({
    queryKey: ['system-health'],
    queryFn: async () => {
      const res = await apiClient.get('/health');
      return res.data;
    },
    refetchInterval: 10000,
  });

  // Fetch cost summary stats
  const { data: costSummary, refetch: refetchCost } = useQuery<CostSummary>({
    queryKey: ['cost-summary'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/stats/cost');
        return res.data;
      } catch {
        return { estimated_cost_usd: 0, total_prompt_tokens: 0, total_completion_tokens: 0 };
      }
    },
    refetchInterval: 10000,
  });

  // Fetch recent request feed
  const { data: recentFeed = [], refetch: refetchRecent } = useQuery<RecentUsageRecord[]>({
    queryKey: ['cost-recent'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/stats/cost/recent?limit=25');
        return res.data;
      } catch {
        return [];
      }
    },
    refetchInterval: 10000,
  });

  // Fetch AI Evaluation Framework stats
  const { data: evalStats, refetch: refetchEval } = useQuery({
    queryKey: ['evaluation-stats'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/evaluation/stats');
        return res.data;
      } catch {
        return {
          sample_size: 0,
          avg_quality_score: 0,
          avg_confidence_score: 0,
          avg_latency_ms: 0,
          sql_success_rate_pct: 0,
          total_estimated_cost_usd: 0,
        };
      }
    },
    refetchInterval: 10000,
  });

  const handleRefreshAll = () => {
    refetchHealth();
    refetchCost();
    refetchRecent();
    refetchEval();
  };

  const totalTokens = (costSummary?.total_prompt_tokens || 0) + (costSummary?.total_completion_tokens || 0);

  // Filtered rows for execution result grid
  const filteredExecutionRows = useMemo(() => {
    if (!executionResult?.rows) return [];
    if (!resultFilter.trim()) return executionResult.rows;
    const q = resultFilter.toLowerCase();
    return executionResult.rows.filter(row =>
      Object.values(row).some(v => String(v).toLowerCase().includes(q))
    );
  }, [executionResult, resultFilter]);

  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-full space-y-6 overflow-y-auto pr-1">
      {/* Top Banner Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/40 pb-5">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2.5">
            <CodeXml className="h-7 w-7 text-primary" />
            Execution Studio & Telemetry
          </h2>
          <p className="text-muted-foreground text-sm mt-1">
            Safe direct query sandbox, AST SQL validation benchmark, LLM token metrics, and execution diagnostics.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={handleRefreshAll} className="gap-2 shrink-0">
          <RefreshCw className="h-4 w-4" />
          Refresh Telemetry
        </Button>
      </div>

      {/* Health & LLM Telemetry Banner */}
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="bg-card/60 backdrop-blur border-border/60 shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">System Status</CardTitle>
            <Activity className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 text-xl font-bold">
              <span className="h-3 w-3 rounded-full bg-emerald-500 animate-pulse" />
              {healthData?.status?.toUpperCase() || "ONLINE"}
            </div>
            <p className="text-xs text-muted-foreground mt-1">FastAPI Backend Operational</p>
          </CardContent>
        </Card>

        <Card className="bg-card/60 backdrop-blur border-border/60 shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Active LLM Model</CardTitle>
            <Cpu className="h-4 w-4 text-sky-500" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold truncate">{healthData?.model || "Groq / OpenAI Tier"}</div>
            <p className="text-xs text-muted-foreground mt-1 capitalize">Provider: {healthData?.llm_provider || "Standard"}</p>
          </CardContent>
        </Card>

        <Card className="bg-card/60 backdrop-blur border-border/60 shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Success Rate / Quality</CardTitle>
            <Zap className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">
              {evalStats?.sample_size ? `${evalStats.sql_success_rate_pct}%` : "100% (Ready)"}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Avg Latency: {evalStats?.avg_latency_ms ? `${Math.round(evalStats.avg_latency_ms)} ms` : "Instant"}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card/60 backdrop-blur border-border/60 shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Total Token Spend</CardTitle>
            <DollarSign className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">
              ${(costSummary?.estimated_cost_usd || 0).toFixed(4)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">{totalTokens.toLocaleString()} Total Tokens Logged</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Tabs Workspace */}
      <Tabs defaultValue="sandbox" className="w-full">
        <TabsList className="grid w-full grid-cols-4 max-w-2xl mb-6">
          <TabsTrigger value="sandbox" className="flex items-center gap-2 text-xs">
            <Play className="h-4 w-4 text-primary" />
            SQL Studio
          </TabsTrigger>
          <TabsTrigger value="pipeline" className="flex items-center gap-2 text-xs">
            <Layers className="h-4 w-4 text-sky-400" />
            Pipeline Flow
          </TabsTrigger>
          <TabsTrigger value="cost-feed" className="flex items-center gap-2 text-xs">
            <BarChart3 className="h-4 w-4 text-emerald-500" />
            Cost Feed ({recentFeed.length})
          </TabsTrigger>
          <TabsTrigger value="eval-telemetry" className="flex items-center gap-2 text-xs">
            <Award className="h-4 w-4 text-amber-500" />
            AI Evaluation
          </TabsTrigger>
        </TabsList>

        {/* 1. Interactive SQL Sandbox & Execution Studio Tab */}
        <TabsContent value="sandbox" className="space-y-6">
          <Card className="border-border/60 shadow-sm bg-card/60 backdrop-blur">
            <CardHeader className="p-6 border-b border-border/40">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-lg font-bold flex items-center gap-2">
                    <Terminal className="h-5 w-5 text-primary" />
                    SQL Execution Studio & Safety Testbench
                  </CardTitle>
                  <CardDescription>
                    Safely write, validate, and execute read-only queries with dialect transpilation and execution plan profiling.
                  </CardDescription>
                </div>

                {/* Row Limit Selector */}
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Max Rows:</span>
                  <select
                    value={maxRowsLimit}
                    onChange={(e) => setMaxRowsLimit(Number(e.target.value))}
                    className="h-8 rounded-md border border-input bg-card px-2 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    <option value={10}>10 rows</option>
                    <option value={50}>50 rows</option>
                    <option value={100}>100 rows</option>
                    <option value={500}>500 rows</option>
                  </select>
                </div>
              </div>

              {/* Quick Template Chips */}
              <div className="flex items-center gap-2 flex-wrap pt-3">
                <span className="text-xs font-semibold text-muted-foreground flex items-center gap-1">
                  <Sparkles className="h-3 w-3 text-primary" /> Templates:
                </span>
                {SQL_TEMPLATES.map((tmpl, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      setTestSql(tmpl.query);
                      setGuardResult(null);
                      setExecutionResult(null);
                    }}
                    className="text-[11px] px-2.5 py-1 rounded-full border border-border/60 bg-muted/40 hover:bg-primary/10 hover:border-primary/40 hover:text-primary transition-colors font-mono"
                  >
                    {tmpl.label}
                  </button>
                ))}
              </div>
            </CardHeader>

            <CardContent className="p-6 space-y-4">
              {/* SQL Input Area */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    SQL Statement
                  </label>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleCopySql(testSql)}
                    className="h-6 text-[11px] gap-1 text-muted-foreground hover:text-foreground"
                  >
                    {copiedSql ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                    {copiedSql ? "Copied" : "Copy SQL"}
                  </Button>
                </div>

                <textarea
                  value={testSql}
                  onChange={(e) => setTestSql(e.target.value)}
                  rows={4}
                  placeholder="Enter SQL statement (e.g., SELECT * FROM users LIMIT 10;)"
                  className="w-full rounded-md border border-input bg-muted/30 p-3 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring resize-y leading-relaxed"
                />
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-3 flex-wrap">
                <Button
                  onClick={handleRunInSandbox}
                  disabled={isExecuting || !testSql.trim()}
                  className="gap-2 bg-gradient-to-r from-primary to-blue-600 hover:from-primary/90 hover:to-blue-700 text-primary-foreground font-semibold shadow"
                >
                  {isExecuting ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
                  {isExecuting ? "Executing Query..." : "Execute Query"}
                </Button>

                <Button
                  onClick={handleTestGuard}
                  disabled={isGuarding || !testSql.trim()}
                  variant="outline"
                  className="gap-2 font-semibold"
                >
                  {isGuarding ? <RefreshCw className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4 text-emerald-400" />}
                  Verify AST Guard
                </Button>
              </div>

              {/* AST Guard Validation Banner */}
              {guardResult && (
                <div
                  className={`p-4 rounded-lg border text-xs font-mono space-y-2 ${
                    guardResult.valid
                      ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                      : "bg-destructive/10 border-destructive/30 text-destructive"
                  }`}
                >
                  <div className="flex items-center gap-2 font-bold text-sm">
                    {guardResult.valid ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <AlertCircle className="h-4 w-4 shrink-0" />}
                    {guardResult.valid ? "AST Security Validation Passed (Safe Query)" : "Validation Blocked"}
                  </div>
                  {guardResult.reason && <p className="text-foreground/90">{guardResult.reason}</p>}
                  {guardResult.sanitized_sql && (
                    <div className="bg-background/80 p-2.5 rounded border border-border/40 text-foreground">
                      <span className="text-[10px] text-muted-foreground block mb-1">Transpiled / Quoted SQL:</span>
                      <code>{guardResult.sanitized_sql}</code>
                    </div>
                  )}
                  {guardResult.dialect && (
                    <span className="inline-block px-2 py-0.5 rounded bg-muted text-muted-foreground text-[10px] uppercase">
                      Dialect: {guardResult.dialect}
                    </span>
                  )}
                </div>
              )}

              {/* Query Execution Results Section */}
              {executionResult && (
                <div className="space-y-4 pt-4 border-t border-border/40">
                  {/* Results Header & Metrics */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-muted/20 p-3.5 rounded-lg border border-border/40">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full ${
                        executionResult.success ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30" : "bg-destructive/15 text-destructive border border-destructive/30"
                      }`}>
                        {executionResult.success ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
                        {executionResult.success ? `Success (${executionResult.row_count} rows)` : "Execution Error"}
                      </span>

                      {executionResult.execution_time_ms !== undefined && (
                        <span className="text-xs text-muted-foreground font-mono flex items-center gap-1">
                          <Gauge className="h-3.5 w-3.5 text-sky-400" />
                          {executionResult.execution_time_ms} ms
                        </span>
                      )}

                      {executionResult.dialect && (
                        <span className="text-[11px] font-mono text-muted-foreground px-2 py-0.5 rounded bg-muted">
                          {executionResult.dialect.toUpperCase()}
                        </span>
                      )}
                    </div>

                    {/* Data Export & Filter Controls */}
                    {executionResult.success && executionResult.rows && executionResult.rows.length > 0 && (
                      <div className="flex items-center gap-2">
                        <div className="relative">
                          <Search className="h-3.5 w-3.5 absolute left-2.5 top-2.5 text-muted-foreground" />
                          <Input
                            placeholder="Filter rows..."
                            value={resultFilter}
                            onChange={(e) => setResultFilter(e.target.value)}
                            className="h-8 pl-8 text-xs font-mono w-40 bg-card"
                          />
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={exportResultsAsCsv}
                          className="h-8 text-xs gap-1"
                        >
                          <Download className="h-3.5 w-3.5" />
                          CSV
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={handleCopyResults}
                          className="h-8 text-xs gap-1"
                        >
                          {copiedResults ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                          JSON
                        </Button>
                      </div>
                    )}
                  </div>

                  {/* Error Message */}
                  {!executionResult.success && executionResult.error && (
                    <div className="p-4 rounded-lg border border-destructive/30 bg-destructive/10 text-destructive text-xs font-mono">
                      <p className="font-bold mb-1">Execution Failure:</p>
                      <pre className="whitespace-pre-wrap">{executionResult.error}</pre>
                    </div>
                  )}

                  {/* Execution Plan Note */}
                  {executionResult.plan && (
                    <div className="px-3.5 py-2 rounded bg-muted/40 border border-border/40 text-[11px] font-mono text-muted-foreground">
                      <span className="font-semibold text-foreground">Query Plan: </span>
                      {executionResult.plan}
                    </div>
                  )}

                  {/* Result Data Table */}
                  {executionResult.success && executionResult.rows && (
                    <div className="rounded-lg border border-border/50 overflow-hidden shadow-sm">
                      {filteredExecutionRows.length > 0 ? (
                        <div className="overflow-x-auto max-h-96">
                          <table className="w-full text-left text-xs border-collapse font-mono">
                            <thead className="sticky top-0 bg-muted/90 backdrop-blur z-10">
                              <tr className="border-b border-border/60 text-muted-foreground uppercase font-semibold">
                                <th className="py-2.5 px-3 w-12 text-center text-muted-foreground/60">#</th>
                                {(executionResult.columns || Object.keys(filteredExecutionRows[0])).map((col) => (
                                  <th key={col} className="py-2.5 px-3 whitespace-nowrap">
                                    {col}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-border/30">
                              {filteredExecutionRows.map((row, rIdx) => (
                                <tr key={rIdx} className="hover:bg-muted/30 transition-colors">
                                  <td className="py-2 px-3 text-center text-muted-foreground/50 text-[10px]">
                                    {rIdx + 1}
                                  </td>
                                  {(executionResult.columns || Object.keys(row)).map((col) => (
                                    <td key={col} className="py-2 px-3 whitespace-nowrap max-w-xs truncate text-foreground">
                                      {row[col] === null ? (
                                        <span className="text-muted-foreground/40 italic">null</span>
                                      ) : typeof row[col] === "boolean" ? (
                                        <span className={row[col] ? "text-emerald-400" : "text-amber-400"}>
                                          {String(row[col])}
                                        </span>
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
                          {resultFilter ? "No rows match your filter query." : "Query executed successfully with 0 rows returned."}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* 2. Agent Pipeline Architecture Tab */}
        <TabsContent value="pipeline" className="space-y-4">
          <Card className="border-border/60 shadow-sm bg-card/60 backdrop-blur">
            <CardHeader>
              <CardTitle className="text-lg font-bold flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-primary" />
                8-Step LangGraph Agent Architecture
              </CardTitle>
              <CardDescription>
                Visual step-by-step trace of how natural language prompts are validated, grounded in schema, executed, and synthesized into executive reports.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4 relative before:absolute before:left-[19px] before:top-3 before:bottom-3 before:w-0.5 before:bg-border/60">
                {[
                  {
                    step: "1",
                    name: "Semantic Router & Intent Parsing",
                    desc: "Classifies intents and extracts target metrics, grouping dimensions, temporal bounds, and filters from English/Arabic prompts.",
                    badge: "Bilingual NLP",
                    color: "text-sky-400 bg-sky-500/10 border-sky-500/20"
                  },
                  {
                    step: "2",
                    name: "Schema Grounding",
                    desc: "Identifies relevant tables and columns, expanding join relationships while pruning irrelevant data to minimize context window overhead.",
                    badge: "Graph Routing",
                    color: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20"
                  },
                  {
                    step: "3",
                    name: "SQL Generator",
                    desc: "Generates dialect-specific SQL candidates (PostgreSQL/SQLite/MySQL) using advanced self-consistency voting and reasoning.",
                    badge: "AST Verified",
                    color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                  },
                  {
                    step: "4",
                    name: "Cost & Safety Guard",
                    desc: "Validates AST to enforce read-only execution, prevent full-table scans, limit output rows, and mask PII data.",
                    badge: "Safety Guard",
                    color: "text-rose-400 bg-rose-500/10 border-rose-500/20"
                  },
                  {
                    step: "5",
                    name: "Database Execution",
                    desc: "Executes the validated query against the live database within strict timeout limits and resource constraints.",
                    badge: "Execution",
                    color: "text-blue-400 bg-blue-500/10 border-blue-500/20"
                  },
                  {
                    step: "6",
                    name: "Auto-Repair Loop",
                    desc: "Detects execution failures or syntax errors, routing back to the SQL Generator with precise error logs for self-correction.",
                    badge: "Self-Healing",
                    color: "text-amber-400 bg-amber-500/10 border-amber-500/20"
                  },
                  {
                    step: "7",
                    name: "Statistical Analytics Engine",
                    desc: "Runs deterministic analytics (trends, outliers, distributions, aggregations) on the raw result grid to extract deep insights.",
                    badge: "Analytics",
                    color: "text-purple-400 bg-purple-500/10 border-purple-500/20"
                  },
                  {
                    step: "8",
                    name: "Report Synthesizer",
                    desc: "Composes an executive, ChatGPT-style analytical report strictly grounded in facts, with dynamic charts and Markdown formatting.",
                    badge: "Report Writer",
                    color: "text-primary bg-primary/10 border-primary/20"
                  }
                ].map((st, idx) => (
                  <div key={idx} className="flex items-start gap-4 relative z-10">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-card border-2 border-border/80 font-bold text-xs shadow-sm">
                      {st.step}
                    </div>
                    <div className="flex-1 rounded-lg border border-border/50 bg-muted/20 p-3.5 shadow-sm">
                      <div className="flex items-center justify-between gap-2 flex-wrap mb-1">
                        <span className="font-semibold text-sm text-foreground">{st.name}</span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-mono border ${st.color}`}>
                          {st.badge}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">{st.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* 3. Cost & Token Feed Tab */}
        <TabsContent value="cost-feed" className="space-y-4">
          <Card className="border-border/60 shadow-sm bg-card/60 backdrop-blur">
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-lg font-bold">Recent Execution Feed</CardTitle>
                <CardDescription>Live telemetry for prompt tokens, completion tokens, and estimated cost.</CardDescription>
              </div>
              <span className="text-xs font-mono text-muted-foreground bg-muted px-2.5 py-1 rounded-full">
                {recentFeed.length} Requests Captured
              </span>
            </CardHeader>
            <CardContent>
              <div className="rounded-lg border border-border/50 overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-border/60 bg-muted/40 text-muted-foreground text-xs uppercase font-semibold">
                        <th className="py-3 px-4">Time</th>
                        <th className="py-3 px-4">Model</th>
                        <th className="py-3 px-4">Analysis Type</th>
                        <th className="py-3 px-4">Prompt Tokens</th>
                        <th className="py-3 px-4">Completion Tokens</th>
                        <th className="py-3 px-4">Estimated Cost</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/30">
                      {recentFeed.map((rec, idx) => (
                        <tr key={idx} className="hover:bg-muted/20 transition-colors">
                          <td className="py-3 px-4 font-mono text-xs text-muted-foreground">{formatTimestamp(rec.timestamp)}</td>
                          <td className="py-3 px-4 font-mono text-xs font-semibold">{rec.model || "Default"}</td>
                          <td className="py-3 px-4 text-xs">
                            <span className="bg-primary/10 text-primary px-2 py-0.5 rounded text-[11px] font-mono">
                              {rec.analysis_type || "general"}
                            </span>
                          </td>
                          <td className="py-3 px-4 font-mono text-xs text-muted-foreground">{rec.prompt_tokens || 0}</td>
                          <td className="py-3 px-4 font-mono text-xs text-muted-foreground">{rec.completion_tokens || 0}</td>
                          <td className="py-3 px-4 font-mono text-xs text-emerald-400 font-semibold">
                            ${(rec.estimated_cost_usd || 0).toFixed(5)}
                          </td>
                        </tr>
                      ))}
                      {recentFeed.length === 0 && (
                        <tr>
                          <td colSpan={6} className="py-8 text-center text-muted-foreground text-sm">
                            No request usage records captured yet. Execute queries in the Chat tab to view telemetry.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* 4. AI Evaluation Telemetry Tab */}
        <TabsContent value="eval-telemetry" className="space-y-4">
          <Card className="border-border/60 shadow-sm bg-card/60 backdrop-blur">
            <CardHeader>
              <CardTitle className="text-lg font-bold flex items-center gap-2">
                <Award className="h-5 w-5 text-amber-500" />
                AI Evaluation Telemetry
              </CardTitle>
              <CardDescription>
                Live aggregate scores from the self-scoring AI Evaluation Framework across all conversational query runs.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="p-4 rounded-lg border border-border/50 bg-muted/20 space-y-1">
                  <span className="text-xs text-muted-foreground font-semibold">Sample Requests Evaluated</span>
                  <div className="text-2xl font-bold text-foreground">{evalStats?.sample_size || 0}</div>
                  <p className="text-[11px] text-muted-foreground">Rolling in-memory buffer</p>
                </div>

                <div className="p-4 rounded-lg border border-border/50 bg-muted/20 space-y-1">
                  <span className="text-xs text-muted-foreground font-semibold">SQL Success Rate</span>
                  <div className="text-2xl font-bold text-emerald-400">
                    {evalStats?.sample_size ? `${evalStats.sql_success_rate_pct}%` : "100%"}
                  </div>
                  <p className="text-[11px] text-muted-foreground">Verified executable queries</p>
                </div>

                <div className="p-4 rounded-lg border border-border/50 bg-muted/20 space-y-1">
                  <span className="text-xs text-muted-foreground font-semibold">Average Quality Score</span>
                  <div className="text-2xl font-bold text-primary">
                    {evalStats?.sample_size ? `${evalStats.avg_quality_score}/100` : "100/100"}
                  </div>
                  <p className="text-[11px] text-muted-foreground">Claim adherence & grounding</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
