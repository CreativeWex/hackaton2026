#!/usr/bin/env bash
# Profile Static Orchestrator — запуск линтеров (параллельно) + единый отчёт.
# Usage: orchestrate.sh [project-root] [min-severity|all] [all|checkstyle-only|pmd-only|spotbugs-only]
set -u

PROJECT_ROOT="${1:-.}"
SEVERITY_FILTER="${2:-all}"   # all | INFO | LOW | MEDIUM | HIGH | CRITICAL (минимальный уровень)
RUN_MODE="${3:-all}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$(command -v python3 || command -v python || echo py)}"
export PYTHON

echo "Profile Static Analysis: $PROJECT_ROOT"
echo "Severity filter: $SEVERITY_FILTER | Mode: $RUN_MODE"
echo ""

mkdir -p "$PROJECT_ROOT/.profile-run"

# SpotBugs нужен скомпилированный код — компилируем ДО параллельного запуска,
# чтобы сборка не гонялась с чтением src другими линтерами.
prepare_spotbugs() {
    if [ -d "$PROJECT_ROOT/target/classes" ] || [ -d "$PROJECT_ROOT/build/classes/java/main" ]; then
        return 0
    fi
    echo "Compiling project for SpotBugs..."
    if [ -f "$PROJECT_ROOT/pom.xml" ]; then
        (cd "$PROJECT_ROOT" && mvn -q compile) || echo "WARNING: mvn compile failed — SpotBugs will be skipped" >&2
    elif [ -f "$PROJECT_ROOT/build.gradle" ] || [ -f "$PROJECT_ROOT/build.gradle.kts" ]; then
        (cd "$PROJECT_ROOT" && ./gradlew -q classes) || echo "WARNING: gradle classes failed — SpotBugs will be skipped" >&2
    else
        echo "WARNING: no pom.xml/build.gradle — cannot compile for SpotBugs" >&2
    fi
}

run_linters() {
    local pids=() names=() failed=0

    if [ "$RUN_MODE" = "all" ] || [ "$RUN_MODE" = "checkstyle-only" ]; then
        echo "> Starting CheckStyle..."
        bash "$SCRIPT_DIR/run-checkstyle.sh" "$PROJECT_ROOT" \
            "$SCRIPT_DIR/../linters/rulesets/checkstyle-smells.xml" \
            "$PROJECT_ROOT/.profile-run/checkstyle-findings.json" &
        pids+=($!); names+=("CheckStyle")
    fi

    if [ "$RUN_MODE" = "all" ] || [ "$RUN_MODE" = "pmd-only" ]; then
        echo "> Starting PMD..."
        bash "$SCRIPT_DIR/run-pmd.sh" "$PROJECT_ROOT" \
            "$SCRIPT_DIR/../linters/rulesets/pmd-smells.xml" \
            "$PROJECT_ROOT/.profile-run/pmd-findings.json" &
        pids+=($!); names+=("PMD")
    fi

    if [ "$RUN_MODE" = "all" ] || [ "$RUN_MODE" = "spotbugs-only" ]; then
        prepare_spotbugs
        echo "> Starting SpotBugs..."
        bash "$SCRIPT_DIR/run-spotbugs.sh" "$PROJECT_ROOT" "" \
            "$PROJECT_ROOT/.profile-run/spotbugs-findings.json" &
        pids+=($!); names+=("SpotBugs")
    fi

    local i
    for i in "${!pids[@]}"; do
        if ! wait "${pids[$i]}"; then
            echo "WARNING: ${names[$i]} failed" >&2
            failed=$((failed + 1))
        fi
    done

    if [ "$failed" -gt 0 ]; then
        echo "WARNING: $failed linter(s) failed — report will cover the rest" >&2
        return 1
    fi
    echo "All linters completed"
}

run_linters || true

echo ""
echo "Generating report..."
RENDER_ARGS=("$PROJECT_ROOT")
if [ "$SEVERITY_FILTER" != "all" ]; then
    RENDER_ARGS+=(--min-severity "$SEVERITY_FILTER")
fi
"$PYTHON" "$SCRIPT_DIR/render-static-report.py" "${RENDER_ARGS[@]}" || exit 1

echo ""
echo "Static analysis complete."
echo "Report: $PROJECT_ROOT/STATICREPORT.md"
