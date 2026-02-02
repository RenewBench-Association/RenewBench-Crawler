#!/bin/bash

# Configuration Parameters.
URL="https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genary_eng.json"

PYTHON_EXE="$HOME/venv/bin/python3"
SCRIPT_PATH="$HOME/RenewBench-Crawler/scripts/energy/taipower_download.py"
ROOT_DATA_DIRECTORY="$HOME/raw_data"
TEMP_DIR="$HOME/temp"
MOST_RECENT_DOWNLOAD="$TEMP_DIR/most_recent_download.json"
LOG_FILE="$TEMP_DIR/current_download.log"
MAIL_CMD="/usr/bin/mail"
CONFIG_FILE="$HOME/recipients.env"

# Save the original standard output to File Descriptor 3 so Cron receives it.
exec 3>&1

# Redirect ALL output (stdout) and errors (stderr) to the log file.
exec > "$LOG_FILE" 2>&1

# Load recipients.
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
else
    # Fallback/Error if the file is missing on the server
    echo "CRITICAL: Config file with emails not found!" >> "$CONFIG_FILE"
    # Optional: Set a default or exit
    RECIPIENTS="renewbench@lists.kit.edu"
fi

# Helper function to handle failure and notify us.
fail_and_print_log() {
    echo "Script failed. Sending alert..."

    $MAIL_CMD -s "⚠️ FAILED: Taipower Crawler" \
              -S from="RenewBench Taiwan Bot <RenewBench-bot@kit.edu>" \
              "$RECIPIENTS" < "$LOG_FILE"

    exit 1
}

if [ ! -f "$PYTHON_EXE" ]; then
    echo "ERROR: Python not found at $PYTHON_EXE"
    fail_and_print_log
fi

# Ensure directories exist.
mkdir -p "$ROOT_DATA_DIRECTORY"
mkdir -p "$TEMP_DIR"

# Check if most recent download file exists.
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
        exit 0
    elif [ "$HTTP_CODE" -eq 200 ]; then
        echo "Update detected (Server returned 200). Proceeding to download..."

        # Download, process, and save data with download script.
        $PYTHON_EXE -u $SCRIPT_PATH "$ROOT_DATA_DIRECTORY"
        PYTHON_EXIT_CODE=$?

        if [ $PYTHON_EXIT_CODE -eq 0 ]; then
          echo "Downloading most recent data was successful - updating most recent file!"
          # Update most recently downloaded file.
          curl -f -s -S -R -o "$MOST_RECENT_DOWNLOAD" "$URL"
          exit 0
        else
          echo "OH NO - The download failed with the errors above!."
          fail_and_print_log
        fi
    else
        echo "DANGER ZONE: The metadata check via curl failed. Server returned HTTP $HTTP_CODE"
        echo "As a result the download could not be started! If this happened I'm sorry - but we are screwed!"
        fail_and_print_log
    fi
else
    echo "First run detected (no recently downloaded file found). Downloading anyway..."
    # Download, process, and save data with download script.
    $PYTHON_EXE -u "$SCRIPT_PATH" "$ROOT_DATA_DIRECTORY"
    PYTHON_EXIT_CODE=$?

    if [ $PYTHON_EXIT_CODE -eq 0 ]; then
      echo "Downloading the data for the first time was a success - creating most recent file!"
      # Update most recently downloaded file.
      curl -f -s -S -R -o "$MOST_RECENT_DOWNLOAD" "$URL"
      exit 0
    else
      echo "OH NO - The download failed with the errors above!."
      fail_and_print_log
    fi
fi

