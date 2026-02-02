#!/bin/bash

# Configuration Parameters.
REMOTE_USER="svc-renewbench-00001"
REMOTE_HOST="os-login.lsdf.kit.edu"
REMOTE_DIR="/lsdf/kit/scc/projects/renewbench"
SSH_KEY="$HOME/.ssh/id_rsa_lsdf"
MOUNT_POINT="$HOME/mnt/lsdf"
SRC_DATA_DIRECTORY="$HOME/raw_data"
DST_DATA_DIRECTORY="$MOUNT_POINT/taipower/raw"
TEMP_DIR="$HOME/temp"
LOG_FILE="$TEMP_DIR/current_copy.log"
MAIL_CMD="/usr/bin/mail"
CONFIG_FILE="$HOME/recipients.env"
FUSERMOUNT_CMD="/usr/bin/fusermount"

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
    echo "Copying to LSDF failed. Sending alert..."

    $MAIL_CMD -s "⚠️ FAILED: Taipower Copier" \
              -S from="RenewBench Taiwan Bot <RenewBench-bot@kit.edu>" \
              "$RECIPIENTS" < "$LOG_FILE"

    exit 1
}
# Check for Zombie Mount.
if mountpoint -q "$MOUNT_POINT"; then
    # Try to list the directory with a 5-second timeout.
    timeout 5s ls "$MOUNT_POINT" > /dev/null 2>&1

    if [ $? -ne 0 ]; then
        echo "Zombie mount detected! Forcing cleanup..."
        $FUSERMOUNT_CMD -uz "$MOUNT_POINT"
        # Give it a second to clean up
        sleep 2
    fi
fi

# Mount LSDF for copying over data if not already mounted.
echo "Checking if LSDF is already mounted..."
if mountpoint -q "$MOUNT_POINT"; then
  echo "The LSDF is already mounted."
else
  echo "Mounting to the LSDF..."
  # Mount using SSHFS with the specific key file.
    sshfs -o IdentityFile="$SSH_KEY" \
          -o StrictHostKeyChecking=no \
          -o allow_other \
          "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR" "$MOUNT_POINT"
  if [ $? -eq 0 ]; then
    echo "Mount successful."
  else
    echo "Failed to mount."
    fail_and_print_log
  fi
fi

# Ensure directories exists.
mkdir -p "$SRC_DATA_DIRECTORY"
mkdir -p "$DST_DATA_DIRECTORY"
mkdir -p "$TEMP_DIR"

# Perform copying (without -u flag meaning existing files in DST will be overwritten).
#--remove-source-files: Deletes successfully copied files.
#-a: Keeps timestamps and recursively copies.
#-v: Gives a log of what happened.
#-h: Human-readable sizes in the logs.
#--no-g: Don't change the group (this prevents a Permission denied error).
#--no-o: Don't change the owner (this prevents a Permission denied error).
rsync -avh --no-g --no-o --remove-source-files "$SRC_DATA_DIRECTORY/" "$DST_DATA_DIRECTORY/"
RSYNC_EXIT_CODE=$?

# Check if copying was successful.
if [ $RSYNC_EXIT_CODE -eq 0 ]; then
  echo "Copying the most recent data to the LSDF was successful!"
  # Safely delete any potentially remaining subdirectories.
  find "$SRC_DATA_DIRECTORY" -mindepth 1 -type d -empty -delete
  exit 0
else
  echo "OH NO - The copying failed with the errors above!"
  fail_and_print_log
fi
