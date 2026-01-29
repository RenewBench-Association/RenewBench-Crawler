#!/bin/bash

# Configuration Paramters.
URL="https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genary_eng.json"
ROOT_DATA_DIRECTORY="./raw/taipower/"
TEMP_DIR="$ROOT_DATA_DIRECTORY/temp"
MOST_RECENT_DOWNLOAD="$TEMP_DIR/most_recent_download.json"
LOG_FILE="$TEMP_DIR/current_run.log"

# Save the original standard output to File Descriptor 3 so Cron receives it.
exec 3>&1

# Redirect ALL output (stdout) and errors (stderr) to the log file.
exec > "$LOG_FILE" 2>&1

# Ensure directories exist.
mkdir -p "$TEMP_DIR"
mkdir -p "$ROOT_DATA_DIRECTORY"

# Helper function to handle failure.
fail_and_print_log() {
    # Print the log file contents to File Descriptor 3 for Cron.
    cat "$LOG_FILE" >&3

    # Exit with error so Cron knows it failed.
    exit 1
}

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
        rm -f "$LOG_FILE"
        exit 0
    elif [ "$HTTP_CODE" -eq 200 ]; then
        echo "Update detected (Server returned 200). Proceeding to download..."

        # Download, process, and save data with download script.
        ~/venv/bin/python3 -u ~/RenewBench-Crawler/rbc/energy/taipower/downloader.py "$ROOT_DATA_DIRECTORY"
        PYTHON_EXIT_CODE=$?

        if [ $PYTHON_EXIT_CODE -eq 0 ]; then
          echo "Downloading most recent data was successful - updating most recent file!"
          # Update most recently downloaded file.
          curl -f -s -S -R -o "$MOST_RECENT_DOWNLOAD" "$URL"
          # Remove log file - no errors!
          rm -f "$LOG_FILE"
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
    ~/venv/bin/python3 -u ~/RenewBench-Crawler/rbc/energy/taipower/downloader.py "$ROOT_DATA_DIRECTORY"
    PYTHON_EXIT_CODE=$?

    if [ $PYTHON_EXIT_CODE -eq 0 ]; then
      echo "Downloading the data for the first time was a success - creating most recent file!"
      # Update most recently downloaded file.
      curl -f -s -S -R -o "$MOST_RECENT_DOWNLOAD" "$URL"
      # Remove log file - no errors!
      rm -f "$LOG_FILE"
      exit 0
    else
      echo "OH NO - The download failed with the errors above!."
      fail_and_print_log
    fi
fi
