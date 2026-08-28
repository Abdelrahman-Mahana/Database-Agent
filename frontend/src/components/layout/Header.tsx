"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/services/api";
import { useAppStore } from "@/store/useAppStore";
import { SchemaResponse } from "@/types/api";
import { 
  Database, 
  Terminal, 
  Settings, 
  Activity,
  History,
  Radio,
  FileCode,
  LineChart
} from "lucide-react";

export function Header() {
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

  const navigation = [
    { name: "Dashboard", href: "/", icon: Activity },
    { name: "Explorer", href: "/explorer", icon: Database },
    { name: "Chat Analyst", href: "/chat", icon: Terminal },
    { name: "Analytics & Profiling", href: "/analytics", icon: LineChart },
    { name: "Execution", href: "/execution", icon: FileCode },
    { name: "Connect", href: "/connect", icon: Radio },
    { name: "History", href: "/history", icon: History },
    { name: "Settings", href: "/settings", icon: Settings },
  ];

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 max-w-screen-2xl items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-center space-x-2">
            <Database className="h-6 w-6 text-primary animate-pulse" />
            <span className="font-bold text-lg bg-gradient-to-r from-primary to-blue-500 bg-clip-text text-transparent">
              DB Agent
            </span>
          </Link>

          <nav className="flex items-center gap-1 sm:gap-2">
            {navigation.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                    isActive
                      ? "bg-primary/10 text-primary font-semibold"
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span className="hidden md:inline">{item.name}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Live Active Database Status Badge */}
        <div className="flex items-center gap-2">
          <Link
            href="/connect"
            className="flex items-center gap-2 px-2.5 py-1 rounded-full border border-border/60 bg-muted/30 hover:bg-muted/60 transition-colors text-xs"
            title="Click to switch database connection"
          >
            <span className={`h-2 w-2 rounded-full ${schema ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
            <span className="font-mono font-medium text-foreground truncate max-w-[120px] sm:max-w-[200px]">
              {dbName}
            </span>
            <span className="text-[10px] uppercase font-mono px-1.5 py-0.2 rounded bg-muted text-muted-foreground hidden sm:inline">
              {dbType}
            </span>
          </Link>
        </div>
      </div>
    </header>
  );
}
