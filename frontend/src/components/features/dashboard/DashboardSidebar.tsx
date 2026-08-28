/* eslint-disable @typescript-eslint/no-explicit-any */

import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Sparkles, Play, Database, ArrowRight, BarChart3, CheckCircle2 } from "lucide-react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { SchemaResponse } from "@/types/api";

interface DashboardSidebarProps {
  schema?: SchemaResponse;
  activityTrendData: any[];
}

/**
 * Dashboard Sidebar Component
 * 
 * Displays the right-side panel of the dashboard containing:
 * 1. AI Recommended Schema Questions generated dynamically.
 * 2. Query Telemetry Trend visualization (Area chart).
 */
export function DashboardSidebar({ schema, activityTrendData }: DashboardSidebarProps) {
  const router = useRouter();

  const handleLaunchChat = (queryText: string) => {
    router.push(`/chat?prompt=${encodeURIComponent(queryText)}`);
  };

  return (
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
  );
}
