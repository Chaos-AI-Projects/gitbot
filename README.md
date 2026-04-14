# GitBot — Automated GitHub Agent

GitBot is a pipeline that fetches GitHub activity (issues, comments, PR reviews) and feeds it to a Claude-powered agent that autonomously acts on it — implementing tasks, responding to reviews, creating task breakdowns, and requesting clarification when needed.

## Why GitBot?

### Cost-efficient automation

Many AI-powered automation tools keep an LLM running continuously or trigger it on every webhook event, which leads to high token consumption — even when nothing meaningful has happened. GitBot takes a different approach:

- **Poll-based architecture** — GitBot fetches GitHub activity on a schedule and only invokes Claude when there is actual new activity to process. No wasted LLM calls when nothing has changed.
- **Event-driven, not speculative** — Claude is called only on concrete, actionable items (new issues, review comments), never speculatively. This significantly reduces token usage compared to always-on agents.
- **Simple state management** — The `.done` file mechanism provides file-based state tracking without requiring a database or webhook infrastructure. Easy to inspect, easy to debug.
- **Cost-effective for real-world repos** — Most repositories have intermittent activity. GitBot's design means you only pay for tokens when there's genuine work to do.

### Trackable prompts for vibe coding

As vibe coding scales, reviewing and tracking the prompts humans give to AI agents becomes as important as reviewing the code itself. In a chat interface, prompts and context disappear after each session, making it difficult to review what was asked and why. By routing AI-assisted work through GitHub issues and comments, every human prompt becomes a trackable, reviewable artifact — with timestamps, authorship, and threading built in. This makes GitBot a natural fit for workflows where auditing and iterating on human-to-agent interaction matters.

### Comparison with GitHub Actions + Claude

An alternative approach is to run Claude directly inside GitHub Actions, triggered by webhooks on issue or PR events. Here's how GitBot compares:

| | **GitBot (poll-based)** | **GitHub Actions + Claude** |
|---|---|---|
| **Trigger model** | Polls on a schedule; batches activity | Fires on every webhook event |
| **Token usage** | Low — Claude is invoked only when there's real work | Higher — every event triggers a full LLM invocation, including noisy ones (label changes, assignment, etc.) |
| **Infrastructure** | Runs anywhere (local machine, VM, server) | Tied to GitHub-hosted or self-hosted runners |
| **State management** | Simple `.done` files; easy to inspect and retry | Stateless by default; needs external storage for cross-run state |
| **Rate / cost control** | Natural batching reduces API calls; easy to tune poll interval | Requires careful workflow filtering to avoid runaway costs |
| **Debugging** | Local logs, local files; straightforward | Scattered across workflow run logs; harder to reproduce locally |
| **Privacy** | Code and prompts stay on your machine | Code and prompts pass through GitHub's runner environment |

In short, GitHub Actions is a good fit when you need instant reaction to every event and are already invested in Actions infrastructure. GitBot is better when you want cost-efficient, self-hosted automation that only invokes the LLM when there's meaningful work — which is most repositories most of the time.

## Usage

Get GitBot running in 5 steps.

### Step 1: Install GitBot

Clone the repository and install Python dependencies. You also need the GitHub CLI (`gh`) and Claude CLI (`claude`).

```bash
git clone https://github.com/ChaosEternal/gitbot.git
cd gitbot
pip install -r requirements.txt
```

Verify the prerequisites are available:

```bash
gh auth status    # GitHub CLI — install from https://cli.github.com/
claude --version  # Claude Code — install from https://docs.anthropic.com/en/docs/claude-code
```

### Step 2: Prepare a GitHub repo and clone it

Create a new **private** repository where the agent will operate, or clone an existing one.

> **Important:** The repository should be private. GitBot reacts to any issues and comments it finds, so a public repo will cause the bot to respond to activity from anyone.

```bash
# Option A: Create a new private repo
gh repo create my-project --private --clone
cd my-project

# Option B: Clone an existing repo (make sure it's private)
gh repo clone owner/existing-repo
cd existing-repo
```

### Step 3: Create a `.jobs` directory and initial `.done` file

Inside the cloned repo, create the `.jobs` directory and a `.done` file. The timestamp in the filename tells GitBot how far back to look for activity — use a time before the earliest issue you want processed.

```bash
mkdir .jobs
touch .jobs/owner_repo-$(date +%Y%m%d-%H%M%S).done
```

Replace `owner_repo` with the target repository using an underscore as separator (e.g., `ChaosEternal_gitbot`).

Optionally, add `.jobs` to your `.gitignore` to keep job files out of version control:

```bash
echo '.jobs/' >> .gitignore
```

### Step 4: Run `gitbot-run.sh`

From the top directory of your cloned repo, start the automation loop:

```bash
/path/to/gitbot/gitbot-run.sh .jobs/
```

Or with options:

```bash
/path/to/gitbot/gitbot-run.sh .jobs/ --branch main --interval 600
```

GitBot will now poll for new GitHub activity and invoke Claude whenever there is work to do.

### Step 5: Create an issue and watch Claude respond

Create an issue in your repository. The bot responds differently depending on what it finds:

- **Normal issues or comments** — the bot will analyze the issue and reply with a structured task breakdown or ask clarifying questions.
- **Task issues** — if an issue has the `task` label and a comment containing `@claude implement`, the bot will create a feature branch, implement the request, and open a pull request.
- **PR review comments** — responding to an open PR will cause the bot to address the feedback, push fixes, and reply to each comment.

Wait for the next poll cycle and Claude will pick up the new activity automatically.

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

## Reference

Detailed documentation for each script.

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

### `gitbot-run.sh` — Main Automation Loop

```bash
./gitbot-run.sh [jobs_dir] [--branch BRANCH] [--interval SECONDS]
```

Wraps the entire pipeline into a single polling loop.

**Arguments:**
- `jobs_dir` (optional): Directory containing `.done`/`.json` files (default: `.jobs`)

**Options:**
- `--branch BRANCH`: Override the default git branch (default: auto-detect from `origin/HEAD`)
- `--interval SECONDS`: Poll interval in seconds (default: 300)
- `-h, --help`: Show help message

**Behavior:**
- Runs pre-flight checks (verifies `gh`, `claude`, and the Python scripts are available)
- Auto-detects the default branch (or uses `--branch`), exports it as `GITBOT_DEFAULT_BRANCH`
- Polls every N seconds (default: 300)
- Fetches new GitHub activity via `process_event_file.py`
- If any `.json` files were produced, checks out the default branch, pulls latest, and runs the agent on each one
- Handles `Ctrl-C` / `SIGTERM` for clean shutdown
- Logs with timestamps

## License

MIT — see [LICENSE](LICENSE) for details.
