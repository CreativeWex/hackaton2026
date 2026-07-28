#!/usr/bin/env bash
# PreToolUse guard for the /profile orchestrator (profile + apply-recommendations
# skills). Hard technical backstop to the prompt-level "never edit these paths"
# instructions in profile/SKILL.md and apply-recommendations/SKILL.md — those are
# soft constraints that depend on the model following instructions correctly;
# this hook blocks the write regardless.
#
# Active ONLY while .profile-run/ACTIVE exists in the current working directory
# (created by /profile Phase 2, removed by Phase 4 when the run finishes) — a
# no-op otherwise, so normal Claude Code usage on any project is never affected,
# including projects that keep .profile-run/checkpoints/ around after a
# completed run.
#
# No jq dependency on purpose (not installed on every machine this runs on) —
# plain grep/sed extraction of tool_input.file_path is sufficient for the flat,
# single-line JSON Claude Code hooks receive on stdin.
set -uo pipefail

MARKER=".profile-run/ACTIVE"
if [ ! -f "$MARKER" ]; then
  exit 0
fi

INPUT=$(cat)

FILE_PATH=$(printf '%s' "$INPUT" \
  | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' \
  | head -1 \
  | sed -E 's/.*:[[:space:]]*"(.*)"$/\1/')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Normalize Windows-style backslashes BEFORE any prefix matching — on Windows
# Claude Code sends file_path as C:\Users\...\project\src\... while pwd -P in
# Git Bash reports /c/Users/...; without normalization the project-root prefix
# never matches and the guard silently becomes a no-op. In the raw JSON each
# backslash arrives escaped as \\, so collapse whole runs of backslashes into
# a single forward slash (a naive per-char replace would yield C://Users//...).
FILE_PATH=$(printf '%s' "$FILE_PATH" | sed -E 's/\\+/\//g')

PWD_ABS=$(pwd -P)
WIN_ROOT=""
if command -v cygpath >/dev/null 2>&1; then
  WIN_ROOT=$(cygpath -m "$PWD_ABS" 2>/dev/null || true)   # e.g. C:/Users/...
fi

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# Strip the project root, trying both the POSIX (/c/Users/... or /home/...)
# and native Windows (C:/Users/...) spellings. Case-insensitive comparison is
# used only when a Windows spelling exists (cygpath present): NTFS paths and
# drive letters vary in case, but UNIX filesystems are case-sensitive and
# must be compared exactly.
REL="$FILE_PATH"
FP_L=$(lower "$FILE_PATH")
for ROOT in "$PWD_ABS" "$WIN_ROOT"; do
  [ -n "$ROOT" ] || continue
  if [ -n "$WIN_ROOT" ]; then
    R_L=$(lower "$ROOT")
    case "$FP_L" in
      "$R_L"/*) REL="${FILE_PATH:$((${#ROOT} + 1))}"; break ;;
    esac
  else
    case "$FILE_PATH" in
      "$ROOT"/*) REL="${FILE_PATH#"$ROOT"/}"; break ;;
    esac
  fi
done

is_forbidden() {
  case "$1" in
    src/test/*|harness/*|scripts/*|judge/*|perf/*|.performance/*|profiler/*|.profiler/*)
      return 0 ;;
    *_report.md|performance_discovery.md)
      return 0 ;;
    *)
      return 1 ;;
  esac
}

if is_forbidden "$REL"; then
  REASON="profile orchestrator guard: '$REL' is a forbidden path during an active /profile run (analysis artifacts, measurement/profiler scripts, or judge-restored paths must not be edited by the fixer). See profile/apply-recommendations SKILL.md."
  REASON_ESCAPED=$(printf '%s' "$REASON" | sed 's/\\/\\\\/g; s/"/\\"/g')
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$REASON_ESCAPED"
  exit 0
fi

exit 0
