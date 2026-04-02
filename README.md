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

## Installation

```bash
git clone https://github.com/ChaosEternal/gitbot.git
cd gitbot
pip install -r requirements.txt
```

### Requirements

- Python 3.7+
- [GitHub CLI (`gh`)](https://cli.github.com/) — authenticated, used for all GitHub API access
- [Claude CLI (`claude`)](https://docs.anthropic.com/en/docs/claude-code) — for the agent script

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

## Automating the Whole Thing

Here's how to set up GitBot to run continuously on a target repository.

### 1. Install and configure `gh` CLI

Install the [GitHub CLI](https://cli.github.com/) and authenticate:

```bash
gh auth login
```

Make sure your token has these scopes:
- Read/write issues and comments
- Read/create/update pull requests

### 2. Install and configure Claude CLI

Install [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and make sure it's authenticated and working:

```bash
claude --version
```

### 3. Clone GitBot and install dependencies

```bash
git clone https://github.com/ChaosEternal/gitbot.git
pip install -r gitbot/requirements.txt
```

### 4. Create a private working repo and clone it

Create a private repo on GitHub where the agent will operate, then clone it:

```bash
gh repo create my-project --private --clone
cd my-project
```

### 5. Create the `.jobs` directory and initial `.done` file

```bash
mkdir .jobs
touch .jobs/owner_repo-$(date +%Y%m%d-%H%M%S).done
```

Replace `owner_repo` with the target repo using underscore as separator (e.g., `torvalds_linux`).

### 6. Run the automation loop

```bash
/path/to/gitbot/gitbot-run.sh .jobs/
```

Or with options:

```bash
/path/to/gitbot/gitbot-run.sh .jobs/ --branch main --interval 600
```

**Arguments:**
- `jobs_dir` (optional): Directory containing `.done`/`.json` files (default: `.jobs`)
- `--branch BRANCH`: Override the default git branch (default: auto-detect from `origin/HEAD`)
- `--interval SECONDS`: Poll interval in seconds (default: 300)

The script:
- Runs pre-flight checks (verifies `gh`, `claude`, and the Python scripts are available)
- Auto-detects the default branch (or uses `--branch`), exports it as `GITBOT_DEFAULT_BRANCH`
- Polls every N seconds (default: 300)
- Fetches new GitHub activity via `process_event_file.py`
- If any `.json` files were produced, checks out the default branch, pulls latest, and runs the agent on each one
- Handles `Ctrl-C` / `SIGTERM` for clean shutdown
- Logs with timestamps

## License

MIT — see [LICENSE](LICENSE) for details.
