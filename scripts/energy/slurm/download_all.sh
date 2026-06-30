#!/bin/bash

# Define the list of sources to download in run order
# - AESO: needs to go first because BOX API token has a 1h limit and needs to be defined immediately in advance
# - EPIAS: needs to be run multiple times due to throttling and authorisation issues!
# - CEN: probably needs to be run multiple times due to API rate limit interrruptions
# - ALL: rerun to ensure all tasks are marked as 1 = completed (downloaded or had to be skipped)
SOURCES=(
	"aeso:01:00:00"
 	"adme"
	"eat:00:30:00"
	"eia"
	"ieso:00:30:00"
	"rei:00:30:00"
	"ons:01:00:00"
	"epias:05:00:00"
	"cen:11:00:00"
	"entsoe:14:00:00"
	"aemo:30:00:00"
)

DEFAULT_TIME="02:00:00"
PREVIOUS_JOB_ID=""

for ENTRY in "${SOURCES[@]}"; do
	# get source as first part before colon or, if no colon, simply the ENTRY
	SOURCE=$(echo "$ENTRY" | cut -d':' -f1)
		
	# get time limit either as segment or the default
	if [[ "$ENTRY" == *":"* ]]; then
		TIME_LIMIT=$(echo "$ENTRY" | cut -d':' -f2-)
	else
		TIME_LIMIT="$DEFAULT_TIME"
	fi

	EXPORT_VARS="ALL,SOURCE=$SOURCE,TIME_LIMIT=$TIME_LIMIT"

	if [ -z "$PREVIOUS_JOB_ID" ]; then
		# 1. first job runs immediately
		OUTPUT=$(sbatch --job-name="$SOURCE" \
				--time="$TIME_LIMIT" \
				--requeue \
				--export="$EXPORT_VARS" \
				scripts/energy/slurm/download.sh)
		PREVIOUS_JOB_ID=$(echo "$OUTPUT" | awk '{print $4}')	# parse job ID out of slurm's response ('submitted batch job XXX')
		echo "Submitted $SOURCE (Job ID: $PREVIOUS_JOB_ID) - Running immediately."
	else
		# 2. subsequent jobs wait for the previous one to finish successfully (afterok)
		OUTPUT=$(sbatch --job-name="$SOURCE" \
				--time="$TIME_LIMIT" \
				--requeue \
				--dependency=afterok:$PREVIOUS_JOB_ID \
				--export="$EXPORT_VARS" \
				scripts/energy/slurm/download.sh)
		PREVIOUS_JOB_ID=$(echo "$OUTPUT" | awk '{print $4}')
		echo "Submitted $SOURCE (Job ID: $PREVIOUS_JOB_ID) - Waiting for previous job."
	fi
done
