#!/bin/bash

#SBATCH --job-name=healpix-regrid
#SBATCH --partition=cpu                      # e.g. cpu, batch -- see `sinfo`
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=26                   # GRIB decode and the regrid each use ~1.5 cores per worker
#SBATCH --mem=500000mb                       # ~20 GB peak per worker at block_memory_mb=8192
#SBATCH --time=24:00:00                      # adjust to how many (year, month, variable) tasks you run
#SBATCH --signal=B:USR1@600                  # SIGUSR1 to this shell 10 min before the limit
#SBATCH --output=logs/slurm/regrid_%x_%j.out # NOTE: relative to the submit dir -- `mkdir -p logs/slurm` first
#SBATCH --error=logs/slurm/regrid_%x_%j.err

set -euo pipefail

# --- 0. Prep ----
# Which source to regrid: one of era5, barra2_r2, barra2_c2, barra2_c2_20min,
# icon_dream_global, icon_dream_eu. Set it here, or pass it at submit time:
#
#   sbatch --export=ALL,SOURCE=barra2_r2 scripts/weather/slurm/regrid_to_healpix.slurm
#
# Anything else Slurm takes on the command line overrides its #SBATCH default,
# which is how a heavier source gets more room:
#
#   sbatch --export=ALL,SOURCE=icon_dream_global,YEARS="2010 2011" \
#          --time=48:00:00 --job-name=healpix-icon scripts/weather/slurm/regrid_to_healpix.slurm
SOURCE=${SOURCE:-""}

JOB_SCRIPT="scripts/weather/slurm/regrid_to_healpix.slurm"
YEARS=${YEARS:-"2010"}
MONTHS=${MONTHS:-""}                         # empty regrids every month of YEARS
WORKERS=${WORKERS:-12}
BLOCK_MEMORY_MB=${BLOCK_MEMORY_MB:-8192}

# safe fallback for the timeout_handler when running script as standalone
TIME_LIMIT=${TIME_LIMIT:-"24:00:00"}

# define what to do when the timeout signal is received
timeout_handler() {
	echo "⚠️ WARNING: Job is approaching its Slurm time limit! Re-submitting automatically..."

	# re-submit a fresh clone of the exact job with identical arguments -- the
	# checkpoint makes it skip whatever this job already finished
	sbatch --job-name="${SLURM_JOB_NAME:-healpix-regrid}" \
	       --time="$TIME_LIMIT" \
	       --export=ALL,SOURCE="$SOURCE",YEARS="$YEARS",MONTHS="$MONTHS",WORKERS="$WORKERS",BLOCK_MEMORY_MB="$BLOCK_MEMORY_MB",TIME_LIMIT="$TIME_LIMIT" \
	       "$JOB_SCRIPT"
	exit 0
}

# register the handler function to trigger on SIGUSR1
trap 'timeout_handler' USR1

# ---- 1. Environment setup ----
module purge
cd "${SLURM_SUBMIT_DIR:-$PWD}"	# dir where job was submitted (should be "rbc" repo root!)

# NOTE: replace with your own environment manager/name
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
eval "$("$HOME/.local/bin/micromamba" shell hook -s bash)"
micromamba activate "${CONDA_ENV:-healpix}"
echo "Environment '${CONDA_ENV:-healpix}' activated..."

# ---- 2. Run regridder ----
# check the required SOURCE was passed
if [ -z "$SOURCE" ]; then
	echo "Error: SOURCE name was not provided!"
	exit 1
fi

echo "Starting HEALPix regrid for source '$SOURCE' at $(date)..."

# YEARS/MONTHS stay unquoted on purpose: each is a list of arguments, not one
python -m scripts.weather.build_healpix_pyramid \
	--sources "$SOURCE" \
	--workers "$WORKERS" \
	-o block_memory_mb="$BLOCK_MEMORY_MB" \
	-y $YEARS \
	${MONTHS:+-m $MONTHS} &
PYTHON_PID=$!

# tell Bash to wait (keeps Bash alive to intercept the Slurm timeout signal)
wait $PYTHON_PID

echo "Finished HEALPix regrid for source '$SOURCE' at $(date)!"
