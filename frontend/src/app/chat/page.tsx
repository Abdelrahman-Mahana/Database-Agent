"use client";

import { useState, useEffect, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { apiClient } from "@/services/api";
import { SchemaResponse, ChatResponse } from "@/types/api";
import { useAppStore } from "@/store/useAppStore";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  MessageSquare,
  Send,
  Bot,
  User,
  Code,
  Table as TableIcon,
  Sparkles,
  Trash2,
  Copy,
  Check,
  AlertTriangle,
  Lightbulb,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  BarChart3,
  LineChart as LineIcon,
  PieChart as PieIcon,
  TrendingUp
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid
} from "recharts";

const CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#6366f1'];

interface MessageItem {
  id: string;
  sender: "user" | "assistant";
  text: string;
  response?: ChatResponse;
  timestamp: string;
  questionLang?: "ar" | "en";
}

// Detect if text contains Arabic characters
function isArabicText(text?: string): boolean {
  if (!text) return false;
  return /[\u0600-\u06FF]/.test(text);
}

// Helper to safely parse inline markdown formatting (bold **text** and backticks `code`)
function parseInlineFormatting(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*.*?\*\*|`.*?`)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
      return (
        <strong key={index} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      return (
        <code key={index} className="px-1.5 py-0.5 rounded bg-muted/60 text-sky-400 font-mono text-xs mx-0.5 inline-block">
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

// Dedicated visual formatter for Analyst Reports to ensure stunning typography and question-aligned layout
function FormattedReportText({ text, isRtl }: { text: string; isRtl: boolean }) {
  if (!text) return null;
  const lines = text.split("\n");

  return (
    <div dir={isRtl ? "rtl" : "ltr"} className={cn("space-y-2 text-sm leading-relaxed w-full", isRtl ? "text-right font-sans" : "text-left font-sans")}>
      {lines.map((line, idx) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={idx} className="h-2" />;

        // Headings (#, ##, ###)
        if (trimmed.startsWith("#")) {
          const content = trimmed.replace(/^#+\s*/, "").replace(/\s*#+$/, "");
          return (
            <h3
              key={idx}
              dir={isRtl ? "rtl" : "ltr"}
              className={cn(
                "flex items-center gap-2 font-bold text-base md:text-lg text-primary pt-3 pb-1.5 mb-2 border-b border-border/40 first:pt-0 w-full",
                isRtl ? "text-right font-sans" : "text-left"
              )}
            >
              <span className="inline-block w-1.5 h-4 bg-sky-400 rounded-full shrink-0" />
              <span>{content}</span>
            </h3>
          );
        }

        // List items (- or * or • or numbered items like 1. 2.)
        const isBullet = /^[-\*•]\s+/.test(trimmed);
        const isNumber = /^\d+\.\s+/.test(trimmed);
        if (isBullet || isNumber) {
          const bulletMatch = trimmed.match(/^([-\*•]|\d+\.)\s+(.*)/);
          const bulletSymbol = bulletMatch ? bulletMatch[1] : "•";
          const bulletText = bulletMatch ? bulletMatch[2] : trimmed;

          return (
            <div
              key={idx}
              dir={isRtl ? "rtl" : "ltr"}
              className={cn(
                "flex items-start gap-2.5 my-1.5 text-sm w-full",
                isRtl ? "text-right pr-2 font-sans" : "text-left pl-2"
              )}
            >
              <span className="text-sky-400 font-bold shrink-0 mt-0.5 text-xs select-none">
                {isNumber ? bulletSymbol : "•"}
              </span>
              <span className={cn("flex-1 leading-relaxed", isRtl ? "text-right font-sans" : "text-left")}>
                {parseInlineFormatting(bulletText)}
              </span>
            </div>
          );
        }

        // Normal paragraphs and italicized system notes
        const isNote = trimmed.startsWith("*Note:") || trimmed.startsWith("*ملاحظة") || trimmed.startsWith("ملاحظة:");
        return (
          <p
            key={idx}
            dir={isRtl ? "rtl" : "ltr"}
            className={cn(
              "whitespace-pre-wrap leading-relaxed w-full",
              isNote ? "text-xs text-muted-foreground italic bg-muted/20 p-2.5 rounded-lg border border-border/40" : "",
              isRtl ? "text-right font-sans" : "text-left"
            )}
          >
            {parseInlineFormatting(trimmed)}
          </p>
        );
      })}
    </div>
  );
}

function QueryResultSection({
  response,
  index,
  copyToClipboard,
  copiedIndex,
  isRtl,
  preferences = {}
}: {
  response: ChatResponse;
  index: number;
  copyToClipboard: (code: string, idx: number) => void;
  copiedIndex: number | null;
  isRtl: boolean;
  preferences?: Record<string, any>;
}) {
  const [showSql, setShowSql] = useState(Boolean(preferences.showSqlDefault));
  const [showResults, setShowResults] = useState(Boolean(preferences.showTableDefault));
  const [showChart, setShowChart] = useState(true);

  // Chart suggestion parsing & data preparation
  const hasChartSuggestion = Boolean(
    response.chart_suggestion &&
    response.chart_suggestion.should_chart &&
    response.results &&
    response.results.length > 0
  );
  const suggestedType = response.chart_suggestion?.chart_type;
  const initialChartType = (suggestedType === "line" || suggestedType === "pie" || suggestedType === "bar") ? suggestedType : "bar";
  const [activeChartType, setActiveChartType] = useState<"bar" | "line" | "pie">(initialChartType as any);

  const keys = response.results && response.results.length > 0 ? Object.keys(response.results[0]) : [];
  let xCol = response.chart_suggestion?.x_column || (keys.length > 0 ? keys[0] : "");
  let yCol = response.chart_suggestion?.y_column || (keys.length > 1 ? keys[1] : (keys.length > 0 ? keys[0] : ""));
  const findKey = (name: string) => keys.find(k => k.toLowerCase() === name.toLowerCase()) || name;
  xCol = findKey(xCol);
  yCol = findKey(yCol);

  const chartData = hasChartSuggestion && response.results
    ? response.results.slice(0, 25).map((row, idx) => {
      const rawVal = row[yCol];
      const numVal = typeof rawVal === "number" ? rawVal : parseFloat(String(rawVal).replace(/[^0-9.-]+/g, ""));
      const finalVal = isNaN(numVal) ? 0 : numVal;
      const labelVal = row[xCol] !== undefined && row[xCol] !== null ? String(row[xCol]) : `#${idx + 1}`;
      return { ...row, _x: labelVal, _y: finalVal };
    })
    : [];

  return (
    <div className="space-y-3 pt-3 border-t border-border/40 w-full" dir={isRtl ? "rtl" : "ltr"}>
      {/* Analytical Chart Visualizer (Shown automatically when AI determines a chart is helpful) */}
      {hasChartSuggestion && (
        <div className="rounded-xl border border-border/60 bg-card overflow-hidden shadow-sm w-full mb-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 px-4 py-3 bg-muted/20 border-b border-border/40">
            <div className="flex items-center justify-between w-full sm:w-auto">
              <div className="flex items-center gap-2 text-foreground font-semibold font-sans text-xs sm:text-sm">
                <TrendingUp className="h-4 w-4 text-emerald-400 shrink-0" />
                <span>
                  {isRtl
                    ? `التحليل البياني (${yCol} مقابل ${xCol})`
                    : `Analytical Chart (${yCol} by ${xCol})`}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setShowChart(!showChart)}
                className="sm:hidden text-[11px] text-muted-foreground px-2 py-1 bg-muted/40 rounded-md hover:text-foreground font-sans"
              >
                {showChart ? (isRtl ? "إخفاء" : "Hide") : (isRtl ? "عرض" : "Show")}
              </button>
            </div>

            <div className="flex items-center justify-between sm:justify-end gap-2 w-full sm:w-auto">
              {/* Chart Type Selector */}
              <div className="flex items-center gap-1 bg-muted/40 p-1 rounded-lg border border-border/40">
                <button
                  type="button"
                  onClick={() => setActiveChartType("bar")}
                  className={`px-2 py-1 rounded text-[11px] font-sans transition-colors flex items-center gap-1 ${activeChartType === "bar" ? "bg-primary text-primary-foreground shadow font-medium" : "text-muted-foreground hover:text-foreground"
                    }`}
                  title={isRtl ? "أعمدة بيانية" : "Bar Chart"}
                >
                  <BarChart3 className="h-3 w-3 shrink-0" />
                  <span>{isRtl ? "أعمدة" : "Bar"}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveChartType("line")}
                  className={`px-2 py-1 rounded text-[11px] font-sans transition-colors flex items-center gap-1 ${activeChartType === "line" ? "bg-primary text-primary-foreground shadow font-medium" : "text-muted-foreground hover:text-foreground"
                    }`}
                  title={isRtl ? "منحنى الاتجاه" : "Line Chart"}
                >
                  <LineIcon className="h-3 w-3 shrink-0" />
                  <span>{isRtl ? "اتجاه" : "Line"}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveChartType("pie")}
                  className={`px-2 py-1 rounded text-[11px] font-sans transition-colors flex items-center gap-1 ${activeChartType === "pie" ? "bg-primary text-primary-foreground shadow font-medium" : "text-muted-foreground hover:text-foreground"
                    }`}
                  title={isRtl ? "توزيع نسبي" : "Pie Chart"}
                >
                  <PieIcon className="h-3 w-3 shrink-0" />
                  <span>{isRtl ? "توزيع" : "Pie"}</span>
                </button>
              </div>

              <button
                type="button"
                onClick={() => setShowChart(!showChart)}
                className="hidden sm:flex items-center gap-1 text-[11px] text-muted-foreground px-2.5 py-1.5 bg-muted/40 rounded-md hover:text-foreground font-sans transition-colors shrink-0"
              >
                {showChart ? (
                  <>
                    <EyeOff className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                    <span>{isRtl ? "إخفاء الرسم" : "Hide Chart"}</span>
                  </>
                ) : (
                  <>
                    <Eye className="h-3.5 w-3.5 text-sky-400 shrink-0" />
                    <span>{isRtl ? "عرض الرسم" : "Show Chart"}</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {showChart && (
            <div className="p-4 pt-4 bg-card/60">
              <div className="h-64 md:h-72 w-full" dir="ltr">
                <ResponsiveContainer width="100%" height="100%">
                  {activeChartType === "bar" ? (
                    <BarChart data={chartData} margin={{ top: 10, right: 15, left: -10, bottom: 25 }}>
                      <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                      <XAxis dataKey="_x" stroke="#888888" fontSize={11} tickLine={false} axisLine={false} angle={-20} textAnchor="end" interval={0} height={50} />
                      <YAxis stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "#18181b", borderColor: "#27272a", borderRadius: "8px", fontSize: "12px", color: "#fff" }}
                        formatter={(val: any) => [val, yCol]}
                        labelFormatter={(label: any) => `${xCol}: ${label}`}
                      />
                      <Bar dataKey="_y" name={yCol} fill="#3b82f6" radius={[6, 6, 0, 0]}>
                        {chartData.map((_, index) => (
                          <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  ) : activeChartType === "line" ? (
                    <LineChart data={chartData} margin={{ top: 10, right: 15, left: -10, bottom: 25 }}>
                      <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                      <XAxis dataKey="_x" stroke="#888888" fontSize={11} tickLine={false} axisLine={false} angle={-20} textAnchor="end" interval={0} height={50} />
                      <YAxis stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "#18181b", borderColor: "#27272a", borderRadius: "8px", fontSize: "12px", color: "#fff" }}
                        formatter={(val: any) => [val, yCol]}
                        labelFormatter={(label: any) => `${xCol}: ${label}`}
                      />
                      <Line type="monotone" dataKey="_y" name={yCol} stroke="#10b981" strokeWidth={2.5} dot={{ r: 4, fill: "#10b981" }} activeDot={{ r: 6 }} />
                    </LineChart>
                  ) : (
                    <PieChart>
                      <Pie
                        data={chartData}
                        cx="50%"
                        cy="50%"
                        innerRadius={55}
                        outerRadius={85}
                        paddingAngle={3}
                        dataKey="_y"
                        nameKey="_x"
                      >
                        {chartData.map((_, index) => (
                          <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ backgroundColor: "#18181b", borderColor: "#27272a", borderRadius: "8px", fontSize: "12px", color: "#fff" }}
                        formatter={(val: any) => [val, yCol]}
                      />
                      <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
                    </PieChart>
                  )}
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Generated SQL Section - Collapsible (Default Hidden) */}
      {response.sql && (
        <div className="rounded-xl border border-border/60 bg-black/40 overflow-hidden shadow-sm w-full">
          <button
            type="button"
            onClick={() => setShowSql(!showSql)}
            className={cn(
              "w-full flex items-center justify-between px-4 py-2.5 bg-muted/20 hover:bg-muted/40 transition-colors text-xs font-mono text-muted-foreground",
              isRtl && "font-sans"
            )}
          >
            <div className="flex items-center gap-2 text-foreground font-semibold font-sans">
              <Code className="h-4 w-4 text-sky-400 shrink-0" />
              <span>{isRtl ? "استعلام SQL المُولّد" : "Generated SQL Query"}</span>
            </div>
            <div className="flex items-center gap-2 bg-muted/40 px-2.5 py-1 rounded-md text-[11px] text-muted-foreground hover:text-foreground font-sans">
              {showSql ? (
                <>
                  <EyeOff className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                  <span>{isRtl ? "إخفاء الاستعلام" : "Hide SQL"}</span>
                  <ChevronDown className="h-3.5 w-3.5 ml-0.5 shrink-0" />
                </>
              ) : (
                <>
                  <Eye className="h-3.5 w-3.5 text-sky-400 shrink-0" />
                  <span>{isRtl ? "عرض الاستعلام" : "Show SQL"}</span>
                  <ChevronRight className={cn("h-3.5 w-3.5 shrink-0", isRtl ? "mr-0.5 rotate-180" : "ml-0.5")} />
                </>
              )}
            </div>
          </button>

          {showSql && (
            <div className="border-t border-border/40">
              <div className={cn("flex items-center px-4 py-1.5 bg-muted/10 border-b border-border/30", isRtl ? "justify-start" : "justify-end")}>
                <button
                  type="button"
                  onClick={() => copyToClipboard(response.sql!, index)}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors font-sans"
                >
                  {copiedIndex === index ? (
                    <>
                      <Check className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                      <span>{isRtl ? "تم النسخ" : "Copied SQL"}</span>
                    </>
                  ) : (
                    <>
                      <Copy className="h-3.5 w-3.5 shrink-0" />
                      <span>{isRtl ? "نسخ الاستعلام" : "Copy SQL"}</span>
                    </>
                  )}
                </button>
              </div>
              <pre className="p-4 text-xs font-mono text-emerald-300 overflow-x-auto whitespace-pre-wrap leading-relaxed text-left" dir="ltr">
                {response.sql}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Query Error Banner */}
      {!response.success && response.error && (
        <div className={cn("p-3.5 rounded-xl bg-destructive/10 text-destructive border border-destructive/20 text-xs flex items-start gap-2.5", isRtl && "text-right font-sans")}>
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">{isRtl ? "فشل تنفيذ الاستعلام" : "Query Execution Failed"}</p>
            <p className="opacity-90 mt-0.5">{response.error}</p>
          </div>
        </div>
      )}

      {/* Results Table Section - Collapsible (Default Hidden) */}
      {response.results && response.results.length > 0 && (
        <div className="rounded-xl border border-border/60 bg-card overflow-hidden shadow-sm w-full">
          <button
            type="button"
            onClick={() => setShowResults(!showResults)}
            className={cn(
              "w-full flex items-center justify-between px-4 py-2.5 bg-muted/20 hover:bg-muted/40 transition-colors text-xs font-mono text-muted-foreground",
              isRtl && "font-sans"
            )}
          >
            <div className="flex items-center gap-2 text-foreground font-semibold font-sans">
              <TableIcon className="h-4 w-4 text-sky-500 shrink-0" />
              <span>{isRtl ? `نتائج الاستعلام (${response.results.length} صف)` : `Query Results (${response.results.length} rows)`}</span>
            </div>
            <div className="flex items-center gap-2 bg-muted/40 px-2.5 py-1 rounded-md text-[11px] text-muted-foreground hover:text-foreground font-sans">
              {showResults ? (
                <>
                  <EyeOff className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                  <span>{isRtl ? "إخفاء الجدول" : "Hide Table"}</span>
                  <ChevronDown className="h-3.5 w-3.5 ml-0.5 shrink-0" />
                </>
              ) : (
                <>
                  <Eye className="h-3.5 w-3.5 text-sky-500 shrink-0" />
                  <span>{isRtl ? "عرض الجدول" : "Show Table"}</span>
                  <ChevronRight className={cn("h-3.5 w-3.5 shrink-0", isRtl ? "mr-0.5 rotate-180" : "ml-0.5")} />
                </>
              )}
            </div>
          </button>

          {showResults && (
            <div className="border-t border-border/40 p-2 overflow-x-auto max-h-96 overflow-y-auto">
              <table className="w-full text-xs border-collapse">
                <thead className="bg-muted/60 border-b border-border/50 sticky top-0 font-mono text-[11px] text-muted-foreground">
                  <tr>
                    {Object.keys(response.results[0]).map((key) => (
                      <th key={key} className={cn("py-2.5 px-3.5 font-sans", isRtl ? "text-right" : "text-left")}>{key}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30">
                  {response.results.slice(0, Number(preferences.maxRowsLimit) || 100).map((row, rIdx) => (
                    <tr key={rIdx} className="hover:bg-muted/20 transition-colors">
                      {Object.values(row).map((val: any, cIdx) => (
                        <td key={cIdx} className={cn("py-2.5 px-3.5 font-mono text-[11px]", isRtl ? "text-right font-sans" : "text-left")}>
                          {val === null ? <span className="text-muted-foreground/40 italic">null</span> : String(val)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Follow-up Suggestions Chips */}
      {response.suggestions && response.suggestions.length > 0 && (
        <div className="pt-2 flex flex-wrap gap-2">
          {response.suggestions.map((sug, sIdx) => (
            <button
              key={sIdx}
              type="button"
              className={cn(
                "text-xs bg-secondary/80 hover:bg-secondary text-secondary-foreground px-3 py-1.5 rounded-full transition-colors flex items-center gap-1.5 border border-border/40 font-medium",
                isRtl && "font-sans"
              )}
            >
              <Sparkles className="h-3.5 w-3.5 text-sky-400 shrink-0" />
              <span>{sug}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ChatContent() {
  const searchParams = useSearchParams();
  const initialPrompt = searchParams.get("prompt") || "";

  const { activeDatabase } = useAppStore();
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Fetch recommended questions from active schema
  const { data: schemaData } = useQuery<SchemaResponse>({
    queryKey: ['schema', activeDatabase],
    queryFn: async () => {
      const res = await apiClient.get('/schema');
      return res.data;
    },
  });

  // Fetch user settings & display defaults
  const { data: prefData } = useQuery({
    queryKey: ['user-preferences', 'default_user'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/memory/preferences?user_id=default_user');
        return res.data?.preferences || {};
      } catch (e) {
        return {};
      }
    },
  });
  const preferences = prefData || {};

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Handle URL query parameter pre-fill
  useEffect(() => {
    if (initialPrompt && messages.length === 0) {
      handleSendMessage(initialPrompt);
    }
  }, [initialPrompt]);

  const chatMutation = useMutation({
    mutationFn: async (messageText: string) => {
      const res = await apiClient.post('/chat', {
        message: messageText,
        session_id: "default_session",
      });
      return res.data as ChatResponse;
    },
    onSuccess: (data, messageText) => {
      const qLang: "ar" | "en" = isArabicText(messageText) ? "ar" : "en";
      const fallbackText = qLang === "ar"
        ? (data.success ? "تم تحليل البيانات بنجاح." : "فشل تنفيذ استعلام SQL.")
        : (data.success ? "Analysis complete." : "SQL query execution failed.");

      const assistantMsg: MessageItem = {
        id: `assistant-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
        sender: "assistant",
        text: data.answer || data.report || fallbackText,
        response: data,
        questionLang: qLang,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      setMessages((prev) => [...prev, assistantMsg]);
    },
    onError: (error: any, messageText: string) => {
      const isAr = isArabicText(messageText);
      const qLang: "ar" | "en" = isAr ? "ar" : "en";
      const rawError = error.response?.data?.detail || error.message || "";
      const isTimeout = rawError.includes("timeout") || rawError.includes("Network Error") || rawError.includes("ERR_NETWORK");
      let text = "";
      if (isTimeout) {
        text = isAr
          ? "استغرقت عملية تحليل البيانات وكتابة التقرير وقتًا أطول من المتوقع (Timeout). يُرجى إعادة محاولة إرسال السؤال مرة أخرى."
          : "Data analysis and report generation took longer than expected (Timeout). Please try submitting your question again.";
      } else {
        text = isAr
          ? `حدث خطأ أثناء معالجة طلبك: ${rawError}`
          : `Error processing request: ${rawError}`;
      }

      const errorMsg: MessageItem = {
        id: `error-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
        sender: "assistant",
        text,
        questionLang: qLang,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    },
  });

  const handleSendMessage = (textToSend?: string) => {
    const queryText = (textToSend || inputMessage).trim();
    if (!queryText || chatMutation.isPending) return;

    const userLang: "ar" | "en" = isArabicText(queryText) ? "ar" : "en";
    const userMsg: MessageItem = {
      id: `user-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
      sender: "user",
      text: queryText,
      questionLang: userLang,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };


    setMessages((prev) => [...prev, userMsg]);
    if (!textToSend) setInputMessage("");

    chatMutation.mutate(queryText);
  };

  const handleClearHistory = async () => {
    try {
      await apiClient.delete('/chat/history?session_id=default_session');
    } catch (e) {
      // ignore clear errors
    }
    setMessages([]);
  };

  const copyToClipboard = (code: string, idx: number) => {
    navigator.clipboard.writeText(code);
    setCopiedIndex(idx);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const isInputRtl = isArabicText(inputMessage);
  const latestMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  const isLoadingRtl = latestMessage ? (latestMessage.questionLang === "ar" || isArabicText(latestMessage.text)) : false;

  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-full space-y-4">
      {/* Top Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-4 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary shadow-sm">
            <Bot className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-xl font-bold tracking-tight flex items-center gap-2">
              AI Database Analyst
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 font-mono font-medium">
                {schemaData?.database_name || "Connected"}
              </span>
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Ask questions in natural language to query, analyze, and visualize data.
            </p>
          </div>
        </div>
        {messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={handleClearHistory} className="gap-1.5 text-xs text-muted-foreground hover:text-destructive">
            <Trash2 className="h-3.5 w-3.5" />
            Clear Chat
          </Button>
        )}
      </div>

      {/* Messages Scroll Container */}
      <div className="flex-1 overflow-y-auto space-y-6 pr-2">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 space-y-6">
            <div className="h-16 w-16 rounded-2xl bg-primary/10 text-primary flex items-center justify-center shadow-inner">
              <Sparkles className="h-8 w-8" />
            </div>
            <div className="max-w-md space-y-2">
              <h3 className="text-lg font-bold">Ask anything about your database</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                The agent automatically converts natural language into optimized SQL, executes it against <strong>{schemaData?.database_name || "your database"}</strong>, and formats insights.
              </p>
            </div>

            {/* Quick Starter Cards */}
            {schemaData?.recommended_questions && schemaData.recommended_questions.length > 0 && (
              <div className="w-full max-w-3xl grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
                {schemaData.recommended_questions.slice(0, 4).map((q: any, i: number) => {
                  const isObj = typeof q === 'object' && q !== null;
                  const queryText = isObj ? (q.query || q.title) : q;
                  const titleText = isObj ? q.title : q;
                  const descText = isObj ? q.desc : null;
                  const isCardRtl = isArabicText(titleText || queryText);

                  return (
                    <button
                      key={i}
                      type="button"
                      dir={isCardRtl ? "rtl" : "ltr"}
                      onClick={() => handleSendMessage(queryText)}
                      className={cn(
                        "p-4 rounded-xl border border-border/60 bg-card hover:bg-muted/40 transition-all group flex flex-col justify-between space-y-2 shadow-sm",
                        isCardRtl ? "text-right" : "text-left"
                      )}
                    >
                      <div className="flex items-start justify-between w-full">
                        <span className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors flex items-center gap-2">
                          <Lightbulb className="h-4 w-4 text-amber-500 shrink-0" />
                          <span className="truncate">{titleText}</span>
                        </span>
                        <ArrowRight className={cn("h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0", isCardRtl && "rotate-180")} />
                      </div>
                      {descText && (
                        <p className="text-xs text-muted-foreground line-clamp-2">{descText}</p>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          messages.map((msg, index) => {
            const isRtl = msg.questionLang ? msg.questionLang === "ar" : isArabicText(msg.text);

            return (
              <div
                key={`${msg.id || 'msg'}-${index}`}
                className={`flex gap-3 ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
              >

                {msg.sender === "assistant" && (
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground font-semibold text-xs mt-1 shadow">
                    <Bot className="h-4 w-4" />
                  </div>
                )}

                <div className={`space-y-3 w-full ${msg.sender === "user" ? "max-w-xl items-end" : "max-w-5xl items-start"}`}>
                  {/* Text Bubble */}
                  <div
                    dir={isRtl ? "rtl" : "ltr"}
                    className={cn(
                      "p-4 rounded-2xl text-sm leading-relaxed transition-all",
                      isRtl ? "text-right font-sans" : "text-left",
                      msg.sender === "user"
                        ? "bg-primary text-primary-foreground rounded-tr-none ml-auto shadow font-medium"
                        : "bg-card border border-border/60 rounded-tl-none shadow-sm space-y-3 text-foreground w-full"
                    )}
                  >
                    {msg.sender === "assistant" ? (
                      <>
                        {msg.response?.warnings && msg.response.warnings.length > 0 && (
                          <div className="mb-4 space-y-2">
                            {msg.response.warnings.map((w, idx) => (
                              <div key={idx} className="p-3 bg-amber-500/10 border border-amber-500/20 text-amber-500 rounded-md text-sm flex items-start gap-2">
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
                                <span>{w}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        <FormattedReportText text={msg.text} isRtl={isRtl} />
                      </>
                    ) : (
                      <p className="whitespace-pre-wrap">{msg.text}</p>
                    )}

                    {/* Assistant Extended Output (Collapsible SQL & Data Table) */}
                    {msg.sender === "assistant" && msg.response && (
                      <QueryResultSection
                        response={msg.response}
                        index={index}
                        copyToClipboard={copyToClipboard}
                        copiedIndex={copiedIndex}
                        isRtl={isRtl}
                        preferences={preferences}
                      />
                    )}
                  </div>

                  <span className={cn("text-[10px] text-muted-foreground px-1 block", isRtl ? "text-right" : "text-left")}>
                    {msg.timestamp}
                  </span>
                </div>

                {msg.sender === "user" && (
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground font-semibold text-xs mt-1 shadow">
                    <User className="h-4 w-4" />
                  </div>
                )}
              </div>
            );
          })
        )}

        {/* Pending Loading State */}
        {chatMutation.isPending && (
          <div className="flex gap-3 justify-start">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground font-semibold text-xs mt-1 animate-pulse">
              <Bot className="h-4 w-4" />
            </div>
            <div
              dir={isLoadingRtl ? "rtl" : "ltr"}
              className={cn(
                "p-4 rounded-2xl bg-card border border-border/60 rounded-tl-none shadow-sm space-y-2 max-w-sm",
                isLoadingRtl ? "text-right font-sans" : "text-left"
              )}
            >
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <Sparkles className="h-3.5 w-3.5 text-primary animate-spin shrink-0" />
                <span>
                  {isLoadingRtl ? "جاري تحليل الجداول وتنفيذ الاستعلام وكتابة التقرير..." : "Analyzing schema & executing SQL query..."}
                </span>
              </div>
              <div className="h-2 bg-muted/60 rounded-full animate-pulse w-3/4" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Box */}
      <div className="shrink-0 pt-2 border-t border-border/40">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="flex gap-2"
        >
          <Input
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            dir={isInputRtl ? "rtl" : "ltr"}
            placeholder={isInputRtl ? "اسأل سؤالاً" : "Ask a question"}
            className={cn(
              "flex-1 h-11 text-sm bg-card shadow-sm transition-all",
              isInputRtl ? "text-right font-sans" : "text-left"
            )}
            disabled={chatMutation.isPending}
          />
          <Button
            type="submit"
            disabled={chatMutation.isPending || !inputMessage.trim()}
            className="h-11 px-5 gap-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow"
          >
            <Send className="h-4 w-4" />
            <span className="hidden sm:inline">Send</span>
          </Button>
        </form>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={
      <div className="flex-1 flex items-center justify-center p-12 text-muted-foreground">
        Loading Chat Interface...
      </div>
    }>
      <ChatContent />
    </Suspense>
  );
}
