"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Bell, User, Moon, Sun } from "lucide-react";
import { useAppStore } from "@/store/useAppStore";
import { useEffect } from "react";

export function Header() {
  const router = useRouter();
  const { theme, toggleTheme } = useAppStore();
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      const prompt = encodeURIComponent(searchQuery.trim());
      router.push(`/chat?prompt=${prompt}`);
      setSearchQuery("");
    }
  };

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b bg-card px-6">
      <div className="flex items-center gap-4 flex-1">
        <form onSubmit={handleSearchSubmit} className="relative w-96">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search schemas, queries, or ask AI..."
            className="h-9 w-full rounded-md border border-input bg-transparent pl-9 pr-4 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </form>
      </div>
      
      <div className="flex items-center gap-4">
        <button 
          onClick={toggleTheme}
          className="rounded-full p-2 hover:bg-accent text-muted-foreground transition-colors"
          title="Toggle Theme"
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
        <button 
          onClick={() => router.push('/history')}
          className="rounded-full p-2 hover:bg-accent text-muted-foreground transition-colors relative"
          title="Notifications & Activity"
        >
          <Bell className="h-4 w-4" />
          <span className="absolute top-1.5 right-2 h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
        </button>
        <button 
          onClick={() => router.push('/settings')}
          className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-secondary-foreground hover:bg-primary/20 transition-colors"
          title="User Profile & Preferences"
        >
          <User className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
