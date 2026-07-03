#!/bin/bash
#SBATCH --job-name=template	# generic name, can be replaced via flag in CL!
#SBATCH --partition=cpu 	# CPU partition on the HPC system. NOTE: Replace with the given partition name!
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --exclusive             # locks the node to prevent API/network throttling from parallel jobs
#SBATCH --time=02:00:00		# default max time period (may have to be extended for some)
#SBATCH --mem=8G		# default safe memore allocation		
# Log file for direct console printing (%x = (new) job name, %j = job ID). NOTE: Replace file path if desired!
#SBATCH --output=slurm_logs/%x_%j.log
# Have Slurm send a signal 60 seconds before timeout!
#SBATCH --signal=B:USR1@60

# --- 0. Prep ----
# define what to do when the timeout signal is received
timeout_handler() {
	echo "⚠️ WARNING: Job is approaching its Slurm time limit! Re-submitting automatically..."
	
	# re-submit a fresh clone of the exact job with identical arguments
	sbatch --job-name="$SLURM_JOB_NAME" \
	       --time="$TIME_LIMIT" \
	       --export=ALL,SOURCE="$SOURCE",TIME_LIMIT="$TIME_LIMIT" \
	       scripts/energy/slurm/download.sh  
	exit 0
}

# register the handler function to trigger on SIGUSR1
trap 'timeout_handler' USR1

# ---- 1. Environment setup ----
module purge
cd $SLURM_SUBMIT_DIR		# set dir where job was submitted (should be "rbc" repo root!)
source venv/bin/activate	# virtual environment for run. NOTE: Replace "venv" with correct name
echo "Virtual environment activated..."

# safe fallback for the timeout_handler when running script as standalone
TIME_LIMIT=${TIME_LIMIT:-"02:00:00"}

# ---- 2. Run crawler ----
# check the required SOURCE was passed
if [ -z "$SOURCE" ]; then
	echo "Error: SOURCE name was not provided!"
	exit 1
fi

echo "Starting download crawler for source '$SOURCE' at $(date)..."

# run the SOURCE download module. NOTE: ENSURE THE SECRET CREDENTIALS ARE CORRECTLY SET IN THE YAML CONFIGS!
python -m scripts.energy."$SOURCE"_download &
PYTHON_PID=$!

# tell Bash to wait (keeps Bash alive to intercept the Slurm timeout signal)
wait $PYTHON_PID

echo "Finished download crawler for source '$SOURCE' at $(date)!"
