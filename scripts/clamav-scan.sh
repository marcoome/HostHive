#!/bin/bash
# Scan a file or directory with ClamAV
# Usage: clamav-scan.sh <path>
if [ -z "$1" ]; then
    echo '{"error": "No path specified"}'
    exit 1
fi
RESULT=$(clamscan --no-summary --infected "$1" 2>&1)
RC=$?
if [ $RC -eq 0 ]; then
    echo '{"clean": true, "threats": []}'
elif [ $RC -eq 1 ]; then
    THREATS=$(echo "$RESULT" | grep "FOUND" | awk -F: '{print $2}' | sed 's/ FOUND//' | tr '\n' ',' | sed 's/,$//')
    echo "{\"clean\": false, \"threats\": [\"${THREATS}\"]}"
else
    echo "{\"error\": \"Scan failed: ${RESULT}\"}"
fi
