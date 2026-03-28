#!/usr/bin/env python3
"""
Script to invoke Claude CLI on GitHub activity JSON files produced by github_fetcher.py.

Claude autonomously acts on the activity — implementing tasks, responding to PR feedback,
creating task breakdowns, and requesting human input when needed. After Claude finishes,
the JSON file is renamed to .done to prevent re-processing.
"""

import sys
import subprocess
import argparse
from pathlib import Path


def build_prompt(json_path: str, repo_dir: str) -> str:
    """
    Construct the prompt that instructs Claude to process a GitHub activity JSON file.

    Args:
        json_path: Absolute path to the JSON file from github_fetcher.py
        repo_dir: Absolute path to the repository working directory

    Returns:
        The prompt string to pass to Claude CLI
    """
    return f"""You are an autonomous GitHub agent. Your task is to process recent GitHub activity and take appropriate action.

## Input

Read the JSON file at: {json_path}

This file was produced by github_fetcher.py and contains recent issues, issue comments, and pull request comments for a repository. The JSON has a `repository` field with the owner/repo name.

## Current State

After reading the JSON, run these commands to understand the current repo state:
- `gh issue list --state open` to see open issues
- `gh pr list --state open` to see open PRs
- `git log --oneline -10` to see recent commits
- `git branch -a` to see branches

## Processing Rules (in priority order)

Process each item from the JSON according to these rules. Work through them in priority order:

### Rule 1: Implement task issues
If an issue has the label "task" AND its body or any comment contains "@claude implement":
1. Create a feature branch from master with a descriptive name (e.g., `feature/issue-N-short-description`)
2. Implement the requested changes
3. Commit with a clear message referencing the issue number
4. Push the branch and create a PR with `gh pr create`
5. Comment on the issue that work has started with a link to the PR

### Rule 2: Respond to PR review comments
If there are review comments on open PRs:
1. Check out the PR branch
2. Address the review feedback by making the requested changes
3. Commit and push the improvements
4. Reply to each review comment explaining what was changed

### Rule 3: Create task breakdown for other issues
If an issue does NOT have the "task" label and is not something you can directly implement:
1. Analyze the issue and create a plan
2. Comment on the issue with a structured task breakdown
3. Do NOT attempt to implement — just plan

### Rule 4: Request clarification
If an issue or comment is ambiguous or unclear:
1. Comment on the issue asking specific clarifying questions
2. Do NOT attempt to implement anything

## Important Rules

- **Prefix all GitHub content you create** (issue comments, PR descriptions, review replies) with `%claude` on the first line so humans can identify agent-generated content.
- **Skip any content that starts with `%claude`** — this was created by a previous agent run, do not process it again.
- **Git workflow**: Always branch from master. Use descriptive branch names. Never commit directly to master.
- **Be conservative**: If unsure, ask for clarification (Rule 4) rather than making assumptions.
- **One thing at a time**: Process the most important item fully before moving to the next.
- If there is nothing actionable in the JSON (no new issues, no review comments needing response), just say so and exit.
"""


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

    Args:
        json_path: Path to the JSON file

    Returns:
        The new path with .done extension
    """
    path = Path(json_path)
    done_path = path.with_suffix('.done')
    path.rename(done_path)
    return done_path


def main():
    parser = argparse.ArgumentParser(
        description='Invoke Claude CLI to act on GitHub activity from a JSON file.'
    )
    parser.add_argument(
        'json_file',
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

    args = parser.parse_args()

    # Resolve paths
    json_path = Path(args.json_file).resolve()
    if not json_path.exists():
        print(f"Error: File not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    if not json_path.suffix == '.json':
        print(f"Error: Expected a .json file, got: {json_path.name}", file=sys.stderr)
        sys.exit(1)

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

    # Verify we are on main or master branch
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=str(repo_dir), capture_output=True, text=True, check=True,
        )
        current_branch = result.stdout.strip()
        if current_branch not in ('main', 'master'):
            print(f"Error: Must be on main or master branch, currently on '{current_branch}'", file=sys.stderr)
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to determine git branch: {e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Build the prompt
    prompt = build_prompt(str(json_path), str(repo_dir))

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

    # Rename JSON to .done regardless of exit code (prevents re-processing)
    done_path = rename_json_to_done(str(json_path))
    print(f"Renamed {json_path.name} → {done_path.name}")


if __name__ == '__main__':
    main()
