import { spawn } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";

const APP_URL = "http://127.0.0.1:5173/?demo=1&section=connect";
const DEBUG_PORT = 9232;
const EDGE_PATHS = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];

const edgePath = EDGE_PATHS.find((path) => existsSync(path));
if (!edgePath) {
  throw new Error("Microsoft Edge was not found for browser QA.");
}

const profilePath = resolve("qa", `autocore-build12-edge-profile-${process.pid}-${Date.now()}`);
function cleanupProfile() {
  try {
    rmSync(profilePath, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  } catch {
    // Edge can hold Windows profile locks for a moment after shutdown. A stale QA
    // profile is not a product failure, and unique profile names avoid reuse.
  }
}

const edge = spawn(edgePath, [
  "--headless=new",
  "--disable-gpu",
  "--disable-dev-shm-usage",
  `--remote-debugging-port=${DEBUG_PORT}`,
  `--user-data-dir=${profilePath}`,
  "about:blank",
], {
  stdio: "ignore",
  windowsHide: true,
});

function wait(ms) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function waitForDebugger() {
  const deadline = Date.now() + 10000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      return await fetchJson(`http://127.0.0.1:${DEBUG_PORT}/json/version`);
    } catch (error) {
      lastError = error;
      await wait(150);
    }
  }
  throw lastError ?? new Error("Timed out waiting for Edge debugger.");
}

function createCdpClient(webSocketUrl) {
  let nextId = 1;
  const callbacks = new Map();
  const listeners = new Map();
  const socket = new WebSocket(webSocketUrl);

  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.id && callbacks.has(payload.id)) {
      const { resolve: resolveCallback, reject } = callbacks.get(payload.id);
      callbacks.delete(payload.id);
      if (payload.error) reject(new Error(payload.error.message));
      else resolveCallback(payload.result);
      return;
    }

    const eventListeners = listeners.get(payload.method) ?? [];
    for (const listener of eventListeners) listener(payload.params);
  });

  return {
    ready: new Promise((resolveReady, rejectReady) => {
      socket.addEventListener("open", resolveReady, { once: true });
      socket.addEventListener("error", rejectReady, { once: true });
    }),
    close() {
      socket.close();
    },
    on(method, listener) {
      listeners.set(method, [...(listeners.get(method) ?? []), listener]);
    },
    send(method, params = {}) {
      const id = nextId++;
      socket.send(JSON.stringify({ id, method, params }));
      return new Promise((resolveSend, rejectSend) => {
        callbacks.set(id, { resolve: resolveSend, reject: rejectSend });
      });
    },
  };
}

async function createPage() {
  const browserMeta = await waitForDebugger();
  const browser = createCdpClient(browserMeta.webSocketDebuggerUrl);
  await browser.ready;
  const { targetId } = await browser.send("Target.createTarget", { url: "about:blank" });
  const { targetInfos } = await browser.send("Target.getTargets");
  const target = targetInfos.find((info) => info.targetId === targetId);
  if (!target?.url) {
    throw new Error("Unable to create Edge CDP target.");
  }

  const targets = await fetchJson(`http://127.0.0.1:${DEBUG_PORT}/json/list`);
  const pageMeta = targets.find((item) => item.id === targetId);
  const page = createCdpClient(pageMeta.webSocketDebuggerUrl);
  await page.ready;
  return { browser, page };
}

async function evaluate(page, expression) {
  const result = await page.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text);
  }
  return result.result.value;
}

async function waitForApp(page) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const ready = await evaluate(page, `Boolean(document.querySelector(".console-shell"))`);
    if (ready) return;
    await wait(200);
  }
  throw new Error("AutoCore UI did not render.");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

let browser;
let page;
try {
  ({ browser, page } = await createPage());
  await page.send("Page.enable");
  await page.send("Runtime.enable");
  await page.send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 980,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await page.send("Page.navigate", { url: APP_URL });
  await waitForApp(page);
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const hasConnectors = await evaluate(page, `document.querySelectorAll("[data-connector]").length >= 6`);
    if (hasConnectors) break;
    await wait(250);
  }
  await wait(1000);

  const report = await evaluate(page, `(() => {
    const text = document.body.innerText;
    const selectedTab = document.querySelector(".cockpit-nav button.selected")?.textContent?.trim();
    const connectorCards = [...document.querySelectorAll("[data-connector]")].map((node) => node.getAttribute("data-connector"));
    return {
      selectedTab,
      hasConnectTab: [...document.querySelectorAll(".cockpit-nav button")].some((button) => button.textContent.trim() === "Connect"),
      connectorCards,
      localRepoState: document.querySelector("[data-connector='local-repo'] .connector-state")?.textContent?.trim(),
      githubState: document.querySelector("[data-connector='github'] .connector-state")?.textContent?.trim(),
      hasBackendBoundary: text.includes("Live local connector inventory"),
      hasNoMockedCopy: !text.includes("Seeded demo data is mounted"),
      permissionLabels: ["Read-only", "Metadata-only", "Evidence export", "No mutation"].filter((label) => text.includes(label)),
      connectionStates: ["Not connected", "Demo connected", "Live connected", "Failed auth", "Syncing", "Paused"].filter((label) => text.includes(label)),
      onboardingSteps: ["Choose source", "Verify permissions", "Run audit", "Review evidence"].filter((label) => text.includes(label)),
      hasNoHorizontalOverflow: document.documentElement.scrollWidth <= window.innerWidth + 2,
    };
  })()`);

  assert(report.hasConnectTab, "Connect tab is missing.");
  assert(report.selectedTab === "Connect", `Expected Connect tab selected, got ${report.selectedTab ?? "none"}.`);
  assert(report.connectorCards.length >= 6, `Expected at least 6 connector cards, got ${report.connectorCards.length}.`);
  assert(report.localRepoState === "Live connected", `Expected Local Repo live, got ${report.localRepoState ?? "none"}.`);
  assert(report.githubState === "Not connected", `Expected GitHub to be not connected without a token, got ${report.githubState ?? "none"}.`);
  assert(report.hasBackendBoundary, "Live backend connector boundary copy is missing.");
  assert(report.hasNoMockedCopy, "Connect surface still contains seeded demo connector copy.");
  assert(report.permissionLabels.length === 4, `Missing permission labels: ${JSON.stringify(report.permissionLabels)}.`);
  assert(report.connectionStates.length >= 6, `Missing connection states: ${JSON.stringify(report.connectionStates)}.`);
  assert(report.onboardingSteps.length === 4, `Missing onboarding steps: ${JSON.stringify(report.onboardingSteps)}.`);
  assert(report.hasNoHorizontalOverflow, "Connect surface overflows horizontally on desktop.");

  console.log(JSON.stringify(report, null, 2));
} finally {
  page?.close();
  browser?.close();
  edge.kill();
  await wait(800);
  cleanupProfile();
}
