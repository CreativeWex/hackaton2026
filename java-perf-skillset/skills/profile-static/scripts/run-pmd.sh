#!/usr/bin/env bash
# PMD runner — поиск code smells и потенциальных ошибок.
# Выход: нормализованный JSON (общая схема, см. normalize-findings.py).
set -u

PROJECT_ROOT="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULESET="${2:-$SCRIPT_DIR/../linters/rulesets/pmd-smells.xml}"
OUTPUT_FILE="${3:-$PROJECT_ROOT/.profile-run/pmd-findings.json}"

PMD_HOME="$SCRIPT_DIR/../linters/pmd/pmd-bin-7.8.0"
PMD_CLI="$PMD_HOME/bin/pmd"
PYTHON="${PYTHON:-$(command -v python3 || command -v python || echo py)}"

if [ ! -f "$PMD_CLI" ]; then
    echo "ERROR: PMD CLI not found at $PMD_CLI" >&2
    exit 1
fi
if [ ! -f "$RULESET" ]; then
    echo "ERROR: Ruleset not found at $RULESET" >&2
    exit 1
fi

SRC_DIR="$PROJECT_ROOT/src/main/java"
[ -d "$SRC_DIR" ] || SRC_DIR="$PROJECT_ROOT/src"
if [ ! -d "$SRC_DIR" ]; then
    echo "ERROR: No Java sources found under $PROJECT_ROOT/src" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"
RAW_JSON="$(dirname "$OUTPUT_FILE")/pmd-raw.json"

# PMD 7 требует подкоманду `check`; отчёт пишем через -r, чтобы stderr
# (прогресс, предупреждения) не смешивался с JSON.
"$PMD_CLI" check -d "$SRC_DIR" -R "$RULESET" -f json -r "$RAW_JSON" \
    --no-cache --no-progress
PMD_EXIT=$?

# Exit code 0 = нарушений нет, 4 = нарушения найдены (оба — успех запуска)
if [ $PMD_EXIT -ne 0 ] && [ $PMD_EXIT -ne 4 ]; then
    echo "ERROR: PMD failed with exit code $PMD_EXIT" >&2
    exit 1
fi

"$PYTHON" "$SCRIPT_DIR/normalize-findings.py" pmd "$RAW_JSON" "$OUTPUT_FILE" || exit 1
rm -f "$RAW_JSON"
echo "PMD completed: $OUTPUT_FILE"
