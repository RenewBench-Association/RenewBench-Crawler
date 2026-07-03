# Energy scripts

This folder contains all scripts for running the various crawler-related downloading and processing steps included in the `rbc` package. The following descriptions are grouped according to purpose and the manner of usage. Some important notes to heed before running anything:

- Relevant parameters that require user definitions are handled by per-source config YAML files, located at `configs/energy/<SOURCE>.yaml`. These can be individually overwritten with the `--cfg_options` flag, but it's best to just set the values once directly in the YAML!
- All scripts are designed to be run from the repo root!
- All scripts require a virtual environment to have been set up (using Python3.11 or 3.12) with the rbc-required packages installed (`pip install .`)!

## Data download

The scripts denoted with `download` can be used to perform the raw data download. Python scripts (`.py`) are designed for direct usage, bash scripts (`.sh`) for running via slurm on HPC systems. 

### Direct

To download the raw data directly for a specific source, simply run the following command:
```
$ python3.12 -m scripts.energy.<SOURCE>_download
```

Run-specific parameters can be set through flags and include `--years` (`-y`) and `--no-resume`, as well as in some cases `--temporal_resolutions` (`-tr`) and `--bidding_zones` (`-bz`). By default, all years, temporal resolutions, and bidding zones will be downloaded and the download will resume from a previous run (if one has already occurred). If you wish to test a downloader by requesting only a specific data segment, you can f.e. do:
```
$ python3.12 -m scripts.energy.<SOURCE>_download -y 2024 2025 --no-resume
```

> [!IMPORTANT]
>
> The above will only work if you have defined the user-specific parameters in the matching `configs/energy/<SOURCE>.yaml` file. If you have not or wish to do so directly in the CL, you can use the `--cfg-options` (`-o`) flag with key-value pairs as follows f.e.:
> ```
> $ python3.12 -m scripts.energy.<SOURCE>_download -o paths.dst_dir_raw="/your/desired/path" -o access.api_key="YOUR_SECRET_TOKEN"
> ```
> Naturally the config options depend on the source in question.

## Slurm

To run a single or all downloaders via Slurm, you can use the related bash scripts in the `slurm` subfolder. Prerequistes to do so include:
1. User-specific parameters **must** be defined in the / all config YAML files!
2. The following lines need to be amended in the `download.sh` script:
	- `#SBATCH --partition=cpu`: define the correct CPU partition name
	- `#SBATCH --output=slurm_logs/%x_%j.log`: if desired, define a more concrete path for the slurm logs
	- `source venv/bin/activate`: if the virtual environment is not named "venv" and located in the rbc repo root, redefine path.

### Single download

To submit a single source downloader job, you can do:
```
$ sbatch --job-name=<SOURCE> --time=<TIME_LIMIT> --requeue --export="SOURCE=<SOURCE>,TIME_LIMIT=<TIME_LIMIT>" scripts/energy/slurm/download.sh
```

### All downloads

To run all downloaders, you can simply do:
```
$ bash scripts/energy/slurm/download_all.sh
```

> [!NOTE]
>
> If you wish to run a specific subset of downloaders, you can amend the `SOURCES` definition at the beginning of the `download_all.sh` script.


## Download evaluation

To evaluate how successful the raw data crawling was, you can run the `evaluate_downloads.py` script. For each downloader, this inspects:
- the `status.pickle` file to check for successful ("1") and unsuccessful ("0") tasks
- the stored CSV / JSON files to find data gaps based on the range of dates one would expect from the file names and those expected by the `status.pickle` file.

To run the script, simply do:
```
$ python3.12 -m scripts.energy.evaluate_downloads
```

Per default, all downloaders are evaluated and only the unsuccessful ("0") tasks in the pickle inspected. Alternatively, the following options can be set via flags:

- `-s <SOURCE>`: evaluate only a specific downloader or list of downloaders, i.e. `-s aemo aeso`
- `-a`: get an overview of all pickle data including the successful ("1") tasks.

