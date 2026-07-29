#!/bin/bash
# CheckStyle runner — проверка стиля кода Java

PROJECT_ROOT="${1:-.}"
RULESET="${2:-$(dirname "$0")/../linters/rulesets/checkstyle-smells.xml}"
OUTPUT_FILE="${3:-.profile-run/checkstyle-findings.json}"

CHECKSTYLE_JAR="$(dirname "$0")/../linters/checkstyle/checkstyle-10.21.0-all.jar"

if [ ! -f "$CHECKSTYLE_JAR" ]; then
    echo "ERROR: CheckStyle JAR not found at $CHECKSTYLE_JAR" >&2
    exit 1
fi

if [ ! -f "$RULESET" ]; then
    echo "ERROR: Ruleset not found at $RULESET" >&2
    exit 1
fi

# Создать директорию для вывода
mkdir -p "$(dirname "$OUTPUT_FILE")"

# Запустить CheckStyle с JSON выводом
java -jar "$CHECKSTYLE_JAR" \
    -c "$RULESET" \
    -f json \
    -o "$OUTPUT_FILE" \
    "$(find "$PROJECT_ROOT/src" -name "*.java" -type f 2>/dev/null | head -100)" \
    2>&1

if [ $? -eq 0 ]; then
    echo "CheckStyle completed: $OUTPUT_FILE"
else
    echo "CheckStyle failed with exit code $?"
    exit 1
fi
