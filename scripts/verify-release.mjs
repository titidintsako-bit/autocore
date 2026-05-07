import { spawnSync } from "node:child_process";

const isWindows = process.platform === "win32";

const steps = [
  ["Backend tests", "python", ["-m", "unittest", "tests.test_backend", "-v"]],
  ["Frontend build", "npm", ["run", "build"]],
  ["Public static build", "npm", ["run", "build:public"]],
  ["Secret scan", "python", ["scripts/secret-scan.py"]],
  ["Public safety scan", "python", ["scripts/public-safety-scan.py"]],
  ["Guided audit and public read-only smoke", "python", ["scripts/release-smoke.py"]],
];

function run(program, args) {
  if (isWindows && program === "npm") {
    return spawnSync("cmd.exe", ["/d", "/s", "/c", "npm", ...args], { stdio: "inherit" });
  }
  return spawnSync(program, args, { stdio: "inherit" });
}

for (const [label, program, args] of steps) {
  console.log(`\n==> ${label}`);
  const result = run(program, args);
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  if (result.status !== 0) {
    console.error(`Release verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log("\nRelease verification passed.");
