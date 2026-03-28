# GitBot — Automated GitHub Agent

GitBot is a pipeline that fetches GitHub activity (issues, comments, PR reviews) and feeds it to a Claude-powered agent that autonomously acts on it — implementing tasks, responding to reviews, creating task breakdowns, and requesting clarification when needed.

## How It Works

```
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  github_fetcher.py  │────▶│ process_event_file.py│────▶│   claude_agent.py   │
│  Fetch issues, PR   │     │ Automate fetch/archive│     │ Claude acts on the  │
│  comments from API  │     │ via .done files       │     │ GitHub activity     │
└─────────────────────┘     └──────────────────────┘     └─────────────────────┘
```

1. **`github_fetcher.py`** — Fetches issues, issue comments, and PR review comments from the GitHub API since a given timestamp.
2. **`process_event_file.py`** — Processes `.done` trigger files to automate fetching and archiving results.
3. **`claude_agent.py`** — Feeds the fetched JSON to Claude CLI, which autonomously acts on the activity.

## Setup

### Requirements

- Python 3.6+
- [GitHub CLI (`gh`)](https://cli.github.com/) — for the agent to interact with GitHub
- [Claude CLI (`claude`)](https://docs.anthropic.com/en/docs/claude-code) — for the agent script

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root with your GitHub token:

```
GITHUB_TOKEN=your_token_here
```

This token needs at minimum `repo` scope for private repositories or `public_repo` for public ones. Without a token, public repos can still be accessed but with stricter rate limits (60 vs 5,000 requests/hour).

## Usage

### `github_fetcher.py` — Fetch GitHub Activity

```bash
python3 github_fetcher.py <owner/repo> <since-timestamp> [options]
```

**Arguments:**
- `repo`: GitHub repository in `owner/repo` format (e.g., `torvalds/linux`)
- `since`: Fetch data newer than this timestamp (formats: `YYYY-MM-DD`, `YYYY-MM-DD HH:MM:SS`, or ISO format)

**Options:**
- `-o, --output`: Output file path (default: stdout)
- `-t, --token`: GitHub personal access token (can also use `GITHUB_TOKEN` env var)
- `--issues-only`: Fetch only issues (not comments)
- `--comments-only`: Fetch only comments (both issue and PR comments)

**Examples:**

```bash
# Fetch all data newer than March 1, 2026
python3 github_fetcher.py torvalds/linux 2026-03-01

# Fetch only issues
python3 github_fetcher.py torvalds/linux "2026-03-15 10:30:00" --issues-only

# Fetch comments and save to file
python3 github_fetcher.py torvalds/linux 2026-03-10 --comments-only --output comments.json

# With GitHub token
export GITHUB_TOKEN=your_token_here
python3 github_fetcher.py torvalds/linux 2026-03-01
```

**Notes:**
- Filters to only open issues (closed issues are skipped)
- Uses UTC timestamps consistently for all GitHub API interactions

**Output format (JSON):**
- `issues`: Array of issue objects (excluding pull requests)
- `issue_comments`: Array of issue comment objects
- `pull_request_comments`: Array of PR review comment objects
- `fetched_at`: Timestamp when data was fetched
- `repository`: The repository that was queried
- `since`: The since timestamp used for filtering

### `process_event_file.py` — Automate Fetching

```bash
python3 process_event_file.py [directory]
```

This script processes `.done` trigger files to automatically run `github_fetcher.py`:

1. Scans the specified directory (default: current directory) for `.done` files
2. Parses filenames matching `username_repo-yyyymmdd-hhMMss.done`
3. Runs `github_fetcher.py` for each matched file
4. Writes output to `username_repo-YYYYMMDD-HHMMSS.json` (using local time in filenames for readability)
5. Only moves `.done` files to `archive/` if meaningful data was fetched (issues, comments, or PR comments)
6. Removes empty output files to avoid clutter

**Notes:**
- Reads `.env` from the script's own directory, not the current working directory
- Converts local timestamps from `.done` filenames to UTC for the GitHub API

### `claude_agent.py` — Invoke Claude on GitHub Activity

```bash
python3 claude_agent.py <json_file> [--dry-run] [--model MODEL] [--repo-dir DIR]
```

Takes a JSON file produced by `github_fetcher.py` and invokes Claude CLI to autonomously act on the activity.

**Options:**
- `--dry-run`: Print the prompt without invoking Claude
- `--model MODEL`: Override the Claude model
- `--repo-dir DIR`: Set the working directory for Claude (default: current directory; must be a git repo root on main/master branch)

**Processing rules (in priority order):**

| Priority | Trigger | Action |
|----------|---------|--------|
| 1 | Issue has label `task` + comment `@claude implement` | Create branch, implement, open PR |
| 2 | PR review comments on open PRs | Address feedback, push fixes |
| 3 | Other issues (no `task` label) | Comment with task breakdown |
| 4 | Ambiguous items | Comment asking for clarification |

**Conventions:**
- All agent-created GitHub content is prefixed with `%claude` on the first line
- Content starting with `%claude` is skipped on subsequent runs to avoid re-processing
- After completion, the JSON file is renamed to `.done` to prevent re-processing

## End-to-End Workflow

A typical automated run looks like this:

```bash
# 1. Create a trigger file (or let your scheduler do it)
touch ChaosEternal_gitbot-20260328-100000.done

# 2. Process trigger files — fetches GitHub activity
python3 process_event_file.py ./jobs

# 3. Run the agent on the fetched JSON
python3 claude_agent.py ./jobs/ChaosEternal_gitbot-20260328-161027.json --repo-dir /path/to/repo
```

## Dependencies

- `requests` (>=2.25.1) — HTTP calls to the GitHub API
- `python-dateutil` (>=2.8.0) — Date parsing

Install with:
```bash
pip install -r requirements.txt
```
