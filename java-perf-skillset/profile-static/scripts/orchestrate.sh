#!/bin/bash
# Profile Static Orchestrator — запуск всех трёх линтеров параллельно

set -e

PROJECT_ROOT="${1:-.}"
SEVERITY_FILTER="${2:-all}"
RUN_MODE="${3:-all}" # all, checkstyle-only, pmd-only, spotbugs-only

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "🔍 Profile Static Analysis for: $PROJECT_ROOT"
echo "📋 Severity filter: $SEVERITY_FILTER"
echo "🚀 Mode: $RUN_MODE"
echo ""

# Создать директорию для результатов
mkdir -p "$PROJECT_ROOT/.profile-run"

# Запустить линтеры параллельно
run_linters() {
    local pids=()

    if [ "$RUN_MODE" = "all" ] || [ "$RUN_MODE" = "checkstyle-only" ]; then
        echo "▶ Starting CheckStyle..."
        bash "$SCRIPT_DIR/run-checkstyle.sh" "$PROJECT_ROOT" \
            "$SKILLS_DIR/profile-static/linters/rulesets/checkstyle-smells.xml" \
            "$PROJECT_ROOT/.profile-run/checkstyle-findings.json" &
        pids+=($!)
    fi

    if [ "$RUN_MODE" = "all" ] || [ "$RUN_MODE" = "pmd-only" ]; then
        echo "▶ Starting PMD..."
        bash "$SCRIPT_DIR/run-pmd.sh" "$PROJECT_ROOT" \
            "$SKILLS_DIR/profile-static/linters/rulesets/pmd-smells.xml" \
            "$PROJECT_ROOT/.profile-run/pmd-findings.json" &
        pids+=($!)
    fi

    if [ "$RUN_MODE" = "all" ] || [ "$RUN_MODE" = "spotbugs-only" ]; then
        echo "▶ Starting SpotBugs..."
        # SpotBugs требует откомпилированного кода
        if [ ! -d "$PROJECT_ROOT/target/classes" ]; then
            echo "⚠️  Compiling project for SpotBugs..."
            cd "$PROJECT_ROOT" && mvn -q clean compile 2>/dev/null || true
            cd - > /dev/null
        fi
        bash "$SCRIPT_DIR/run-spotbugs.sh" "$PROJECT_ROOT" "" \
            "$PROJECT_ROOT/.profile-run/spotbugs-findings.json" &
        pids+=($!)
    fi

    # Ждем завершения всех процессов
    local failed=0
    for pid in "${pids[@]}"; do
        if ! wait "$pid"; then
            failed=$((failed + 1))
        fi
    done

    if [ $failed -gt 0 ]; then
        echo "⚠️  $failed linter(s) failed"
        return 1
    fi

    echo "✅ All linters completed"
    return 0
}

# Генерировать отчет
generate_report() {
    echo ""
    echo "📝 Generating report..."
    python3 "$SCRIPT_DIR/render-static-report.py" "$PROJECT_ROOT"
}

# Main execution
main() {
    echo ""
    run_linters || {
        echo "⚠️  Some linters had issues, but continuing with report generation..."
    }

    generate_report

    echo ""
    echo "✨ Static analysis complete!"
    echo "📄 Report: $PROJECT_ROOT/STATICREPORT.md"
}

main
