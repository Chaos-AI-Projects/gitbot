#!/usr/bin/env python3
"""
Automation script to process .done files and run github_fetcher.py on specified repositories.

This script implements the requirements from issue #1:
1. List files in a directory
2. For filename in format username_repo-yyyymmdd-hhMMss.done, run github_fetcher.py for username/repo
   and since yyyymmdd-hhMMss, output written to username_repo-$newdatetime
3. Move the old .done file to an archive directory (only if meaningful data was fetched)
4. Get github token from .env from the same directory of this script

Enhanced per issue #3:
- Accepts a directory argument to process .done files from a specific directory
- Reads .env from the same directory as the script (not current working directory)
"""

import os
import sys
import json
import shutil
from datetime import datetime
import re
import subprocess
from pathlib import Path


def load_env_file(env_path):
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


def has_meaningful_data(data):
    """
    Check if the fetched data contains meaningful information (issues, comments, etc.).

    Args:
        data: The parsed JSON data from github_fetcher.py

    Returns:
        bool: True if there are issues, issue_comments, or pull_request_comments
    """
    issues_count = len(data.get('issues', []))
    issue_comments_count = len(data.get('issue_comments', []))
    pr_comments_count = len(data.get('pull_request_comments', []))

    return (issues_count > 0 or issue_comments_count > 0 or pr_comments_count > 0)


def main():
    # Handle command line arguments
    import argparse

    parser = argparse.ArgumentParser(
        description='Process .done files and fetch GitHub data for specified repositories.'
    )
    parser.add_argument(
        'directory',
        nargs='?',
        default='.',
        help='Directory to search for .done files (default: current directory)'
    )

    args = parser.parse_args()

    # Get the directory where this script is located (for .env file)
    script_dir = Path(__file__).parent.absolute()
    env_path = script_dir / '.env'

    # Load environment variables from .env file in script directory
    env_vars = load_env_file(env_path)
    github_token = env_vars.get('GITHUB_TOKEN')

    if not github_token:
        print("Error: GITHUB_TOKEN not found in .env file", file=sys.stderr)
        print(f"Looked for .env file at: {env_path}", file=sys.stderr)
        sys.exit(1)

    # Set up directories
    target_dir = Path(args.directory).resolve()
    if not target_dir.is_dir():
        print(f"Error: Directory '{args.directory}' does not exist", file=sys.stderr)
        sys.exit(1)

    archive_dir = target_dir / 'archive'
    archive_dir.mkdir(exist_ok=True)

    # Find all .done files in the specified directory
    done_files = list(target_dir.glob('*.done'))

    if not done_files:
        print(f"No .done files found to process in directory: {target_dir}")
        return

    print(f"Found {len(done_files)} .done file(s) to process in directory: {target_dir}")
    print(f"Loading .env file from: {env_path}")

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
        # Using current timestamp for the output file (local time for human readability)
        output_timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        output_filename = f"{username}_{repo}-{output_timestamp}.json"
        output_path = target_dir / output_filename

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

            # Read and parse the output to check if it contains meaningful data
            with open(output_path, 'r') as f:
                output_data = json.load(f)

            if has_meaningful_data(output_data):
                print(f"  Successfully fetched meaningful data for {repo_full}")
                print(f"  Output saved to: {output_filename}")

                # Move the .done file to archive only if we got meaningful data
                archive_path = archive_dir / done_file.name
                shutil.move(str(done_file), str(archive_path))
                print(f"  Moved {done_file.name} to archive/")
            else:
                print(f"  No meaningful data found for {repo_full} (no issues/comments)")
                print(f"  Removing empty output file: {output_filename}")
                # Remove the output file since it contains no meaningful data
                output_path.unlink()
                # Do NOT archive the .done file since no meaningful data was fetched
                print(f"  Kept {done_file.name} in place (no archive)")

        except subprocess.CalledProcessError as e:
            print(f"  Error processing {done_file.name}:", file=sys.stderr)
            print(f"  Exit code: {e.returncode}", file=sys.stderr)
            print(f"  stderr: {e.stderr}", file=sys.stderr)
            # Clean up output file if it exists
            if output_path.exists():
                output_path.unlink()
        except json.JSONDecodeError as e:
            print(f"  Error parsing JSON output for {done_file.name}: {e}", file=sys.stderr)
            # Clean up output file if it exists
            if output_path.exists():
                output_path.unlink()
        except Exception as e:
            print(f"  Unexpected error processing {done_file.name}: {e}", file=sys.stderr)
            # Clean up output file if it exists
            if output_path.exists():
                output_path.unlink()


if __name__ == '__main__':
    main()