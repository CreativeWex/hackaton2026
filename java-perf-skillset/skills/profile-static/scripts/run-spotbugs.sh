#!/usr/bin/env bash
# SpotBugs runner — поиск настоящих Java-багов (по байткоду).
# Требует скомпилированных классов (Maven target/classes или Gradle build/classes).
# Выход: нормализованный JSON (общая схема, см. normalize-findings.py).
set -u

PROJECT_ROOT="${1:-.}"
# $2 зарезервирован под ruleset для единообразия с другими runner'ами
OUTPUT_FILE="${3:-$PROJECT_ROOT/.profile-run/spotbugs-findings.json}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPOTBUGS_HOME="$SCRIPT_DIR/../linters/spotbugs/spotbugs-4.8.6"
SPOTBUGS_CLI="$SPOTBUGS_HOME/bin/spotbugs"
PYTHON="${PYTHON:-$(command -v python3 || command -v python || echo py)}"

if [ ! -f "$SPOTBUGS_CLI" ]; then
    echo "ERROR: SpotBugs CLI not found at $SPOTBUGS_CLI" >&2
    exit 1
fi

# Maven или Gradle layout
CLASSES_DIR=""
for candidate in "$PROJECT_ROOT/target/classes" "$PROJECT_ROOT/build/classes/java/main"; do
    if [ -d "$candidate" ]; then
        CLASSES_DIR="$candidate"
        break
    fi
done
if [ -z "$CLASSES_DIR" ]; then
    echo "ERROR: Compiled classes not found (target/classes or build/classes/java/main)." >&2
    echo "       Run 'mvn compile' or 'gradle classes' first." >&2
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"
TEMP_XML="$(dirname "$OUTPUT_FILE")/spotbugs-raw.xml"

# -xml:withMessages даёт человекочитаемые LongMessage в отчёте.
# maxRank 15: scariest/scary/troubling + верх "of concern".
"$SPOTBUGS_CLI" -textui -quiet \
    -xml:withMessages -output "$TEMP_XML" \
    -maxRank 15 \
    "$CLASSES_DIR"
SB_EXIT=$?

# Exit-код SpotBugs — битовая маска: бит 0 (1) = баги найдены (успех запуска),
# бит 1 (2) = missing classes (анализ всё равно завершён), бит 2 (4) = ошибка.
if [ $((SB_EXIT & 4)) -ne 0 ] || [ ! -s "$TEMP_XML" ]; then
    echo "ERROR: SpotBugs failed with exit code $SB_EXIT" >&2
    exit 1
fi

"$PYTHON" "$SCRIPT_DIR/normalize-findings.py" spotbugs "$TEMP_XML" "$OUTPUT_FILE" || exit 1
rm -f "$TEMP_XML"
echo "SpotBugs completed: $OUTPUT_FILE"
