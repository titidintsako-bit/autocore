import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import net from "node:net";
import { setTimeout as delay } from "node:timers/promises";
import path from "node:path";

const isWindows = process.platform === "win32";

function parseArgs(argv) {
  const options = {
    backendPort: Number(process.env.AUTOCORE_PORT || 8787),
    frontendPort: Number(process.env.AUTOCORE_FRONTEND_PORT || 5173),
    host: "127.0.0.1",
    open: true,
    projectRoot: process.env.AUTOCORE_PROJECT_ROOT || process.cwd(),
    check: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--check") options.check = true;
    if (arg === "--no-open") options.open = false;
    if (arg === "--project") options.projectRoot = path.resolve(argv[index + 1] || options.projectRoot);
    if (arg === "--backend-port") options.backendPort = Number(argv[index + 1] || options.backendPort);
    if (arg === "--frontend-port") options.frontendPort = Number(argv[index + 1] || options.frontendPort);
  }

  return options;
}

function runVersion(command) {
  const result = isWindows ? spawnSync("cmd.exe", ["/d", "/s", "/c", command, "--version"], {
    stdio: "pipe",
    encoding: "utf-8",
  }) : spawnSync(command, ["--version"], {
    stdio: "pipe",
    encoding: "utf-8",
  });
  return {
    ok: result.status === 0,
    value: (result.stdout || result.stderr || "").trim().split(/\r?\n/)[0] || null,
  };
}

function portAvailable(host, port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, host);
  });
}

async function readJson(url, timeoutMs = 900) {
  return new Promise((resolve) => {
    const request = http.get(url, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => {
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString("utf-8")));
        } catch {
          resolve(null);
        }
      });
    });
    request.on("error", () => resolve(null));
    request.setTimeout(timeoutMs, () => {
      request.destroy();
      resolve(null);
    });
  });
}

async function findOpenPort(host, startPort) {
  for (let port = startPort + 1; port < startPort + 100; port += 1) {
    if (await portAvailable(host, port)) return port;
  }
  throw new Error(`Could not find an open port near ${startPort}.`);
}

async function resolvePort(host, requestedPort, role) {
  if (await portAvailable(host, requestedPort)) {
    return {
      requested_port: requestedPort,
      port: requestedPort,
      port_status: "available",
      port_message: `${role} port ${requestedPort} is available.`,
      warning: null,
    };
  }

  const replacement = await findOpenPort(host, requestedPort);
  const probe = role === "backend" ? await readJson(`http://${host}:${requestedPort}/api/health`) : null;
  let portStatus = "busy";
  let portMessage = `${role} port ${requestedPort} is busy; using ${replacement}.`;
  if (probe?.service === "autocore-runtime" && probe?.capabilities?.guided_audit) {
    portStatus = "autocore_active";
    portMessage = `AutoCore is already running on ${requestedPort}; using ${replacement} for this new session.`;
  } else if (probe?.service === "autocore-runtime") {
    portStatus = "stale_autocore";
    portMessage = `An older AutoCore backend is running on ${requestedPort}; restart it or use ${replacement}.`;
  }

  return {
    requested_port: requestedPort,
    port: replacement,
    port_status: portStatus,
    port_message: portMessage,
    warning: portMessage,
  };
}

async function launcherPlan(options) {
  const backendPort = await resolvePort(options.host, options.backendPort, "backend");
  const frontendPort = await resolvePort(options.host, options.frontendPort, "frontend");
  const frontendUrl = `http://${options.host}:${frontendPort.port}/?section=setup`;
  const backendUrl = `http://${options.host}:${backendPort.port}`;
  const prereqMap = [
    ["python", "Python"],
    ["node", "Node.js"],
    ["npm", "npm"],
  ];

  return {
    command: "npm run start:local",
    mode: "live",
    project_root: options.projectRoot,
    opens_browser: options.open,
    warnings: [backendPort.warning, frontendPort.warning].filter(Boolean),
    backend: {
      requested_port: backendPort.requested_port,
      url: backendUrl,
      command: `python -m autocore.server`,
      port: backendPort.port,
      port_status: backendPort.port_status,
      port_message: backendPort.port_message,
    },
    frontend: {
      requested_port: frontendPort.requested_port,
      url: frontendUrl,
      command: `npx vite --host ${options.host} --port ${frontendPort.port}`,
      port: frontendPort.port,
      port_status: frontendPort.port_status,
      port_message: frontendPort.port_message,
    },
    environment: {
      AUTOCORE_MODE: "live",
      AUTOCORE_HOST: options.host,
      AUTOCORE_PORT: String(backendPort.port),
      AUTOCORE_PROJECT_ROOT: options.projectRoot,
      AUTOCORE_ALLOWED_ORIGINS: `http://${options.host}:${frontendPort.port},http://localhost:${frontendPort.port}`,
      VITE_AUTOCORE_API_URL: `http://${options.host}:${backendPort.port}`,
    },
    prerequisites: prereqMap.map(([id, label]) => {
      const version = runVersion(id);
      return {
        id,
        label,
        status: version.ok ? "ready" : "missing",
        value: version.value,
      };
    }),
  };
}

function spawnFrontend(options) {
  if (isWindows) {
    return spawn("cmd.exe", ["/d", "/s", "/c", `npx vite --host ${options.host} --port ${options.frontendPort}`], {
      cwd: process.cwd(),
      env: {
        ...process.env,
        VITE_AUTOCORE_API_URL: `http://${options.host}:${options.backendPort}`,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
  }
  return spawn("npx", ["vite", "--host", options.host, "--port", String(options.frontendPort)], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      VITE_AUTOCORE_API_URL: `http://${options.host}:${options.backendPort}`,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function waitForUrl(url, timeoutMs = 30000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get(url, (response) => {
        response.resume();
        if ((response.statusCode || 0) < 500) {
          resolve();
          return;
        }
        retry();
      });
      request.on("error", retry);
      request.setTimeout(1800, () => {
        request.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(attempt, 500);
    };
    attempt();
  });
}

function openBrowser(url) {
  const command = isWindows ? "cmd.exe" : process.platform === "darwin" ? "open" : "xdg-open";
  const args = isWindows ? ["/c", "start", "", url] : [url];
  const opener = spawn(command, args, { detached: true, stdio: "ignore" });
  opener.unref();
}

function attachOutput(child, label) {
  child.stdout?.on("data", (chunk) => {
    for (const line of chunk.toString().split(/\r?\n/).filter(Boolean)) {
      console.log(`[${label}] ${line}`);
    }
  });
  child.stderr?.on("data", (chunk) => {
    for (const line of chunk.toString().split(/\r?\n/).filter(Boolean)) {
      console.error(`[${label}] ${line}`);
    }
  });
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const plan = await launcherPlan(options);
  options.backendPort = plan.backend.port;
  options.frontendPort = plan.frontend.port;

  if (options.check) {
    process.stdout.write(`${JSON.stringify(plan, null, 2)}\n`);
    return;
  }

  const missing = plan.prerequisites.filter((item) => item.status !== "ready");
  if (missing.length) {
    console.error("AutoCore cannot start yet. Missing:");
    for (const item of missing) console.error(`- ${item.label}`);
    process.exit(1);
  }

  const backend = spawn("python", ["-m", "autocore.server"], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      ...plan.environment,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const frontend = spawnFrontend(options);
  attachOutput(backend, "api");
  attachOutput(frontend, "web");
  const children = [backend, frontend];

  const shutdown = () => {
    for (const child of children) {
      if (!child.killed) child.kill();
    }
  };
  process.on("SIGINT", () => {
    shutdown();
    process.exit(0);
  });
  process.on("SIGTERM", shutdown);

  backend.on("exit", (code) => {
    if (code && code !== 0) {
      console.error(`AutoCore backend exited with code ${code}.`);
      shutdown();
      process.exit(code);
    }
  });
  frontend.on("exit", (code) => {
    if (code && code !== 0) {
      console.error(`AutoCore frontend exited with code ${code}.`);
      shutdown();
      process.exit(code);
    }
  });

  await Promise.all([
    waitForUrl(`${plan.backend.url}/api/health`),
    waitForUrl(`http://${options.host}:${options.frontendPort}`),
  ]);
  console.log("");
  for (const warning of plan.warnings) console.log(`Port notice: ${warning}`);
  console.log("AutoCore is ready.");
  console.log(`Open ${plan.frontend.url}`);
  console.log("Keep this terminal open while using AutoCore. Press Ctrl+C to stop.");
  if (options.open) openBrowser(plan.frontend.url);

  while (true) {
    await delay(3600000);
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
