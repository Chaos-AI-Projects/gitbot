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
pip install git+https://<PUBLIC_REPO_URL>.git
```

This installs three console commands:
- `gitbot-fetch` — fetch GitHub activity (wraps `github_fetcher.py`)
- `gitbot-process` — process `.done` trigger files (wraps `process_event_file.py`)
- `gitbot-agent` — invoke Claude on fetched activity (wraps `claude_agent.py`)

### Requirements

- Python 3.7+
- [GitHub CLI (`gh`)](https://cli.github.com/) — authenticated, used for all GitHub API access
- [Claude CLI (`claude`)](https://docs.anthropic.com/en/docs/claude-code) — for the agent script

## Usage

### `gitbot-fetch` — Fetch GitHub Activity

```bash
gitbot-fetch <owner/repo> <since-timestamp> [options]
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
gitbot-fetch torvalds/linux 2026-03-01

# Fetch only issues
gitbot-fetch torvalds/linux "2026-03-15 10:30:00" --issues-only

# Fetch comments and save to file
gitbot-fetch torvalds/linux 2026-03-10 --comments-only --output comments.json
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

### `gitbot-process` — Automate Fetching

```bash
gitbot-process [directory]
```

This script processes `.done` trigger files to automatically run `gitbot-fetch`:

1. Scans the specified directory (default: current directory) for `.done` files
2. Parses filenames matching `username_repo-yyyymmdd-hhMMss.done`
3. Runs `gitbot-fetch` for each matched file
4. Writes output to `username_repo-YYYYMMDD-HHMMSS.json` (using local time in filenames for readability)
5. Only moves `.done` files to `archive/` if meaningful data was fetched (issues, comments, or PR comments)
6. Removes empty output files to avoid clutter

**Notes:**
- Converts local timestamps from `.done` filenames to UTC for the GitHub API

### `gitbot-agent` — Invoke Claude on GitHub Activity

```bash
gitbot-agent <json_file> [--dry-run] [--model MODEL] [--repo-dir DIR]
```

Takes a JSON file produced by `gitbot-fetch` and invokes Claude CLI to autonomously act on the activity.

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

### 3. Install GitBot

```bash
pip install git+https://<PUBLIC_REPO_URL>.git
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
while sleep 300; do
  gitbot-process .jobs/
  ls .jobs/*.json 2>/dev/null && (
    git checkout master
    git pull
    for i in .jobs/*.json; do gitbot-agent "$i"; done
  )
done
```

This loop:
- Polls every 5 minutes (300 seconds)
- Fetches new GitHub activity via `gitbot-process`
- If any `.json` files were produced, checks out master, pulls latest, and runs the agent on each one
- The agent processes the activity and renames `.json` to `.done` when finished

## License

MIT — see [LICENSE](LICENSE) for details.
