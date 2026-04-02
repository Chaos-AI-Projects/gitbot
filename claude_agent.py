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

    Reads the prompt template from prompt_template.md (located next to this script)
    and substitutes placeholders with the provided values.

    Args:
        json_path: Absolute path to the JSON file from github_fetcher.py
        repo_dir: Absolute path to the repository working directory

    Returns:
        The prompt string to pass to Claude CLI
    """
    # Look for template next to this script first (dev), then in installed data location
    template_path = Path(__file__).resolve().parent / 'prompt_template.md'
    if not template_path.exists():
        template_path = Path(sys.prefix) / 'share' / 'gitbot' / 'prompt_template.md'
    template = template_path.read_text()
    return template.format(json_path=json_path, repo_dir=repo_dir)


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
