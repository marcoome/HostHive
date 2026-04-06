#!/bin/bash
# Scan a file or directory with ClamAV
# Usage: clamav-scan.sh <path> [--quarantine]
if [ -z "$1" ]; then
    echo '{"error": "No path specified"}'
    exit 1
fi

SCAN_PATH="$1"
QUARANTINE_DIR="/opt/hosthive/quarantine"
QUARANTINE_FLAG=""

if [ "$2" = "--quarantine" ]; then
    mkdir -p "$QUARANTINE_DIR"
    QUARANTINE_FLAG="--move=${QUARANTINE_DIR}"
fi

RESULT=$(clamscan --no-summary --infected --recursive $QUARANTINE_FLAG "$SCAN_PATH" 2>&1)
RC=$?
if [ $RC -eq 0 ]; then
    echo '{"clean": true, "threats": [], "quarantined": false}'
elif [ $RC -eq 1 ]; then
    THREATS=$(echo "$RESULT" | grep "FOUND" | awk -F: '{print $2}' | sed 's/ FOUND//' | tr '\n' ',' | sed 's/,$//')
    if [ -n "$QUARANTINE_FLAG" ]; then
        echo "{\"clean\": false, \"threats\": [\"${THREATS}\"], \"quarantined\": true}"
    else
        echo "{\"clean\": false, \"threats\": [\"${THREATS}\"], \"quarantined\": false}"
    fi
else
    echo "{\"error\": \"Scan failed: ${RESULT}\"}"
fi
