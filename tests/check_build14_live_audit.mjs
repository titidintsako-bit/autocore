import { spawn } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const APP_URL = "http://127.0.0.1:5173/?section=overview";
const DEBUG_PORT = 9235;
const EDGE_PATHS = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];
const edgePath = EDGE_PATHS.find((path) => existsSync(path));
if (!edgePath) throw new Error("Microsoft Edge was not found for browser QA.");

const profilePath = resolve("qa", `autocore-build14-edge-profile-${process.pid}-${Date.now()}`);
const edge = spawn(edgePath, [
  "--headless=new",
  "--disable-gpu",
  "--disable-dev-shm-usage",
  `--remote-debugging-port=${DEBUG_PORT}`,
  `--user-data-dir=${profilePath}`,
  "about:blank",
], { stdio: "ignore", windowsHide: true });

const wait = (ms) => new Promise((resolveWait) => setTimeout(resolveWait, ms));

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function waitForDebugger() {
  let lastError;
  for (let attempt = 0; attempt < 70; attempt += 1) {
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
  const socket = new WebSocket(webSocketUrl);
  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (!payload.id || !callbacks.has(payload.id)) return;
    const callback = callbacks.get(payload.id);
    callbacks.delete(payload.id);
    if (payload.error) callback.reject(new Error(payload.error.message));
    else callback.resolve(payload.result);
  });

  return {
    ready: new Promise((resolveReady, rejectReady) => {
      socket.addEventListener("open", resolveReady, { once: true });
      socket.addEventListener("error", rejectReady, { once: true });
    }),
    close() {
      socket.close();
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
  const targets = await fetchJson(`http://127.0.0.1:${DEBUG_PORT}/json/list`);
  const target = targets.find((item) => item.id === targetId);
  const page = createCdpClient(target.webSocketDebuggerUrl);
  await page.ready;
  return { browser, page };
}

async function evaluate(page, expression) {
  const result = await page.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}

async function waitFor(page, expression, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await evaluate(page, expression);
    if (result) return result;
    await wait(250);
  }
  throw new Error(`Timed out waiting for ${expression}`);
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
  await waitFor(page, `Boolean(document.querySelector(".project-target-console"))`);
  await waitFor(page, `Boolean(document.querySelector(".live-proof-console"))`);
  await waitFor(page, `Boolean(document.querySelector(".evidence-library-dock"))`);
  await waitFor(page, `(document.querySelector(".project-path-row input")?.value || "").length > 0`);

  const initial = await evaluate(page, `(() => ({
    selectedTab: document.querySelector(".cockpit-nav button.selected")?.textContent?.trim(),
    hasReleaseDocket: Boolean(document.querySelector(".release-docket")),
    targetPath: document.querySelector(".project-path-row input")?.value || "",
    proofRows: document.querySelectorAll(".live-proof-step").length,
    evidenceDock: document.querySelector(".evidence-library-dock")?.innerText || "",
    quickScanDisabled: document.querySelector(".quick-scan-row button")?.disabled ?? true,
    overflow: document.documentElement.scrollWidth > window.innerWidth + 2,
  }))()`);

  assert(initial.selectedTab === "Dashboard", `Expected Dashboard selected, got ${initial.selectedTab}`);
  assert(!initial.hasReleaseDocket, "Live mode should not show the demo release docket.");
  assert(initial.targetPath.length > 0, "Project target input is empty.");
  assert(initial.proofRows >= 7, `Expected proof rows, got ${initial.proofRows}.`);
  assert(!initial.quickScanDisabled, "Quick scan should be enabled in live mode.");
  assert(!initial.overflow, "Live overview overflows horizontally before audit.");

  await evaluate(page, `document.querySelector(".quick-scan-row button").click()`);
  await waitFor(page, `document.querySelector(".approval-actions button") && !document.querySelector(".approval-actions button").disabled`, 20000);
  await evaluate(page, `document.querySelector(".approval-actions button").click()`);
  await waitFor(page, `document.body.innerText.includes("Evidence written") && !document.body.innerText.includes("Evidence written\\nwaiting")`, 90000);
  await waitFor(page, `document.querySelectorAll(".live-proof-step.complete").length >= 7`, 30000);

  const finalReport = await evaluate(page, `(() => {
    const text = document.body.innerText;
    return {
      statusBadges: [...document.querySelectorAll(".status-badge")].map((node) => node.textContent.trim()),
      completedProofRows: document.querySelectorAll(".live-proof-step.complete").length,
      evidenceText: document.querySelector(".evidence-library-dock")?.innerText || "",
      hasEvidenceReport: /run_[a-z0-9]+\\.md/.test(text),
      hasOutputProof: [...document.querySelectorAll(".live-proof-step.complete")].some((node) => node.innerText.includes("Output captured")),
      overflow: document.documentElement.scrollWidth > window.innerWidth + 2,
    };
  })()`);

  assert(finalReport.completedProofRows >= 7, `Expected 7 completed proof rows, got ${finalReport.completedProofRows}.`);
  assert(finalReport.hasEvidenceReport, "Evidence folder did not show a generated markdown report.");
  assert(finalReport.hasOutputProof, "Proof panel did not mark output captured.");
  assert(!finalReport.overflow, "Live overview overflows horizontally after audit.");

  console.log(JSON.stringify({ initial, finalReport }, null, 2));
} finally {
  page?.close();
  browser?.close();
  edge.kill();
  await wait(800);
  try {
    rmSync(profilePath, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  } catch {
    // Ignore Windows profile cleanup locks.
  }
}
