# Fog/Edge IDS Scheduling Research

This repository is a working scaffold for research on IDS inference scheduling
across edge, fog, and cloud environments. It currently provides a pinned iFogSim2
setup and a small Python package for building and launching the simulator.

The reviewed papers and their bibliography are listed in [papers/](papers/README.md).

## Quick Start

From the repository root:

```bash
source .venv/bin/activate
fogids doctor
fogids run
```

`fogids run` launches the original upstream `VRGameFog` example. This is an
installation smoke test, not an IDS experiment. The full output is written to
`artifacts/VRGameFog.log`.

To rebuild the Java simulator classes:

```bash
fogids build
```

To run another upstream class:

```bash
fogids run --class-name org.fog.test.perfeval.VRGameFog --timeout 120
```

## Versions And Reproducibility

- Python: tested with **3.12.14** in an isolated `.venv` environment.
- Java: tested with **Temurin 17.0.20.1**, using the existing system Java.
- iFogSim2: official **v2.0.0** release, commit
  `643c433b9d6c9f031a2e31f129f2b2c6c7fae835`.
- Source: https://github.com/Cloudslab/iFogSim
- The simulator version is pinned in `configs/ifogsim.lock.json`.

The current upstream branch at `5f68d3947e450d8d2b4af42670be819206be68c9`
contains CloudSim 7 integration and does not compile on Java 17, for example
because it uses `List.getLast()`. For that reason, this repository uses the
official iFogSim2 v2.0.0 release. The upstream sources are not modified.
Compilation uses ISO-8859-1 because some older GUI source files contain
non-UTF-8 bytes. `javac` warnings about deprecated upstream constructors do not
prevent the build.

To restore the environment after cloning this repository, use JDK 17,
Python 3.10+, and access to GitHub/PyPI:

```bash
python3.12 scripts/bootstrap.py
source .venv/bin/activate
fogids run
```

The bootstrap script does not switch an existing checkout to another version and
does not change system-wide installations. Java libraries are taken from the
upstream `jars/` directory; precompiled upstream `out/` and `output/`
directories are not used.

## Repository Structure

```text
src/fogids/               Python package and CLI
scripts/ifogsim.py        Java build and JVM launch wrapper
scripts/bootstrap.py      Environment restoration script
configs/ifogsim.lock.json Pinned simulator version
vendor/ifogsim/           Original upstream checkout, excluded from Git
build/ifogsim/classes/    Locally compiled Java classes, excluded from Git
artifacts/                Run logs, excluded from Git
tmp/pdfs/                 Existing literature-review materials
```

## Current Scope

The environment is ready: all 327 Java source files compile successfully, the
Python CLI is available, and the standard upstream simulation runs. Python
currently controls the JVM as an external process. There is **no persistent RPC
bridge for online scheduling decisions yet**.

The next step is to define a small IDS scenario, a state and assignment contract,
a persistent Java-Python communication channel, and a simple baseline policy.
The protocol will need a `snapshot_id`, simulation time for the snapshot,
assignments, solver runtime, and a freshness check before applying decisions.

ML, QUBO, and QPU dependencies have not been added yet because the exact method
is still being selected. VRGameFog outputs are not IDS experimental results and
do not demonstrate the advantage of any scheduler.
