#!/bin/bash
# PMD runner — поиск code smells и потенциальных ошибок

PROJECT_ROOT="${1:-.}"
RULESET="${2:-$(dirname "$0")/../linters/rulesets/pmd-smells.xml}"
OUTPUT_FILE="${3:-.profile-run/pmd-findings.json}"

PMD_HOME="$(dirname "$0")/../linters/pmd/pmd-bin-7.8.0"
PMD_CLI="$PMD_HOME/bin/pmd"

if [ ! -f "$PMD_CLI" ]; then
    echo "ERROR: PMD CLI not found at $PMD_CLI" >&2
    exit 1
fi

if [ ! -f "$RULESET" ]; then
    echo "ERROR: Ruleset not found at $RULESET" >&2
    exit 1
fi

# Создать директорию для вывода
mkdir -p "$(dirname "$OUTPUT_FILE")"

# Запустить PMD с JSON выводом
"$PMD_CLI" \
    -d "$PROJECT_ROOT/src" \
    -R "$RULESET" \
    -f json \
    > "$OUTPUT_FILE" 2>&1

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ] || [ $EXIT_CODE -eq 4 ]; then
    # Exit code 0 = no violations, 4 = violations found (both OK for us)
    echo "PMD completed: $OUTPUT_FILE"
else
    echo "PMD failed with exit code $EXIT_CODE"
    exit 1
fi
