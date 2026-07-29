#!/usr/bin/env bash
# CheckStyle runner — проверка стиля кода Java.
# Выход: нормализованный JSON (общая схема, см. normalize-findings.py).
set -u

PROJECT_ROOT="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULESET="${2:-$SCRIPT_DIR/../linters/rulesets/checkstyle-smells.xml}"
OUTPUT_FILE="${3:-$PROJECT_ROOT/.profile-run/checkstyle-findings.json}"

CHECKSTYLE_JAR="$SCRIPT_DIR/../linters/checkstyle/checkstyle-10.21.0-all.jar"
PYTHON="${PYTHON:-$(command -v python3 || command -v python || echo py)}"

if [ ! -f "$CHECKSTYLE_JAR" ]; then
    echo "ERROR: CheckStyle JAR not found at $CHECKSTYLE_JAR" >&2
    exit 1
fi
if [ ! -f "$RULESET" ]; then
    echo "ERROR: Ruleset not found at $RULESET" >&2
    exit 1
fi

# Анализируем только основные исходники; fallback на весь src/
SRC_DIR="$PROJECT_ROOT/src/main/java"
[ -d "$SRC_DIR" ] || SRC_DIR="$PROJECT_ROOT/src"
if [ ! -d "$SRC_DIR" ]; then
    echo "ERROR: No Java sources found under $PROJECT_ROOT/src" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"
RAW_XML="$(dirname "$OUTPUT_FILE")/checkstyle-raw.xml"

# CheckStyle поддерживает только plain/xml/sarif (json нет) — берём XML и
# нормализуем. Каталог передаём напрямую: CheckStyle рекурсивно обходит его сам.
# Ненулевой exit code означает и «нарушения найдены» — не считаем это провалом,
# если XML-отчёт создан.
java -jar "$CHECKSTYLE_JAR" -c "$RULESET" -f xml -o "$RAW_XML" "$SRC_DIR"
CS_EXIT=$?

if [ ! -s "$RAW_XML" ]; then
    echo "ERROR: CheckStyle produced no output (exit code $CS_EXIT)" >&2
    exit 1
fi

"$PYTHON" "$SCRIPT_DIR/normalize-findings.py" checkstyle "$RAW_XML" "$OUTPUT_FILE" || exit 1
rm -f "$RAW_XML"
echo "CheckStyle completed: $OUTPUT_FILE"
