"""Thin CLI for launching the Java simulator from Python."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local runtime and simulator checkout")
    sub.add_parser("build", help="Compile the pinned iFogSim checkout")
    run = sub.add_parser("run", help="Run an upstream example; not a custom IDS simulation")
    run.add_argument("--class-name", default="org.fog.test.perfeval.VRGameFog")
    run.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.command == "doctor":
        checks = {
            "java": shutil.which("java"),
            "javac": shutil.which("javac"),
            "ifogsim_source": (ROOT / "vendor/ifogsim/src").is_dir(),
            "compiled": (ROOT / "build/ifogsim/classes/org/fog/entities/FogDevice.class").is_file(),
        }
        print(json.dumps(checks, indent=2))
        return 0 if all(checks.values()) else 1
    script = ROOT / "scripts/ifogsim.py"
    import sys
    command = [sys.executable, str(script), args.command]
    if args.command == "run":
        command += ["--class-name", args.class_name, "--timeout", str(args.timeout)]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
