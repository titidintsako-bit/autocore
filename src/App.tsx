import { type CSSProperties, type ReactNode, useEffect, useMemo, useState } from "react";
import {
  type LucideIcon,
  Activity,
  BadgeCheck,
  Ban,
  Cable,
  ChevronDown,
  ChevronRight,
  Check,
  CircleDot,
  Clock3,
  Command,
  Copy,
  Cloud,
  Database,
  Download,
  FileSearch,
  FileJson,
  FileText,
  FolderGit2,
  GitCompareArrows,
  Github,
  KeyRound,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  MessagesSquare,
  PauseCircle,
  Play,
  PlugZap,
  RadioTower,
  RefreshCcw,
  SearchCheck,
  ShieldCheck,
  Tickets,
  Unplug,
  Square,
  TerminalSquare,
  X,
} from "lucide-react";
import {
  baseTrace,
  evidenceItems,
  initialGates,
  type GateState,
  type PermissionGate,
  type TraceEvent,
} from "./data/autonomy";
import {
  approveRuntimeCommand,
  auditCompanionChanges,
  createRuntimeRun,
  evaluatePrompt,
  fetchBuildAudits,
  fetchCompanionStatus,
  fetchConnectorInventory,
  fetchDemoSnapshot,
  fetchEvidenceBundle,
  fetchEvidenceLibrary,
  fetchLatestRun,
  fetchPolicyProfile,
  fetchPromptEvaluations,
  fetchProjectProfile,
  fetchSetupStatus,
  fetchRun,
  fetchRunHistory,
  fetchRuntimeHealth,
  fetchTaskPacks,
  holdRuntimeCommand,
  pickProjectFolder,
  runBuildAudit,
  runGuidedAudit,
  PUBLIC_SNAPSHOT_MODE,
  RUNTIME_API_URL,
  type BuildAudit,
  type CompanionStatus,
  type ConnectorInventory,
  type ConnectorSource,
  type ConnectorState,
  type DemoSnapshot,
  type EvidenceBundle,
  type EvidenceLibrary,
  type GuidedAudit,
  type PolicyProfile,
  type PromptEvaluation,
  type ProjectProfile,
  type RuntimeHealth,
  type RuntimeHistory,
  type RuntimeRun,
  type SandboxDecision,
  type SetupStatus,
  type TaskPack,
  updateProjectProfile,
} from "./runtime/api";

const viewerTabs = ["replay", "planner", "output", "scorecard", "report"] as const;
type ViewerTab = (typeof viewerTabs)[number];
const surfaceTabs = ["setup", "companion", "lab", "audit", "overview", "connect", "runs", "evidence", "policy"] as const;
type SurfaceTab = (typeof surfaceTabs)[number];
const ansiEscapePattern = /\u001b\[[0-?]*[ -/]*[@-~]/g;

const surfaceTabLabel: Record<SurfaceTab, string> = {
  setup: "Setup",
  companion: "Companion",
  lab: "Lab",
  audit: "Audit",
  overview: "Dashboard",
  connect: "Connect",
  runs: "Runs",
  evidence: "Evidence",
  policy: "Policy",
};

const requiredRuntimeCapabilities = ["guided_audit", "prompt_lab", "build_auditor"] as const;

function runtimeCompatibilityMessage(health: RuntimeHealth | null) {
  if (!health) return null;
  const missing = requiredRuntimeCapabilities.filter((capability) => !health.capabilities?.[capability]);
  if (!missing.length) return null;
  return `Restart AutoCore; your backend is outdated. Missing capabilities: ${missing.join(", ")}.`;
}

function runtimeApiLabel() {
  try {
    return new URL(RUNTIME_API_URL).host;
  } catch {
    return RUNTIME_API_URL.replace(/^https?:\/\//, "") || "local runtime";
  }
}

const gateLabel: Record<GateState, string> = {
  approved: "Approved",
  pending: "Needs approval",
  blocked: "Blocked",
  locked: "Locked",
};

const connectorStateLabel: Record<ConnectorState, string> = {
  not_connected: "Not connected",
  demo_connected: "Demo connected",
  live_connected: "Live connected",
  failed_auth: "Failed auth",
  syncing: "Syncing",
  paused: "Paused",
};

const connectorStateIcon: Record<ConnectorState, LucideIcon> = {
  not_connected: Unplug,
  demo_connected: Database,
  live_connected: Cable,
  failed_auth: Ban,
  syncing: LoaderCircle,
  paused: PauseCircle,
};

const connectorIconMap: Record<string, LucideIcon> = {
  github: Github,
  slack: MessagesSquare,
  "linear-jira": Tickets,
  "google-drive": FileSearch,
  "cloud-logs": Cloud,
  "local-repo": FolderGit2,
};

const onboardingIconMap: Record<string, LucideIcon> = {
  "Choose source": PlugZap,
  "Verify permissions": ShieldCheck,
  "Run audit": SearchCheck,
  "Review evidence": FileText,
};

function initialViewerTab(): ViewerTab {
  const requestedTab = new URLSearchParams(window.location.search).get("tab");
  return viewerTabs.includes(requestedTab as ViewerTab) ? (requestedTab as ViewerTab) : "replay";
}

function initialDemoMode() {
  return new URLSearchParams(window.location.search).get("demo") === "1";
}

function initialSurfaceTab(): SurfaceTab {
  const requestedSurface = new URLSearchParams(window.location.search).get("section");
  return surfaceTabs.includes(requestedSurface as SurfaceTab) ? (requestedSurface as SurfaceTab) : "setup";
}

function initialCollapsedRows() {
  try {
    return JSON.parse(window.localStorage.getItem("autocore.collapsedRows") ?? "{}") as Record<string, boolean>;
  } catch {
    return {};
  }
}

function formatDelta(delta: number) {
  return delta > 0 ? `+${delta}` : `${delta}`;
}

function formatDuration(ms: number) {
  if (!ms) return "--";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDate(value: string | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleDateString([], { month: "short", day: "2-digit" });
}

function stripAnsiText(value: string) {
  return value.replace(ansiEscapePattern, "");
}

function clampScore(value: number | undefined) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Number(value)));
}

function gaugeStyle(value: number, color = "#7ee03f"): CSSProperties {
  const degrees = clampScore(value) * 3.6;
  return {
    background: `conic-gradient(${color} ${degrees}deg, rgba(255, 255, 255, 0.09) ${degrees}deg 360deg)`,
  };
}

function shortRunId(value: string | undefined) {
  if (!value) return "--";
  return value.length > 15 ? `${value.slice(0, 7)}...${value.slice(-4)}` : value;
}

function scoreDimensionLabel(dimension: { id: string; label: string }) {
  return dimension.id === "intervention_efficiency" ? "Hands-off Autonomy" : dimension.label;
}

function scoreDimensionEvidence(dimension: { id: string; evidence: string }) {
  if (dimension.id !== "intervention_efficiency") return dimension.evidence;
  if (dimension.evidence.toLowerCase().includes("operator dependency")) return dimension.evidence;
  return `${dimension.evidence} Required approval is counted as operator dependency, so this stays low until the run can complete hands-off.`;
}

function taskPackTask(pack: TaskPack | undefined) {
  if (!pack) return undefined;
  return pack.tasks.find((task) => task.id === pack.default_task_id) ?? pack.tasks[0];
}

function sandboxValue(
  sandbox: SandboxDecision,
  profile: PolicyProfile | null,
  key: keyof SandboxDecision & keyof PolicyProfile,
) {
  return String(sandbox[key] ?? profile?.[key] ?? "unknown");
}

function runtimeGates(run: RuntimeRun): PermissionGate[] {
  const command = run.commands[0];
  const terminalState: GateState =
    command?.state === "completed"
      ? "approved"
      : command?.state === "blocked" || command?.state === "failed"
        ? "blocked"
        : "pending";

  return [
    { ...initialGates[0], scope: `${run.inspection.stack}, ${run.inspection.manifests.length} manifests` },
    { ...initialGates[1], scope: command?.command_text ?? "No safe command detected", state: terminalState },
    { ...initialGates[2], state: "blocked" },
    { ...initialGates[3], state: "locked" },
  ];
}

function runtimeTrace(run: RuntimeRun): TraceEvent[] {
  if (!run.events.length) return baseTrace;

  return run.events.map((event) => {
    const icon =
      event.status === "blocked"
        ? Ban
        : event.kind === "execute"
          ? TerminalSquare
          : event.kind === "approval"
            ? KeyRound
            : event.kind === "plan"
              ? CircleDot
              : Check;

    return {
      id: event.id,
      time: formatTime(event.created_at),
      title: event.title,
      detail: event.detail,
      status: event.status,
      icon,
    } satisfies TraceEvent;
  });
}

function GaugeDial({
  label,
  value,
  detail,
  color = "#7ee03f",
  size = "medium",
}: {
  label: string;
  value: number;
  detail: string;
  color?: string;
  size?: "large" | "medium" | "small";
}) {
  return (
    <div className={`gauge-dial ${size}`}>
      <div className="gauge-ring" style={gaugeStyle(value, color)}>
        <div>
          <span>{label}</span>
          <strong>{clampScore(value)}%</strong>
        </div>
      </div>
      <p>{detail}</p>
    </div>
  );
}

function TelemetryGraph({ tone = "green" }: { tone?: "green" | "red" }) {
  const fillId = `telemetry-${tone}`;
  return (
    <svg className={`telemetry-graph ${tone}`} viewBox="0 0 720 190" role="img" aria-label="Runtime telemetry trend">
      <defs>
        <linearGradient id={fillId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={tone === "green" ? "#7ee03f" : "#ff5b32"} stopOpacity="0.72" />
          <stop offset="100%" stopColor={tone === "green" ? "#7ee03f" : "#ff5b32"} stopOpacity="0.06" />
        </linearGradient>
      </defs>
      <path
        d="M0 160 L0 132 L22 119 L44 142 L66 94 L88 126 L110 74 L132 112 L154 86 L176 102 L198 70 L220 126 L242 92 L264 116 L286 68 L308 118 L330 104 L352 76 L374 128 L396 91 L418 108 L440 82 L462 122 L484 66 L506 134 L528 116 L550 75 L572 121 L594 100 L616 58 L638 132 L660 82 L682 112 L704 64 L720 92 L720 190 L0 190 Z"
        fill={`url(#${fillId})`}
      />
      <path
        d="M0 132 L22 119 L44 142 L66 94 L88 126 L110 74 L132 112 L154 86 L176 102 L198 70 L220 126 L242 92 L264 116 L286 68 L308 118 L330 104 L352 76 L374 128 L396 91 L418 108 L440 82 L462 122 L484 66 L506 134 L528 116 L550 75 L572 121 L594 100 L616 58 L638 132 L660 82 L682 112 L704 64 L720 92"
        fill="none"
        stroke={tone === "green" ? "#8ade42" : "#ff6b35"}
        strokeWidth="2"
      />
    </svg>
  );
}

function DashboardRow({
  id,
  title,
  layout,
  children,
  collapsed,
  onToggle,
  className = "",
}: {
  id: string;
  title: string;
  layout: "Auto grid" | "Custom grid";
  children: ReactNode;
  collapsed: boolean;
  onToggle: (id: string) => void;
  className?: string;
}) {
  return (
    <section className={`dashboard-row ${collapsed ? "collapsed" : ""} ${className}`} aria-label={title}>
      <div className="dashboard-row-header">
        <button
          aria-expanded={!collapsed}
          className="row-toggle"
          onClick={() => onToggle(id)}
          type="button"
        >
          {collapsed ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
          <span>{title}</span>
        </button>
        <small>{layout}</small>
      </div>
      {!collapsed && <div className="dashboard-row-body">{children}</div>}
    </section>
  );
}

function App() {
  const [localGates, setLocalGates] = useState<PermissionGate[]>(initialGates);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>(baseTrace);
  const [selectedTrace, setSelectedTrace] = useState(baseTrace[baseTrace.length - 1].id);
  const [mode, setMode] = useState<"guarded" | "observe">("guarded");
  const [runtimeRun, setRuntimeRun] = useState<RuntimeRun | null>(null);
  const [runtimeState, setRuntimeState] = useState<"connecting" | "live" | "offline">("connecting");
  const [runtimeHealth, setRuntimeHealth] = useState<RuntimeHealth | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [launchBusy, setLaunchBusy] = useState(false);
  const [evidenceBundle, setEvidenceBundle] = useState<EvidenceBundle | null>(null);
  const [runHistory, setRunHistory] = useState<RuntimeHistory | null>(null);
  const [policyProfile, setPolicyProfile] = useState<PolicyProfile | null>(null);
  const [demoSnapshot, setDemoSnapshot] = useState<DemoSnapshot | null>(null);
  const [demoMode, setDemoMode] = useState(initialDemoMode);
  const [taskPacks, setTaskPacks] = useState<TaskPack[]>([]);
  const [selectedPackId, setSelectedPackId] = useState("repo-readiness");
  const [viewerTab, setViewerTab] = useState<ViewerTab>(initialViewerTab);
  const [activeSurface, setActiveSurface] = useState<SurfaceTab>(initialSurfaceTab);
  const [collapsedRows, setCollapsedRows] = useState<Record<string, boolean>>(initialCollapsedRows);
  const [panelNotice, setPanelNotice] = useState<string | null>(null);
  const [connectorInventory, setConnectorInventory] = useState<ConnectorInventory | null>(null);
  const [connectorError, setConnectorError] = useState<string | null>(null);
  const [selectedConnectorId, setSelectedConnectorId] = useState("local-repo");
  const [projectProfile, setProjectProfile] = useState<ProjectProfile | null>(null);
  const [projectPathDraft, setProjectPathDraft] = useState("");
  const [projectError, setProjectError] = useState<string | null>(null);
  const [projectBusy, setProjectBusy] = useState(false);
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [companionStatus, setCompanionStatus] = useState<CompanionStatus | null>(null);
  const [companionBusy, setCompanionBusy] = useState(false);
  const [companionError, setCompanionError] = useState<string | null>(null);
  const [evidenceLibrary, setEvidenceLibrary] = useState<EvidenceLibrary | null>(null);
  const [promptDraft, setPromptDraft] = useState(
    "Audit this repo for deployment readiness, run only safe checks, capture evidence, and flag release risks.",
  );
  const [promptProvider, setPromptProvider] = useState("offline");
  const [promptModel, setPromptModel] = useState("heuristic");
  const [promptCritiqueEnabled, setPromptCritiqueEnabled] = useState(false);
  const [promptEvaluations, setPromptEvaluations] = useState<PromptEvaluation[]>([]);
  const [selectedPromptEvaluationId, setSelectedPromptEvaluationId] = useState<string | null>(null);
  const [promptLabBusy, setPromptLabBusy] = useState(false);
  const [promptLabError, setPromptLabError] = useState<string | null>(null);
  const [buildAudits, setBuildAudits] = useState<BuildAudit[]>([]);
  const [selectedBuildAuditId, setSelectedBuildAuditId] = useState<string | null>(null);
  const [buildAuditBusy, setBuildAuditBusy] = useState(false);
  const [buildAuditError, setBuildAuditError] = useState<string | null>(null);
  const [guidedAudit, setGuidedAudit] = useState<GuidedAudit | null>(null);
  const [guidedAuditBusy, setGuidedAuditBusy] = useState(false);
  const [guidedAuditError, setGuidedAuditError] = useState<string | null>(null);

  function applyDemoSnapshot(snapshot: DemoSnapshot) {
    setDemoMode(true);
    setDemoSnapshot(snapshot);
    setRuntimeRun(snapshot.run);
    setSelectedPackId(snapshot.run.task_pack_id);
    setEvidenceBundle(snapshot.evidence);
    setRunHistory(snapshot.history);
    const nextTrace = runtimeTrace(snapshot.run);
    setTraceEvents(nextTrace);
    setSelectedTrace(nextTrace[nextTrace.length - 1]?.id ?? baseTrace[0].id);
    setRuntimeState("live");
    setRuntimeError(null);
    setViewerTab("report");
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (demoMode) params.set("demo", "1");
    params.set("section", activeSurface);
    if (viewerTab !== "replay") params.set("tab", viewerTab);
    if (viewerTab === "replay") params.delete("tab");
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [activeSurface, demoMode, viewerTab]);

  useEffect(() => {
    window.localStorage.setItem("autocore.collapsedRows", JSON.stringify(collapsedRows));
  }, [collapsedRows]);

  useEffect(() => {
    if (PUBLIC_SNAPSHOT_MODE || demoMode) return;

    let cancelled = false;
    fetchRuntimeHealth()
      .then((health) => {
        if (cancelled) return null;
        setRuntimeHealth(health);
        const compatibilityError = runtimeCompatibilityMessage(health);
        if (compatibilityError) {
          setRuntimeState("offline");
          setRuntimeError(compatibilityError);
          return null;
        }
        return fetchLatestRun();
      })
      .then((run) => {
        if (!run) return;
        if (cancelled) return;
        setRuntimeRun(run);
        setSelectedPackId(run.task_pack_id);
        const nextTrace = runtimeTrace(run);
        setTraceEvents(nextTrace);
        setSelectedTrace(nextTrace[nextTrace.length - 1]?.id ?? baseTrace[0].id);
        setRuntimeState("live");
        setRuntimeError(null);
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setRuntimeState("offline");
        setRuntimeError(error.message);
      });

    return () => {
      cancelled = true;
    };
  }, [demoMode]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchDemoSnapshot(), fetchRuntimeHealth().catch(() => null)])
      .then(([snapshot, health]) => {
        if (cancelled) return;
        setDemoSnapshot(snapshot);
        setRuntimeHealth(health);
        if (PUBLIC_SNAPSHOT_MODE || initialDemoMode() || health?.mode === "public") {
          applyDemoSnapshot(snapshot);
        }
      })
      .catch((error: Error) => {
        if (!cancelled && initialDemoMode()) {
          setRuntimeState("offline");
          setRuntimeError(error.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchSetupStatus()
      .then((status) => {
        if (cancelled) return;
        setSetupStatus(status);
        setSetupError(null);
      })
      .catch((error: Error) => {
        if (!cancelled) setSetupError(error.message);
      });

    return () => {
      cancelled = true;
    };
  }, [demoMode]);

  useEffect(() => {
    let cancelled = false;
    fetchCompanionStatus()
      .then((status) => {
        if (cancelled) return;
        setCompanionStatus(status);
        setCompanionError(null);
      })
      .catch((error: Error) => {
        if (!cancelled) setCompanionError(error.message);
      });

    return () => {
      cancelled = true;
    };
  }, [demoMode]);

  useEffect(() => {
    let cancelled = false;
    fetchTaskPacks()
      .then((packs) => {
        if (cancelled) return;
        setTaskPacks(packs);
        if (!packs.some((pack) => pack.id === selectedPackId) && packs[0]) {
          setSelectedPackId(packs[0].id);
        }
      })
      .catch(() => {
        if (!cancelled) setTaskPacks([]);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (PUBLIC_SNAPSHOT_MODE) return;

    let cancelled = false;
    fetchConnectorInventory()
      .then((inventory) => {
        if (cancelled) return;
        setConnectorInventory(inventory);
        setConnectorError(null);
        if (!inventory.connectors.some((connector) => connector.id === selectedConnectorId)) {
          setSelectedConnectorId(inventory.connectors.find((connector) => connector.id === "local-repo")?.id ?? inventory.connectors[0]?.id ?? "");
        }
      })
      .catch((error: Error) => {
        if (!cancelled) setConnectorError(error.message);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (PUBLIC_SNAPSHOT_MODE) return;

    let cancelled = false;
    fetchProjectProfile()
      .then((profile) => {
        if (cancelled) return;
        setProjectProfile(profile);
        setProjectPathDraft(profile.path);
        setProjectError(null);
      })
      .catch((error: Error) => {
        if (!cancelled) setProjectError(error.message);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (PUBLIC_SNAPSHOT_MODE) return;

    let cancelled = false;
    fetchEvidenceLibrary()
      .then((library) => {
        if (!cancelled) setEvidenceLibrary(library);
      })
      .catch(() => {
        if (!cancelled) setEvidenceLibrary({ reports: [] });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (PUBLIC_SNAPSHOT_MODE) return;

    let cancelled = false;
    fetchPromptEvaluations()
      .then((evaluations) => {
        if (cancelled) return;
        setPromptEvaluations(evaluations);
        setSelectedPromptEvaluationId((current) => current ?? evaluations[0]?.id ?? null);
      })
      .catch((error: Error) => {
        if (!cancelled) setPromptLabError(error.message);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (PUBLIC_SNAPSHOT_MODE) return;

    let cancelled = false;
    fetchBuildAudits()
      .then((audits) => {
        if (cancelled) return;
        setBuildAudits(audits);
        setSelectedBuildAuditId((current) => current ?? audits[0]?.id ?? null);
      })
      .catch((error: Error) => {
        if (!cancelled) setBuildAuditError(error.message);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (PUBLIC_SNAPSHOT_MODE) return;

    let cancelled = false;
    fetchPolicyProfile()
      .then((profile) => {
        if (!cancelled) setPolicyProfile(profile);
      })
      .catch(() => {
        if (!cancelled) setPolicyProfile(null);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (demoMode) return;

    let cancelled = false;
    fetchRunHistory(12)
      .then((history) => {
        if (!cancelled) setRunHistory(history);
      })
      .catch(() => {
        if (!cancelled) setRunHistory(null);
      });

    return () => {
      cancelled = true;
    };
  }, [demoMode]);

  useEffect(() => {
    if (demoMode || !runtimeRun || runtimeRun.status !== "evidence_ready") return;

    let cancelled = false;
    fetchEvidenceBundle(runtimeRun.id)
      .then((bundle) => {
        if (!cancelled) setEvidenceBundle(bundle);
      })
      .catch((error: Error) => {
        if (!cancelled) setRuntimeError(error.message);
      });

    return () => {
      cancelled = true;
    };
  }, [demoMode, runtimeRun]);

  const displayedGates = useMemo(() => (runtimeRun ? runtimeGates(runtimeRun) : localGates), [localGates, runtimeRun]);
  const terminalGate = displayedGates.find((gate) => gate.id === "terminal");
  const approvalState = terminalGate?.state ?? "pending";
  const approved = approvalState === "approved";
  const held = approvalState === "blocked";
  const pendingCommand = runtimeRun?.commands.find((command) => command.state === "pending") ?? null;
  const primaryCommand = pendingCommand ?? runtimeRun?.commands[0] ?? null;
  const planner = runtimeRun?.planner ?? {};
  const plannerProvider = planner.provider ?? {};
  const providerLabel =
    plannerProvider.name && plannerProvider.model
      ? `${plannerProvider.name} / ${plannerProvider.model}`
      : plannerProvider.name
        ? plannerProvider.name
        : "BYOK / local";
  const plannerCommandText =
    planner.selected_command?.length ? planner.selected_command.join(" ") : primaryCommand?.command_text ?? "No command selected";
  const selectedPack = taskPacks.find((pack) => pack.id === selectedPackId) ?? taskPacks[0];
  const selectedTask = taskPackTask(selectedPack);
  const selectedPromptEvaluation =
    promptEvaluations.find((evaluation) => evaluation.id === selectedPromptEvaluationId) ?? promptEvaluations[0] ?? null;
  const selectedBuildAudit = buildAudits.find((audit) => audit.id === selectedBuildAuditId) ?? buildAudits[0] ?? null;
  const historyRows = runHistory?.runs ?? [];
  const historySummary = runHistory?.summary;
  const commandSandbox = primaryCommand?.sandbox ?? {};
  const sandboxChecks = commandSandbox.checks ?? [];
  const activeTrace = traceEvents.find((event) => event.id === selectedTrace) ?? traceEvents[0];
  const ActiveTraceIcon = activeTrace.icon;
  const scorecard = runtimeRun?.scorecard;
  const runtimeCompatibilityError = runtimeCompatibilityMessage(runtimeHealth);
  const statusLabel = runtimeCompatibilityError ? "Backend restart needed" : demoMode ? "Release snapshot" : runtimeState === "live" ? "Live runtime" : "Offline";
  const runtimeLabel = runtimeApiLabel();
  const runStatus = runtimeRun?.status ?? (held ? "blocked" : approved ? "approved" : "approval_required");
  const commandOutput = stripAnsiText(
    primaryCommand?.stdout || primaryCommand?.stderr || "No command output captured yet.",
  ).trim();
  const evidenceMarkdown = stripAnsiText(evidenceBundle?.markdown ?? "Evidence report has not been generated yet.");
  const evidenceJsonText = JSON.stringify(evidenceBundle?.json ?? runtimeRun ?? {}, null, 2);
  const scoreDimensions = scorecard?.dimensions ?? [];
  const taskSuccessScore = scoreDimensions.find((dimension) => dimension.id === "task_success")?.score ?? 0;
  const evidenceScore = scoreDimensions.find((dimension) => dimension.id === "evidence_completeness")?.score ?? 0;
  const handsOffScore = scoreDimensions.find((dimension) => dimension.id === "intervention_efficiency")?.score ?? 0;
  const blockedActions = scorecard?.counters.blocked_actions ?? 0;
  const completedCommands = scorecard?.counters.completed_commands ?? 0;
  const failedCommands = scorecard?.counters.failed_commands ?? 0;
  const cockpitTone = scorecard?.grade === "not_ready" || runStatus === "failed" ? "red" : "green";
  const topDelayRows = scoreDimensions.length ? scoreDimensions : [];
  const connectorSources = connectorInventory?.connectors ?? [];
  const selectedConnector = connectorSources.find((connector) => connector.id === selectedConnectorId) ?? connectorSources[0] ?? null;
  const SelectedConnectorIcon = selectedConnector ? (connectorIconMap[selectedConnector.id] ?? Cable) : FolderGit2;
  const connectorSummary = connectorInventory?.summary ?? {
    total: 0,
    active: 0,
    guarded: 0,
    attention: 0,
    not_connected: 0,
  };
  const connectorPermissions = connectorInventory?.permissions ?? [];
  const connectorOnboarding = connectorInventory?.onboarding ?? [];
  const connectorStateLegend = connectorInventory?.state_legend ?? [];
  const connectionBoundaryLabel = connectorInventory?.boundary.label ?? "Connector backend offline";
  const evidenceReports = evidenceLibrary?.reports ?? [];
  const activeEvidenceReport = runtimeRun ? evidenceReports.find((report) => report.run_id === runtimeRun.id) : undefined;
  const liveProofSteps = [
    {
      label: "Repo inspected",
      detail: projectProfile
        ? `${projectProfile.name} / ${projectProfile.stack} / ${projectProfile.manifests.length} manifests`
        : "Waiting for project profile",
      complete: Boolean(runtimeRun?.inspection.manifests.length || projectProfile?.manifests.length),
    },
    {
      label: "Command proposed",
      detail: plannerCommandText,
      complete: Boolean(primaryCommand || planner.selected_command?.length),
    },
    {
      label: "Policy checked",
      detail: primaryCommand?.sandbox?.profile_id ?? policyProfile?.profile_id ?? "guarded.local",
      complete: Boolean(primaryCommand?.sandbox?.checks?.length || policyProfile),
    },
    {
      label: "Command approved",
      detail: primaryCommand?.state ?? "waiting for approval",
      complete: primaryCommand?.state === "completed",
    },
    {
      label: "Output captured",
      detail: commandOutput === "No command output captured yet." ? "waiting" : `${commandOutput.length} chars`,
      complete: commandOutput !== "No command output captured yet.",
    },
    {
      label: "Score generated",
      detail: scorecard ? `${scorecard.overall} / ${scorecard.grade.replace("_", " ")}` : "waiting",
      complete: Boolean(scorecard),
    },
    {
      label: "Evidence written",
      detail: activeEvidenceReport?.markdown_filename ?? evidenceBundle?.summary.markdown_filename ?? "waiting",
      complete: Boolean(activeEvidenceReport || evidenceBundle),
    },
  ];
  const activeRowTitle: Record<SurfaceTab, string> = {
    setup: "First-run guide",
    companion: "Codex change review",
    lab: "Prompt preflight",
    audit: "Build trust audit",
    overview: "Current run and signal",
    connect: "Connector readiness",
    runs: "Run execution and replay",
    evidence: "Evidence bundle",
    policy: "Policy controls",
  };
  const activeRowLayout: Record<SurfaceTab, "Auto grid" | "Custom grid"> = {
    setup: "Auto grid",
    companion: "Custom grid",
    lab: "Custom grid",
    audit: "Custom grid",
    overview: "Custom grid",
    connect: "Custom grid",
    runs: "Custom grid",
    evidence: "Custom grid",
    policy: "Custom grid",
  };

  const displayedEvidenceItems = useMemo(() => {
    if (!runtimeRun?.scorecard?.counters) return evidenceItems;
    return [
      { label: "Task Pack", value: runtimeRun.scorecard.task_pack_name, status: "ready" as const },
      {
        label: "Score Grade",
        value: runtimeRun.scorecard.grade.replace("_", " "),
        status:
          runtimeRun.scorecard.grade === "ready"
            ? ("ready" as const)
            : runtimeRun.scorecard.grade === "watch"
              ? ("pending" as const)
              : ("blocked" as const),
      },
      {
        label: "Command Evidence",
        value: runtimeRun.scorecard.counters.completed_commands ? "Ready" : "Waiting",
        status: runtimeRun.scorecard.counters.completed_commands ? ("ready" as const) : ("pending" as const),
      },
      {
        label: "Safety Exceptions",
        value: `${runtimeRun.scorecard.counters.blocked_actions} blocked`,
        status: runtimeRun.scorecard.counters.blocked_actions ? ("blocked" as const) : ("ready" as const),
      },
    ];
  }, [runtimeRun]);

  function toggleRow(rowId: string) {
    setCollapsedRows((current) => ({ ...current, [rowId]: !current[rowId] }));
  }

  async function copyText(label: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setPanelNotice(`${label} copied`);
    } catch {
      setPanelNotice("Copy is unavailable in this browser context");
    }
  }

  function downloadText(filename: string, value: string, type: string) {
    const blob = new Blob([value], { type });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = filename;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(href);
    setPanelNotice(`${filename} queued`);
  }

  async function refreshActiveRun() {
    if (demoMode && demoSnapshot) {
      applyDemoSnapshot(demoSnapshot);
      setPanelNotice("Snapshot refreshed");
      return;
    }
    if (!runtimeRun) return;
    try {
      const run = await fetchRun(runtimeRun.id);
      setRuntimeRun(run);
      setRunHistory(await fetchRunHistory(12));
      if (run.status === "evidence_ready") {
        setEvidenceBundle(await fetchEvidenceBundle(run.id));
      }
      setEvidenceLibrary(await fetchEvidenceLibrary());
      setPanelNotice("Run refreshed");
    } catch (error) {
      setRuntimeError(error instanceof Error ? error.message : "Refresh failed");
    }
  }

  async function refreshConnectors() {
    try {
      const inventory = await fetchConnectorInventory();
      setConnectorInventory(inventory);
      setConnectorError(null);
      if (!inventory.connectors.some((connector) => connector.id === selectedConnectorId)) {
        setSelectedConnectorId(inventory.connectors.find((connector) => connector.id === "local-repo")?.id ?? inventory.connectors[0]?.id ?? "");
      }
      setPanelNotice("Connector inventory refreshed");
    } catch (error) {
      setConnectorError(error instanceof Error ? error.message : "Connector refresh failed");
    }
  }

  async function refreshProject() {
    try {
      const profile = await fetchProjectProfile();
      setProjectProfile(profile);
      setProjectPathDraft(profile.path);
      setProjectError(null);
      setConnectorInventory(await fetchConnectorInventory());
      setSetupStatus(await fetchSetupStatus());
      setCompanionStatus(await fetchCompanionStatus());
      setPanelNotice("Project target refreshed");
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "Project refresh failed");
    }
  }

  async function saveProjectTarget() {
    if (!projectPathDraft.trim()) return;
    setProjectBusy(true);
    try {
      const profile = await updateProjectProfile(projectPathDraft.trim());
      setProjectProfile(profile);
      setProjectPathDraft(profile.path);
      setProjectError(null);
      setConnectorInventory(await fetchConnectorInventory());
      setEvidenceLibrary(await fetchEvidenceLibrary());
      setSetupStatus(await fetchSetupStatus());
      setCompanionStatus(await fetchCompanionStatus());
      setPanelNotice("Project target updated");
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "Project target update failed");
    } finally {
      setProjectBusy(false);
    }
  }

  async function chooseProjectFolder() {
    if (demoMode || PUBLIC_SNAPSHOT_MODE) {
      setPanelNotice("Public preview is read-only. Run AutoCore locally to choose a project folder.");
      return;
    }
    setProjectBusy(true);
    try {
      const result = await pickProjectFolder();
      if (!result.picked) {
        setPanelNotice("Project selection cancelled");
        return;
      }
      setProjectProfile(result.project);
      setProjectPathDraft(result.project.path);
      setProjectError(null);
      setConnectorInventory(await fetchConnectorInventory());
      setEvidenceLibrary(await fetchEvidenceLibrary());
      setSetupStatus(await fetchSetupStatus());
      setCompanionStatus(await fetchCompanionStatus());
      setActiveSurface("companion");
      setPanelNotice("Project folder selected");
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "Project folder selection failed");
      setPanelNotice("Folder picker unavailable; paste the path instead");
    } finally {
      setProjectBusy(false);
    }
  }

  function openEvidenceReport() {
    setActiveSurface("evidence");
    setViewerTab("report");
  }

  async function evaluatePromptDraft() {
    if (demoMode || !selectedPack || !selectedTask || !promptDraft.trim()) return;

    setPromptLabBusy(true);
    try {
      const evaluation = await evaluatePrompt({
        prompt: promptDraft,
        task_pack_id: selectedPack.id,
        task_id: selectedTask.id,
        provider: promptProvider,
        model: promptModel,
        critique_enabled: promptCritiqueEnabled,
      });
      setPromptEvaluations((current) => [evaluation, ...current.filter((item) => item.id !== evaluation.id)]);
      setSelectedPromptEvaluationId(evaluation.id);
      setPromptLabError(null);
      setPanelNotice("Prompt Lab preflight saved");
    } catch (error) {
      setPromptLabError(error instanceof Error ? error.message : "Prompt evaluation failed");
    } finally {
      setPromptLabBusy(false);
    }
  }

  async function launchPromptEvaluation() {
    if (demoMode || !selectedPack || !selectedTask || !selectedPromptEvaluation) return;

    setLaunchBusy(true);
    try {
      const run = await createRuntimeRun({
        goal: selectedPromptEvaluation.prompt_preview,
        task_pack_id: selectedPromptEvaluation.task_pack_id || selectedPack.id,
        task_id: selectedPromptEvaluation.task_id || selectedTask.id,
        prompt_evaluation_id: selectedPromptEvaluation.id,
      });
      setRuntimeRun(run);
      setSelectedPackId(run.task_pack_id);
      setEvidenceBundle(null);
      const nextTrace = runtimeTrace(run);
      setTraceEvents(nextTrace);
      setSelectedTrace(nextTrace[nextTrace.length - 1]?.id ?? selectedTrace);
      setRunHistory(await fetchRunHistory(12));
      setEvidenceLibrary(await fetchEvidenceLibrary());
      void fetchCompanionStatus().then(setCompanionStatus).catch(() => undefined);
      void fetchSetupStatus().then(setSetupStatus).catch(() => undefined);
      setRuntimeState("live");
      setRuntimeError(null);
      setActiveSurface("runs");
      setViewerTab("planner");
      setPanelNotice("Prompt Lab run created");
    } catch (error) {
      setRuntimeError(error instanceof Error ? error.message : "Prompt Lab launch failed");
    } finally {
      setLaunchBusy(false);
    }
  }

  async function runCurrentBuildAudit() {
    if (demoMode) return;

    setBuildAuditBusy(true);
    try {
      const audit = await runBuildAudit({ path: projectProfile?.path });
      setBuildAudits((current) => [audit, ...current.filter((item) => item.id !== audit.id)]);
      setSelectedBuildAuditId(audit.id);
      setBuildAuditError(null);
      setPanelNotice("Build Auditor scan saved");
    } catch (error) {
      setBuildAuditError(error instanceof Error ? error.message : "Build audit failed");
    } finally {
      setBuildAuditBusy(false);
    }
  }

  async function checkCurrentProject() {
    if (runtimeCompatibilityError) {
      setPanelNotice(runtimeCompatibilityError);
      return;
    }
    if (demoMode || PUBLIC_SNAPSHOT_MODE || setupStatus?.read_only || companionStatus?.read_only) {
      setPanelNotice("Public preview is read-only. Run AutoCore locally to check a real project.");
      return;
    }

    setGuidedAuditBusy(true);
    setGuidedAuditError(null);
    try {
      const guided = await runGuidedAudit({
        path: projectProfile?.path,
        task_pack_id: selectedPack?.id,
        task_id: selectedTask?.id,
        provider: promptProvider,
        model: promptModel,
        critique_enabled: promptCritiqueEnabled,
      });
      setGuidedAudit(guided);
      setPromptEvaluations((current) => [guided.prompt_evaluation, ...current.filter((item) => item.id !== guided.prompt_evaluation.id)]);
      setSelectedPromptEvaluationId(guided.prompt_evaluation.id);
      setBuildAudits((current) => [guided.build_audit, ...current.filter((item) => item.id !== guided.build_audit.id)]);
      setSelectedBuildAuditId(guided.build_audit.id);
      setRuntimeRun(guided.run);
      setSelectedPackId(guided.run.task_pack_id);
      setEvidenceBundle(null);
      const nextTrace = runtimeTrace(guided.run);
      setTraceEvents(nextTrace);
      setSelectedTrace(nextTrace[nextTrace.length - 1]?.id ?? selectedTrace);
      setRunHistory(await fetchRunHistory(12));
      setEvidenceLibrary(await fetchEvidenceLibrary());
      setRuntimeState("live");
      setRuntimeError(null);
      setBuildAuditError(null);
      setPromptLabError(null);
      setActiveSurface("runs");
      setViewerTab("planner");
      setPanelNotice(`${guided.next_action.label}: ${guided.next_action.detail}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Guided audit failed";
      setGuidedAuditError(message);
      setPanelNotice(message);
    } finally {
      setGuidedAuditBusy(false);
    }
  }

  async function launchSelectedTaskPack() {
    if (demoMode || !selectedPack || !selectedTask) return;

    setLaunchBusy(true);
    try {
      const run = await createRuntimeRun({
        task_pack_id: selectedPack.id,
        task_id: selectedTask.id,
      });
      setRuntimeRun(run);
      setSelectedPackId(run.task_pack_id);
      setEvidenceBundle(null);
      const nextTrace = runtimeTrace(run);
      setTraceEvents(nextTrace);
      setSelectedTrace(nextTrace[nextTrace.length - 1]?.id ?? selectedTrace);
      setRunHistory(await fetchRunHistory(12));
      setEvidenceLibrary(await fetchEvidenceLibrary());
      setRuntimeState("live");
      setRuntimeError(null);
      setViewerTab("planner");
    } catch (error) {
      setRuntimeError(error instanceof Error ? error.message : "Task pack launch failed");
    } finally {
      setLaunchBusy(false);
    }
  }

  async function loadHistoryRun(runId: string) {
    setActiveSurface("runs");
    if (demoSnapshot?.run.id === runId) {
      applyDemoSnapshot(demoSnapshot);
      return;
    }

    if (demoMode) return;

    try {
      const run = await fetchRun(runId);
      setRuntimeRun(run);
      setSelectedPackId(run.task_pack_id);
      setEvidenceBundle(null);
      const nextTrace = runtimeTrace(run);
      setTraceEvents(nextTrace);
      setSelectedTrace(nextTrace[nextTrace.length - 1]?.id ?? baseTrace[0].id);
      if (run.status === "evidence_ready") {
        setEvidenceBundle(await fetchEvidenceBundle(run.id));
        setViewerTab("report");
      } else {
        setViewerTab("planner");
      }
      setRuntimeState("live");
      setRuntimeError(null);
    } catch (error) {
      setRuntimeError(error instanceof Error ? error.message : "Run selection failed");
    }
  }

  async function updateTerminalGate(nextState: GateState) {
    if (demoMode) return;

    if (runtimeRun && primaryCommand) {
      setActionBusy(true);
      try {
        const updated =
          nextState === "approved"
            ? await approveRuntimeCommand(runtimeRun.id, primaryCommand.id)
            : await holdRuntimeCommand(runtimeRun.id, primaryCommand.id);
        setRuntimeRun(updated);
        if (updated.status === "evidence_ready") {
          setEvidenceBundle(await fetchEvidenceBundle(updated.id));
          setActiveSurface("evidence");
          setViewerTab("report");
          setPanelNotice("Evidence report ready");
        }
        setRunHistory(await fetchRunHistory(12));
        setEvidenceLibrary(await fetchEvidenceLibrary());
        const nextTrace = runtimeTrace(updated);
        setTraceEvents(nextTrace);
        setSelectedTrace(nextTrace[nextTrace.length - 1]?.id ?? selectedTrace);
        setRuntimeState("live");
        setRuntimeError(null);
      } catch (error) {
        setRuntimeError(error instanceof Error ? error.message : "Runtime action failed");
      } finally {
        setActionBusy(false);
      }
      return;
    }

    setLocalGates((current) =>
      current.map((gate) => (gate.id === "terminal" ? { ...gate, state: nextState } : gate)),
    );

    const nextEvent: TraceEvent =
      nextState === "approved"
        ? {
            id: `t-${Date.now()}`,
            time: formatTime(new Date().toISOString()),
            title: "Safe checks approved",
            detail: "Operator approved allowlisted terminal commands with output capture.",
            status: "ok",
            icon: Check,
          }
        : {
            id: `t-${Date.now()}`,
            time: formatTime(new Date().toISOString()),
            title: "Execution held",
            detail: "Operator kept command execution paused pending a narrower plan.",
            status: "attention",
            icon: Square,
          };

    setTraceEvents((current) => [...current, nextEvent]);
    setSelectedTrace(nextEvent.id);
  }

  async function auditLatestCodexChanges() {
    if (demoMode || PUBLIC_SNAPSHOT_MODE || companionStatus?.read_only) {
      setPanelNotice("Public preview is read-only. Run AutoCore locally to audit Codex changes.");
      return;
    }
    setCompanionBusy(true);
    try {
      const result = await auditCompanionChanges();
      setCompanionStatus(result.companion);
      setBuildAudits((current) => [result.audit, ...current.filter((audit) => audit.id !== result.audit.id)]);
      setSelectedBuildAuditId(result.audit.id);
      setActiveSurface("audit");
      setPanelNotice("Codex changes audited and evidence saved");
      setCompanionError(null);
    } catch (error) {
      setCompanionError(error instanceof Error ? error.message : "Codex companion audit failed");
    } finally {
      setCompanionBusy(false);
    }
  }

  function handleSetupStep(stepId: string) {
    if (stepId === "choose_project") {
      void chooseProjectFolder();
      return;
    }
    if (stepId === "guided_audit" || stepId === "check_this_project") {
      void checkCurrentProject();
      return;
    }
    if (stepId === "run_prompt_lab") {
      setActiveSurface("lab");
      return;
    }
    if (stepId === "preflight_next_prompt") {
      setActiveSurface("lab");
      return;
    }
    if (stepId === "inspect_high_risk_files") {
      setActiveSurface("companion");
      return;
    }
    if (stepId === "review_claims") {
      setActiveSurface("audit");
      return;
    }
    if (stepId === "run_audit") {
      setActiveSurface("runs");
      void launchSelectedTaskPack();
      return;
    }
    if (stepId === "review_snapshot" || stepId === "switch_live") {
      setActiveSurface(stepId === "review_snapshot" ? "evidence" : "connect");
      return;
    }
    if (stepId === "optional_byok") {
      setActiveSurface("lab");
      setPromptCritiqueEnabled(true);
      return;
    }
    if (stepId === "audit_latest_codex_changes") {
      setActiveSurface("companion");
      void auditLatestCodexChanges();
      return;
    }
    setActiveSurface("overview");
  }

  return (
    <main className="console-shell">
      <aside className="console-rail" aria-label="AutoCore navigation">
        <div className="rail-brand">
          <div className="brand-mark">
            <Command size={18} aria-hidden="true" />
          </div>
          <div>
            <strong>AutoCore</strong>
            <span>Evidence Console</span>
          </div>
        </div>

        <section className="rail-section">
          <div className="rail-title">
            <span>Runtime</span>
            <strong>{statusLabel}</strong>
          </div>
          <div className="runtime-ledger">
            <span>{demoMode ? "snapshot" : runtimeState === "live" ? runtimeLabel : "fallback"}</span>
            <p>
              {demoMode
                ? "Seeded run loaded. Mutating controls are locked."
                : runtimeState === "live"
                  ? "Local API connected. Live approvals are available."
                  : runtimeError ?? "Start the backend to connect live runs."}
            </p>
          </div>
        </section>

        <section className="rail-section">
          <div className="rail-title">
            <span>Run Queue</span>
            <strong>{historySummary?.total_runs ?? "--"}</strong>
          </div>
          <div className="run-list">
            {historyRows.length ? (
              historyRows.slice(0, 6).map((row) => (
                <button
                  aria-current={runtimeRun?.id === row.id ? "true" : undefined}
                  className={`run-row ${row.grade} ${runtimeRun?.id === row.id ? "selected" : ""}`}
                  key={row.id}
                  onClick={() => void loadHistoryRun(row.id)}
                  type="button"
                >
                  <span>{row.id}</span>
                  <strong>{row.goal}</strong>
                  <small>
                    {row.grade} / {row.score}
                  </small>
                </button>
              ))
            ) : (
              <div className="empty-rail-row">No stored run history yet.</div>
            )}
          </div>
        </section>

        <section className="rail-section task-rail">
          <div className="rail-title">
            <span>Task Packs</span>
            <strong>{taskPacks.length || "--"}</strong>
          </div>
          <div className="pack-stack">
            {taskPacks.map((pack) => (
              <button
                className={`pack-row ${selectedPackId === pack.id ? "selected" : ""}`}
                key={pack.id}
                onClick={() => setSelectedPackId(pack.id)}
              >
                <span>{pack.category}</span>
                <strong>{pack.name}</strong>
                <small>{pack.risk_level} risk</small>
              </button>
            ))}
            {!taskPacks.length && <div className="empty-rail-row">Task registry waiting for runtime.</div>}
          </div>
        </section>
      </aside>

      <section className={`console-workspace surface-${activeSurface}`}>
        <header className="console-topbar">
          <div className="topbar-title">
            <span className="screen-label">Corporate Cockpit / Evidence Operations</span>
            <h1>AutoCore OCC Dashboard</h1>
            <nav className="cockpit-nav" aria-label="Dashboard sections" role="tablist">
              {surfaceTabs.map((tab) => (
                <button
                  aria-controls={`surface-panel-${tab}`}
                  aria-current={activeSurface === tab ? "page" : undefined}
                  aria-selected={activeSurface === tab}
                  className={activeSurface === tab ? "selected" : ""}
                  id={`surface-tab-${tab}`}
                  key={tab}
                  onClick={() => setActiveSurface(tab)}
                  role="tab"
                  type="button"
                >
                  {surfaceTabLabel[tab]}
                </button>
              ))}
            </nav>
          </div>
          <div className="topbar-actions">
            <div className="topbar-clock">
              <span>Local time</span>
              <strong>{formatTime(new Date().toISOString())}</strong>
            </div>
            <div className="mode-switch" aria-label="Execution mode">
              <button className={mode === "guarded" ? "selected" : ""} onClick={() => setMode("guarded")}>
                <ShieldCheck size={15} aria-hidden="true" />
                Guarded
              </button>
              <button className={mode === "observe" ? "selected" : ""} onClick={() => setMode("observe")}>
                <Activity size={15} aria-hidden="true" />
                Observe
              </button>
            </div>
            <button className="demo-load-button" disabled={!demoSnapshot} onClick={() => demoSnapshot && applyDemoSnapshot(demoSnapshot)}>
              <FileJson size={15} aria-hidden="true" />
              {demoMode ? "Reset Snapshot" : "Load Snapshot"}
            </button>
          </div>
        </header>

        {demoMode && demoSnapshot && (
          <section className={`release-docket ${demoMode ? "active" : ""}`} aria-label="Public release docket">
            <div>
              <span>Public read-only snapshot</span>
              <strong>{demoSnapshot.case_study.title}</strong>
              <p>{demoSnapshot.case_study.problem}</p>
            </div>
            <div className="release-proofs">
              {demoSnapshot.case_study.proof_points.slice(0, 3).map((point) => (
                <span key={point}>
                  <Check size={13} aria-hidden="true" />
                  {point}
                </span>
              ))}
            </div>
          </section>
        )}

        {runtimeCompatibilityError && !demoMode && (
          <section className="runtime-mismatch" role="alert">
            <div>
              <span>Runtime mismatch</span>
              <strong>Restart AutoCore</strong>
              <p>{runtimeCompatibilityError}</p>
            </div>
            <code>{runtimeLabel}</code>
          </section>
        )}

        {panelNotice && (
          <div className="operator-toast" role="status">
            {panelNotice}
            <button onClick={() => setPanelNotice(null)} type="button">
              Dismiss
            </button>
          </div>
        )}

        <section
          aria-labelledby={`surface-tab-${activeSurface}`}
          className="dashboard-tab-panel"
          id={`surface-panel-${activeSurface}`}
          role="tabpanel"
        >
          <section className="companion-console" aria-label="Codex Companion Mode">
            <div className="companion-hero">
              <div>
                <span>Codex Companion Mode</span>
                <h2>
                  {companionStatus?.verdict === "clean"
                    ? "No Codex changes waiting."
                    : companionStatus?.read_only
                      ? "Preview the workflow, then run locally."
                      : "Review the latest Codex changes before trusting them."}
                </h2>
                <p>
                  {companionStatus
                    ? `${companionStatus.summary.changed_files} changed files / ${companionStatus.summary.high_risk_files} high risk`
                    : companionError ?? "Checking the current workspace for changed files and audit evidence."}
                </p>
              </div>
              <div className="companion-actions">
                <div className={`status-badge ${companionStatus?.verdict ?? "waiting"}`}>{companionStatus?.verdict ?? "waiting"}</div>
                <button disabled={demoMode || PUBLIC_SNAPSHOT_MODE || guidedAuditBusy || companionStatus?.read_only} onClick={() => void checkCurrentProject()} type="button">
                  <Play size={15} aria-hidden="true" />
                  {guidedAuditBusy ? "Checking" : companionStatus?.read_only ? "Read-only" : "Check this project"}
                </button>
                <button disabled={demoMode || PUBLIC_SNAPSHOT_MODE || companionBusy || companionStatus?.read_only} onClick={() => void auditLatestCodexChanges()} type="button">
                  <SearchCheck size={15} aria-hidden="true" />
                  {companionBusy ? "Auditing" : companionStatus?.read_only ? "Read-only" : "Audit latest Codex changes"}
                </button>
              </div>
            </div>

            <div className="companion-grid">
              <section className="companion-card">
                <div className="panel-title-row compact">
                  <div>
                    <span>Working Tree</span>
                    <h3>{companionStatus?.project.name ?? "No project loaded"}</h3>
                  </div>
                  <GitCompareArrows size={17} aria-hidden="true" />
                </div>
                <div className="companion-metrics">
                  <div>
                    <span>Changed</span>
                    <strong>{companionStatus?.summary.changed_files ?? "--"}</strong>
                  </div>
                  <div>
                    <span>High risk</span>
                    <strong>{companionStatus?.summary.high_risk_files ?? "--"}</strong>
                  </div>
                  <div>
                    <span>Tests</span>
                    <strong>{companionStatus?.summary.tests_changed ?? "--"}</strong>
                  </div>
                  <div>
                    <span>Docs</span>
                    <strong>{companionStatus?.summary.docs_changed ?? "--"}</strong>
                  </div>
                </div>
                <p>
                  {companionStatus?.latest_audit
                    ? `Latest audit ${companionStatus.latest_audit.verdict} / ${companionStatus.latest_audit.overall}.`
                    : "No companion audit has been attached to these changes yet."}
                </p>
                <div className="setup-action-row">
                  <button disabled={demoMode || PUBLIC_SNAPSHOT_MODE || projectBusy || companionStatus?.read_only} onClick={() => void chooseProjectFolder()} type="button">
                    <FolderGit2 size={14} aria-hidden="true" />
                    {projectBusy ? "Choosing" : companionStatus?.read_only ? "Read-only" : "Choose repo folder"}
                  </button>
                  <button disabled={demoMode || PUBLIC_SNAPSHOT_MODE || projectBusy || companionStatus?.read_only} onClick={() => void refreshProject()} type="button">
                    <RefreshCcw size={14} aria-hidden="true" />
                    Refresh
                  </button>
                </div>
              </section>

              <section className="companion-card companion-prompt-card">
                <div className="panel-title-row compact">
                  <div>
                    <span>Codex Prompt</span>
                    <h3>Use this before the next large change</h3>
                  </div>
                  <Copy size={17} aria-hidden="true" />
                </div>
                <p>{companionStatus?.suggested_prompt ?? "Load companion status to generate a prompt."}</p>
                <button onClick={() => companionStatus && void copyText("Companion prompt", companionStatus.suggested_prompt)} type="button" disabled={!companionStatus}>
                  <Copy size={14} aria-hidden="true" />
                  Copy prompt
                </button>
              </section>
            </div>

            <section className="companion-files-card">
              <div className="panel-title-row compact">
                <div>
                  <span>Changed Files</span>
                  <h3>What AutoCore will inspect</h3>
                </div>
                <FileSearch size={17} aria-hidden="true" />
              </div>
              {companionError && <div className="connector-error">Companion error: {companionError}</div>}
              <div className="companion-file-list">
                {(companionStatus?.changed_files ?? []).slice(0, 18).map((file) => (
                  <div className={`companion-file ${file.risk}`} key={`${file.status}-${file.path}`}>
                    <div>
                      <strong>{file.path}</strong>
                      <small>{file.status} / {file.category}</small>
                    </div>
                    <span>{file.risk}</span>
                    <p>{file.signals.length ? file.signals.join(" / ") : "No immediate risk marker found."}</p>
                  </div>
                ))}
                {companionStatus && !companionStatus.changed_files.length && <div className="connector-empty">No changed files found. Use Codex, then refresh this surface.</div>}
                {!companionStatus && <div className="connector-empty">Companion status is loading.</div>}
              </div>
            </section>

            <section className="companion-next-card">
              <div className="panel-title-row compact">
                <div>
                  <span>Next Actions</span>
                  <h3>Plain path to trust</h3>
                </div>
                <Play size={17} aria-hidden="true" />
              </div>
              <div className="setup-step-list">
                {(companionStatus?.next_steps ?? []).map((step, index) => (
                  <button key={step.id} onClick={() => handleSetupStep(step.id)} type="button">
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <strong>{step.label}</strong>
                    <p>{step.detail}</p>
                  </button>
                ))}
              </div>
            </section>
          </section>

          <section className="setup-console" aria-label="First-run setup">
            <div className="setup-hero">
              <div>
                <span>First-run setup</span>
                <h2>{setupStatus?.headline ?? "Connect AutoCore, then run one guided audit."}</h2>
                <p>
                  {setupStatus
                    ? `${setupStatus.project.name} / ${setupStatus.project.stack}`
                    : setupError ?? "Checking project, runtime, providers, and containment status."}
                </p>
              </div>
              <GaugeDial detail={setupStatus?.readiness.label ?? "checking"} label="Setup" size="small" value={setupStatus?.readiness.score ?? 0} />
            </div>

            <div className="setup-grid">
              <section className="setup-card setup-project-card">
                <div className="panel-title-row compact">
                  <div>
                    <span>Project</span>
                    <h3>{setupStatus?.project.exists ? setupStatus.project.name : "Choose a project"}</h3>
                  </div>
                  <FolderGit2 size={17} aria-hidden="true" />
                </div>
                <p>{setupStatus?.project.path ?? "Start the local runtime to inspect a project folder."}</p>
                <div className="connector-scope-chips">
                  <span>{setupStatus?.project.stack ?? "unknown stack"}</span>
                  <span>{setupStatus?.project.recommended_command ?? "no command selected"}</span>
                </div>
                <div className="setup-action-row">
                  <button disabled={demoMode || PUBLIC_SNAPSHOT_MODE || projectBusy || setupStatus?.read_only} onClick={() => void chooseProjectFolder()} type="button">
                    <FolderGit2 size={14} aria-hidden="true" />
                    {projectBusy ? "Choosing" : setupStatus?.read_only ? "Read-only" : "Choose folder"}
                  </button>
                  <button disabled={demoMode || PUBLIC_SNAPSHOT_MODE || projectBusy || setupStatus?.read_only} onClick={() => setActiveSurface("connect")} type="button">
                    Paste path
                  </button>
                </div>
              </section>

              <section className="setup-card">
                <div className="panel-title-row compact">
                  <div>
                    <span>Modes</span>
                    <h3>Choose how to use AutoCore</h3>
                  </div>
                  <ShieldCheck size={17} aria-hidden="true" />
                </div>
                <div className="setup-mode-list">
                  {(setupStatus?.modes ?? []).map((modeOption) => (
                    <div className={modeOption.available ? "ready" : "optional"} key={modeOption.id}>
                      <strong>{modeOption.label}</strong>
                      <span>{modeOption.available ? "available" : "not active"}</span>
                      <p>{modeOption.detail}</p>
                    </div>
                  ))}
                </div>
              </section>

              <section className="setup-card">
                <div className="panel-title-row compact">
                  <div>
                    <span>Requirements</span>
                    <h3>Can AutoCore run?</h3>
                  </div>
                  <Activity size={17} aria-hidden="true" />
                </div>
                <div className="setup-check-list">
                  {(setupStatus?.checks ?? []).map((check) => (
                    <div className={`setup-check ${check.status}`} key={check.id}>
                      <strong>{check.label}</strong>
                      <span>{check.status}</span>
                      <p>{check.detail}</p>
                    </div>
                  ))}
                </div>
              </section>

              <section className="setup-card">
                <div className="panel-title-row compact">
                  <div>
                    <span>BYOK</span>
                    <h3>Provider options</h3>
                  </div>
                  <KeyRound size={17} aria-hidden="true" />
                </div>
                <div className="setup-provider-list">
                  {(setupStatus?.providers ?? []).map((provider) => (
                    <div className={provider.configured ? "ready" : "optional"} key={provider.id}>
                      <strong>{provider.label}</strong>
                      <span>{provider.configured ? "connected" : "optional"}</span>
                      <p>{provider.detail}</p>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            <section className="setup-next-card">
              <div className="panel-title-row compact">
                <div>
                  <span>Guided audit</span>
                  <h3>What to do next</h3>
                </div>
                <Play size={17} aria-hidden="true" />
              </div>
              <div className="guided-audit-banner">
                <div>
                  <strong>{guidedAudit ? guidedAudit.next_action.label : "Check this project"}</strong>
                  <p>
                    {guidedAudit
                      ? guidedAudit.next_action.detail
                      : "Create a Prompt Lab score, Build Auditor scan, and approval-gated run in one local workflow."}
                  </p>
                </div>
                <button disabled={demoMode || PUBLIC_SNAPSHOT_MODE || guidedAuditBusy || setupStatus?.read_only} onClick={() => void checkCurrentProject()} type="button">
                  <SearchCheck size={15} aria-hidden="true" />
                  {guidedAuditBusy ? "Checking" : setupStatus?.read_only ? "Read-only" : "Check this project"}
                </button>
              </div>
              {guidedAuditError && <div className="connector-error">Guided audit error: {guidedAuditError}</div>}
              <div className="setup-step-list">
                {(setupStatus?.next_steps ?? []).map((step, index) => (
                  <button key={step.id} onClick={() => handleSetupStep(step.id)} type="button">
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <strong>{step.label}</strong>
                    <p>{step.detail}</p>
                  </button>
                ))}
              </div>
            </section>
          </section>

          <DashboardRow
            className="summary-row"
            collapsed={Boolean(collapsedRows["health-quick-scan"])}
            id="health-quick-scan"
            layout="Auto grid"
            onToggle={toggleRow}
            title="Health and quick scan"
          >
            <section className="cockpit-summary" aria-label="AutoCore operational overview">
              <div className="cockpit-card health-card">
                <div className="panel-title-row compact">
                  <div>
                    <span>Health</span>
                    <h2>Autonomy control status</h2>
                  </div>
                  <ShieldCheck size={18} aria-hidden="true" />
                </div>
                <div className="health-grid">
                  <GaugeDial
                    detail={scorecard?.grade?.replace("_", " ") ?? "waiting for scorecard"}
                    label="Score"
                    size="large"
                    value={scorecard?.overall ?? 0}
                  />
                  <div className="node-ledger">
                    <strong>Nodes</strong>
                    <span className="node-line online">
                      <Check size={15} aria-hidden="true" />
                      Evidence: {completedCommands}
                    </span>
                    <span className={`node-line ${failedCommands ? "offline" : "online"}`}>
                      <X size={15} aria-hidden="true" />
                      Failed: {failedCommands}
                    </span>
                    <span className={`node-line ${blockedActions ? "offline" : "online"}`}>
                      <Ban size={15} aria-hidden="true" />
                      Blocked: {blockedActions}
                    </span>
                  </div>
                </div>
              </div>

              <div className="cockpit-card resources-card">
                <div className="panel-title-row compact">
                  <div>
                    <span>Resources</span>
                    <h2>Run readiness</h2>
                  </div>
                  <Activity size={18} aria-hidden="true" />
                </div>
                <div className="resource-gauges">
                  <GaugeDial detail="verification" label="Task" size="small" value={taskSuccessScore} />
                  <GaugeDial detail="bundle" label="Evidence" size="small" value={evidenceScore} />
                  <GaugeDial detail="dependency" label="Hands off" size="small" value={handsOffScore} />
                </div>
              </div>

              <div className="cockpit-card quick-scan-card">
                <div className="panel-title-row compact">
                  <div>
                    <span>Start quick scan</span>
                    <h2>{selectedTask?.title ?? "Select task pack"}</h2>
                  </div>
                  <TerminalSquare size={18} aria-hidden="true" />
                </div>
                <div className="quick-scan-row">
                  <code>{plannerCommandText}</code>
                  <button disabled={demoMode || launchBusy || !selectedPack || !selectedTask} onClick={launchSelectedTaskPack}>
                    {demoMode ? "Read-only" : launchBusy ? "Starting" : "Quick scan"}
                  </button>
                </div>
                <div className="scanner-strip">
                  <span>NMAP</span>
                  <i />
                  <span>POLICY</span>
                  <i />
                  <span>EVIDENCE</span>
                </div>
              </div>
            </section>
          </DashboardRow>

          <DashboardRow
            className="detail-row"
            collapsed={Boolean(collapsedRows[`detail-${activeSurface}`])}
            id={`detail-${activeSurface}`}
            layout={activeRowLayout[activeSurface]}
            onToggle={toggleRow}
            title={activeRowTitle[activeSurface]}
          >
            <div className="workbench-grid">
          <section className="primary-stack">
            <section className="console-panel prompt-lab-console" aria-label="Prompt Lab preflight">
              <div className="panel-title-row">
                <div>
                  <span>Prompt Lab</span>
                  <h2>Pre-run readiness check</h2>
                </div>
                <div className="panel-title-actions">
                  <div className={`status-badge ${selectedPromptEvaluation?.verdict ?? "waiting"}`}>
                    {selectedPromptEvaluation?.verdict ?? "waiting"}
                  </div>
                  <FileSearch size={18} aria-hidden="true" />
                </div>
              </div>
              <div className="prompt-lab-grid">
                <div className="prompt-input-stack">
                  <textarea
                    aria-label="Task prompt to evaluate"
                    disabled={demoMode}
                    onChange={(event) => setPromptDraft(event.target.value)}
                    value={promptDraft}
                  />
                  <div className="prompt-control-row">
                    <label>
                      <span>Provider</span>
                      <select disabled={demoMode} onChange={(event) => setPromptProvider(event.target.value)} value={promptProvider}>
                        <option value="offline">offline</option>
                        <option value="groq">groq</option>
                        <option value="openai">openai</option>
                        <option value="ollama">ollama</option>
                      </select>
                    </label>
                    <label>
                      <span>Model</span>
                      <input disabled={demoMode} onChange={(event) => setPromptModel(event.target.value)} value={promptModel} />
                    </label>
                    <label className="prompt-check">
                      <input
                        checked={promptCritiqueEnabled}
                        disabled={demoMode}
                        onChange={(event) => setPromptCritiqueEnabled(event.target.checked)}
                        type="checkbox"
                      />
                      <span>BYOK critique</span>
                    </label>
                  </div>
                  <div className="prompt-action-row">
                    <button disabled={demoMode || promptLabBusy || !promptDraft.trim()} onClick={() => void evaluatePromptDraft()} type="button">
                      <SearchCheck size={15} aria-hidden="true" />
                      {demoMode ? "Read-only" : promptLabBusy ? "Evaluating" : "Evaluate"}
                    </button>
                    <button
                      disabled={demoMode || launchBusy || !selectedPromptEvaluation || selectedPromptEvaluation.verdict === "blocked"}
                      onClick={() => void launchPromptEvaluation()}
                      type="button"
                    >
                      <Play size={15} aria-hidden="true" />
                      {launchBusy ? "Launching" : "Launch run"}
                    </button>
                  </div>
                  {promptLabError && <div className="connector-error">Prompt Lab error: {promptLabError}</div>}
                </div>

                <div className="prompt-score-board">
                  <GaugeDial
                    detail={selectedPromptEvaluation?.verdict ?? "not evaluated"}
                    label="Lab"
                    size="small"
                    value={selectedPromptEvaluation?.overall ?? 0}
                  />
                  <div className="prompt-score-grid">
                    {Object.entries(selectedPromptEvaluation?.scores ?? {}).map(([label, value]) => (
                      <div className="prompt-score-line" key={label}>
                        <span>{label.replace("_", " ")}</span>
                        <strong>{value}</strong>
                        <i style={{ width: `${value}%` }} />
                      </div>
                    ))}
                    {!selectedPromptEvaluation && <p>Evaluate a prompt to score clarity, evidence fit, tool risk, and budget fit.</p>}
                  </div>
                </div>
              </div>
            </section>

            <section className="console-panel prompt-budget-console" aria-label="Prompt Lab budget forecast">
              <div className="panel-title-row">
                <div>
                  <span>Budget Forecast</span>
                  <h2>{selectedPromptEvaluation ? `${selectedPromptEvaluation.token_forecast.est_total_tokens} tokens est.` : "No forecast yet"}</h2>
                </div>
                <Activity size={18} aria-hidden="true" />
              </div>
              <div className="prompt-budget-grid">
                <div>
                  <span>Input est.</span>
                  <strong>{selectedPromptEvaluation?.token_forecast.est_input_tokens ?? "--"}</strong>
                </div>
                <div>
                  <span>Output est.</span>
                  <strong>{selectedPromptEvaluation?.token_forecast.est_output_tokens ?? "--"}</strong>
                </div>
                <div>
                  <span>Context left</span>
                  <strong>{selectedPromptEvaluation?.token_forecast.context_remaining ?? "--"}</strong>
                </div>
                <div>
                  <span>Quota signal</span>
                  <strong>{selectedPromptEvaluation?.provider_signal.quota_known ? "known" : "unknown"}</strong>
                </div>
              </div>
              <div className="provider-signal-box">
                <strong>
                  {selectedPromptEvaluation
                    ? `${selectedPromptEvaluation.provider_signal.provider} / ${selectedPromptEvaluation.provider_signal.model}`
                    : "Provider signal waiting"}
                </strong>
                <p>{selectedPromptEvaluation?.provider_signal.notes ?? "Exact provider quota appears only when a real provider exposes it."}</p>
                <div className="connector-scope-chips">
                  <span>source: {selectedPromptEvaluation?.provider_signal.source ?? "none"}</span>
                  <span>freshness: {selectedPromptEvaluation?.provider_signal.freshness ?? "unknown"}</span>
                  <span>remaining tokens: {selectedPromptEvaluation?.provider_signal.remaining_tokens ?? "unknown"}</span>
                </div>
              </div>
            </section>

            <section className="console-panel prompt-recommendations-console" aria-label="Prompt Lab recommendations">
              <div className="panel-title-row">
                <div>
                  <span>Recommended Action</span>
                  <h2>{selectedPromptEvaluation?.verdict ?? "Evaluate first"}</h2>
                </div>
                <ShieldCheck size={18} aria-hidden="true" />
              </div>
              <div className="prompt-finding-list">
                {(selectedPromptEvaluation?.findings.length ? selectedPromptEvaluation.findings : [{ severity: "info", message: "No findings yet." }]).map(
                  (finding) => (
                    <div className={`prompt-finding ${finding.severity}`} key={finding.message}>
                      <strong>{finding.severity}</strong>
                      <p>{finding.message}</p>
                    </div>
                  ),
                )}
              </div>
              <div className="prompt-recommendation-list">
                {(selectedPromptEvaluation?.recommendations ?? ["Evaluate a prompt to generate run guidance."]).map((recommendation) => (
                  <span key={recommendation}>{recommendation}</span>
                ))}
              </div>
            </section>

            <section className="console-panel build-auditor-console" aria-label="AI Build Auditor">
              <div className="panel-title-row">
                <div>
                  <span>AI Build Auditor</span>
                  <h2>{selectedBuildAudit ? `${selectedBuildAudit.project.name} trust check` : "No audit yet"}</h2>
                </div>
                <div className="panel-title-actions">
                  <div className={`status-badge ${selectedBuildAudit?.verdict ?? "waiting"}`}>
                    {selectedBuildAudit?.verdict ?? "waiting"}
                  </div>
                  <button className="panel-mini-button" disabled={demoMode || buildAuditBusy} onClick={() => void runCurrentBuildAudit()} type="button">
                    <SearchCheck size={13} aria-hidden="true" />
                    {demoMode ? "Read-only" : buildAuditBusy ? "Scanning" : "Run audit"}
                  </button>
                </div>
              </div>
              {buildAuditError && <div className="connector-error">Build audit error: {buildAuditError}</div>}
              <div className="build-audit-grid">
                <div>
                  <span>Verdict</span>
                  <strong>{selectedBuildAudit?.verdict ?? "--"}</strong>
                </div>
                <div>
                  <span>Score</span>
                  <strong>{selectedBuildAudit?.overall ?? "--"}</strong>
                </div>
                <div>
                  <span>No mocked data</span>
                  <strong>{selectedBuildAudit ? (selectedBuildAudit.no_mocked_data ? "yes" : "no") : "--"}</strong>
                </div>
                <div>
                  <span>Source</span>
                  <strong>{selectedBuildAudit?.source ?? "none"}</strong>
                </div>
              </div>
              <div className="build-claim-grid">
                <div className={selectedBuildAudit?.claims.quality.status ?? "limited"}>
                  <span>Quality claim</span>
                  <strong>{selectedBuildAudit?.claims.quality.status.replace("_", " ") ?? "limited"}</strong>
                  <p>{selectedBuildAudit?.claims.quality.claim ?? "Run an audit before claiming code quality."}</p>
                </div>
                <div className={selectedBuildAudit?.claims.security.status ?? "limited"}>
                  <span>Security claim</span>
                  <strong>{selectedBuildAudit?.claims.security.status.replace("_", " ") ?? "limited"}</strong>
                  <p>{selectedBuildAudit?.claims.security.claim ?? "Run an audit before claiming security readiness."}</p>
                </div>
              </div>
              <div className="containment-box">
                <span>Execution containment</span>
                <strong>{selectedBuildAudit?.containment?.mode.replace("_", " ") ?? "not configured"}</strong>
                <p>{selectedBuildAudit?.containment?.notes ?? "Current execution uses guarded policy until a real containment runner is configured."}</p>
              </div>
            </section>

            <section className="console-panel build-audit-checks-console" aria-label="Build audit checks">
              <div className="panel-title-row">
                <div>
                  <span>Evidence Checks</span>
                  <h2>{selectedBuildAudit ? `${selectedBuildAudit.checks.length} checks` : "waiting"}</h2>
                </div>
                <ShieldCheck size={18} aria-hidden="true" />
              </div>
              <div className="build-check-list">
                {(selectedBuildAudit?.checks ?? []).map((check) => (
                  <div className={`build-check-line ${check.status}`} key={check.id}>
                    <div>
                      <strong>{check.label}</strong>
                      <p>{check.evidence}</p>
                    </div>
                    <span>{check.score}</span>
                  </div>
                ))}
                {!selectedBuildAudit && <div className="connector-empty">Run a local audit to inspect mocked data, quality signals, and security claim limits.</div>}
              </div>
            </section>

            <section className="console-panel claim-readiness-console" aria-label="Claim readiness">
              <div className="panel-title-row">
                <div>
                  <span>Claim Readiness</span>
                  <h2>{selectedBuildAudit ? "Honest public claims" : "waiting"}</h2>
                </div>
                <ShieldCheck size={18} aria-hidden="true" />
              </div>
              <div className="claim-readiness-list">
                {(selectedBuildAudit?.claim_readiness ?? []).map((item) => (
                  <div className={`claim-line ${item.status}`} key={item.claim}>
                    <div>
                      <strong>{item.claim}</strong>
                      <p>{item.evidence}</p>
                    </div>
                    <span>{item.status}</span>
                  </div>
                ))}
                {!selectedBuildAudit && <div className="connector-empty">Run an audit to see what AutoCore can honestly claim.</div>}
              </div>
            </section>

            <section className="console-panel security-scan-console" aria-label="Security scan evidence">
              <div className="panel-title-row">
                <div>
                  <span>Security Scan</span>
                  <h2>{selectedBuildAudit?.security_scan ? `${selectedBuildAudit.security_scan.status} / ${selectedBuildAudit.security_scan.overall}` : "waiting"}</h2>
                </div>
                <LockKeyhole size={18} aria-hidden="true" />
              </div>
              <p className="scan-scope">{selectedBuildAudit?.security_scan?.scope ?? "Static local scan has not run yet."}</p>
              <div className="build-check-list">
                {(selectedBuildAudit?.security_scan?.checks ?? []).map((check) => (
                  <div className={`build-check-line ${check.status}`} key={check.id}>
                    <div>
                      <strong>{check.label}</strong>
                      <p>{check.evidence}</p>
                    </div>
                    <span>{check.score}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="console-panel build-audit-recommendations-console" aria-label="Build audit recommendations">
              <div className="panel-title-row">
                <div>
                  <span>Next Fixes</span>
                  <h2>{selectedBuildAudit?.no_mocked_data === false ? "Mocked data found" : "Evidence gaps"}</h2>
                </div>
                <BadgeCheck size={18} aria-hidden="true" />
              </div>
              <div className="prompt-recommendation-list">
                {(selectedBuildAudit?.recommendations ?? ["Run an audit to generate evidence-backed recommendations."]).map((recommendation) => (
                  <span key={recommendation}>{recommendation}</span>
                ))}
              </div>
              {selectedBuildAudit?.mocked_findings.length ? (
                <div className="mock-finding-list">
                  {selectedBuildAudit.mocked_findings.slice(0, 6).map((finding) => (
                    <div key={finding.path}>
                      <strong>{finding.path}</strong>
                      <span>{finding.markers.join(" / ")}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>

            <section className="console-panel project-target-console" aria-label="Project target control">
              <div className="panel-title-row">
                <div>
                  <span>Project Target</span>
                  <h2>{projectProfile?.name ?? "Loading target"}</h2>
                </div>
                <div className="panel-title-actions">
                  <div className={`status-badge ${projectProfile?.exists ? "completed" : "blocked"}`}>
                    {projectProfile?.stack ?? "waiting"}
                  </div>
                  <button className="panel-mini-button" onClick={() => void refreshProject()} type="button">
                    <RefreshCcw size={13} aria-hidden="true" />
                    Refresh
                  </button>
                </div>
              </div>
              <div className="project-target-grid">
                <div>
                  <span>Control</span>
                  <strong>{projectProfile?.control ?? "AUTOCORE_PROJECT_ROOT"}</strong>
                </div>
                <div>
                  <span>Manifests</span>
                  <strong>{projectProfile?.manifests.length ?? "--"}</strong>
                </div>
                <div>
                  <span>Scripts</span>
                  <strong>{projectProfile?.scripts.length ?? "--"}</strong>
                </div>
                <div>
                  <span>Evidence</span>
                  <strong>{evidenceReports.length}</strong>
                </div>
              </div>
              <div className="project-path-row">
                <input
                  aria-label="Project target path"
                  onChange={(event) => setProjectPathDraft(event.target.value)}
                  value={projectPathDraft}
                />
                <button disabled={projectBusy || !projectPathDraft.trim()} onClick={() => void saveProjectTarget()} type="button">
                  {projectBusy ? "Saving" : "Use target"}
                </button>
              </div>
              {projectError && <div className="connector-error">Project target error: {projectError}</div>}
              <div className="connector-scope-chips project-manifests">
                {(projectProfile?.manifests ?? []).slice(0, 8).map((manifest) => (
                  <span key={manifest}>{manifest}</span>
                ))}
              </div>
            </section>

            <section className="console-panel live-proof-console" aria-label="Live audit proof">
              <div className="panel-title-row">
                <div>
                  <span>Live Personal Audit</span>
                  <h2>What just happened</h2>
                </div>
                <SearchCheck size={18} aria-hidden="true" />
              </div>
              <div className="live-proof-list">
                {liveProofSteps.map((step, index) => (
                  <div className={`live-proof-step ${step.complete ? "complete" : "waiting"}`} key={step.label}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    {step.complete ? <Check size={15} aria-hidden="true" /> : <Clock3 size={15} aria-hidden="true" />}
                    <div>
                      <strong>{step.label}</strong>
                      <p>{step.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="console-panel connector-console" aria-label="Connector setup">
              <div className="panel-title-row">
                <div>
                  <span>Connector Setup</span>
                  <h2>Source registry</h2>
                </div>
                <div className="panel-title-actions">
                  <div className="status-badge evidence_ready">{connectionBoundaryLabel}</div>
                  <button className="panel-mini-button" onClick={() => void refreshConnectors()} type="button">
                    <RefreshCcw size={13} aria-hidden="true" />
                    Refresh
                  </button>
                  <PlugZap size={18} aria-hidden="true" />
                </div>
              </div>
              {connectorError && <div className="connector-error">Connector backend error: {connectorError}</div>}

              <div className="connector-overview-grid">
                <div>
                  <span>Sources</span>
                  <strong>{connectorSummary.total}</strong>
                  <small>registered</small>
                </div>
                <div>
                  <span>Connected</span>
                  <strong>{connectorSummary.active}</strong>
                  <small>real source access</small>
                </div>
                <div>
                  <span>Guarded</span>
                  <strong>{connectorSummary.guarded}</strong>
                  <small>paused or syncing</small>
                </div>
                <div>
                  <span>Attention</span>
                  <strong>{connectorSummary.attention}</strong>
                  <small>auth review</small>
                </div>
              </div>

              <div className="connector-grid">
                {connectorSources.map((connector) => {
                  const ConnectorIcon = connectorIconMap[connector.id] ?? Cable;
                  return (
                    <button
                      className={`connector-card ${connector.state} ${selectedConnector?.id === connector.id ? "selected" : ""}`}
                      data-connector={connector.id}
                      key={connector.id}
                      onClick={() => setSelectedConnectorId(connector.id)}
                      type="button"
                    >
                      <div className="connector-card-head">
                        <ConnectorIcon size={18} aria-hidden="true" />
                        <div>
                          <strong>{connector.name}</strong>
                          <span>{connector.category}</span>
                        </div>
                      </div>
                      <span className={`connector-state ${connector.state}`}>{connectorStateLabel[connector.state]}</span>
                      <p>{connector.description}</p>
                      <div className="connector-scope-chips">
                        {connector.scopes.slice(0, 3).map((scope) => (
                          <span key={scope}>{scope}</span>
                        ))}
                      </div>
                    </button>
                  );
                })}
                {!connectorSources.length && <div className="connector-empty">Connector inventory is waiting for the backend.</div>}
              </div>
            </section>

            <section className="console-panel connector-permissions-console" aria-label="Connector permission model">
              <div className="panel-title-row">
                <div>
                  <span>Permission Model</span>
                  <h2>Default connector contract</h2>
                </div>
                <ShieldCheck size={18} aria-hidden="true" />
              </div>
              <div className="permission-matrix">
                {connectorPermissions.map((permission) => (
                  <div className={`permission-cell ${permission.status}`} key={permission.label}>
                    <span>{permission.label}</span>
                    <p>{permission.detail}</p>
                  </div>
                ))}
                {!connectorPermissions.length && <div className="connector-empty">Permission model unavailable until the backend responds.</div>}
              </div>
              <div className="connector-scope-table">
                <div className="scope-table-header">
                  <span>Selected source</span>
                  <span>Approved read scopes</span>
                </div>
                <div className="scope-table-row">
                  <strong>{selectedConnector?.name ?? "No source selected"}</strong>
                  <p>{selectedConnector?.scopes.join(" / ") ?? "Backend inventory unavailable"}</p>
                </div>
              </div>
            </section>

            <section className="console-panel run-docket" aria-label="Active run docket">
              <div className="panel-title-row">
                <div>
                  <span>Current Run</span>
                  <h2>{runtimeRun?.goal ?? "Repo hardening audit"}</h2>
                </div>
                <div className="panel-title-actions">
                  <div className={`status-badge ${runStatus}`}>{runStatus}</div>
                  <div className="panel-actions" aria-label="Current run actions">
                    <button disabled={!runtimeRun} onClick={() => runtimeRun && void copyText("Run ID", runtimeRun.id)} type="button">
                      <Copy size={13} aria-hidden="true" />
                      Copy ID
                    </button>
                    <button onClick={() => void refreshActiveRun()} type="button">
                      <RefreshCcw size={13} aria-hidden="true" />
                      Refresh
                    </button>
                  </div>
                </div>
              </div>

              <div className="run-docket-grid">
                <div>
                  <span>Run ID</span>
                  <strong>{runtimeRun?.id ?? "local-seed"}</strong>
                </div>
                <div>
                  <span>Stack</span>
                  <strong>{runtimeRun?.inspection.stack ?? "React/Vite"}</strong>
                </div>
                <div>
                  <span>Provider</span>
                  <strong>{providerLabel}</strong>
                </div>
                <div>
                  <span>Score</span>
                  <strong>{scorecard?.overall ?? "--"}</strong>
                </div>
              </div>

              <div className="selected-command">
                <TerminalSquare size={17} aria-hidden="true" />
                <div>
                  <span>Selected command</span>
                  <code>{plannerCommandText}</code>
                </div>
              </div>
            </section>

            <section className="console-panel trace-console" aria-label="Replay timeline">
              <div className="panel-title-row">
                <div>
                  <span>Replay</span>
                  <h2>Trace Timeline</h2>
                </div>
                <small>{traceEvents.length} events</small>
              </div>
              <div className="trace-console-grid">
                <div className="trace-table">
                  {traceEvents.map((event) => {
                    const Icon = event.icon;
                    return (
                      <button
                        className={`trace-line ${event.status} ${selectedTrace === event.id ? "selected" : ""}`}
                        key={event.id}
                        onClick={() => setSelectedTrace(event.id)}
                      >
                        <span>{event.time}</span>
                        <Icon size={15} aria-hidden="true" />
                        <strong>{event.title}</strong>
                      </button>
                    );
                  })}
                </div>
                <div className={`trace-inspector ${activeTrace.status}`}>
                  <ActiveTraceIcon size={20} aria-hidden="true" />
                  <span>{activeTrace.time}</span>
                  <strong>{activeTrace.title}</strong>
                  <p>{activeTrace.detail}</p>
                  <code>{activeTrace.status === "blocked" ? "policy.network = deny" : "trace.replay = recorded"}</code>
                </div>
              </div>
            </section>

            <section className="console-panel command-console" aria-label="Command transcript">
              <div className="panel-title-row">
                <div>
                  <span>Transcript</span>
                  <h2>{primaryCommand?.command_text ?? "No command selected"}</h2>
                </div>
                <div className="panel-title-actions">
                  <div className={`status-badge ${primaryCommand?.state ?? "pending"}`}>{primaryCommand?.state ?? "none"}</div>
                  <div className="panel-actions" aria-label="Transcript actions">
                    <button onClick={() => void copyText("Command output", commandOutput)} type="button">
                      <Copy size={13} aria-hidden="true" />
                      Copy output
                    </button>
                  </div>
                </div>
              </div>
              <div className="command-meta">
                <span>exit: {primaryCommand?.exit_code ?? "--"}</span>
                <span>duration: {formatDuration(primaryCommand?.duration_ms ?? 0)}</span>
                <span>policy: {primaryCommand?.policy_allowed ? "allowed" : "waiting"}</span>
              </div>
              <pre>{commandOutput}</pre>
            </section>

            <section className="console-panel telemetry-panel" aria-label="Runtime telemetry">
              <div className="panel-title-row">
                <div>
                  <span>Real time</span>
                  <h2>Evidence signal</h2>
                </div>
                <small>{runtimeRun ? `created ${formatDate(runtimeRun.created_at)}` : "waiting"}</small>
              </div>
              <TelemetryGraph tone={cockpitTone} />
              <div className="delay-table">
                <div className="delay-header">
                  <span>Dimension</span>
                  <span>Weight</span>
                  <span>Score</span>
                </div>
                {topDelayRows.map((dimension) => (
                  <div className="delay-row" key={dimension.id}>
                    <span>{scoreDimensionLabel(dimension)}</span>
                    <strong>{dimension.weight}</strong>
                    <strong>{dimension.score}</strong>
                  </div>
                ))}
              </div>
            </section>

            <section className="console-panel viewer-console" aria-label="Evidence viewer">
              <div className="panel-title-row">
                <div>
                  <span>Evidence Viewer</span>
                  <h2>{evidenceBundle?.summary.markdown_filename ?? "No report loaded"}</h2>
                </div>
                <div className="viewer-tools">
                  <div className="panel-actions" aria-label="Evidence report actions">
                    <button onClick={() => void copyText("Report", evidenceMarkdown)} type="button">
                      <Copy size={13} aria-hidden="true" />
                      Copy report
                    </button>
                    <button
                      onClick={() =>
                        downloadText(
                          evidenceBundle?.summary.markdown_filename ?? "autocore-evidence.md",
                          evidenceMarkdown,
                          "text/markdown",
                        )
                      }
                      type="button"
                    >
                      <Download size={13} aria-hidden="true" />
                      Download MD
                    </button>
                    <button
                      onClick={() =>
                        downloadText(
                          evidenceBundle?.summary.json_filename ?? "autocore-evidence.json",
                          evidenceJsonText,
                          "application/json",
                        )
                      }
                      type="button"
                    >
                      <Download size={13} aria-hidden="true" />
                      Download JSON
                    </button>
                  </div>
                  <div className="viewer-tabs" role="tablist" aria-label="Evidence sections">
                    {viewerTabs.map((tab) => (
                      <button
                        aria-selected={viewerTab === tab}
                        className={viewerTab === tab ? "selected" : ""}
                        key={tab}
                        onClick={() => setViewerTab(tab)}
                        role="tab"
                      >
                        {tab}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {viewerTab === "replay" && (
                <div className="ledger-list">
                  {traceEvents.map((event) => (
                    <div className={`ledger-row ${event.status}`} key={event.id}>
                      <span>{event.time}</span>
                      <strong>{event.title}</strong>
                      <p>{event.detail}</p>
                    </div>
                  ))}
                </div>
              )}

              {viewerTab === "planner" && (
                <div className="planner-grid">
                  <div>
                    <span>Provider</span>
                    <strong>{providerLabel}</strong>
                  </div>
                  <div>
                    <span>Mode</span>
                    <strong>{plannerProvider.mode ?? "local"}</strong>
                  </div>
                  <div>
                    <span>Confidence</span>
                    <strong>{planner.confidence ?? "--"}</strong>
                  </div>
                  <div>
                    <span>Selected</span>
                    <strong>{plannerCommandText}</strong>
                  </div>
                  <div className="planner-notes">
                    <span>Notes</span>
                    <p>{planner.notes ?? "No planner notes captured yet."}</p>
                  </div>
                  <div className="planner-notes">
                    <span>Risks</span>
                    {(planner.risks?.length ? planner.risks : ["No planner risk notes captured."]).map((risk) => (
                      <p key={risk}>{risk}</p>
                    ))}
                  </div>
                </div>
              )}

              {viewerTab === "output" && <pre className="evidence-pre">{commandOutput}</pre>}

              {viewerTab === "scorecard" && (
                <div className="score-ledger">
                  {(scorecard?.dimensions ?? []).map((dimension) => (
                    <div className="score-line" key={dimension.id}>
                      <div>
                        <strong>{scoreDimensionLabel(dimension)}</strong>
                        <p>{scoreDimensionEvidence(dimension)}</p>
                      </div>
                      <span>{dimension.score}</span>
                    </div>
                  ))}
                </div>
              )}

              {viewerTab === "report" && (
                <pre className="evidence-pre">{evidenceMarkdown}</pre>
              )}
            </section>
          </section>

          <aside className="inspector-stack" aria-label="Run inspectors">
            <section className="console-panel build-audit-history-dock">
              <div className="panel-title-row compact">
                <div>
                  <span>Audit History</span>
                  <h2>{buildAudits.length ? `${buildAudits.length} scans` : "empty"}</h2>
                </div>
                <FileSearch size={18} aria-hidden="true" />
              </div>
              <div className="prompt-history-list">
                {buildAudits.slice(0, 6).map((audit) => (
                  <button
                    className={selectedBuildAudit?.id === audit.id ? "selected" : ""}
                    key={audit.id}
                    onClick={() => setSelectedBuildAuditId(audit.id)}
                    type="button"
                  >
                    <span>{audit.verdict}</span>
                    <strong>{audit.project.name}</strong>
                    <small>{audit.overall} score / no mocked data: {audit.no_mocked_data ? "yes" : "no"}</small>
                  </button>
                ))}
                {!buildAudits.length && <div className="connector-empty">No saved build audits yet.</div>}
              </div>
            </section>

            <section className="console-panel prompt-history-dock">
              <div className="panel-title-row compact">
                <div>
                  <span>Lab History</span>
                  <h2>{promptEvaluations.length ? `${promptEvaluations.length} evals` : "empty"}</h2>
                </div>
                <FileText size={18} aria-hidden="true" />
              </div>
              <div className="prompt-history-list">
                {promptEvaluations.slice(0, 6).map((evaluation) => (
                  <button
                    className={selectedPromptEvaluation?.id === evaluation.id ? "selected" : ""}
                    key={evaluation.id}
                    onClick={() => setSelectedPromptEvaluationId(evaluation.id)}
                    type="button"
                  >
                    <span>{evaluation.verdict}</span>
                    <strong>{evaluation.prompt_preview}</strong>
                    <small>{evaluation.overall} score / {evaluation.token_forecast.est_total_tokens} tokens</small>
                  </button>
                ))}
                {!promptEvaluations.length && <div className="connector-empty">No saved Prompt Lab evaluations yet.</div>}
              </div>
            </section>

            <section className="console-panel evidence-library-dock">
              <div className="panel-title-row compact">
                <div>
                  <span>Evidence Folder</span>
                  <h2>{evidenceReports.length ? `${evidenceReports.length} reports` : "waiting"}</h2>
                </div>
                <FileText size={18} aria-hidden="true" />
              </div>
              <div className="evidence-file-list">
                {evidenceReports.slice(0, 5).map((report) => (
                  <button
                    className={runtimeRun?.id === report.run_id ? "selected" : ""}
                    key={report.run_id}
                    onClick={() => void loadHistoryRun(report.run_id)}
                    type="button"
                  >
                    <strong>{report.markdown_filename}</strong>
                    <span>{report.markdown_path}</span>
                    <small>{report.markdown_bytes} bytes / {formatDate(report.updated_at)}</small>
                  </button>
                ))}
                {!evidenceReports.length && <div className="connector-empty">Approve a live audit to write .autocore/evidence reports.</div>}
              </div>
            </section>

            <section className="console-panel connector-detail-dock">
              <div className="panel-title-row compact">
                <div>
                  <span>Source Detail</span>
                  <h2>{selectedConnector?.name ?? "No source selected"}</h2>
                </div>
                <SelectedConnectorIcon size={18} aria-hidden="true" />
              </div>
              <p>{selectedConnector?.evidence.detail ?? connectorInventory?.boundary.detail ?? "Waiting for connector inventory from the backend."}</p>
              <div className="connector-detail-grid">
                <div>
                  <span>State</span>
                  <strong>{selectedConnector ? connectorStateLabel[selectedConnector.state] : "waiting"}</strong>
                </div>
                <div>
                  <span>Risk</span>
                  <strong>{selectedConnector?.risk ?? "--"}</strong>
                </div>
                <div>
                  <span>Category</span>
                  <strong>{selectedConnector?.category ?? "--"}</strong>
                </div>
                <div>
                  <span>Mutation</span>
                  <strong>blocked</strong>
                </div>
              </div>
              <div className="connector-actions">
                <button disabled type="button">
                  <PlugZap size={14} aria-hidden="true" />
                  {selectedConnector?.state === "live_connected" ? "Live read active" : "Add local env"}
                </button>
                <button onClick={() => setActiveSurface("policy")} type="button">
                  <ShieldCheck size={14} aria-hidden="true" />
                  Open policy
                </button>
              </div>
              {selectedConnector?.evidence.manifests?.length ? (
                <div className="connector-manifest-list">
                  {selectedConnector.evidence.manifests.slice(0, 6).map((manifest) => (
                    <span key={manifest}>{manifest}</span>
                  ))}
                </div>
              ) : null}
            </section>

            <section className="console-panel onboarding-dock">
              <div className="panel-title-row compact">
                <div>
                  <span>First-run Onboarding</span>
                  <h2>Connector path</h2>
                </div>
                <SearchCheck size={18} aria-hidden="true" />
              </div>
              <div className="onboarding-steps">
                {connectorOnboarding.map((step, index) => {
                  const StepIcon = onboardingIconMap[step.title] ?? CircleDot;
                  return (
                    <div className="onboarding-step" key={step.title}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <StepIcon size={15} aria-hidden="true" />
                      <div>
                        <strong>{step.title}</strong>
                        <p>{step.detail}</p>
                      </div>
                    </div>
                  );
                })}
                {!connectorOnboarding.length && <div className="connector-empty">Onboarding contract unavailable until the backend responds.</div>}
              </div>
            </section>

            <section className="console-panel demo-boundary-dock">
              <div className="panel-title-row compact">
                <div>
                  <span>Demo-to-live Boundary</span>
                  <h2>{connectionBoundaryLabel}</h2>
                </div>
                <LockKeyhole size={18} aria-hidden="true" />
              </div>
              <p>{connectorInventory?.boundary.detail ?? "Connector inventory has not loaded yet."}</p>
              <div className="boundary-list">
                <span>Token values never returned</span>
                <span>Absent env means not connected</span>
                <span>Evidence exports carry redaction notes</span>
              </div>
            </section>

            <section className="console-panel connector-state-dock">
              <div className="panel-title-row compact">
                <div>
                  <span>Connection States</span>
                  <h2>Operational legend</h2>
                </div>
                <Cable size={18} aria-hidden="true" />
              </div>
              <div className="connector-state-grid">
                {connectorStateLegend.map((entry) => {
                  const StateIcon = connectorStateIcon[entry.state];
                  return (
                    <div className={`state-line ${entry.state}`} key={entry.state}>
                      <StateIcon size={15} aria-hidden="true" />
                      <div>
                        <strong>{entry.label}</strong>
                        <span>{entry.detail}</span>
                      </div>
                    </div>
                  );
                })}
                {!connectorStateLegend.length && <div className="connector-empty">State legend unavailable until the backend responds.</div>}
              </div>
            </section>

            <section className={`console-panel approval-dock ${primaryCommand?.state === "pending" ? "needs-approval" : ""}`}>
              <div className="panel-title-row compact">
                <div>
                  <span>Approval</span>
                  <h2>{demoMode ? "Read-only playback" : primaryCommand?.state === "completed" ? "Execution complete" : "Terminal request"}</h2>
                </div>
                <KeyRound size={18} aria-hidden="true" />
              </div>
              <p>
                {demoMode
                  ? "Seeded snapshot evidence is locked. Live approve and hold actions are disabled."
                  : primaryCommand?.state === "completed"
                    ? `Completed ${primaryCommand.command_text} and captured evidence.`
                    : `Allow ${primaryCommand?.command_text ?? "the selected command"} with policy re-check and output capture.`}
              </p>
              <div className="approval-actions">
                <button disabled={demoMode || actionBusy || !primaryCommand || approved} onClick={() => updateTerminalGate("approved")}>
                  <Check size={15} aria-hidden="true" />
                  {actionBusy ? "Running" : primaryCommand?.state === "pending" ? "Approve guarded check" : "Approve"}
                </button>
                <button disabled={demoMode || actionBusy || !primaryCommand || approved} onClick={() => updateTerminalGate("blocked")}>
                  <X size={15} aria-hidden="true" />
                  Hold
                </button>
              </div>
            </section>

            <section className="console-panel policy-inspector">
              <div className="panel-title-row compact">
                <div>
                  <span>Policy Inspector</span>
                  <h2>{sandboxValue(commandSandbox, policyProfile, "profile_id")}</h2>
                </div>
                <div className="panel-title-actions">
                  <ShieldCheck size={18} aria-hidden="true" />
                  <div className="panel-actions icon-only" aria-label="Policy actions">
                    <button
                      onClick={() => void copyText("Policy", JSON.stringify(commandSandbox.checks ? commandSandbox : policyProfile, null, 2))}
                      type="button"
                    >
                      <Copy size={13} aria-hidden="true" />
                      Copy
                    </button>
                  </div>
                </div>
              </div>
              <div className="policy-grid">
                <div>
                  <ShieldCheck size={15} aria-hidden="true" />
                  <span>Control</span>
                  <strong>{sandboxValue(commandSandbox, policyProfile, "control_type").replace("_", " ")}</strong>
                </div>
                <div>
                  <CircleDot size={15} aria-hidden="true" />
                  <span>Containment</span>
                  <strong>{sandboxValue(commandSandbox, policyProfile, "containment")}</strong>
                </div>
                <div>
                  <LockKeyhole size={15} aria-hidden="true" />
                  <span>Filesystem</span>
                  <strong>{sandboxValue(commandSandbox, policyProfile, "filesystem")}</strong>
                </div>
                <div>
                  <RadioTower size={15} aria-hidden="true" />
                  <span>Network</span>
                  <strong>{sandboxValue(commandSandbox, policyProfile, "network")}</strong>
                </div>
                <div>
                  <KeyRound size={15} aria-hidden="true" />
                  <span>Secrets</span>
                  <strong>{sandboxValue(commandSandbox, policyProfile, "secrets")}</strong>
                </div>
                <div>
                  <TerminalSquare size={15} aria-hidden="true" />
                  <span>Capability</span>
                  <strong>{commandSandbox.capability ?? "pending"}</strong>
                </div>
              </div>
              <p className="policy-warning">{commandSandbox.execution_warning ?? policyProfile?.execution_warning ?? "Guarded policy is not real OS containment."}</p>
              <div className="check-ledger">
                {(sandboxChecks.length
                  ? sandboxChecks
                  : [
                      {
                        id: "network",
                        status: policyProfile?.network === "deny" ? "pass" : "waiting",
                        detail: "Network policy loaded from profile.",
                      },
                      {
                        id: "secrets",
                        status: policyProfile?.secrets === "deny" ? "pass" : "waiting",
                        detail: "Secret policy loaded from profile.",
                      },
                      { id: "allowlist", status: "waiting", detail: "Select or start a run to inspect command checks." },
                    ]).map((check) => (
                  <div className={`check-line ${check.status}`} key={check.id}>
                    <strong>{check.id.replace("_", " ")}</strong>
                    <span>{check.status}</span>
                    <p>{check.detail}</p>
                  </div>
                ))}
              </div>
            </section>

            <section className="console-panel score-inspector">
              <div className="panel-title-row compact">
                <div>
                  <span>Scorecard</span>
                  <h2>{scorecard?.grade?.replace("_", " ") ?? "waiting"}</h2>
                </div>
                <BadgeCheck size={18} aria-hidden="true" />
              </div>
              <div className="score-summary">
                <strong>{scorecard?.overall ?? "--"}</strong>
                <span>overall</span>
              </div>
              <div className="score-bars">
                {(scorecard?.dimensions ?? []).map((dimension) => (
                  <div className="score-bar" key={dimension.id}>
                    <span>{scoreDimensionLabel(dimension)}</span>
                    <strong>{dimension.score}</strong>
                    <div>
                      <i style={{ width: `${dimension.score}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="console-panel evidence-inspector">
              <div className="panel-title-row compact">
                <div>
                  <span>Evidence Package</span>
                  <h2>{evidenceBundle ? "attached" : "waiting"}</h2>
                </div>
                <FileText size={18} aria-hidden="true" />
              </div>
              <div className="evidence-ledger">
                {displayedEvidenceItems.map((item) => (
                  <div className={`evidence-line ${item.status}`} key={item.label}>
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </div>
                ))}
              </div>
              <button className="open-report" onClick={openEvidenceReport}>
                <Database size={15} aria-hidden="true" />
                Open report
              </button>
            </section>

            <section className="console-panel task-launch-dock">
              <div className="panel-title-row compact">
                <div>
                  <span>Launch Pack</span>
                  <h2>{selectedTask?.title ?? "Select task pack"}</h2>
                </div>
                <Layers3 size={18} aria-hidden="true" />
              </div>
              <p>{selectedTask?.goal ?? "Choose a pack from the left rail."}</p>
              <div className="task-scope-list">
                {(selectedTask?.tool_scope ?? []).map((scope) => (
                  <span key={scope}>{scope.replace("_", " ")}</span>
                ))}
              </div>
              <button className="launch-pack-button" disabled={demoMode || launchBusy || !selectedPack || !selectedTask} onClick={launchSelectedTaskPack}>
                <Play size={15} aria-hidden="true" />
                {demoMode ? "Read-only" : launchBusy ? "Launching" : "Start Eval"}
              </button>
            </section>

            <section className="console-panel history-inspector">
              <div className="panel-title-row compact">
                <div>
                  <span>History</span>
                  <h2>{historySummary?.trend ?? "waiting"}</h2>
                </div>
                <GitCompareArrows size={18} aria-hidden="true" />
              </div>
              <div className="history-metrics">
                <div>
                  <span>Delta</span>
                  <strong>{historySummary ? formatDelta(historySummary.score_delta) : "--"}</strong>
                </div>
                <div>
                  <span>Average</span>
                  <strong>{historySummary?.average_score ?? "--"}</strong>
                </div>
                <div>
                  <span>Best</span>
                  <strong>{historySummary?.best_score ?? "--"}</strong>
                </div>
              </div>
            </section>
          </aside>
            </div>
          </DashboardRow>
        </section>
      </section>
    </main>
  );
}

export default App;
