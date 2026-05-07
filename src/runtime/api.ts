export type RuntimeEvent = {
  id: string;
  run_id: string;
  kind: string;
  title: string;
  detail: string;
  status: "ok" | "attention" | "blocked";
  created_at: string;
};

export type SandboxCheck = {
  id: string;
  status: "pass" | "fail" | string;
  detail: string;
};

export type SandboxDecision = {
  profile_id?: string;
  control_type?: string;
  containment?: string;
  filesystem?: string;
  network?: string;
  secrets?: string;
  shell?: string;
  capability?: string;
  execution_warning?: string;
  checks?: SandboxCheck[];
};

export type RuntimeCommand = {
  id: string;
  run_id: string;
  command: string[];
  command_text: string;
  purpose: string;
  state: "pending" | "completed" | "failed" | "blocked";
  policy_allowed: boolean;
  policy_reason: string;
  sandbox: SandboxDecision;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
};

export type RuntimePlannerProposal = {
  command: string[];
  command_text: string;
  allowed: boolean;
  reason: string;
  risk: "low" | "medium" | "high" | string;
  sandbox?: SandboxDecision;
};

export type RuntimePlanner = {
  provider?: {
    name?: string;
    model?: string;
    mode?: string;
    fallback_reason?: string;
  };
  goal?: string;
  task_pack_id?: string;
  task_id?: string;
  notes?: string;
  risks?: string[];
  proposals?: RuntimePlannerProposal[];
  blocked_proposals?: RuntimePlannerProposal[];
  selected_command?: string[];
  confidence?: number;
  prompt_evaluation?: PromptEvaluationSummary;
};

export type RuntimeRun = {
  id: string;
  path: string;
  goal: string;
  task_pack_id: string;
  task_id: string;
  status: "approval_required" | "evidence_ready" | "failed" | "blocked";
  autonomy_score: number;
  safety_score: number;
  scorecard: {
    overall: number;
    grade: "ready" | "watch" | "not_ready";
    task_pack_id: string;
    task_pack_name: string;
    task_id: string;
    task_title: string;
    dimensions: Array<{
      id: string;
      label: string;
      score: number;
      weight: number;
      evidence: string;
    }>;
    counters: {
      completed_commands: number;
      failed_commands: number;
      pending_commands: number;
      blocked_actions: number;
      interventions: number;
      duration_ms: number;
    };
  };
  inspection: {
    stack: string;
    manifests: string[];
    recommended_commands: string[][];
    risk_surfaces: Record<string, boolean>;
  };
  planner: RuntimePlanner;
  created_at: string;
  updated_at: string;
  events: RuntimeEvent[];
  commands: RuntimeCommand[];
};

export type RuntimeHistoryEntry = {
  id: string;
  goal: string;
  status: RuntimeRun["status"];
  score: number;
  grade: RuntimeRun["scorecard"]["grade"] | "unknown";
  task_pack_id: string;
  task_id: string;
  provider: string;
  selected_command: string;
  duration_ms: number;
  interventions: number;
  blocked_actions: number;
  created_at: string;
  updated_at: string;
};

export type RuntimeHistory = {
  summary: {
    total_runs: number;
    latest_score: number;
    previous_score: number;
    score_delta: number;
    trend: "improving" | "regressing" | "stable";
    average_score: number;
    best_score: number;
    worst_score: number;
  };
  runs: RuntimeHistoryEntry[];
};

export type TaskPackTask = {
  id: string;
  title: string;
  category: string;
  tool_scope: string[];
  evidence_requirements: string[];
  goal: string;
  success_criteria: string[];
  scoring_dimensions: Record<string, number>;
};

export type TaskPack = {
  id: string;
  name: string;
  category: "coding" | "research" | "data" | "browser" | string;
  version: string;
  default_task_id: string;
  risk_level: "low" | "medium" | "high" | string;
  tags: string[];
  description: string;
  tasks: TaskPackTask[];
};

export type PolicyProfile = {
  profile_id: string;
  control_type?: string;
  containment?: string;
  filesystem: string;
  network: string;
  secrets: string;
  shell: string;
  execution_warning?: string;
  allowed_prefixes: string[];
  trusted_project_prefixes?: string[];
  trusted_project_scripts?: boolean;
  blocked_programs: string[];
  secret_markers: string[];
};

export type EvidenceBundle = {
  markdown_path: string;
  json_path: string;
  markdown: string;
  json: RuntimeRun;
  summary: {
    run_id: string;
    status: RuntimeRun["status"];
    score: number;
    grade: RuntimeRun["scorecard"]["grade"] | "unknown";
    commands: number;
    events: number;
    markdown_filename: string;
    json_filename: string;
  };
};

export type DemoSnapshot = {
  mode: "demo";
  read_only: boolean;
  public_safe: boolean;
  case_study: {
    title: string;
    problem: string;
    solution: string;
    proof_points: string[];
    next_steps: string[];
  };
  onboarding: Array<{
    title: string;
    detail: string;
  }>;
  artifacts: Record<string, string>;
  redactions: string[];
  run: RuntimeRun;
  history: RuntimeHistory;
  evidence: EvidenceBundle;
};

export type ConnectorState = "not_connected" | "demo_connected" | "live_connected" | "failed_auth" | "syncing" | "paused";
export type PermissionLabel = "Read-only" | "Metadata-only" | "Evidence export" | "No mutation";

export type ConnectorSource = {
  id: string;
  name: string;
  category: string;
  state: ConnectorState;
  source: "workspace" | "environment" | "missing_env" | string;
  description: string;
  scopes: string[];
  required_env: string[];
  configured_env: string[];
  permissions: PermissionLabel[];
  risk: "low" | "medium" | "high" | string;
  evidence: {
    detail: string;
    stack?: string;
    manifests?: string[];
    scripts?: string[];
    recommended_commands?: string[];
    risk_surfaces?: Record<string, boolean>;
    workspace_name?: string;
    validated?: boolean;
    redacted?: boolean;
  };
};

export type ConnectorInventory = {
  mode: "live";
  mocked: boolean;
  generated_at: string;
  project: {
    name: string;
    stack: string;
  };
  summary: {
    total: number;
    active: number;
    guarded: number;
    attention: number;
    not_connected: number;
  };
  permissions: Array<{
    label: PermissionLabel;
    detail: string;
    status: "allow" | "guarded" | "deny";
  }>;
  state_legend: Array<{
    state: ConnectorState;
    label: string;
    detail: string;
  }>;
  onboarding: Array<{
    title: string;
    detail: string;
  }>;
  boundary: {
    label: string;
    detail: string;
  };
  connectors: ConnectorSource[];
};

export type ProjectProfile = {
  name: string;
  path: string;
  exists: boolean;
  stack: string;
  manifests: string[];
  scripts: string[];
  recommended_commands: string[];
  risk_surfaces: Record<string, boolean>;
  control: string;
};

export type SetupStatus = {
  mode: "live" | "public";
  read_only: boolean;
  headline: string;
  project: {
    name: string;
    path: string;
    exists: boolean;
    stack: string;
    manifests?: string[];
    recommended_command?: string | null;
  };
  modes: Array<{
    id: string;
    label: string;
    available: boolean;
    detail: string;
  }>;
  checks: Array<{
    id: string;
    label: string;
    status: "ready" | "optional" | "attention" | "missing" | "blocked" | string;
    detail: string;
    value?: string | null;
  }>;
  providers: Array<{
    id: string;
    label: string;
    status: "ready" | "optional" | string;
    detail: string;
    configured: boolean;
    configured_env: string[];
  }>;
  readiness: {
    score: number;
    label: string;
  };
  next_steps: Array<{
    id: string;
    label: string;
    detail: string;
  }>;
};

export type CompanionStatus = {
  mode: "live" | "public";
  read_only: boolean;
  project: {
    name: string;
    path: string;
    stack: string;
  };
  verdict: "clean" | "needs_audit" | "audit_current" | "preview_only" | string;
  summary: {
    changed_files: number;
    high_risk_files: number;
    tests_changed: number;
    docs_changed: number;
  };
  changed_files: Array<{
    path: string;
    status: string;
    category: string;
    risk: "low" | "medium" | "high" | string;
    signals: string[];
  }>;
  latest_audit: {
    id: string;
    verdict: string;
    overall: number;
    created_at: string;
  } | null;
  suggested_prompt: string;
  next_steps: Array<{
    id: string;
    label: string;
    detail: string;
  }>;
  created_at: string;
};

export type EvidenceLibraryEntry = {
  run_id: string;
  markdown_filename: string;
  json_filename: string;
  markdown_path: string;
  json_path: string;
  markdown_bytes: number;
  json_bytes: number;
  updated_at: string;
};

export type EvidenceLibrary = {
  reports: EvidenceLibraryEntry[];
};

export type ProviderSignal = {
  provider: string;
  model: string;
  source: string;
  quota_known: boolean;
  usage_known: boolean;
  remaining_tokens: number | null;
  remaining_requests: number | null;
  used_tokens?: number | null;
  freshness: string;
  notes: string;
};

export type PromptEvaluationSummary = {
  id: string;
  verdict: "ready" | "revise" | "blocked" | string;
  overall: number;
  prompt_preview: string;
  token_forecast: PromptEvaluation["token_forecast"];
  provider_signal: ProviderSignal;
  recommendations: string[];
  created_at: string;
};

export type PromptEvaluation = {
  id: string;
  task_pack_id: string;
  task_id: string;
  prompt_preview: string;
  prompt_hash: string;
  verdict: "ready" | "revise" | "blocked" | string;
  overall: number;
  scores: Record<string, number>;
  findings: Array<{
    severity: "info" | "warning" | "blocked" | string;
    message: string;
  }>;
  recommendations: string[];
  token_forecast: {
    est_input_tokens: number;
    est_output_tokens: number;
    est_total_tokens: number;
    context_window: number;
    context_remaining: number;
    confidence: string;
    notes: string;
  };
  provider_signal: ProviderSignal;
  model_critique?: {
    enabled: boolean;
    source: string;
    note: string;
  } | null;
  created_at: string;
};

export type BuildAudit = {
  id: string;
  project: {
    name: string;
    path: string;
    stack: string;
    manifests: string[];
  };
  verdict: "ready" | "watch" | "not_ready" | string;
  overall: number;
  no_mocked_data: boolean;
  mocked_findings: Array<{
    path: string;
    markers: string[];
    evidence: string;
  }>;
  checks: Array<{
    id: string;
    label: string;
    status: "pass" | "warn" | "fail" | string;
    score: number;
    evidence: string;
  }>;
  claims: {
    quality: {
      status: "evidence_backed" | "limited" | string;
      claim: string;
      evidence: string[];
    };
    security: {
      status: "evidence_backed" | "limited" | string;
      claim: string;
      evidence: string[];
    };
  };
  claim_readiness: Array<{
    claim: string;
    status: "supported" | "limited" | "blocked" | string;
    evidence: string;
  }>;
  security_scan: {
    source: string;
    status: "pass" | "warn" | "fail" | string;
    overall: number;
    scope: string;
    checks: Array<{
      id: string;
      label: string;
      status: "pass" | "warn" | "fail" | string;
      score: number;
      evidence: string;
    }>;
  };
  containment: {
    mode: string;
    available: boolean;
    engine: string | null;
    notes: string;
  };
  recommendations: string[];
  source: string;
  created_at: string;
};

export type GuidedAudit = {
  id: string;
  status: RuntimeRun["status"];
  project: {
    name: string;
    path: string;
    stack: string;
  };
  prompt_evaluation: PromptEvaluation;
  build_audit: BuildAudit;
  run: RuntimeRun;
  next_action: {
    id: string;
    label: string;
    detail: string;
  };
  created_at: string;
};

const DEFAULT_API_URL = import.meta.env.DEV ? "http://127.0.0.1:8787" : window.location.origin;
const API_URL = import.meta.env.VITE_AUTOCORE_API_URL ?? DEFAULT_API_URL;
export const RUNTIME_API_URL = API_URL;
export const PUBLIC_SNAPSHOT_MODE = import.meta.env.VITE_AUTOCORE_PUBLIC_SNAPSHOT === "1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(payload.error ?? response.statusText);
  }

  return response.json() as Promise<T>;
}

export type RuntimeHealth = {
  ok: boolean;
  service: string;
  version?: string;
  ui_min_version?: string;
  capabilities?: Record<string, boolean>;
  mode: "live" | "public";
  live_enabled: boolean;
};

export async function fetchRuntimeHealth(): Promise<RuntimeHealth> {
  return request<RuntimeHealth>("/api/health");
}

export async function fetchLatestRun(): Promise<RuntimeRun> {
  const payload = await request<{ run: RuntimeRun }>("/api/runs/latest");
  return payload.run;
}

export async function fetchRun(runId: string): Promise<RuntimeRun> {
  const payload = await request<{ run: RuntimeRun }>(`/api/runs/${runId}`);
  return payload.run;
}

export async function fetchRunHistory(limit = 12): Promise<RuntimeHistory> {
  const payload = await request<{ history: RuntimeHistory }>(`/api/runs?limit=${limit}`);
  return payload.history;
}

export async function fetchTaskPacks(): Promise<TaskPack[]> {
  const payload = await request<{ task_packs: TaskPack[] }>("/api/task-packs").catch(() =>
    fetch("/task-packs.json").then((response) => {
      if (!response.ok) throw new Error("Task packs are unavailable");
      return response.json() as Promise<{ task_packs: TaskPack[] }>;
    }),
  );
  return payload.task_packs;
}

export async function fetchPolicyProfile(): Promise<PolicyProfile> {
  const payload = await request<{ policy: PolicyProfile }>("/api/policy");
  return payload.policy;
}

export async function fetchDemoSnapshot(): Promise<DemoSnapshot> {
  const payload = await request<{ demo: DemoSnapshot }>("/api/demo").catch(() =>
    fetch("/demo-snapshot.json").then((response) => {
      if (!response.ok) throw new Error("Demo snapshot is unavailable");
      return response.json() as Promise<{ demo: DemoSnapshot }>;
    }),
  );
  return payload.demo;
}

export async function fetchConnectorInventory(): Promise<ConnectorInventory> {
  return request<ConnectorInventory>("/api/connectors");
}

export async function fetchProjectProfile(): Promise<ProjectProfile> {
  const payload = await request<{ project: ProjectProfile }>("/api/project");
  return payload.project;
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  const payload = await request<{ setup: SetupStatus }>("/api/setup").catch(() =>
    fetch("/setup-status.json").then((response) => {
      if (!response.ok) throw new Error("Setup status is unavailable");
      return response.json() as Promise<{ setup: SetupStatus }>;
    }),
  );
  return payload.setup;
}

export async function fetchCompanionStatus(): Promise<CompanionStatus> {
  const payload = await request<{ companion: CompanionStatus }>("/api/companion").catch(() =>
    fetch("/companion-status.json").then((response) => {
      if (!response.ok) throw new Error("Codex Companion status is unavailable");
      return response.json() as Promise<{ companion: CompanionStatus }>;
    }),
  );
  return payload.companion;
}

export async function auditCompanionChanges(): Promise<{ audit: BuildAudit; companion: CompanionStatus }> {
  return request<{ audit: BuildAudit; companion: CompanionStatus }>("/api/companion/audit", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function updateProjectProfile(path: string): Promise<ProjectProfile> {
  const payload = await request<{ project: ProjectProfile }>("/api/project", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
  return payload.project;
}

export async function pickProjectFolder(): Promise<{ project: ProjectProfile; picked: boolean }> {
  return request<{ project: ProjectProfile; picked: boolean }>("/api/project/pick", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function fetchEvidenceLibrary(): Promise<EvidenceLibrary> {
  return request<EvidenceLibrary>("/api/evidence");
}

export async function fetchPromptEvaluations(): Promise<PromptEvaluation[]> {
  const payload = await request<{ evaluations: PromptEvaluation[] }>("/api/prompt-lab");
  return payload.evaluations;
}

export async function evaluatePrompt(input: {
  prompt: string;
  task_pack_id?: string;
  task_id?: string;
  provider?: string;
  model?: string;
  critique_enabled?: boolean;
}): Promise<PromptEvaluation> {
  const payload = await request<{ evaluation: PromptEvaluation }>("/api/prompt-lab/evaluate", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.evaluation;
}

export async function fetchBuildAudits(): Promise<BuildAudit[]> {
  const payload = await request<{ audits: BuildAudit[] }>("/api/build-audits");
  return payload.audits;
}

export async function runBuildAudit(input?: { path?: string }): Promise<BuildAudit> {
  const payload = await request<{ audit: BuildAudit }>("/api/build-audits", {
    method: "POST",
    body: JSON.stringify(input ?? {}),
  });
  return payload.audit;
}

export async function runGuidedAudit(input?: {
  path?: string;
  prompt?: string;
  task_pack_id?: string;
  task_id?: string;
  provider?: string;
  model?: string;
  critique_enabled?: boolean;
}): Promise<GuidedAudit> {
  const payload = await request<{ guided_audit: GuidedAudit }>("/api/guided-audit", {
    method: "POST",
    body: JSON.stringify(input ?? {}),
  });
  return payload.guided_audit;
}

export async function createRuntimeRun(input: {
  goal?: string;
  task_pack_id?: string;
  task_id?: string;
  prompt_evaluation_id?: string;
}): Promise<RuntimeRun> {
  const payload = await request<{ run: RuntimeRun }>("/api/runs", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.run;
}

export async function approveRuntimeCommand(runId: string, commandId: string): Promise<RuntimeRun> {
  const payload = await request<{ run: RuntimeRun }>(`/api/runs/${runId}/commands/approve`, {
    method: "POST",
    body: JSON.stringify({ command_id: commandId }),
  });
  return payload.run;
}

export async function holdRuntimeCommand(runId: string, commandId: string): Promise<RuntimeRun> {
  const payload = await request<{ run: RuntimeRun }>(`/api/runs/${runId}/commands/hold`, {
    method: "POST",
    body: JSON.stringify({ command_id: commandId }),
  });
  return payload.run;
}

export async function fetchEvidenceBundle(runId: string): Promise<EvidenceBundle> {
  const payload = await request<{ evidence: EvidenceBundle }>(`/api/runs/${runId}/evidence`);
  return payload.evidence;
}
