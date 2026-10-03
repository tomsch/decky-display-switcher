"""Build the Decky plugin ZIP and its complete corresponding source archive."""

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
metadata = json.loads((root / "package.json").read_text())
runtime_files = [
    "package.json", "plugin.json", "main.py", "display_core.py", "session.py",
    "bin/gamescope", "README.md", "LICENSE", "CHANGELOG.md", "docs/references.md",
    "docs/third-party-notices.md", "dist/index.js",
]
source_files = [
    "package.json", "plugin.json", "main.py", "display_core.py", "session.py",
    "README.md", "LICENSE", "CHANGELOG.md", "pnpm-lock.yaml", "tsconfig.json",
    "rollup.config.js", ".gitignore",
]


def files_under(directory):
    for path in sorted((root / directory).rglob("*")):
        relative = path.relative_to(root)
        if any(part in {"__pycache__", "node_modules", "dist", ".git"} for part in relative.parts):
            continue
        if path.is_file() and path.suffix not in {".pyc", ".tsbuildinfo"}:
            yield relative.as_posix()


runtime_files.extend(files_under("licenses"))
for directory in ("src", "bin", "scripts", "tests", "docs", "licenses", "third_party"):
    source_files.extend(files_under(directory))
files = sorted(set(runtime_files + source_files))
for name in files:
    if not (root / name).is_file():
        raise SystemExit(f"Missing {name}; restore the sources or run pnpm build.")

required_sources = [
    "third_party/decky-api/src/index.ts", "third_party/decky-api/src/types.ts",
    "third_party/decky-api/src/types.d.ts", "third_party/decky-api/LICENSE",
    "third_party/decky-api/tsconfig.json", "third_party/decky-api-source.json",
    "licenses/LGPL-2.1.txt", "licenses/react-icons.txt",
    "licenses/font-awesome.txt", "licenses/decky-template.txt",
]
for name in required_sources:
    if name not in files:
        raise SystemExit(f"Missing corresponding source or license: {name}")

release = root / "release"
release.mkdir(exist_ok=True)
stem = f"display-switcher-{metadata['version']}"
source_output = release / f"{stem}-source.zip"
with ZipFile(source_output, "w", compression=ZIP_DEFLATED) as archive:
    for name in sorted(set(source_files)):
        archive.write(root / name, f"{stem}-source/{name}")

output = release / f"{stem}.zip"
with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
    for name in sorted(set(runtime_files)):
        archive.write(root / name, f"display-switcher/{name}")
    archive.write(source_output, "display-switcher/sources.zip")

print(output)
print(source_output)
