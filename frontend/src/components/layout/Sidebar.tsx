"use client";

import { useState, useEffect } from "react";
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
  Radio,
  Menu,
  X
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
  const [isOpen, setIsOpen] = useState(false);

  // Close sidebar on navigation
  useEffect(() => {
    setIsOpen(false);
  }, [pathname]);

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
    <>
      {/* Mobile Header */}
      <div className="md:hidden flex items-center justify-between p-4 border-b border-border/50 bg-card shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold shadow-sm">
            AI
          </div>
          <span className="text-sm font-bold">Database Analyst</span>
        </div>
        <button
          onClick={() => setIsOpen(true)}
          className="p-2 -mr-2 rounded-md hover:bg-secondary/50 text-muted-foreground"
        >
          <Menu className="h-5 w-5" />
        </button>
      </div>

      {/* Overlay */}
      {isOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-background/80 backdrop-blur-sm"
          onClick={() => setIsOpen(false)}
        />
      )}

      {/* Sidebar Content */}
      <div className={cn(
        "fixed inset-y-0 left-0 z-50 w-64 transform bg-card border-r border-border/50 px-4 py-6 flex flex-col transition-transform duration-200 ease-in-out",
        "md:relative md:translate-x-0 md:h-full", // Desktop styles
        isOpen ? "translate-x-0" : "-translate-x-full" // Mobile animation
      )}>
        <div className="flex items-center justify-between mb-8 px-2">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold shadow-sm shrink-0">
              AI
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-bold leading-tight truncate">Database Analyst</span>
            </div>
          </div>
          <button
            onClick={() => setIsOpen(false)}
            className="md:hidden p-1.5 rounded-md hover:bg-secondary/50 text-muted-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto pr-1">
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
                <span className="truncate">{item.name}</span>
              </Link>
            );
          })}
        </nav>

        {/* Bottom Section: Active DB Status Pill Only */}
        <div className="mt-4 pt-4 border-t border-border/40 shrink-0">
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
    </>
  );
}
