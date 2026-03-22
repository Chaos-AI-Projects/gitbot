#!/usr/bin/env python3
"""
Automation script to process .done files and run github_fetcher.py on specified repositories.

This script implements the requirements from issue #1:
1. List files in a directory
2. For filename in format username_repo-yyyymmdd-hhMMss.done, run github_fetcher.py for username/repo
   and since yyyymmdd-hhMMss, output written to username_repo-$newdatetime
3. Move the old .done file to an archive directory
4. Get github token from .env from the same directory of this script
"""

import os
import sys
import json
import shutil
from datetime import datetime
import re
import subprocess
from pathlib import Path


def load_env_file(env_path='.env'):
    """Load environment variables from .env file."""
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    # Handle both "KEY=value" and "export KEY=value" formats
                    if line.startswith('export '):
                        line = line[7:]  # Remove 'export ' prefix
                    key, value = line.split('=', 1)
                    env_vars[key] = value.strip('"\'')
    return env_vars


def parse_done_filename(filename):
    """
    Parse a done filename to extract username, repo, and timestamp.

    Expected format: username_repo-yyyymmdd-hhMMss.done

    Returns:
        tuple: (username, repo, since_datetime) or None if parsing fails
    """
    # Remove .done extension
    basename = filename[:-5] if filename.endswith('.done') else filename

    # Match pattern: username_repo-yyyymmdd-hhMMss
    pattern = r'^(.+?)_(.+)-(\d{8})-(\d{6})$'
    match = re.match(pattern, basename)

    if not match:
        return None

    username, repo, date_str, time_str = match.groups()

    try:
        # Parse the timestamp: yyyymmdd-hhMMss
        dt_str = f"{date_str}-{time_str}"
        since_dt = datetime.strptime(dt_str, '%Y%m%d-%H%M%S')
        return username, repo, since_dt
    except ValueError:
        return None


def main():
    # Load environment variables from .env file
    env_vars = load_env_file()
    github_token = env_vars.get('GITHUB_TOKEN')

    if not github_token:
        print("Error: GITHUB_TOKEN not found in .env file", file=sys.stderr)
        sys.exit(1)

    # Set up directories
    current_dir = Path('.')
    archive_dir = current_dir / 'archive'
    archive_dir.mkdir(exist_ok=True)

    # Find all .done files
    done_files = list(current_dir.glob('*.done'))

    if not done_files:
        print("No .done files found to process.")
        return

    print(f"Found {len(done_files)} .done file(s) to process.")

    for done_file in done_files:
        print(f"\nProcessing {done_file.name}...")

        # Parse the filename
        parsed = parse_done_filename(done_file.name)
        if not parsed:
            print(f"  Skipping {done_file.name}: invalid format")
            continue

        username, repo, since_dt = parsed
        repo_full = f"{username}/{repo}"

        # Format since timestamp for the script
        since_str = since_dt.strftime('%Y-%m-%d %H:%M:%S')

        # Generate output filename: username_repo-$newdatetime
        # Using current timestamp for the output file
        output_timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        output_filename = f"{username}_{repo}-{output_timestamp}.json"
        output_path = current_dir / output_filename

        # Build command to run github_fetcher.py
        cmd = [
            sys.executable,  # Use the same Python interpreter
            'github_fetcher.py',
            repo_full,
            since_str,
            '--output', str(output_path),
            '--token', github_token
        ]

        print(f"  Running: {' '.join(cmd[:-3])} <repo> <since> --output {output_filename} --token <hidden>")

        try:
            # Run the github_fetcher.py script
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )

            print(f"  Successfully fetched data for {repo_full}")
            print(f"  Output saved to: {output_filename}")

            # Move the .done file to archive
            archive_path = archive_dir / done_file.name
            shutil.move(str(done_file), str(archive_path))
            print(f"  Moved {done_file.name} to archive/")

        except subprocess.CalledProcessError as e:
            print(f"  Error processing {done_file.name}:", file=sys.stderr)
            print(f"  Exit code: {e.returncode}", file=sys.stderr)
            print(f"  stderr: {e.stderr}", file=sys.stderr)
        except Exception as e:
            print(f"  Unexpected error processing {done_file.name}: {e}", file=sys.stderr)


if __name__ == '__main__':
    main()