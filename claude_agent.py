#!/usr/bin/env python3
"""
Script to invoke Claude CLI on GitHub activity JSON files produced by github_fetcher.py.

Claude autonomously acts on the activity — implementing tasks, responding to PR feedback,
creating task breakdowns, and requesting human input when needed. After Claude finishes,
the JSON file is renamed to .done to prevent re-processing.
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path


def build_resume_prompt(timeout_file: str, repo_dir: str, default_branch: str = 'master') -> str:
    """
    Construct a prompt that instructs Claude to resume a previously timed-out task.

    Reads the timeout metadata file and the original JSON file (if still present)
    to build a prompt that asks Claude to attempt resumption.

    Args:
        timeout_file: Absolute path to the .timeout metadata file
        repo_dir: Absolute path to the repository working directory
        default_branch: The default git branch name

    Returns:
        The prompt string to pass to Claude CLI
    """
    timeout_path = Path(timeout_file)
    metadata = {}
    for line in timeout_path.read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            metadata[key.strip()] = value.strip()

    json_filename = metadata.get('json_file', 'unknown')
    timestamp = metadata.get('timestamp', 'unknown')
    timeout_seconds = metadata.get('timeout_seconds', 'unknown')

    # Try to find the original JSON file for context
    json_path = timeout_path.parent / json_filename
    json_context = ''
    if json_path.exists():
        json_context = (
            f'\n\nThe original JSON file is still available at: {json_path}\n'
            f'Read it to understand what task was being worked on.'
        )
    else:
        done_path = json_path.with_suffix('.done')
        if done_path.exists():
            json_context = (
                f'\n\nThe original JSON was already processed and renamed to: {done_path}\n'
                f'Read it to understand what task was being worked on.'
            )

    return f"""You are an autonomous GitHub agent resuming a previously timed-out task.

## Context

A previous agent run was killed due to timeout:
- **Timed out at**: {timestamp}
- **Timeout limit**: {timeout_seconds} seconds
- **Original JSON file**: {json_filename}{json_context}

## Current State

Run these commands to understand the current repo state:
- `gh issue list --state open` to see open issues
- `gh pr list --state open` to see open PRs
- `git log --oneline -10` to see recent commits
- `git branch -a` to see branches
- `git status` to check for any in-progress work from the timed-out run

## Instructions

1. Investigate what the previous agent was working on (check branches, partial commits, open PRs, issue comments)
2. Determine whether the task was partially completed
3. If the task can be resumed, continue from where it left off and complete it
4. If the task cannot be resumed (e.g., conflicts, unclear state), comment on the relevant issue explaining what happened and what needs to be done

## Important Rules

- **Prefix all GitHub content you create** (issue comments, PR descriptions, review replies) with `%claude` on the first line.
- **Skip any content that starts with `%claude`** — this was created by a previous agent run.
- **Git workflow**: Always branch from {default_branch}. Use descriptive branch names. Never commit directly to {default_branch}.
- **Do NOT rename, move, or delete the timeout file or JSON file.** Their lifecycle is managed externally.
"""


def build_prompt(json_path: str, repo_dir: str, default_branch: str = 'master') -> str:
    """
    Construct the prompt that instructs Claude to process a GitHub activity JSON file.

    Reads the prompt template from prompt_template.md located next to this script
    and substitutes placeholders with the provided values.

    Args:
        json_path: Absolute path to the JSON file from github_fetcher.py
        repo_dir: Absolute path to the repository working directory
        default_branch: The default git branch name

    Returns:
        The prompt string to pass to Claude CLI
    """
    template_path = Path(__file__).resolve().parent / 'prompt_template.md'
    template = template_path.read_text()
    return template.format(json_path=json_path, repo_dir=repo_dir,
                           default_branch=default_branch)


def invoke_claude(prompt: str, workdir: str, model: str = None) -> int:
    """
    Run the Claude CLI with the given prompt.

    Args:
        prompt: The prompt to send to Claude
        workdir: Working directory for the Claude process
        model: Optional model override

    Returns:
        The exit code from the Claude CLI process
    """
    cmd = ['claude', '-p', '--dangerously-skip-permissions']

    if model:
        cmd.extend(['--model', model])

    result = subprocess.run(
        cmd,
        input=prompt,
        cwd=workdir,
        text=True,
    )

    return result.returncode


def rename_json_to_done(json_path: str) -> Path:
    """
    Rename a .json file to .done to mark it as processed.

    If the JSON file has already been moved (e.g., by the Claude agent subprocess),
    creates a .done marker file and archives all other files in the same
    directory so the next processing round can proceed cleanly.

    Args:
        json_path: Path to the JSON file

    Returns:
        The new path with .done extension
    """
    path = Path(json_path)
    done_path = path.with_suffix('.done')
    try:
        path.rename(done_path)
    except FileNotFoundError:
        print(f"Warning: {path.name} already moved, creating {done_path.name} marker",
              file=sys.stderr)
        done_path.touch()
        # Move other files to archive so they are not reprocessed
        archive_dir = path.parent / 'archive'
        archive_dir.mkdir(exist_ok=True)
        for other in path.parent.iterdir():
            if other == done_path or other == archive_dir or other.name.startswith('.'):
                continue
            shutil.move(str(other), str(archive_dir / other.name))
            print(f"  Archived {other.name}", file=sys.stderr)
    return done_path


def main():
    parser = argparse.ArgumentParser(
        description='Invoke Claude CLI to act on GitHub activity from a JSON file.'
    )
    parser.add_argument(
        'json_file',
        nargs='?',
        default=None,
        help='Path to JSON file produced by github_fetcher.py'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print the prompt without invoking Claude'
    )
    parser.add_argument(
        '--model',
        default=None,
        help='Override the Claude model to use'
    )
    parser.add_argument(
        '--repo-dir',
        default=None,
        help='Repository directory for Claude to work in (default: current working directory)'
    )
    parser.add_argument(
        '--resume-timeout',
        default=None,
        help='Path to a .timeout file to resume a previously timed-out task'
    )
    args = parser.parse_args()

    if not args.json_file and not args.resume_timeout:
        parser.error('Either json_file or --resume-timeout is required')

    # Determine repo directory (default: current working directory)
    if args.repo_dir:
        repo_dir = Path(args.repo_dir).resolve()
    else:
        repo_dir = Path.cwd().resolve()

    if not repo_dir.is_dir():
        print(f"Error: Repository directory not found: {repo_dir}", file=sys.stderr)
        sys.exit(1)

    # Verify repo_dir is the top of a git repository
    if not (repo_dir / '.git').exists():
        print(f"Error: {repo_dir} is not the top of a git repository (no .git directory)", file=sys.stderr)
        sys.exit(1)

    # Require the default branch to be specified via environment variable
    default_branch = os.environ.get('GITBOT_DEFAULT_BRANCH', '')
    if not default_branch:
        print("Error: GITBOT_DEFAULT_BRANCH environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    # Verify we are on the default branch
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=str(repo_dir), capture_output=True, text=True, check=True,
        )
        current_branch = result.stdout.strip()
        if current_branch != default_branch:
            print(f"Error: Must be on {default_branch} branch, currently on '{current_branch}'", file=sys.stderr)
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to determine git branch: {e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Handle --resume-timeout mode
    if args.resume_timeout:
        timeout_path = Path(args.resume_timeout).resolve()
        if not timeout_path.exists():
            print(f"Error: Timeout file not found: {timeout_path}", file=sys.stderr)
            sys.exit(1)

        prompt = build_resume_prompt(str(timeout_path), str(repo_dir),
                                     default_branch=default_branch)

        if args.dry_run:
            print("=== DRY RUN — Resume prompt that would be sent to Claude ===\n")
            print(prompt)
            print(f"\n=== Working directory: {repo_dir} ===")
            return

        print(f"Resuming timed-out task from {timeout_path.name} in {repo_dir}...")
        if args.model:
            print(f"Using model: {args.model}")

        exit_code = invoke_claude(prompt, str(repo_dir), model=args.model)
        print(f"\nClaude exited with code: {exit_code}")

        if exit_code == 0:
            # Parse the original JSON filename from the timeout metadata
            metadata = {}
            for line in timeout_path.read_text().splitlines():
                if '=' in line:
                    key, value = line.split('=', 1)
                    metadata[key.strip()] = value.strip()

            # Rename original JSON to .done if it still exists
            json_filename = metadata.get('json_file')
            if json_filename:
                original_json = timeout_path.parent / json_filename
                if original_json.exists():
                    done_path = rename_json_to_done(str(original_json))
                    print(f"Renamed {original_json.name} → {done_path.name}")

            # Remove the timeout file
            timeout_path.unlink()
            print(f"Removed timeout file: {timeout_path.name}")
        else:
            print(f"Warning: Resume exited with code {exit_code}, "
                  f"keeping {timeout_path.name} for retry.", file=sys.stderr)
            sys.exit(exit_code)
        return

    # Normal mode: process a JSON file
    json_path = Path(args.json_file).resolve()
    if not json_path.exists():
        print(f"Error: File not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    if json_path.suffix != '.json':
        print(f"Error: Expected a .json file, got: {json_path.name}", file=sys.stderr)
        sys.exit(1)

    # Build the prompt
    prompt = build_prompt(str(json_path), str(repo_dir), default_branch=default_branch)

    if args.dry_run:
        print("=== DRY RUN — Prompt that would be sent to Claude ===\n")
        print(prompt)
        print(f"\n=== Working directory: {repo_dir} ===")
        if args.model:
            print(f"=== Model: {args.model} ===")
        return

    # Invoke Claude
    print(f"Invoking Claude on {json_path.name} in {repo_dir}...")
    if args.model:
        print(f"Using model: {args.model}")

    exit_code = invoke_claude(prompt, str(repo_dir), model=args.model)
    print(f"\nClaude exited with code: {exit_code}")

    if exit_code != 0:
        print(f"Warning: Claude exited with non-zero code {exit_code}, "
              f"leaving {json_path.name} for retry.", file=sys.stderr)
        sys.exit(exit_code)

    done_path = rename_json_to_done(str(json_path))
    print(f"Renamed {json_path.name} → {done_path.name}")


if __name__ == '__main__':
    main()
