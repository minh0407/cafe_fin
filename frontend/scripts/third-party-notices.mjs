import { readdir, readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const entries = new Map();
async function visit(directory) {
  let folders;
  try { folders = await readdir(directory, { withFileTypes: true }); } catch { return; }
  for (const folder of folders) {
    if (!folder.isDirectory() || folder.name.startsWith('.')) continue;
    const location = path.join(directory, folder.name);
    if (folder.name.startsWith('@')) { await visit(location); continue; }
    let pkg;
    try { pkg = JSON.parse(await readFile(path.join(location, 'package.json'), 'utf8')); } catch { continue; }
    const identity = `${pkg.name}@${pkg.version}`;
    if (!entries.has(identity)) {
      const files = (await readdir(location)).filter(name => /^(licen[sc]e|copying|notice)([.-]|$)/i.test(name));
      const texts = [];
      for (const file of files) {
        try { texts.push(`Source file: ${file}\n${await readFile(path.join(location, file), 'utf8')}`); } catch { /* directory or unavailable optional file */ }
      }
      entries.set(identity, `${identity}\nLicense metadata: ${JSON.stringify(pkg.license ?? pkg.licenses ?? 'UNKNOWN')}\nSource: ${typeof pkg.repository === 'string' ? pkg.repository : pkg.repository?.url ?? pkg.homepage ?? ''}\n${texts.join('\n\n')}`);
    }
    await visit(path.join(location, 'node_modules'));
  }
}
await visit(path.join(project, 'node_modules'));
const destination = path.resolve(project, '../desktop/notices');
await mkdir(destination, { recursive: true });
await writeFile(path.join(destination, 'frontend.txt'), `Cafe Fin frontend/build third-party notices\nGenerated from locked installed packages. Development tool notices included conservatively.\n\n${[...entries].sort(([a], [b]) => a.localeCompare(b)).map(([, text]) => text).join('\n\n' + '='.repeat(80) + '\n\n')}\n`, 'utf8');
console.log(`Collected notices for ${entries.size} locked installed packages.`);
