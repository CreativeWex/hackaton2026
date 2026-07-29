#!/usr/bin/env python3
"""Build (or reuse) a cached structural index of a Java/Kotlin project.

Part of the `profile-orchestrator` Claude Code skill. The index is built
once per run and read by the router and by every selected detector skill —
so detectors never repeat project discovery or re-read the whole tree.

Usage:
    build_project_index.py --project-root DIR
    build_project_index.py --project-root DIR --force

Output: <project-root>/.profile-run/project-index.json

Cache policy: the index stores the Git SHA it was built from
(`git -C <root> rev-parse HEAD`). If the file already exists and its
`git_sha` equals the current SHA, the scan is skipped and the cached file
is reused, unless --force is given. When the project is not a git repo
(or git is unavailable) the SHA falls back to "nogit" — a "nogit" index is
NEVER treated as a cache hit, because there is no signal to invalidate it.
Note: the SHA does not reflect uncommitted changes; use --force after
editing files without committing.

Python 3.10+, stdlib only. Never crashes on files with broken encodings
(reads with errors="replace"). Cross-platform: Linux/macOS/Git Bash.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

INDEX_VERSION = 1

# Minimum ignore set required by the contract, plus this system's own
# run artifacts and Python cache dirs.
IGNORED_DIRS = {
    ".git", ".gradle", "build", "target", "out", ".idea", "node_modules",
    ".profile-run", ".performance", ".profiler", "__pycache__",
}

SOURCE_EXTS = {".java", ".kt", ".kts"}

BUILD_FILE_NAMES = {
    "pom.xml", "build.gradle", "build.gradle.kts",
    "settings.gradle", "settings.gradle.kts",
}
CONFIG_EXTS = {".properties", ".yml", ".yaml", ".xml", ".sql", ".toml"}

# Framework detection markers, checked against build/config files and
# source file contents. Spring/JPA/Kafka are the contract minimum.
FRAMEWORK_MARKERS: dict[str, tuple[str, ...]] = {
    "Spring": ("org.springframework", "spring-boot", "@SpringBootApplication",
               "spring-context", "spring-webmvc", "spring-web"),
    "JPA": ("javax.persistence", "jakarta.persistence", "spring-data-jpa",
            "@Entity", "hibernate-core", "org.hibernate"),
    "Kafka": ("org.apache.kafka", "spring-kafka", "@KafkaListener",
              "kafka-clients"),
}

REPOSITORY_RE = re.compile(
    r"@Repository\b|extends\s+\w*(?:JpaRepository|CrudRepository|"
    r"PagingAndSortingRepository|ReactiveCrudRepository)|JpaSpecificationExecutor"
)
ENTITY_RE = re.compile(r"@Entity\b|@MappedSuperclass\b|@Embeddable\b")
ENTRYPOINT_RE = re.compile(
    r"@RestController\b|@Controller\b|@KafkaListener\b|@Scheduled\b|"
    r"@SpringBootApplication\b|public\s+static\s+void\s+main\s*\("
)

MAX_CONTENT_BYTES = 5 * 1024 * 1024  # skip content classification above this


def git_sha(root: Path) -> str:
    """Current HEAD SHA, or the safe "nogit" fallback."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "nogit"
    if proc.returncode != 0:
        return "nogit"
    sha = proc.stdout.strip()
    return sha if re.fullmatch(r"[0-9a-f]{7,64}", sha) else "nogit"


def read_text_safe(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_CONTENT_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def scan(root: Path) -> dict:
    source_files: list[str] = []
    build_files: list[str] = []
    config_files: list[str] = []
    repositories: list[str] = []
    entities: list[str] = []
    entrypoints: list[str] = []
    frameworks: set[str] = set()
    modules: set[str] = set()

    def check_frameworks(text: str) -> None:
        for name, markers in FRAMEWORK_MARKERS.items():
            if name not in frameworks and any(m in text for m in markers):
                frameworks.add(name)

    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            children = sorted(cur.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for child in children:
            name = child.name
            if child.is_dir():
                # dot-dirs beyond the contract list are tool/VCS state,
                # never Java sources
                if name in IGNORED_DIRS or name.startswith("."):
                    continue
                stack.append(child)
                continue
            if not child.is_file():
                continue
            rel = child.relative_to(root).as_posix()
            suffix = child.suffix.lower()

            if name in BUILD_FILE_NAMES:
                build_files.append(rel)
                if name in ("pom.xml", "build.gradle", "build.gradle.kts"):
                    modules.add(child.parent.relative_to(root).as_posix() or ".")
                check_frameworks(read_text_safe(child))
                continue

            if suffix in SOURCE_EXTS:
                # *.kts build scripts are already handled above by name
                source_files.append(rel)
                text = read_text_safe(child)
                check_frameworks(text)
                if REPOSITORY_RE.search(text) or name.endswith(
                        ("Repository.java", "Repository.kt")):
                    repositories.append(rel)
                if ENTITY_RE.search(text):
                    entities.append(rel)
                if ENTRYPOINT_RE.search(text):
                    entrypoints.append(rel)
                continue

            if suffix in CONFIG_EXTS:
                config_files.append(rel)
                # config files are cheap confirmation of frameworks
                # (application.yml with spring:, kafka: sections etc.)
                check_frameworks(read_text_safe(child))

    if (root / "pom.xml").is_file():
        build_tool = "maven"
    elif any((root / n).is_file() for n in
             ("build.gradle", "build.gradle.kts",
              "settings.gradle", "settings.gradle.kts")):
        build_tool = "gradle"
    else:
        # nested single-module layouts: any build file anywhere decides
        if any(f.endswith("pom.xml") for f in build_files):
            build_tool = "maven"
        elif build_files:
            build_tool = "gradle"
        else:
            build_tool = "unknown"

    return {
        "build_tool": build_tool,
        "modules": sorted(modules) or ["."],
        "frameworks": sorted(frameworks),
        "source_files": sorted(source_files),
        "repositories": sorted(repositories),
        "entities": sorted(entities),
        "entrypoints": sorted(entrypoints),
        "build_files": sorted(build_files),
        "config_files": sorted(config_files),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", required=True, type=Path)
    ap.add_argument("--force", action="store_true",
                    help="Rebuild even if the cached index matches the current git SHA")
    ap.add_argument("--output", type=Path, default=None,
                    help="Index path (default: <project-root>/.profile-run/project-index.json)")
    args = ap.parse_args()

    root = args.project_root.resolve()
    if not root.is_dir():
        print(f"error: --project-root {root} is not a directory", file=sys.stderr)
        return 2
    out = args.output or (root / ".profile-run" / "project-index.json")

    sha = git_sha(root)

    if out.is_file() and not args.force and sha != "nogit":
        try:
            cached = json.loads(out.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cached = None
        if isinstance(cached, dict) and cached.get("git_sha") == sha:
            print(f"cache hit: index already built for git_sha={sha[:12]}, "
                  f"skipping rescan (use --force to rebuild)", file=sys.stderr)
            print(str(out))
            return 0

    index = {
        "version": INDEX_VERSION,
        "git_sha": sha,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **scan(root),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"index built: {len(index['source_files'])} source files, "
          f"build_tool={index['build_tool']}, frameworks={index['frameworks']}, "
          f"git_sha={sha[:12]}", file=sys.stderr)
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
