"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { apiClient } from "@/services/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Label } from "@/components/ui/label";
import { 
  History, 
  Bookmark, 
  Search, 
  Play, 
  Trash2, 
  Copy, 
  Check, 
  Plus, 
  Sparkles,
  Sliders,
  Clock,
  ExternalLink,
  MessageSquare,
  MessageSquarePlus
} from "lucide-react";
import { useAppStore } from "@/store/useAppStore";
import { cn } from "@/lib/utils";

interface SavedQueryItem {
  id: string;
  question: string;
  sql: string;
  label?: string;
  created_at: number;
}

interface SessionTurn {
  question: string;
  sql: string;
  result_summary: string;
  intent: string;
  timestamp: number;
}

const USER_ID = "default_user";

export default function HistoryPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // New Saved Query Form State
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newQuestion, setNewQuestion] = useState("");
  const [newSql, setNewSql] = useState("");
  const [newLabel, setNewLabel] = useState("");

  // Fetch saved queries
  const { data: savedQueries = [], isLoading } = useQuery<SavedQueryItem[]>({
    queryKey: ['saved-queries', USER_ID],
    queryFn: async () => {
      const res = await apiClient.get(`/memory/queries?user_id=${USER_ID}`);
      return res.data;
    },
  });

  // Fetch user preferences
  const { data: preferencesData } = useQuery({
    queryKey: ['user-preferences', USER_ID],
    queryFn: async () => {
      const res = await apiClient.get(`/memory/preferences?user_id=${USER_ID}`);
      return res.data;
    },
  });

  // Fetch all chat sessions
  const { data: sessionsData, isLoading: isSessionsLoading } = useQuery({
    queryKey: ['chatSessions'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/chat/sessions');
        return res.data;
      } catch {
        return { sessions: [] };
      }
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      await apiClient.delete(`/chat/history?session_id=${sessionId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chatSessions'] });
    },
  });

  // Save new query mutation
  const saveMutation = useMutation({
    mutationFn: async (payload: { question: string; sql: string; label?: string }) => {
      const res = await apiClient.post('/memory/queries', {
        user_id: USER_ID,
        ...payload,
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-queries', USER_ID] });
      setNewQuestion("");
      setNewSql("");
      setNewLabel("");
      setIsAddOpen(false);
    },
  });

  // Delete query mutation
  const deleteMutation = useMutation({
    mutationFn: async (queryId: string) => {
      await apiClient.delete(`/memory/queries/${queryId}?user_id=${USER_ID}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-queries', USER_ID] });
    },
  });

  // Filter queries based on search input
  const filteredQueries = useMemo(() => {
    if (!searchQuery.trim()) return savedQueries;
    const q = searchQuery.toLowerCase();
    return savedQueries.filter(item => 
      item.question.toLowerCase().includes(q) || 
      item.sql.toLowerCase().includes(q) ||
      (item.label && item.label.toLowerCase().includes(q))
    );
  }, [savedQueries, searchQuery]);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleRunInChat = (questionText: string) => {
    const prompt = encodeURIComponent(questionText);
    router.push(`/chat?prompt=${prompt}`);
  };

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newQuestion && newSql) {
      saveMutation.mutate({ question: newQuestion, sql: newSql, label: newLabel });
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-full space-y-6 overflow-y-auto pr-1">
      {/* Top Banner Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/40 pb-5">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2.5">
            <History className="h-7 w-7 text-primary" />
            Query History & Bookmarks
          </h2>
          <p className="text-muted-foreground text-sm mt-1">
            Access your saved SQL templates, frequent questions, and long-term user preferences.
          </p>
        </div>
        <Button onClick={() => setIsAddOpen(!isAddOpen)} className="gap-2 shrink-0">
          <Plus className="h-4 w-4" />
          Bookmark New Query
        </Button>
      </div>

      {/* Add New Bookmark Form Modal/Accordion */}
      {isAddOpen && (
        <Card className="border-primary/40 bg-card/80 shadow-md animate-in fade-in slide-in-from-top-2">
          <form onSubmit={handleCreateSubmit}>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Bookmark className="h-4 w-4 text-primary" />
                Bookmark Query Template
              </CardTitle>
              <CardDescription>Save a custom question and SQL snippet to your long-term query library.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="question">Natural Language Question</Label>
                  <Input 
                    id="question"
                    placeholder="e.g. List top 5 customers by revenue"
                    value={newQuestion}
                    onChange={(e) => setNewQuestion(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="label">Category / Tag (Optional)</Label>
                  <Input 
                    id="label"
                    placeholder="e.g. Sales, Customers, Monthly Report"
                    value={newLabel}
                    onChange={(e) => setNewLabel(e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sql">SQL Query</Label>
                <textarea
                  id="sql"
                  rows={3}
                  placeholder="SELECT * FROM customers ORDER BY total_spent DESC LIMIT 5;"
                  value={newSql}
                  onChange={(e) => setNewSql(e.target.value)}
                  required
                  className="w-full rounded-md border border-input bg-black/40 px-3 py-2 text-xs font-mono text-emerald-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
              </div>
            </CardContent>
            <CardFooter className="flex justify-end gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => setIsAddOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" size="sm" disabled={saveMutation.isPending}>
                {saveMutation.isPending ? "Saving..." : "Save Query"}
              </Button>
            </CardFooter>
          </form>
        </Card>
      )}

      {/* Main Tabs Container */}
      <Tabs defaultValue="bookmarks" className="w-full">
        <TabsList className="grid w-full grid-cols-3 max-w-2xl">
          <TabsTrigger value="bookmarks" className="flex items-center gap-2 text-xs">
            <Bookmark className="h-4 w-4" />
            Saved Bookmarks ({savedQueries.length})
          </TabsTrigger>
          <TabsTrigger value="session-history" className="flex items-center gap-2 text-xs">
            <MessageSquare className="h-4 w-4 text-sky-400" />
            Chat Sessions ({sessionsData?.sessions?.length || 0})
          </TabsTrigger>
          <TabsTrigger value="quick-actions" className="flex items-center gap-2 text-xs">
            <Sparkles className="h-4 w-4 text-emerald-400" />
            Quick Launcher
          </TabsTrigger>
        </TabsList>

        {/* Bookmarks Tab */}
        <TabsContent value="bookmarks" className="space-y-4 mt-6">
          <div className="relative max-w-md">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              type="text"
              placeholder="Filter saved queries..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 h-9 text-xs"
            />
          </div>

          {isLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-pulse">
              {[1, 2, 3, 4].map(i => (
                <div key={i} className="h-36 bg-muted/20 rounded-xl border border-border/40" />
              ))}
            </div>
          ) : filteredQueries.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filteredQueries.map((item) => (
                <Card key={item.id} className="border-border/60 hover:border-primary/40 transition-all shadow-sm flex flex-col justify-between">
                  <CardHeader className="p-4 pb-2 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="font-semibold text-sm leading-snug">{item.question}</h4>
                      {item.label && (
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-primary/10 text-primary border border-primary/20 shrink-0">
                          {item.label}
                        </span>
                      )}
                    </div>
                    {item.created_at && (
                      <p className="text-[10px] text-muted-foreground flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {new Date(item.created_at * 1000).toLocaleDateString()}
                      </p>
                    )}
                  </CardHeader>

                  <CardContent className="p-4 pt-0">
                    <div className="rounded-md bg-black/40 border border-border/40 p-2.5 relative group">
                      <pre className="text-xs font-mono text-emerald-300 overflow-x-auto whitespace-pre-wrap max-h-24">
                        {item.sql}
                      </pre>
                    </div>
                  </CardContent>

                  <CardFooter className="p-4 pt-0 flex items-center justify-between border-t border-border/20 mt-2">
                    <Button 
                      size="sm" 
                      variant="secondary"
                      onClick={() => handleRunInChat(item.question)}
                      className="gap-1.5 text-xs text-primary"
                    >
                      <Play className="h-3.5 w-3.5 fill-current" />
                      Run Query
                    </Button>
                    <div className="flex items-center gap-1">
                      <Button 
                        size="icon" 
                        variant="ghost" 
                        onClick={() => copyToClipboard(item.sql, item.id)}
                        className="h-8 w-8 text-muted-foreground hover:text-foreground"
                        title="Copy SQL"
                      >
                        {copiedId === item.id ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                      </Button>
                      <Button 
                        size="icon" 
                        variant="ghost" 
                        onClick={() => deleteMutation.mutate(item.id)}
                        className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        title="Delete Bookmark"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </CardFooter>
                </Card>
              ))}
            </div>
          ) : (
            <Card className="border-border/60 p-12 text-center text-muted-foreground space-y-3">
              <Bookmark className="h-10 w-10 mx-auto opacity-40 text-primary" />
              <p className="text-sm">No saved queries match your search.</p>
              <Button size="sm" onClick={() => setIsAddOpen(true)} className="gap-2">
                <Plus className="h-4 w-4" />
                Bookmark Your First Query
              </Button>
            </Card>
          )}
        </TabsContent>

        {/* Chat Sessions Tab */}
        <TabsContent value="session-history" className="space-y-4 mt-6">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground font-sans">
              Your recent conversations with the AI Database Analyst.
            </p>
            <Button 
              variant="default" 
              size="sm" 
              onClick={() => {
                useAppStore.getState().setSessionId(Date.now().toString(36) + Math.random().toString(36).substring(2, 8));
                router.push('/chat');
              }}
              className="gap-1.5 text-xs bg-primary/90 hover:bg-primary text-primary-foreground shrink-0"
            >
              <MessageSquarePlus className="h-3.5 w-3.5" />
              New Chat
            </Button>
          </div>

          {isSessionsLoading ? (
            <div className="space-y-3 animate-pulse">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-20 bg-muted/20 rounded-xl border border-border/40" />
              ))}
            </div>
          ) : sessionsData?.sessions?.length > 0 ? (
            <div className="space-y-3">
              {sessionsData.sessions.map((session: any) => (
                <Card 
                  key={session.session_id} 
                  className="border-border/60 hover:border-primary/30 transition-all shadow-sm cursor-pointer group"
                  onClick={() => {
                    useAppStore.getState().setSessionId(session.session_id);
                    router.push('/chat');
                  }}
                >
                  <CardHeader className="p-4 flex flex-row items-center justify-between space-y-0">
                    <div className="flex items-center gap-3">
                      <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                        <MessageSquare className="h-4 w-4 text-primary" />
                      </div>
                      <div>
                        <h4 className="font-semibold text-sm leading-snug text-foreground">
                          {session.title || "Analytical Session"}
                        </h4>
                        <p className="text-xs text-muted-foreground font-mono mt-0.5 flex items-center gap-1.5">
                          <Clock className="h-3 w-3" />
                          {new Date(session.created_at * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                        </p>
                      </div>
                    </div>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={(e) => {
                        e.stopPropagation();
                        if(confirm("Delete this session?")) {
                           deleteSessionMutation.mutate(session.session_id);
                        }
                      }}
                      className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </CardHeader>
                </Card>
              ))}
            </div>
          ) : (
            <Card className="border-border/60 p-12 text-center text-muted-foreground space-y-3">
              <MessageSquare className="h-10 w-10 mx-auto opacity-40 text-sky-400" />
              <p className="text-sm">No chat sessions found.</p>
              <Button size="sm" onClick={() => {
                  useAppStore.getState().setSessionId(Date.now().toString(36) + Math.random().toString(36).substring(2, 8));
                  router.push('/chat');
                }} className="gap-2 bg-primary text-primary-foreground">
                <MessageSquarePlus className="h-3.5 w-3.5 fill-current" />
                Start New Chat
              </Button>
            </Card>
          )}
        </TabsContent>

        {/* Quick Launcher Tab */}
        <TabsContent value="quick-actions" className="space-y-4 mt-6">
          <Card className="border-border/60 p-6">
            <CardHeader className="px-0 pt-0">
              <CardTitle className="text-lg font-bold">Preset Analytical Launchers</CardTitle>
              <CardDescription>Instant baseline questions to evaluate database schema performance.</CardDescription>
            </CardHeader>
            <CardContent className="px-0">
              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  { title: "Database Summary", q: "Summarize total records and active tables in the database" },
                  { title: "Top Entity Analysis", q: "List the top 10 highest-value records" },
                  { title: "Recent Activity", q: "Show recent timestamped transactions" },
                  { title: "Categorical Grouping", q: "Count entries grouped by category" },
                ].map((preset, idx) => (
                  <div key={idx} className="p-4 rounded-xl border border-border/50 bg-muted/10 hover:bg-muted/30 transition-colors flex items-center justify-between">
                    <div>
                      <h5 className="font-semibold text-sm">{preset.title}</h5>
                      <p className="text-xs text-muted-foreground mt-0.5">{preset.q}</p>
                    </div>
                    <Button 
                      size="sm" 
                      onClick={() => handleRunInChat(preset.q)}
                      className="gap-1 text-xs shrink-0 ml-3"
                    >
                      Run
                      <ExternalLink className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
