import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { BaseDBObject } from "@/types/api";
import { Layers, Search, Eye, Terminal, FileCode2, TableProperties, Key, Link as LinkIcon, ExternalLink, Sparkles, ArrowRight } from "lucide-react";

interface DashboardSchemaExplorerProps {
  allObjects: BaseDBObject[];
}

export function DashboardSchemaExplorer({ allObjects }: DashboardSchemaExplorerProps) {
  const router = useRouter();
  const [schemaSearch, setSchemaSearch] = useState("");

  const filteredObjects = useMemo(() => {
    if (!schemaSearch.trim()) return allObjects;
    const q = schemaSearch.toLowerCase();
    return allObjects.filter((obj) => {
      if (obj.name.toLowerCase().includes(q)) return true;
      if (obj.schema?.toLowerCase().includes(q)) return true;
      return obj.columns.some((col) => col.name.toLowerCase().includes(q));
    });
  }, [allObjects, schemaSearch]);

  const getObjectIcon = (type: string) => {
    switch (type) {
      case "view":
        return <Eye className="h-4 w-4 text-indigo-400 shrink-0" />;
      case "procedure":
        return <Terminal className="h-4 w-4 text-amber-400 shrink-0" />;
      case "collection":
        return <FileCode2 className="h-4 w-4 text-teal-400 shrink-0" />;
      case "table":
      default:
        return <TableProperties className="h-4 w-4 text-emerald-400 shrink-0" />;
    }
  };

  const handleLaunchChat = (queryText: string) => {
    router.push(`/chat?prompt=${encodeURIComponent(queryText)}`);
  };

  return (
    <Card className="lg:col-span-8 border-border/60 shadow-sm flex flex-col">
      <CardHeader className="p-6 border-b border-border/40 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <CardTitle className="text-lg font-bold flex items-center gap-2">
              <Layers className="h-5 w-5 text-primary" />
              Database Schema Objects & Fields
            </CardTitle>
            <CardDescription className="text-xs mt-0.5">
              Direct overview of database tables, views, stored procedures, and collections.
            </CardDescription>
          </div>

          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              type="text"
              placeholder="Filter schema objects or columns..."
              value={schemaSearch}
              onChange={(e) => setSchemaSearch(e.target.value)}
              className="pl-9 h-9 text-xs"
            />
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-4 space-y-3 overflow-y-auto max-h-[600px]">
        {filteredObjects.length > 0 ? (
          <div className="grid gap-3">
            {filteredObjects.map((obj) => (
              <div
                key={obj.name}
                className="p-4 rounded-xl border border-border/50 bg-card/60 hover:bg-muted/30 transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-4 group"
              >
                <div className="space-y-1.5 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    {getObjectIcon(obj.object_type)}
                    <h4 className="font-bold text-base text-foreground group-hover:text-primary transition-colors">
                      {obj.name}
                    </h4>
                    <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-muted text-muted-foreground uppercase">
                      {obj.object_type}
                    </span>
                    {obj.primary_key && obj.primary_key.length > 0 && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                        <Key className="h-2.5 w-2.5" />
                        PK: {obj.primary_key.join(", ")}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap font-mono">
                    <span>{obj.columns?.length || 0} Columns</span>
                    {obj.foreign_keys && obj.foreign_keys.length > 0 && (
                      <span className="text-amber-400 flex items-center gap-1">
                        <LinkIcon className="h-3 w-3" />
                        {obj.foreign_keys.length} FKs
                      </span>
                    )}
                    {obj.indexes && obj.indexes.length > 0 && (
                      <span>{obj.indexes.length} Indexes</span>
                    )}
                    {obj.document_count !== undefined && (
                      <span>{obj.document_count} Documents</span>
                    )}
                  </div>

                  {obj.columns && obj.columns.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {obj.columns.slice(0, 5).map((col) => (
                        <span
                          key={col.name}
                          className="px-2 py-0.5 rounded bg-muted/60 text-[11px] font-mono text-muted-foreground flex items-center gap-1"
                        >
                          <span>{col.name}</span>
                          <span className="text-[9px] opacity-75">({col.type})</span>
                        </span>
                      ))}
                      {obj.columns.length > 5 && (
                        <span className="px-2 py-0.5 rounded bg-muted/40 text-[10px] font-mono text-muted-foreground">
                          +{obj.columns.length - 5} more
                        </span>
                      )}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => router.push(`/explorer?selected=${encodeURIComponent(obj.name)}`)}
                    className="gap-1 text-xs"
                  >
                    Inspect
                    <ExternalLink className="h-3 w-3" />
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => handleLaunchChat(`Explain table ${obj.name}: summarize its purpose, key columns and relationships, and show 3 practical SQL query examples with explanations.`)}
                    className="gap-1.5 text-xs bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-600 hover:to-indigo-700 text-white"
                  >
                    <Sparkles className="h-3 w-3" />
                    Ask AI
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-12 text-center text-muted-foreground text-sm border border-dashed border-border/60 rounded-xl">
            No schema objects match your filter query.
          </div>
        )}
      </CardContent>

      <CardFooter className="p-4 border-t border-border/40 bg-muted/10 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          Showing {filteredObjects.length} of {allObjects.length} schema objects
        </span>
        <Button variant="ghost" size="sm" onClick={() => router.push('/explorer')} className="gap-1 text-xs text-primary">
          Open Full Interactive Explorer
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </CardFooter>
    </Card>
  );
}
