#!/bin/bash

# Configuration Paramters.
URL="https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genary_eng.json"
ROOT_DIRECTORY="./raw/taipower/"
MOST_RECENT_DOWNLOAD="$ROOT_DIRECTORY/temp/most_recent_download.json"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
NEW_FILE="$ROOT_DIRECTORY/data_$TIMESTAMP.json"
LOG_FILE="$ROOT_DIRECTORY/temp/current_run.log"

# Redirect ALL output (stdout) and errors (stderr) to the log file.
exec > "$LOG_FILE" 2>&1

if [ -f "$MOST_RECENT_DOWNLOAD" ]; then

    # -I: Fetch headers only (HEAD request).
    # -z: Check if newer than MOST_RECENT_DOWNLOAD.
    # -s: Silent.
    # -o /dev/null: Throw away the output (we only want the status code).
    # -w "%{http_code}": Returns just the number (200, 304, 404, etc.).
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -I -z "$MOST_RECENT_DOWNLOAD" "$URL")

    if [ "$HTTP_CODE" -eq 304 ]; then
        # 304 = Not Modified, we have the latest data.
        echo "No update detected (Server returned 304). Exiting."
        rm -f "$LOG_FILE"
        exit 0
    elif [ "$HTTP_CODE" -eq 200 ]; then
        echo "Update detected (Server returned 200). Proceeding to download..."

        # Update most recently downloaded file
        curl -f -s -S -R -o "$MOST_RECENT_DOWNLOAD" "$URL"
    else
        echo "CRITICAL: Metadata check via curl failed. Server returned HTTP $HTTP_CODE"
    fi
else
    echo "First run detected (No recently downloaded file found). Downloading anyway..."
fi


if [ $CURL_EXIT_CODE -ne 0 ]; then
    echo "CRITICAL: Curl failed to download. Exit code: $CURL_EXIT_CODE"
    send_failure_email
    rm -f "$LOG_FILE"
    exit 1
fi

# 2. Check if a new file was actually downloaded
if [ -s "$NEW_FILE" ]; then
    echo "New data detected ($NEW_FILE). Starting processing..."

    # 3. Run Python Script
    # We add '-u' (unbuffered) so prints appear in the log instantly.
    # We use '2>&1' to ensure Python errors are treated as standard output for the log.
    /usr/bin/python3 -u "$ROOT_DIRECTORY/process_data.py" "$NEW_FILE"

    PYTHON_EXIT_CODE=$?

    # 4. Check Python Success
    if [ $PYTHON_EXIT_CODE -eq 0 ]; then
        echo "Python processing complete. Committing changes."
        cp -p "$NEW_FILE" "$MOST_RECENT_DOWNLOAD"

        # Success! Remove the log file (unless you want a log of successes too)
        rm -f "$LOG_FILE"
    else
        echo "CRITICAL: Python script failed. See above for stack trace."
        send_failure_email
        exit 1
    fi

else
    # No new data (304 Not Modified). Cleanup.
    [ -f "$NEW_FILE" ] && rm "$NEW_FILE"
    rm -f "$LOG_FILE"
fi
