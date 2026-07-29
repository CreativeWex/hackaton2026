#!/bin/bash
# SpotBugs runner — поиск настоящих Java багов

PROJECT_ROOT="${1:-.}"
OUTPUT_FILE="${3:-.profile-run/spotbugs-findings.json}"

SPOTBUGS_HOME="$(dirname "$0")/../linters/spotbugs/spotbugs-4.8.6"
SPOTBUGS_CLI="$SPOTBUGS_HOME/bin/spotbugs"

if [ ! -f "$SPOTBUGS_CLI" ]; then
    echo "ERROR: SpotBugs CLI not found at $SPOTBUGS_CLI" >&2
    exit 1
fi

# Проверить что код откомпилирован
if [ ! -d "$PROJECT_ROOT/target/classes" ]; then
    echo "ERROR: Compiled code not found. Run 'mvn clean compile' first" >&2
    exit 1
fi

# Создать директорию для вывода
mkdir -p "$(dirname "$OUTPUT_FILE")"

# Запустить SpotBugs с XML выводом (потом переведем в JSON)
TEMP_XML="$(dirname "$OUTPUT_FILE")/spotbugs-temp.xml"

"$SPOTBUGS_CLI" \
    -textui \
    -output "$TEMP_XML" \
    -outputFormat xml \
    -effort:more \
    -maxRank 15 \
    "$PROJECT_ROOT/target/classes" 2>&1

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ] || [ $EXIT_CODE -eq 1 ]; then
    # Exit code 0 = no bugs, 1 = bugs found (both OK for us)

    # Конвертировать XML в JSON
    python3 - << 'PYTHON_EOF' "$TEMP_XML" "$OUTPUT_FILE"
import sys
import xml.etree.ElementTree as ET
import json

xml_file = sys.argv[1]
json_file = sys.argv[2]

tree = ET.parse(xml_file)
root = tree.getroot()

bugs = []
for bug in root.findall('.//BugInstance'):
    bug_dict = {
        'type': bug.get('type', 'Unknown'),
        'abbrev': bug.get('abbrev', ''),
        'category': bug.get('category', 'CORRECTNESS'),
        'priority': int(bug.get('priority', 2)),
        'instanceHash': bug.get('instanceHash', ''),
        'instanceOccurrenceNum': int(bug.get('instanceOccurrenceNum', 0)),
        'instanceOccurrenceNum': int(bug.get('instanceOccurrenceNum', 0)),
        'rank': int(bug.get('rank', 20)),
        'abbrev': bug.get('abbrev', ''),
    }

    # Get file/line info
    source = bug.find('SourceLine')
    if source is not None:
        bug_dict['file'] = source.get('sourcefile', '')
        bug_dict['line'] = int(source.get('start', 0))

    bugs.append(bug_dict)

with open(json_file, 'w') as f:
    json.dump(bugs, f, indent=2)
PYTHON_EOF

    rm -f "$TEMP_XML"
    echo "SpotBugs completed: $OUTPUT_FILE"
else
    echo "SpotBugs failed with exit code $EXIT_CODE"
    exit 1
fi
