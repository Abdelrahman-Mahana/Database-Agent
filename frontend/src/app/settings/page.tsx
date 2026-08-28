"use client";

/* eslint-disable @typescript-eslint/no-explicit-any, react-hooks/set-state-in-effect */

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/services/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { 
  Settings as SettingsIcon, 
  Languages, 
  ShieldCheck, 
  Save, 
  Check, 
  Eye, 
  RotateCcw, 
  RefreshCw, 
  Play, 
  Bot
} from "lucide-react";

const USER_ID = "default_user";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [savedSuccess, setSavedSuccess] = useState(false);

  // Settings State
  const [language, setLanguage] = useState("auto");
  const [arabicDialect, setArabicDialect] = useState("egyptian");
  const [reportTone, setReportTone] = useState("executive");
  const [preferredChart, setPreferredChart] = useState("bar");
  const [showSqlDefault, setShowSqlDefault] = useState(false);
  const [showTableDefault, setShowTableDefault] = useState(false);
  const [maxRowsLimit, setMaxRowsLimit] = useState(100);
  const [timeoutSeconds, setTimeoutSeconds] = useState(180);

  // Live preview state
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [previewData, setPreviewData] = useState<{ preview_text: string; language_detected: string; dialect: string; tone: string } | null>(null);

  // Fetch long-term memory preferences
  const { data: prefData } = useQuery({
    queryKey: ['user-preferences', USER_ID],
    queryFn: async () => {
      const res = await apiClient.get(`/memory/preferences?user_id=${USER_ID}`);
      return res.data;
    },
  });

  useEffect(() => {
    if (prefData?.preferences) {
      const p = prefData.preferences;
      if (p.language) setLanguage(p.language);
      if (p.arabicDialect) setArabicDialect(p.arabicDialect);
      if (p.reportTone) setReportTone(p.reportTone);
      if (p.preferredChart) setPreferredChart(p.preferredChart);
      if (typeof p.showSqlDefault === 'boolean') setShowSqlDefault(p.showSqlDefault);
      if (typeof p.showTableDefault === 'boolean') setShowTableDefault(p.showTableDefault);
      if (p.maxRowsLimit) setMaxRowsLimit(p.maxRowsLimit);
      if (p.timeoutSeconds) setTimeoutSeconds(p.timeoutSeconds);
    }
  }, [prefData]);

  // Preference update mutation
  const prefMutation = useMutation({
    mutationFn: async (payload: { key: string; value: any }) => {
      await apiClient.put('/memory/preferences', {
        user_id: USER_ID,
        ...payload
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-preferences', USER_ID] });
    }
  });

  const handleSaveAll = async (e: React.FormEvent) => {
    e.preventDefault();
    // Run sequentially to prevent race conditions on the backend's read-modify-write cycle
    const updates = [
      { key: "language", value: language },
      { key: "arabicDialect", value: arabicDialect },
      { key: "reportTone", value: reportTone },
      { key: "preferredChart", value: preferredChart },
      { key: "showSqlDefault", value: showSqlDefault },
      { key: "showTableDefault", value: showTableDefault },
      { key: "maxRowsLimit", value: maxRowsLimit },
      { key: "timeoutSeconds", value: timeoutSeconds },
    ];
    for (const update of updates) {
      await prefMutation.mutateAsync(update);
    }

    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 3000);
  };

  const handleResetDefaults = async () => {
    setLanguage("auto");
    setArabicDialect("egyptian");
    setReportTone("executive");
    setPreferredChart("bar");
    setShowSqlDefault(false);
    setShowTableDefault(false);
    setMaxRowsLimit(100);
    setTimeoutSeconds(180);

    const updates = [
      { key: "language", value: "auto" },
      { key: "arabicDialect", value: "egyptian" },
      { key: "reportTone", value: "executive" },
      { key: "preferredChart", value: "bar" },
      { key: "showSqlDefault", value: false },
      { key: "showTableDefault", value: false },
      { key: "maxRowsLimit", value: 100 },
      { key: "timeoutSeconds", value: 180 },
    ];
    for (const update of updates) {
      await prefMutation.mutateAsync(update);
    }
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 3000);
  };

  const handlePreviewTone = async () => {
    try {
      setIsPreviewing(true);
      const res = await apiClient.post("/memory/preferences/preview", {
        language,
        arabic_dialect: arabicDialect,
        report_tone: reportTone
      });
      setPreviewData(res.data);
    } catch (err) {
      console.error("Preview failed:", err);
    } finally {
      setIsPreviewing(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-full space-y-6 overflow-y-auto pr-1">
      {/* Top Banner Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/40 pb-5">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2.5">
            <SettingsIcon className="h-7 w-7 text-primary" />
            System & Agent Settings
          </h2>
          <p className="text-muted-foreground text-sm mt-1">
            Configure language preferences, dialect matching, report formatting, and security guardrails.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="outline" size="sm" onClick={handleResetDefaults} className="gap-1.5 text-xs">
            <RotateCcw className="h-3.5 w-3.5" />
            Reset Defaults
          </Button>
          <Button onClick={handleSaveAll} size="sm" className="gap-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow">
            {savedSuccess ? <Check className="h-4 w-4 text-emerald-400" /> : <Save className="h-4 w-4" />}
            {savedSuccess ? "Preferences Saved!" : "Save Preferences"}
          </Button>
        </div>
      </div>

      {/* Main Settings Form */}
      <form onSubmit={handleSaveAll} className="grid gap-6 grid-cols-1 lg:grid-cols-2">
        {/* Language & Dialect Matching */}
        <Card className="border-border/60">
          <CardHeader>
            <CardTitle className="text-base font-bold flex items-center gap-2">
              <Languages className="h-4 w-4 text-sky-400" />
              Language & Dialect Preferences
            </CardTitle>
            <CardDescription>
              Control response language and colloquial Arabic dialect mirroring.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="language" className="text-xs font-semibold">Response Language</Label>
              <select
                id="language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full h-10 rounded-md border border-input bg-card px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="auto">Auto-Detect (Match User Question Language)</option>
                <option value="ar">Arabic (العربية)</option>
                <option value="en">English</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="arabicDialect" className="text-xs font-semibold">Preferred Arabic Dialect</Label>
              <select
                id="arabicDialect"
                value={arabicDialect}
                onChange={(e) => setArabicDialect(e.target.value)}
                className="w-full h-10 rounded-md border border-input bg-card px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="egyptian">Egyptian Arabic (اللهجة المصرية - عاوز/ازاي)</option>
                <option value="gulf">Gulf Arabic (اللهجة الخليجية - أبي/وش)</option>
                <option value="levantine">Levantine Arabic (اللهجة الشامية - بدي/كيف)</option>
                <option value="north_african">North African (اللهجة المغاربية)</option>
                <option value="msa">Modern Standard Arabic (الفصحى)</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="reportTone" className="text-xs font-semibold">Analyst Report Tone</Label>
              <select
                id="reportTone"
                value={reportTone}
                onChange={(e) => setReportTone(e.target.value)}
                className="w-full h-10 rounded-md border border-input bg-card px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="executive">Executive Briefing (Direct, High-Level Summary)</option>
                <option value="technical">Detailed Technical (Deep Metrics Breakdown)</option>
                <option value="concise">Concise Bullet Points</option>
              </select>
            </div>
          </CardContent>
        </Card>

        {/* Data Display & Collapsible Defaults */}
        <Card className="border-border/60">
          <CardHeader>
            <CardTitle className="text-base font-bold flex items-center gap-2">
              <Eye className="h-4 w-4 text-emerald-400" />
              Chat & Display Defaults
            </CardTitle>
            <CardDescription>
              Configure default visibility for SQL code blocks and raw result tables.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex items-center justify-between p-3 rounded-xl border border-border/40 bg-muted/10">
              <div>
                <Label className="text-xs font-semibold">Expand Generated SQL by Default</Label>
                <p className="text-[11px] text-muted-foreground mt-0.5">Automatically show generated SQL code when query results arrive.</p>
              </div>
              <input
                type="checkbox"
                checked={showSqlDefault}
                onChange={(e) => setShowSqlDefault(e.target.checked)}
                className="h-4 w-4 rounded border-input bg-card text-primary focus:ring-primary"
              />
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl border border-border/40 bg-muted/10">
              <div>
                <Label className="text-xs font-semibold">Expand Results Data Table by Default</Label>
                <p className="text-[11px] text-muted-foreground mt-0.5">Automatically show query results table rows when response arrives.</p>
              </div>
              <input
                type="checkbox"
                checked={showTableDefault}
                onChange={(e) => setShowTableDefault(e.target.checked)}
                className="h-4 w-4 rounded border-input bg-card text-primary focus:ring-primary"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="preferredChart" className="text-xs font-semibold">Default Visualization Preference</Label>
              <select
                id="preferredChart"
                value={preferredChart}
                onChange={(e) => setPreferredChart(e.target.value)}
                className="w-full h-10 rounded-md border border-input bg-card px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="bar">Bar Chart (Categorical Comparisons)</option>
                <option value="line">Line Chart (Time Series Trends)</option>
                <option value="pie">Pie Chart (Proportional Distribution)</option>
                <option value="auto">Automatic (Rule-based Heuristic)</option>
              </select>
            </div>
          </CardContent>
        </Card>

        {/* Security & Query Execution Limits */}
        <Card className="border-border/60 lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base font-bold flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-amber-400" />
              Security & Query Execution Limits
            </CardTitle>
            <CardDescription>
              Enforce timeouts, maximum row truncation, and read-only database isolation.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="maxRowsLimit" className="text-xs font-semibold">Maximum Displayed Rows</Label>
              <select
                id="maxRowsLimit"
                value={maxRowsLimit}
                onChange={(e) => setMaxRowsLimit(Number(e.target.value))}
                className="w-full h-10 rounded-md border border-input bg-card px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value={50}>50 Rows Limit</option>
                <option value={100}>100 Rows Limit (Recommended)</option>
                <option value={500}>500 Rows Limit</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="timeoutSeconds" className="text-xs font-semibold">API Execution Timeout</Label>
              <select
                id="timeoutSeconds"
                value={timeoutSeconds}
                onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
                className="w-full h-10 rounded-md border border-input bg-card px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value={60}>60 Seconds (1 Minute)</option>
                <option value={180}>180 Seconds (3 Minutes - Standard)</option>
                <option value={300}>300 Seconds (5 Minutes - Deep Analysis)</option>
              </select>
            </div>

            <div className="p-3 rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-400 space-y-1">
              <h5 className="font-semibold text-xs flex items-center gap-1.5">
                <ShieldCheck className="h-4 w-4" />
                Read-Only Mode Lock
              </h5>
              <p className="text-[11px] opacity-90 leading-tight">
                All queries executed by the agent are enforced read-only (SELECT queries only).
              </p>
            </div>
          </CardContent>

          <CardFooter className="flex justify-end pt-2 border-t border-border/30">
            <Button type="submit" className="gap-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow">
              {savedSuccess ? <Check className="h-4 w-4 text-emerald-400" /> : <Save className="h-4 w-4" />}
              {savedSuccess ? "Preferences Saved!" : "Save All Settings"}
            </Button>
          </CardFooter>
        </Card>

        {/* Live Agent Dialect & Report Tone Preview Sandbox */}
        <Card className="border-border/60 lg:col-span-2 bg-card/60 backdrop-blur shadow-sm">
          <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <Bot className="h-5 w-5 text-sky-400" />
                Live Agent Dialect & Tone Simulation Preview
              </CardTitle>
              <CardDescription>
                Test how the analyst agent will phrase executive greetings and report insights with your currently selected dialect ({arabicDialect}) and tone ({reportTone}).
              </CardDescription>
            </div>
            <Button
              type="button"
              onClick={handlePreviewTone}
              disabled={isPreviewing}
              variant="outline"
              className="gap-2 border-sky-500/40 hover:bg-sky-500/10 text-sky-400 shrink-0 font-semibold shadow-sm"
            >
              {isPreviewing ? <RefreshCw className="h-4 w-4 animate-spin text-sky-400" /> : <Play className="h-4 w-4 text-sky-400 fill-sky-400/20" />}
              Generate Live Tone Preview
            </Button>
          </CardHeader>
          {previewData && (
            <CardContent className="pt-2 border-t border-border/40 space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs font-mono text-muted-foreground">
                <span className="bg-sky-500/10 text-sky-400 border border-sky-500/30 px-2.5 py-0.5 rounded-full text-[11px] font-semibold">
                  Language: {previewData.language_detected}
                </span>
                <span className="bg-primary/10 text-primary border border-primary/30 px-2.5 py-0.5 rounded-full text-[11px] font-semibold">
                  Dialect: {previewData.dialect.toUpperCase()}
                </span>
                <span className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2.5 py-0.5 rounded-full text-[11px] font-semibold">
                  Tone: {previewData.tone.toUpperCase()}
                </span>
              </div>
              <div className="p-4 rounded-xl border border-border/50 bg-muted/20 text-foreground text-sm font-sans whitespace-pre-wrap leading-relaxed shadow-inner" dir={previewData.language_detected.includes("Arabic") ? "rtl" : "ltr"}>
                {previewData.preview_text}
              </div>
            </CardContent>
          )}
        </Card>
      </form>
    </div>
  );
}
