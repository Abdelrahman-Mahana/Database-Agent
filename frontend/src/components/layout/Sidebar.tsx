"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/services/api";
import { useAppStore } from "@/store/useAppStore";
import { SchemaResponse } from "@/types/api";
import { 
  LayoutDashboard, 
  Database, 
  MessageSquare, 
  History, 
  Activity, 
  Settings, 
  CodeXml, 
  Radio
} from "lucide-react";
import { cn } from "@/lib/utils";

const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Database Explorer", href: "/explorer", icon: Database },
  { name: "Chat", href: "/chat", icon: MessageSquare },
  { name: "Analytics", href: "/analytics", icon: Activity },
  { name: "Execution Details", href: "/execution", icon: CodeXml },
  { name: "Connect Database", href: "/connect", icon: Radio },
  { name: "History", href: "/history", icon: History },
  { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const { activeDatabase } = useAppStore();

  const { data: schema } = useQuery<SchemaResponse>({
    queryKey: ['schema', activeDatabase],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/schema');
        return res.data;
      } catch {
        return null;
      }
    },
    staleTime: 60000,
  });

  const dbName = schema?.database_name || activeDatabase || "Not Connected";
  const dbType = schema?.database_type || "SQL";

  return (
    <div className="flex h-full w-64 flex-col border-r border-border/50 bg-card px-4 py-6">
      <div className="flex items-center gap-3 px-2 mb-8">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold shadow-sm">
          AI
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-bold leading-tight">Database Analyst</span>
          <span className="text-[10px] text-muted-foreground">Enterprise Intelligence</span>
        </div>
      </div>

      <nav className="flex-1 space-y-1">
        {navigation.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                "group flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-secondary text-secondary-foreground font-semibold"
                  : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
              )}
            >
              <item.icon
                className={cn(
                  "h-4 w-4 shrink-0",
                  isActive ? "text-foreground" : "text-muted-foreground group-hover:text-foreground"
                )}
              />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* Bottom Section: Active DB Status Pill Only */}
      <div className="mt-auto pt-4 border-t border-border/40">
        <Link
          href="/connect"
          className="flex items-center justify-between p-2.5 rounded-lg border border-border/60 bg-muted/20 hover:bg-muted/40 transition-colors group"
          title="Active Database Connection (Click to manage)"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className={`h-2 w-2 rounded-full shrink-0 ${schema ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
            <div className="flex flex-col min-w-0">
              <span className="text-xs font-mono font-medium text-foreground truncate">{dbName}</span>
              <span className="text-[10px] uppercase font-mono text-muted-foreground">{dbType}</span>
            </div>
          </div>
          <Radio className="h-3.5 w-3.5 text-muted-foreground group-hover:text-primary transition-colors shrink-0" />
        </Link>
      </div>
    </div>
  );
}
