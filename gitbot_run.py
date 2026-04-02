#!/usr/bin/env python3
"""
Thin wrapper that execs gitbot-run.sh as an installed console script.

Looks for the shell script next to this file first (development), then
in the installed data directory (pip install).
"""

import os
import sys
from pathlib import Path


def main():
    # Look next to this script first (dev), then in installed data location
    script_path = Path(__file__).resolve().parent / 'gitbot-run.sh'
    if not script_path.exists():
        script_path = Path(sys.prefix) / 'share' / 'gitbot' / 'gitbot-run.sh'

    if not script_path.exists():
        print("Error: gitbot-run.sh not found. Reinstall gitbot.", file=sys.stderr)
        sys.exit(1)

    os.execvp("bash", ["bash", str(script_path)] + sys.argv[1:])


if __name__ == '__main__':
    main()
