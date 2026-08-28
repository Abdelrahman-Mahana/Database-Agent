/* eslint-disable @typescript-eslint/no-explicit-any */

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

interface AnalyticsTableProfilerTabProps {
  tables: any[];
  handleProfileTable: (name: string) => void;
  profileTableMutation: any;
}

/**
 * Table Profiler Tab Component
 * 
 * Displays all tables and provides a mechanism to incrementally refresh
 * the statistical profile of each table individually without re-indexing the whole DB.
 */
export function AnalyticsTableProfilerTab({ tables, handleProfileTable, profileTableMutation }: AnalyticsTableProfilerTabProps) {
  return (
    <Card className="border-border/60">
      <CardHeader>
        <CardTitle className="text-base font-bold flex items-center gap-2">
          <RefreshCw className="h-4 w-4 text-emerald-400" />
          Incremental Catalog Data Profiler
        </CardTitle>
        <CardDescription>
          Refresh statistical profiles (exact row counts, value samples, date ranges) for specific tables on demand without re-indexing the entire database.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {tables.map((t) => (
            <div
              key={t.name}
              className="p-4 rounded-xl border border-border/60 bg-muted/20 hover:bg-muted/40 transition-all flex flex-col justify-between space-y-3"
            >
              <div>
                <div className="flex items-center justify-between">
                  <h4 className="font-bold text-sm font-mono text-foreground">{t.name}</h4>
                  <span className="text-[10px] bg-primary/10 text-primary px-2 py-0.5 rounded font-semibold uppercase">
                    {t.object_type}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {t.columns?.length || 0} Columns • {t.foreign_keys?.length || 0} Foreign Keys
                </p>
              </div>

              <Button
                size="sm"
                onClick={() => handleProfileTable(t.name)}
                disabled={profileTableMutation.isPending}
                className="w-full gap-1.5 text-xs bg-primary hover:bg-primary/90 text-primary-foreground"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${profileTableMutation.isPending ? "animate-spin" : ""}`} />
                Refresh Data Profile
              </Button>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
