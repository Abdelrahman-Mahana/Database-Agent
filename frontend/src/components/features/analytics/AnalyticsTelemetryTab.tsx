/* eslint-disable @typescript-eslint/no-explicit-any */

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Award, CheckCircle2 } from "lucide-react";

interface AnalyticsTelemetryTabProps {
  evalHistory: any[];
}

/**
 * AI Telemetry Tab Component
 * 
 * Displays the historical stream of user queries and their associated AI evaluation
 * metrics (Quality Score, Confidence, SQL Execution Success, Latency, and Cost).
 */
export function AnalyticsTelemetryTab({ evalHistory }: AnalyticsTelemetryTabProps) {
  return (
    <Card className="border-border/60">
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-base font-bold flex items-center gap-2">
            <Award className="h-4 w-4 text-emerald-400" />
            Live AI Evaluation Framework Telemetry
          </CardTitle>
          <CardDescription>
            Every user question is scored by the AI Evaluation Framework for confidence, quality, repair attempts, and latency.
          </CardDescription>
        </div>
        <span className="text-xs font-mono bg-muted px-2.5 py-1 rounded-full text-muted-foreground">
          {evalHistory.length} Scored Queries
        </span>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-border/50 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-border/60 bg-muted/40 text-muted-foreground text-xs uppercase font-semibold">
                  <th className="py-3 px-4">User Question</th>
                  <th className="py-3 px-4">Quality Score</th>
                  <th className="py-3 px-4">Confidence</th>
                  <th className="py-3 px-4">Execution</th>
                  <th className="py-3 px-4">Latency</th>
                  <th className="py-3 px-4">Tokens & Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {evalHistory.map((rec, idx) => (
                  <tr key={idx} className="hover:bg-muted/20 transition-colors">
                    <td className="py-3 px-4 font-medium max-w-xs truncate">{rec.question}</td>
                    <td className="py-3 px-4 font-mono">
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        {Math.round(rec.quality_score * (rec.quality_score <= 1 ? 100 : 1))}/100
                      </span>
                    </td>
                    <td className="py-3 px-4 font-mono">
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">
                        {Math.round(rec.confidence_score * (rec.confidence_score <= 1 ? 100 : 1))}%
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      {rec.metrics?.sql_execution_success !== false ? (
                        <span className="text-emerald-400 flex items-center gap-1">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Success
                        </span>
                      ) : (
                        <span className="text-rose-400 flex items-center gap-1">
                          Failed
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 font-mono text-muted-foreground">
                      {rec.stage_latency?.total_ms ? `${Math.round(rec.stage_latency.total_ms)}ms` : "—"}
                    </td>
                    <td className="py-3 px-4 font-mono text-muted-foreground">
                      {rec.token_usage?.total_tokens || 0} tokens (${(rec.token_usage?.estimated_cost_usd || 0).toFixed(5)})
                    </td>
                  </tr>
                ))}
                {evalHistory.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-muted-foreground text-sm">
                      No evaluation scores captured yet. Send a query in the Chat tab to view live AI evaluation benchmarks.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
