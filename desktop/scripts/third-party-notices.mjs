import { spawnSync } from "node:child_process";
import { readdir, readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const result = spawnSync("cargo", ["metadata", "--locked", "--format-version=1", "--filter-platform", "x86_64-pc-windows-msvc"], { cwd: desktop, encoding: "utf8", maxBuffer: 32 * 1024 * 1024, windowsHide: true });
if (result.status !== 0) throw new Error("Cargo metadata failed. Load the native build environment and install locked crates first.");
const metadata = JSON.parse(result.stdout);
const nodes = new Map(metadata.resolve.nodes.map(node => [node.id, node]));
const reachable = new Set();
function include(id) { if (reachable.has(id)) return; reachable.add(id); for (const dep of nodes.get(id)?.deps ?? []) include(dep.pkg); }
include(metadata.resolve.root);
const sections = [];
for (const pkg of metadata.packages.filter(pkg => pkg.source && reachable.has(pkg.id)).sort((a, b) => a.name.localeCompare(b.name))) {
  if (!pkg.license) throw new Error(`Missing license metadata: ${pkg.name}@${pkg.version}`);
  const directory = path.dirname(pkg.manifest_path);
  const files = (await readdir(directory)).filter(name => /^(licen[sc]e|copying|notice)([.-]|$)/i.test(name));
  const notices = [];
  async function collect(name, limit = 2) {
    const location = path.join(directory, name);
    try { notices.push(`Source file: ${name}\n${await readFile(location, "utf8")}`); }
    catch { if (limit) { for (const child of await readdir(location)) await collect(path.join(name, child), limit - 1); } }
  }
  for (const file of files) await collect(file);
  sections.push(`${pkg.name}@${pkg.version}\nLicense metadata: ${pkg.license}\nSource: ${pkg.repository ?? `https://crates.io/crates/${pkg.name}/${pkg.version}`}\nExact unmodified source archive: https://crates.io/api/v1/crates/${pkg.name}/${pkg.version}/download\n${notices.join("\n\n")}`);
}
await mkdir(path.join(desktop, "notices"), { recursive: true });
await writeFile(path.join(desktop, "notices/rust.txt"), `Cafe Fin Windows Rust dependency notices\nGenerated from Cargo.lock and cargo metadata filtered for x86_64-pc-windows-msvc. Build dependencies included conservatively.\n\n${sections.join("\n\n" + "=".repeat(80) + "\n\n")}\n`, "utf8");
console.log(`Collected notices for ${sections.length} locked Rust crates.`);
