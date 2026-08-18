"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { apiClient } from "@/services/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  CodeXml, 
  Activity, 
  Cpu, 
  Zap, 
  Clock, 
  ShieldCheck, 
  Layers, 
  BarChart3, 
  DollarSign, 
  RefreshCw, 
  CheckCircle2, 
  Play, 
  AlertCircle,
  FileCode,
  Sparkles
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

export default function ExecutionDetailsPage() {
  const [testSql, setTestSql] = useState("SELECT * FROM albums WHERE AlbumId > 10;");
  const [guardResult, setGuardResult] = useState<any>(null);
  const [isGuarding, setIsGuarding] = useState(false);

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

  const formatTimestamp = (ts?: number | string) => {
    if (!ts) return "Just now";
    const date = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
    return isNaN(date.getTime()) ? "Recent" : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  // Fetch health telemetry
  const { data: healthData, isLoading: isHealthLoading, refetch: refetchHealth } = useQuery<HealthData>({
    queryKey: ['system-health'],
    queryFn: async () => {
      const res = await apiClient.get('/health');
      return res.data;
    },
    refetchInterval: 10000,
  });

  // Fetch cost summary stats
  const { data: costSummary, isLoading: isCostLoading, refetch: refetchCost } = useQuery<CostSummary>({
    queryKey: ['cost-summary'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/stats/cost');
        return res.data;
      } catch (e) {
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
      } catch (e) {
        return [];
      }
    },
    refetchInterval: 10000,
  });

  const handleRefreshAll = () => {
    refetchHealth();
    refetchCost();
    refetchRecent();
  };

  const totalTokens = (costSummary?.total_prompt_tokens || 0) + (costSummary?.total_completion_tokens || 0);

  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-full space-y-6 overflow-y-auto pr-1">
      {/* Top Banner Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/40 pb-5">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2.5">
            <CodeXml className="h-7 w-7 text-primary" />
            Execution & Telemetry Details
          </h2>
          <p className="text-muted-foreground text-sm mt-1">
            Deep-dive into agent pipeline execution metrics, LLM provider latency, and query cost tracking.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={handleRefreshAll} className="gap-2 shrink-0">
          <RefreshCw className="h-4 w-4" />
          Refresh Metrics
        </Button>
      </div>

      {/* Health & LLM Telemetry Banner */}
      <div className="grid gap-4 grid-cols-1 md:grid-cols-4">
        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">System Status</CardTitle>
            <Activity className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 text-xl font-bold">
              <span className="h-3 w-3 rounded-full bg-emerald-500 animate-pulse" />
              {healthData?.status?.toUpperCase() || "ONLINE"}
            </div>
            <p className="text-xs text-muted-foreground mt-1">FastAPI container healthy</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">LLM Engine</CardTitle>
            <Cpu className="h-4 w-4 text-sky-500" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold truncate">{healthData?.model || "Standard Tier"}</div>
            <p className="text-xs text-muted-foreground mt-1 capitalize">Provider: {healthData?.llm_provider || "Local/Cloud"}</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">LLM Latency</CardTitle>
            <Zap className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">
              {healthData?.llm_latency_ms ? `${Math.round(healthData.llm_latency_ms)} ms` : "Not probed"}
            </div>
            <p className="text-xs text-muted-foreground mt-1">Use dependency health for a provider probe</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/60">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Total Token Spend</CardTitle>
            <DollarSign className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">
              ${(costSummary?.estimated_cost_usd || 0).toFixed(4)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">{totalTokens.toLocaleString()} Total Tokens</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Tabs Workspace */}
      <Tabs defaultValue="pipeline" className="w-full">
        <TabsList className="grid w-full grid-cols-3 max-w-lg">
          <TabsTrigger value="pipeline" className="flex items-center gap-2 text-xs">
            <Layers className="h-4 w-4 text-primary" />
            Agent Pipeline
          </TabsTrigger>
          <TabsTrigger value="cost-feed" className="flex items-center gap-2 text-xs">
            <BarChart3 className="h-4 w-4 text-emerald-500" />
            Token & Cost Feed
          </TabsTrigger>
          <TabsTrigger value="security" className="flex items-center gap-2 text-xs">
            <ShieldCheck className="h-4 w-4 text-sky-500" />
            Cost & Security Guard
          </TabsTrigger>
        </TabsList>

        {/* Agent Pipeline Architecture Tab */}
        <TabsContent value="pipeline" className="space-y-4 mt-6">
          <Card className="border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-bold flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-primary" />
                7-Stage Analyst Agent Architecture
              </CardTitle>
              <CardDescription>
                Visual step-by-step trace of how natural language prompts are validated, executed, and synthesized into reports.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4 relative before:absolute before:left-[19px] before:top-3 before:bottom-3 before:w-0.5 before:bg-border/60">
                {[
                  {
                    step: "1",
                    name: "Intent Classification & Schema Grounding",
                    desc: "Parses user prompt intent (database analysis vs schema lookup vs off-topic) and retrieves grounded schema subsets.",
                    badge: "Hybrid Matcher",
                    color: "text-sky-400 bg-sky-500/10 border-sky-500/20"
                  },
                  {
                    step: "2",
                    name: "Business Synonym Resolution",
                    desc: "Maps domain-specific business terminology (e.g. 'sales', 'revenue') to catalog tables and columns.",
                    badge: "Catalog Glossary",
                    color: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20"
                  },
                  {
                    step: "3",
                    name: "SQL Generation & Self-Consistency Voting",
                    desc: "Generates dialect-accurate SELECT queries using low temperature (0.1) and self-consistency voting for complex queries.",
                    badge: "LLM Synthesizer",
                    color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                  },
                  {
                    step: "4",
                    name: "SQL Safety & Cost Guard Validation",
                    desc: "Enforces strict SELECT-only read permissions and inspects query complexity to prevent unbounded dataset scans.",
                    badge: "Safety Gate",
                    color: "text-amber-400 bg-amber-500/10 border-amber-500/20"
                  },
                  {
                    step: "5",
                    name: "Database Execution & Bounded Auto-Repair",
                    desc: "Executes SQL against active SQLAlchemy engine. If execution fails, bounded auto-repair retries with corrected schema hints.",
                    badge: "Auto-Repair Loop",
                    color: "text-rose-400 bg-rose-500/10 border-rose-500/20"
                  },
                  {
                    step: "6",
                    name: "Data Masking & Analytics Engine",
                    desc: "Masks sensitive columns (SSNs, API keys) and computes statistical metrics (MIN/MAX, distributions, top rankings).",
                    badge: "Privacy & Math Engine",
                    color: "text-purple-400 bg-purple-500/10 border-purple-500/20"
                  },
                  {
                    step: "7",
                    name: "Report Synthesis & Grounding Verification",
                    desc: "Generates executive summaries with citation tags and performs factual grounding verification to prevent hallucinations.",
                    badge: "Factual Verifier",
                    color: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20"
                  },
                ].map((item) => (
                  <div key={item.step} className="flex items-start gap-4 relative pl-2">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-card border border-border/80 font-bold text-xs shadow-sm z-10">
                      {item.step}
                    </div>
                    <div className="flex-1 p-4 rounded-xl border border-border/50 bg-muted/10 space-y-1">
                      <div className="flex items-center justify-between">
                        <h4 className="font-semibold text-sm">{item.name}</h4>
                        <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-medium border ${item.color}`}>
                          {item.badge}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">{item.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Cost & Token Feed Tab */}
        <TabsContent value="cost-feed" className="space-y-4 mt-6">
          <Card className="border-border/60">
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

        {/* Security & Cost Guard Tab */}
        <TabsContent value="security" className="space-y-6 mt-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <Card className="border-border/60">
              <CardHeader>
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-emerald-500" />
                  Read-Only SQL Enforcer
                </CardTitle>
                <CardDescription>Validates queries to prevent data mutations.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-xs text-muted-foreground">
                <p className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  Allows ONLY standard SELECT queries.
                </p>
                <p className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  Blocks DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE statements.
                </p>
                <p className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  Quotes table and column identifiers dialect-safely.
                </p>
              </CardContent>
            </Card>

            <Card className="border-border/60">
              <CardHeader>
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-amber-500" />
                  Cost & Scan Guard
                </CardTitle>
                <CardDescription>Prevents runaway query execution on massive tables.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-xs text-muted-foreground">
                <p className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  Inspects query structure for missing WHERE or LIMIT clauses.
                </p>
                <p className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  Prevents full table scans on datasets exceeding row threshold limits.
                </p>
                <p className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  Automatic column masking for sensitive fields (SSNs, passwords).
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Live Interactive SQL Guard Sandbox */}
          <Card className="border-border/60 shadow-sm bg-card/60 backdrop-blur">
            <CardHeader>
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <Play className="h-4 w-4 text-primary" />
                Live SQL Security Guard & Transpiler Sandbox
              </CardTitle>
              <CardDescription>
                Test custom SQL queries in real-time against our AST security validator, read-only enforcement, and automatic scan limiters.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Test SQL Statement
                </label>
                <div className="flex flex-col sm:flex-row gap-2.5">
                  <Input
                    value={testSql}
                    onChange={(e) => setTestSql(e.target.value)}
                    placeholder="e.g. DROP TABLE users; or SELECT * FROM invoices;"
                    className="font-mono text-xs flex-1 bg-muted/30"
                  />
                  <Button
                    onClick={handleTestGuard}
                    disabled={isGuarding || !testSql.trim()}
                    className="gap-2 shrink-0 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold shadow"
                  >
                    {isGuarding ? <RefreshCw className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                    Verify against Guard
                  </Button>
                </div>
                <div className="flex flex-wrap items-center gap-2 pt-1 text-xs text-muted-foreground">
                  <span className="font-semibold text-[11px]">Quick presets:</span>
                  <button type="button" onClick={() => { setTestSql("DROP TABLE users;"); setGuardResult(null); }} className="underline hover:text-foreground text-rose-400 font-mono text-[11px] transition-colors">DROP TABLE users;</button>
                  <button type="button" onClick={() => { setTestSql("UPDATE tracks SET unit_price = 0 WHERE TrackId = 1;"); setGuardResult(null); }} className="underline hover:text-foreground text-amber-400 font-mono text-[11px] transition-colors">UPDATE tracks...</button>
                  <button type="button" onClick={() => { setTestSql("SELECT * FROM invoices WHERE Total > 10;"); setGuardResult(null); }} className="underline hover:text-foreground text-emerald-400 font-mono text-[11px] transition-colors">SELECT * FROM invoices...</button>
                </div>
              </div>

              {guardResult && (
                <div className="pt-4 border-t border-border/40 space-y-3">
                  <div className={`p-3.5 rounded-xl border flex items-start gap-3 ${
                    guardResult.valid ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" : "bg-rose-500/10 border-rose-500/30 text-rose-400"
                  }`}>
                    {guardResult.valid ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400 mt-0.5" /> : <AlertCircle className="h-5 w-5 shrink-0 text-rose-400 mt-0.5" />}
                    <div>
                      <h4 className="font-bold text-sm text-foreground">
                        {guardResult.valid ? "✅ Query Passed Security Guard & Scan Limits" : "⛔ Query Blocked by Security Guard"}
                      </h4>
                      <p className="text-xs text-muted-foreground mt-1 font-sans leading-relaxed">{guardResult.reason}</p>
                    </div>
                  </div>

                  {guardResult.valid && guardResult.sanitized_sql && (
                    <div className="space-y-2 bg-muted/20 p-3.5 rounded-xl border border-border/40">
                      <span className="text-xs font-mono font-semibold text-muted-foreground flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                        <span>Transpiled & Bounded SQL ({guardResult.dialect?.toUpperCase() || "SQLITE"})</span>
                        <span className="text-emerald-400 font-normal flex items-center gap-1">
                          <CheckCircle2 className="h-3 w-3 inline" /> Auto-enforced LIMIT applied
                        </span>
                      </span>
                      <pre className="text-xs font-mono bg-black/50 p-3 rounded-lg text-sky-300 overflow-x-auto border border-border/20">
                        {guardResult.sanitized_sql}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
