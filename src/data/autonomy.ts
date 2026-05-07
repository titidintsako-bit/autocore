import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BadgeCheck,
  Ban,
  BrainCircuit,
  CheckCircle2,
  CircleDot,
  Clock3,
  Code2,
  FileText,
  FolderSearch,
  GitBranch,
  KeyRound,
  LockKeyhole,
  Network,
  PlayCircle,
  ShieldCheck,
  TerminalSquare,
  TriangleAlert,
} from "lucide-react";

export type Metric = {
  label: string;
  value: string;
  detail: string;
  tone: "teal" | "blue" | "amber" | "red";
  icon: LucideIcon;
};

export type TimelineStep = {
  id: string;
  label: string;
  detail: string;
  status: "complete" | "active" | "waiting" | "locked";
  time: string;
};

export type GateState = "approved" | "pending" | "blocked" | "locked";

export type PermissionGate = {
  id: string;
  title: string;
  scope: string;
  state: GateState;
  risk: "low" | "medium" | "high";
  icon: LucideIcon;
};

export type TraceEvent = {
  id: string;
  time: string;
  title: string;
  detail: string;
  status: "ok" | "attention" | "blocked";
  icon: LucideIcon;
};

export type EvidenceItem = {
  label: string;
  value: string;
  status: "ready" | "pending" | "blocked";
};

export const metrics: Metric[] = [
  {
    label: "Autonomy Score",
    value: "74",
    detail: "goal progress with 2 human interventions",
    tone: "teal",
    icon: BrainCircuit,
  },
  {
    label: "Safety Rating",
    value: "93%",
    detail: "unsafe tool attempts blocked",
    tone: "blue",
    icon: ShieldCheck,
  },
  {
    label: "Time Horizon",
    value: "18m",
    detail: "stable work before approval pause",
    tone: "amber",
    icon: Clock3,
  },
  {
    label: "Risk Delta",
    value: "-31%",
    detail: "lower exposure after gate review",
    tone: "red",
    icon: TriangleAlert,
  },
];

export const timeline: TimelineStep[] = [
  {
    id: "intake",
    label: "Goal Intake",
    detail: "Classified user request as repo readiness audit.",
    status: "complete",
    time: "00:12",
  },
  {
    id: "inspect",
    label: "Workspace Inspect",
    detail: "Mapped manifests, scripts, tests, and risk surfaces.",
    status: "complete",
    time: "02:40",
  },
  {
    id: "plan",
    label: "Plan Draft",
    detail: "Built a five-step verification plan from local evidence.",
    status: "complete",
    time: "07:18",
  },
  {
    id: "approval",
    label: "Approval Gate",
    detail: "Waiting for terminal execution approval.",
    status: "active",
    time: "09:03",
  },
  {
    id: "execute",
    label: "Safe Checks",
    detail: "Run allowlisted checks with captured output.",
    status: "waiting",
    time: "--",
  },
  {
    id: "evidence",
    label: "Evidence Report",
    detail: "Package score, traces, and reproducible replay.",
    status: "locked",
    time: "--",
  },
];

export const initialGates: PermissionGate[] = [
  {
    id: "filesystem",
    title: "Filesystem Read",
    scope: "Repo files, manifests, configs",
    state: "approved",
    risk: "low",
    icon: FolderSearch,
  },
  {
    id: "terminal",
    title: "Terminal Execute",
    scope: "npm test, npm build, python -m pytest",
    state: "pending",
    risk: "medium",
    icon: TerminalSquare,
  },
  {
    id: "network",
    title: "Network Access",
    scope: "Package registries and external URLs",
    state: "blocked",
    risk: "high",
    icon: Network,
  },
  {
    id: "secrets",
    title: "Secret Access",
    scope: ".env, tokens, credential stores",
    state: "locked",
    risk: "high",
    icon: LockKeyhole,
  },
];

export const baseTrace: TraceEvent[] = [
  {
    id: "t1",
    time: "00:12",
    title: "Run created",
    detail: "Objective bound to local workspace with read-only default policy.",
    status: "ok",
    icon: PlayCircle,
  },
  {
    id: "t2",
    time: "02:40",
    title: "Manifest map complete",
    detail: "Detected Vite app, TypeScript config, and build scripts.",
    status: "ok",
    icon: Code2,
  },
  {
    id: "t3",
    time: "07:18",
    title: "Execution plan generated",
    detail: "Recommended typecheck and production build before report.",
    status: "ok",
    icon: GitBranch,
  },
  {
    id: "t4",
    time: "08:51",
    title: "Network request rejected",
    detail: "Blocked dependency lookup because network policy is disabled.",
    status: "blocked",
    icon: Ban,
  },
  {
    id: "t5",
    time: "09:03",
    title: "Approval required",
    detail: "Terminal execution is paused until the operator approves safe checks.",
    status: "attention",
    icon: KeyRound,
  },
];

export const evidenceItems: EvidenceItem[] = [
  {
    label: "Inspection Summary",
    value: "Ready",
    status: "ready",
  },
  {
    label: "Tool Trace Replay",
    value: "9 events",
    status: "ready",
  },
  {
    label: "Command Evidence",
    value: "Waiting",
    status: "pending",
  },
  {
    label: "Safety Exceptions",
    value: "2 blocked",
    status: "blocked",
  },
];

export const navItems = [
  { label: "Live Run", icon: Activity, active: true },
  { label: "Task Packs", icon: CircleDot, active: false },
  { label: "Replay", icon: PlayCircle, active: false },
  { label: "Evidence", icon: FileText, active: false },
  { label: "Policies", icon: ShieldCheck, active: false },
  { label: "Scorecards", icon: BadgeCheck, active: false },
];

export const statusIcon = {
  complete: CheckCircle2,
  active: Activity,
  waiting: Clock3,
  locked: LockKeyhole,
};
