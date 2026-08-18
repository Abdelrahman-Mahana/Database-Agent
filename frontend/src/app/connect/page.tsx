"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Label } from "@/components/ui/label";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/services/api";
import { useAppStore } from "@/store/useAppStore";
import { 
  Database, 
  Link as LinkIcon, 
  Upload, 
  ShieldCheck, 
  CheckCircle2, 
  AlertCircle, 
  Clock, 
  Server, 
  KeyRound, 
  Layers,
  ArrowRight
} from "lucide-react";
import { ConnectionConfigRequest, SavedProfile } from "@/types/api";

const DB_TYPES = [
  { id: "postgresql", name: "PostgreSQL", defaultPort: 5432, icon: "🐘", desc: "Enterprise relational database" },
  { id: "mysql", name: "MySQL", defaultPort: 3306, icon: "🐬", desc: "Popular open-source SQL database" },
  { id: "sqlserver", name: "SQL Server", defaultPort: 1433, icon: "🟦", desc: "Microsoft SQL Server database" },
  { id: "sqlite", name: "SQLite", defaultPort: 0, icon: "📦", desc: "Embedded local file database" },
  { id: "mongodb", name: "MongoDB", defaultPort: 27017, icon: "🍃", desc: "NoSQL document database" },
];

export default function ConnectPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { setActiveDatabase } = useAppStore();

  // Active form tab
  const [selectedDbType, setSelectedDbType] = useState<string>("postgresql");
  
  // Structured form state
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState<number>(5432);
  const [database, setDatabase] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [sslEnabled, setSslEnabled] = useState(false);
  const [sslMode, setSslMode] = useState("require");
  const [filePath, setFilePath] = useState("");
  const [displayName, setDisplayName] = useState("");

  // Connection URL state
  const [dbUrl, setDbUrl] = useState("sqlite:///app.db");
  const [uploadFile, setUploadFile] = useState<File | null>(null);

  // Validation feedback state
  const [validationSuccess, setValidationSuccess] = useState<{
    database_name: string;
    database_type: string;
    object_count: number;
  } | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleSuccess = (data: any) => {
    setActiveDatabase(data.database_name, data.database_type);
    queryClient.invalidateQueries({ queryKey: ["schema"] });
    queryClient.invalidateQueries({ queryKey: ["saved-profiles"] });
    router.push("/explorer");
  };

  const handleDbChange = (typeId: string) => {
    setSelectedDbType(typeId);
    setValidationSuccess(null);
    setValidationError(null);
    const target = DB_TYPES.find((d) => d.id === typeId);
    if (target && target.defaultPort > 0) {
      setPort(target.defaultPort);
    }
  };

  const handleMutationError = (err: any) => {
    setValidationSuccess(null);
    const msg = err.response?.data?.detail || err.message || "Failed to establish database connection.";
    setValidationError(msg);
  };

  // 1. Structured Connection Mutation
  const configConnectMutation = useMutation({
    mutationFn: async (payload: ConnectionConfigRequest) => {
      const res = await apiClient.post("/connect/config", payload);
      return res.data;
    },
    onSuccess: handleSuccess,
    onError: handleMutationError,
  });

  // 2. Test Connection Validation Mutation
  const validateMutation = useMutation({
    mutationFn: async (payload: ConnectionConfigRequest) => {
      const res = await apiClient.post("/connect/validate", payload);
      return res.data;
    },
    onSuccess: (data: any) => {
      setValidationError(null);
      setValidationSuccess({
        database_name: data.database_name,
        database_type: data.database_type,
        object_count: data.summary?.objects || 0,
      });
    },
    onError: handleMutationError,
  });

  // 3. Connection URL Mutation
  const urlConnectMutation = useMutation({
    mutationFn: async (url: string) => {
      const res = await apiClient.post("/connect/url", { database_url: url });
      return res.data;
    },
    onSuccess: handleSuccess,
    onError: handleMutationError,
  });

  // 3b. Reconnect Saved Profile Mutation
  const reconnectMutation = useMutation({
    mutationFn: async (connectionId: string) => {
      const res = await apiClient.post(`/connect/reconnect/${connectionId}`);
      return res.data;
    },
    onSuccess: handleSuccess,
    onError: handleMutationError,
  });

  // 4. Preset Database Mutation
  const presetConnectMutation = useMutation({
    mutationFn: async (filename: string) => {
      const res = await apiClient.post("/connect/preset", { filename });
      return res.data;
    },
    onSuccess: handleSuccess,
    onError: handleMutationError,
  });

  // 5. File Upload Mutation
  const uploadConnectMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await apiClient.post("/connect/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return res.data;
    },
    onSuccess: handleSuccess,
    onError: handleMutationError,
  });


  // Fetch available preset databases
  const { data: databasesData } = useQuery({
    queryKey: ["available-databases"],
    queryFn: async () => {
      const res = await apiClient.get("/connect/databases");
      return res.data;
    },
  });

  // Fetch saved profiles
  const { data: profilesData } = useQuery({
    queryKey: ["saved-profiles"],
    queryFn: async () => {
      const res = await apiClient.get("/connect/profiles");
      return res.data;
    },
  });

  const buildPayload = (): ConnectionConfigRequest => {
    if (selectedDbType === "sqlite") {
      return {
        db_type: "sqlite",
        file_path: filePath || "app.db",
        display_name: displayName || undefined,
        store_credentials: true,
      };
    }
    return {
      db_type: selectedDbType,
      host,
      port: Number(port),
      database,
      username,
      password: password || undefined,
      ssl_enabled: sslEnabled,
      ssl_mode: sslEnabled ? sslMode : undefined,
      display_name: displayName || undefined,
      store_credentials: true,
    };
  };

  const handleTestConnection = () => {
    setValidationSuccess(null);
    setValidationError(null);
    validateMutation.mutate(buildPayload());
  };

  const handleStructuredConnect = (e: React.FormEvent) => {
    e.preventDefault();
    configConnectMutation.mutate(buildPayload());
  };

  const handleUrlConnect = (e: React.FormEvent) => {
    e.preventDefault();
    if (dbUrl) {
      urlConnectMutation.mutate(dbUrl);
    }
  };

  const handleUploadConnect = (e: React.FormEvent) => {
    e.preventDefault();
    if (uploadFile) {
      uploadConnectMutation.mutate(uploadFile);
    }
  };

  const isPending =
    configConnectMutation.isPending ||
    urlConnectMutation.isPending ||
    reconnectMutation.isPending ||
    presetConnectMutation.isPending ||
    uploadConnectMutation.isPending ||
    validateMutation.isPending;

  const activeError =
    configConnectMutation.error ||
    urlConnectMutation.error ||
    reconnectMutation.error ||
    presetConnectMutation.error ||
    uploadConnectMutation.error;


  return (
    <div className="flex-1 flex flex-col h-full w-full max-w-full space-y-6 overflow-y-auto pr-1">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/40 pb-5">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Connect Database</h2>
          <p className="text-muted-foreground text-sm mt-1">
            Establish connection with PostgreSQL, MySQL, SQL Server, SQLite, or MongoDB.
          </p>
        </div>
      </div>

      {/* Main Tabs Navigation */}
      <Tabs defaultValue="structured" className="w-full space-y-6">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="structured" className="flex items-center gap-2">
            <Server className="h-4 w-4" />
            Database Setup
          </TabsTrigger>
          <TabsTrigger value="profiles" className="flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Saved Profiles ({profilesData?.profiles?.length || 0})
          </TabsTrigger>
          <TabsTrigger value="url" className="flex items-center gap-2">
            <LinkIcon className="h-4 w-4" />
            Connection URL
          </TabsTrigger>
          <TabsTrigger value="preset" className="flex items-center gap-2">
            <Upload className="h-4 w-4" />
            Presets / Upload
          </TabsTrigger>
        </TabsList>

        {/* Tab 1: Structured Connection Form */}
        <TabsContent value="structured" className="space-y-6">
          <Card className="border-border/60 shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg">Select Database Engine</CardTitle>
              <CardDescription>Choose target database type to configure connection credentials.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {DB_TYPES.map((type) => {
                  const isSelected = selectedDbType === type.id;
                  return (
                    <button
                      key={type.id}
                      type="button"
                      onClick={() => handleDbChange(type.id)}
                      className={`p-4 rounded-xl border text-left transition-all flex flex-col justify-between space-y-2 ${
                        isSelected
                          ? "border-primary bg-primary/10 ring-2 ring-primary/20"
                          : "border-border/60 bg-card/50 hover:bg-muted/40"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-2xl">{type.icon}</span>
                        {isSelected && <CheckCircle2 className="h-4 w-4 text-primary" />}
                      </div>
                      <div>
                        <div className="font-semibold text-sm">{type.name}</div>
                        <div className="text-[11px] text-muted-foreground mt-0.5 truncate">{type.desc}</div>
                      </div>
                    </button>
                  );
                })}
              </div>

              <form onSubmit={handleStructuredConnect} className="mt-8 space-y-6">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="displayName">Display Name (Optional)</Label>
                    <Input
                      id="displayName"
                      placeholder="e.g. Production Analytics DB"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      className="mt-1.5"
                    />
                  </div>

                  {selectedDbType === "sqlite" ? (
                    <div>
                      <Label htmlFor="filePath">SQLite Database File Path</Label>
                      <Input
                        id="filePath"
                        placeholder="e.g. app.db or /path/to/database.db"
                        value={filePath}
                        onChange={(e) => setFilePath(e.target.value)}
                        required
                        className="mt-1.5"
                      />
                    </div>
                  ) : (
                    <>
                      <div>
                        <Label htmlFor="host">Host / IP Address</Label>
                        <Input
                          id="host"
                          placeholder="localhost or db.example.com"
                          value={host}
                          onChange={(e) => setHost(e.target.value)}
                          required
                          className="mt-1.5"
                        />
                      </div>

                      <div>
                        <Label htmlFor="port">Port</Label>
                        <Input
                          id="port"
                          type="number"
                          value={port}
                          onChange={(e) => setPort(Number(e.target.value))}
                          required
                          className="mt-1.5"
                        />
                      </div>

                      <div>
                        <Label htmlFor="database">Database Name</Label>
                        <Input
                          id="database"
                          placeholder="e.g. postgres, mydb"
                          value={database}
                          onChange={(e) => setDatabase(e.target.value)}
                          required
                          className="mt-1.5"
                        />
                      </div>

                      <div>
                        <Label htmlFor="username">Username</Label>
                        <Input
                          id="username"
                          placeholder="Database user"
                          value={username}
                          onChange={(e) => setUsername(e.target.value)}
                          className="mt-1.5"
                        />
                      </div>

                      <div>
                        <Label htmlFor="password">Password</Label>
                        <Input
                          id="password"
                          type="password"
                          placeholder="••••••••"
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          className="mt-1.5"
                        />
                      </div>
                    </>
                  )}
                </div>

                {selectedDbType !== "sqlite" && (
                  <div className="p-4 rounded-lg border border-border/50 bg-muted/20 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <ShieldCheck className="h-4 w-4 text-emerald-500" />
                        <span className="text-sm font-semibold">SSL / TLS Connection</span>
                      </div>
                      <label className="relative inline-flex items-center cursor-pointer">
                        <input
                          type="checkbox"
                          checked={sslEnabled}
                          onChange={(e) => setSslEnabled(e.target.checked)}
                          className="sr-only peer"
                        />
                        <div className="w-9 h-5 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary"></div>
                      </label>
                    </div>

                    {sslEnabled && (
                      <div className="pt-2 border-t border-border/40 grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                          <Label htmlFor="sslMode" className="text-xs">SSL Mode</Label>
                          <select
                            id="sslMode"
                            value={sslMode}
                            onChange={(e) => setSslMode(e.target.value)}
                            className="w-full mt-1 px-3 py-1.5 rounded-md text-xs bg-background border border-input focus:outline-none focus:ring-1 focus:ring-ring"
                          >
                            <option value="require">Require (verify-ca)</option>
                            <option value="prefer">Prefer</option>
                            <option value="verify-full">Verify Full</option>
                            <option value="allow">Allow</option>
                          </select>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Validation Diagnostics Feedback */}
                {validationSuccess && (
                  <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-5 w-5 shrink-0" />
                      <div>
                        <p className="text-sm font-semibold">Connection Verified Successfully!</p>
                        <p className="text-xs opacity-90 mt-0.5">
                          Discovered {validationSuccess.object_count} schema objects in {validationSuccess.database_name} ({validationSuccess.database_type}).
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {validationError && (
                  <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive flex items-center gap-2">
                    <AlertCircle className="h-5 w-5 shrink-0" />
                    <div>
                      <p className="text-sm font-semibold">Validation Failed</p>
                      <p className="text-xs opacity-90 mt-0.5">{validationError}</p>
                    </div>
                  </div>
                )}

                <div className="flex items-center gap-3 pt-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleTestConnection}
                    disabled={isPending}
                    className="gap-2 text-xs"
                  >
                    <ShieldCheck className="h-4 w-4" />
                    {validateMutation.isPending ? "Testing..." : "Test Connection"}
                  </Button>

                  <Button
                    type="submit"
                    disabled={isPending}
                    className="gap-2 text-xs bg-primary hover:bg-primary/90 text-primary-foreground shadow"
                  >
                    <Database className="h-4 w-4" />
                    {configConnectMutation.isPending ? "Connecting..." : "Connect & Explore"}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 2: Encrypted Saved Profiles */}
        <TabsContent value="profiles" className="space-y-4">
          <Card className="border-border/60 shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg">Recent Connection Profiles</CardTitle>
              <CardDescription>
                Credentials stored with Fernet AES-256 encryption. Select a profile to re-establish connection instantly.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {profilesData?.profiles?.length > 0 ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {profilesData.profiles.map((p: SavedProfile) => (
                    <div
                      key={p.connection_id}
                      className="p-4 rounded-xl border border-border/60 bg-muted/20 hover:bg-muted/40 transition-all flex flex-col justify-between space-y-4 group"
                    >
                      <div className="space-y-1">
                        <div className="flex items-center justify-between">
                          <h4 className="font-semibold text-sm group-hover:text-primary transition-colors">
                            {p.display_name}
                          </h4>
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-primary/10 text-primary uppercase">
                            {p.db_type}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground font-mono truncate">{p.masked_url}</p>
                      </div>
                      <Button
                        size="sm"
                        disabled={isPending}
                        onClick={() => reconnectMutation.mutate(p.connection_id)}
                        className="w-full gap-1.5 text-xs"
                      >
                        {reconnectMutation.isPending ? "Reconnecting..." : "Reconnect"}
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Button>

                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center border border-dashed border-border/60 rounded-xl text-muted-foreground text-sm">
                  No encrypted connection profiles saved yet. Establish a connection to store profiles automatically.
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 3: Connection URL */}
        <TabsContent value="url">
          <Card className="border-border/60 shadow-sm">
            <form onSubmit={handleUrlConnect}>
              <CardHeader>
                <CardTitle className="text-lg">Connect via Connection String</CardTitle>
                <CardDescription>
                  Enter a valid connection URI (SQLAlchemy or MongoDB connection string).
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="url">Database Connection URL</Label>
                  <Input
                    id="url"
                    placeholder="postgresql://user:pass@localhost:5432/dbname or mongodb://localhost:27017/mydb"
                    value={dbUrl}
                    onChange={(e) => setDbUrl(e.target.value)}
                    required
                  />
                </div>
              </CardContent>
              <CardFooter>
                <Button type="submit" disabled={isPending} className="gap-2">
                  <LinkIcon className="h-4 w-4" />
                  {urlConnectMutation.isPending ? "Connecting..." : "Connect Database"}
                </Button>
              </CardFooter>
            </form>
          </Card>
        </TabsContent>

        {/* Tab 4: Presets / File Upload */}
        <TabsContent value="preset" className="space-y-6">
          <Card className="border-border/60 shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg">Local Preset Databases</CardTitle>
              <CardDescription>Select from local SQLite files present in the backend directory.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 sm:grid-cols-2">
                {databasesData?.databases?.map((db: any) => (
                  <div
                    key={db.filename}
                    className="p-4 rounded-xl border border-border/60 bg-muted/20 flex items-center justify-between"
                  >
                    <div>
                      <h4 className="font-semibold text-sm">{db.name}</h4>
                      <p className="text-xs text-muted-foreground mt-0.5">{db.filename} ({db.size_mb} MB)</p>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={isPending}
                      onClick={() => presetConnectMutation.mutate(db.filename)}
                    >
                      {presetConnectMutation.isPending ? "Loading..." : "Use Database"}
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/60 shadow-sm">
            <form onSubmit={handleUploadConnect}>
              <CardHeader>
                <CardTitle className="text-lg">Upload Local SQLite File</CardTitle>
                <CardDescription>Upload a `.db`, `.sqlite`, or `.sqlite3` file to inspect.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="file">Select File</Label>
                  <Input
                    id="file"
                    type="file"
                    accept=".db,.sqlite,.sqlite3,.db3"
                    onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                    required
                  />
                </div>
              </CardContent>
              <CardFooter>
                <Button type="submit" disabled={isPending || !uploadFile} className="gap-2">
                  <Upload className="h-4 w-4" />
                  {uploadConnectMutation.isPending ? "Uploading..." : "Upload & Connect"}
                </Button>
              </CardFooter>
            </form>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Global Error Banner */}
      {activeError && (
        <div className="p-4 rounded-lg bg-destructive/10 text-destructive border border-destructive/20 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <div>
            <p className="text-sm font-semibold">Connection Error</p>
            <p className="text-xs opacity-90 mt-0.5">
              {(activeError as any).response?.data?.detail || activeError.message}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
