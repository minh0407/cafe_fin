import path from "node:path";
import os from "node:os";
import fs from "node:fs/promises";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
const root = path.resolve(__dirname, "../../..");
const frontendRequire = createRequire(path.join(root, "frontend/package.json"));
const { test } = frontendRequire("@playwright/test");

function runHarness(
  script: string,
  directory: string,
): Promise<{ code: number | null; output: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [path.join(__dirname, script)], {
      cwd: root,
      env: { ...process.env, REPORTING_QA_OUTPUT: directory },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe", "ipc"],
    });
    let output = "";
    let timedOut = false;
    let escalation: ReturnType<typeof setTimeout> | undefined;
    child.stdout?.on("data", (data: Buffer) => {
      output += data.toString();
    });
    child.stderr?.on("data", (data: Buffer) => {
      output += data.toString();
    });
    const deadline = setTimeout(() => {
      timedOut = true;
      output += "\nHarness timeout; closing its owned browser/process.\n";
      if (child.connected) child.send({ type: "reporting-ui-cancel" });
      escalation = setTimeout(() => child.kill(), 5000);
    }, 70000);
    child.once("error", (error) => {
      clearTimeout(deadline);
      if (escalation) clearTimeout(escalation);
      reject(error);
    });
    child.once("close", (code) => {
      clearTimeout(deadline);
      if (escalation) clearTimeout(escalation);
      resolve({ code: timedOut ? -1 : code, output });
    });
  });
}

test("reporting UI assertion harnesses", async ({}, testInfo) => {
  const directory = await fs.mkdtemp(
    path.join(os.tmpdir(), "cafe-fin-reporting-ui-"),
  );
  for (const script of ["check.mjs", "check-books.mjs"]) {
    const result = await runHarness(script, directory);
    const log = path.join(directory, `${script}.log`);
    await fs.writeFile(log, result.output, "utf8");
    await testInfo.attach(script, { path: log, contentType: "text/plain" });
    if (result.code !== 0 || !result.output.includes('"status":"PASS"')) {
      throw new Error(
        `${script} failed (exit ${result.code}). Evidence: ${directory}\n${result.output}`,
      );
    }
    console.log(result.output.trim());
  }
  console.log(`Synthetic reporting evidence: ${directory}`);
});
