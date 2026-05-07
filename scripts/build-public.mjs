import { spawnSync } from "node:child_process";

const command = process.platform === "win32" ? "cmd.exe" : "npm";
const args = process.platform === "win32" ? ["/d", "/s", "/c", "npm run build"] : ["run", "build"];
const result = spawnSync(command, args, {
  env: {
    ...process.env,
    VITE_AUTOCORE_PUBLIC_SNAPSHOT: "1",
  },
  stdio: "inherit",
});

if (result.error) {
  console.error(result.error.message);
}

process.exit(result.status ?? 1);
