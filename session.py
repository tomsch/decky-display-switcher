#!/usr/bin/env python3
"""Run the stock session with the Display Switcher Gamescope shim."""

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path, help="Stock session executable")
    parser.add_argument("--settings", required=True, type=Path, help="Monitor preference JSON")
    arguments = parser.parse_args(argv)
    try:
        if not arguments.session.is_absolute() or not arguments.settings.is_absolute():
            raise ValueError("Session and settings paths must be absolute")
        session = arguments.session.resolve(strict=True)
        if session == Path(__file__).resolve():
            raise ValueError("The stock session cannot be the Display Switcher launcher")
        if not session.is_file() or not os.access(session, os.X_OK):
            raise ValueError(f"Stock session is not executable: {session}")
        shim_directory = Path(__file__).resolve().parent / "bin"
        shim = shim_directory / "gamescope"
        if not shim.is_file() or not os.access(shim, os.X_OK):
            raise ValueError(f"Gamescope shim is not executable: {shim}")
        environment = dict(os.environ)
        environment["PATH"] = str(shim_directory) + os.pathsep + environment.get("PATH", os.defpath)
        environment["DISPLAY_SWITCHER_SETTINGS"] = str(arguments.settings)
        os.execve(session, [str(session)], environment)
    except (OSError, ValueError) as exc:
        print(f"Display Switcher: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
