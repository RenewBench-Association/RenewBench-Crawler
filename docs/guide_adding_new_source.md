# Guide: Adding a new data source

To add a new data source to the RenewBench-Crawler repository, you'll need to amend and
create several files. Here is an overview of the necessary changes to
include your `<source>` for `<type> = energy | weather` data.
You can always look at existing crawlers (such as `energy/entsoe`) for reference.

At a high level, each data source consists of:
- a YAML config under `configs/<type>/<source>.yaml`,
- a config model in `rbc/config/schema.py` to validate and access that config,
- crawler logic under `rbc/<type>/<source>/` (typically a `<Source>Downloader` class),
- one or more CLI scripts in `scripts/<type>/` for running,
- tests under `tests/` for code validation,
- a mention in the [data sources catalogue](data_sources.md).

## Configuration

In general, your source will always need a config file and loading logic:

1. **Config** ([configs/\<type\>/](../configs)):

    Create a `<type>/<source>.yaml` with (at minimum)
    - a destination directory for storing data (`paths/dst_dir_raw`)
    - any potential access information required to crawl the data (`access/...`), i.e.
      API tokens or account log-in data.

> Example: [_entsoe.yaml_ file](../configs/energy/entsoe.yaml)

2. **Config loader** ([rbc/config/schema.py](../rbc/config/schema.py)):

    Amend the `rbc/config/schema.py` to
    - include a `class <Source>Config` with the attributes required by the
      `.yaml`.
    - add your class to the `SCHEMA_REGISTRY` at the bottom of the file.

> Example: [_EntsoeConfig_ class](../rbc/config/schema.py#L75)

3. **Tests** ([tests/](tests)):

    In the `tests/config/conftest.py`, update the dict returned by the
    `source_configs` function to include a dict version of your `<source>.yaml` with
    placeholders.

> Example: [_source_configs_ function](../tests/config/conftest.py#L16)

## Downloader

The following files will be required to set up the downloading logic for your crawler:

1. **Source folder** ([rbc/\<type\>/\<source\>](../rbc)):

    Create a `rbc/<type>/<source>` folder containing
    - a `downloader.py` with a `class <Source>Downloader` to coordinate data crawling.

> Example: [_entsoe_ folder](../rbc/energy/entsoe)

2. **Script** ([scripts/\<type\>/\<source\>_...py](../scripts)):

    Create a script for each of your source's functionalities from step 3, i.e.
    - a `<type>/<source>_download.py` to run the `downloader.py`.

> Example: [_entsoe_download.py_ file](../scripts/energy/entsoe_download.py)

3. **Tests** ([tests/](../tests)):

    In the `tests/<type>/<source>` folder, create a `test_...py` with tests for
    each of the given functionalities, i.e. `test_downloader.py`.

> Example: [_test_downloader.py_ file](../tests/energy/entsoe/test_downloader.py)

## Processor

The following files will be required to set up the data processing logic for your
crawler:

\<tbd\>
