# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commit Convention
When committing changes via Claude Code, omit the Co-Authored-By line as specified in project preferences.

## Development Commands

### Installation
```bash
pip install -r requirements.txt
```

### Running the Scripts

#### Main GitHub Fetcher
Basic usage:
```bash
python3 github_fetcher.py <owner/repo> <since-timestamp>
```

Examples:
- Fetch all data newer than March 1, 2026:
  ```bash
  python3 github_fetcher.py torvalds/linux 2026-03-01
  ```

- Fetch only issues newer than March 15, 2026 at 10:30 AM:
  ```bash
  python3 github_fetcher.py torvalds/linux "2026-03-15 10:30:00" --issues-only
  ```

- Fetch comments and save to file:
  ```bash
  python3 github_fetcher.py torvalds/linux 2026-03-10 --comments-only --output comments.json
  ```

- With GitHub token (required for private repos, recommended for public to avoid rate limits):
  ```bash
  export GITHUB_TOKEN=your_token_here
  python3 github_fetcher.py torvalds/linux 2026-03-01
  ```

#### Key Improvements in GitHub Fetcher:
- **Filters to only open issues** (skips closed issues as requested in issue #5)
- **Uses UTC timestamps consistently** for all GitHub API interactions
- **process_event_file.py converts local time from .done files to UTC** for GitHub API calls
- **Output filenames in process_event_file.py use local time** for better human readability (as requested in PR feedback)

#### Automation Script (process_event_file.py)
Process .done files to automatically fetch GitHub data:
```bash
python3 process_event_file.py [directory]
```

This script:
1. Lists files in the specified directory (or current directory if none specified)
2. Processes files matching `username_repo-yyyymmdd-hhMMss.done` format
3. Runs github_fetcher.py for each matched file
4. Writes output to `username_repo-YYYYMMDD-HHMMSS.json` (using UTC time)
5. **Only moves .done files to archive if meaningful data was fetched** (issues, comments, or PR comments)
6. **Removes output file if no meaningful data was found** (to avoid clutter)
7. **Accepts an optional directory argument** to process .done files from a specific directory
8. Locates `github_fetcher.py` relative to its own directory

#### Claude Agent Script (claude_agent.py)
Invoke Claude CLI to autonomously act on GitHub activity:
```bash
python3 claude_agent.py <json_file> [--dry-run] [--model MODEL] [--repo-dir DIR]
```

This script:
1. Takes a JSON file produced by `github_fetcher.py`
2. Builds a prompt from `prompt_template.md` (template file with `{json_path}`, `{repo_dir}`, and `{default_branch}` placeholders)
3. Invokes `claude -p` with all tools available
4. Claude reads the JSON, identifies actionable items, and acts according to priority rules:
   - **Task issues** (label "task" + "@claude implement") → implement and create PR
   - **PR review comments** → address feedback and push fixes
   - **Other issues** → create task breakdown comment
   - **Ambiguous items** → ask for clarification
5. All agent-created GitHub content is prefixed with `%claude`
6. Renames the JSON file to `.done` after completion (prevents re-processing)

Options:
- `--dry-run`: Print the prompt without invoking Claude
- `--model MODEL`: Override the Claude model
- `--repo-dir DIR`: Set the working directory for Claude (default: current working directory; must be git repo root on default branch)

Environment variables:
- `GITBOT_DEFAULT_BRANCH`: Override the default branch name (auto-detected if not set). Set automatically by `gitbot-run.sh`.

#### Automation Script (gitbot-run.sh)
Main automation loop that wraps the entire pipeline:
```bash
./gitbot-run.sh [jobs_dir] [--branch BRANCH] [--interval SECONDS]
```

This script:
1. Runs pre-flight checks (`gh`, `claude`, and Python scripts in the same directory)
2. Auto-detects the default git branch (or accepts `--branch` override)
3. Exports `GITBOT_DEFAULT_BRANCH` for downstream tools
4. Polls for new GitHub activity at the specified interval
5. Fetches activity via `process_event_file.py`, then runs `claude_agent.py` on each JSON result
6. Handles SIGINT/SIGTERM for clean shutdown

#### History Generator (generate_history.py)
Generate a chronological Markdown history of a GitHub repository:
```bash
python3 generate_history.py <owner/repo> [-o OUTPUT] [--since TIMESTAMP] [--append]
```

This standalone script:
1. Fetches all issues, issue comments, PR events, and PR comments via `gh` CLI
2. Merges all events into a single chronological timeline
3. Renders as Markdown with `##` headings per event and comments in fenced code blocks

Examples:
- Full history to stdout:
  ```bash
  python3 generate_history.py ChaosEternal/gitbot
  ```
- Incremental update since a date, appending to existing file:
  ```bash
  python3 generate_history.py ChaosEternal/gitbot --since 2026-04-01 -o HISTORY.md --append
  ```

### Working with Private Repositories
To access private repositories, you must provide a GitHub personal access token with appropriate permissions (at minimum, `repo` scope for private repos or `public_repo` for public repos):

```bash
export GITHUB_TOKEN=your_token_here
python3 github_fetcher.py private-owner/private-repo 2026-03-01
```

#### Using a .env File
While the scripts don't automatically load .env files, you can use one of these approaches:

1. **Manual export**:
   ```bash
   export GITHUB_TOKEN=your_token_here
   python3 github_fetcher.py <repo> <since>
   ```

2. **Source a .env file**:
   Create a `.env` file with:
   ```
   GITHUB_TOKEN=your_token_here
   ```
   Then load it:
   ```bash
   source .env
   python3 github_fetcher.py <repo> <since>
   ```

3. **Using direnv or similar tools** that automatically load environment variables

Without a token, the script will still work for public repositories but will be subject to GitHub's stricter rate limits for unauthenticated requests (60 requests/hour vs 5,000 requests/hour for authenticated requests).

### Testing
Run the script with different parameters to verify functionality:
```bash
# Test basic functionality
python3 github_fetcher.py <small-repo> 2026-03-01 --issues-only

# Test with output file
python3 github_fetcher.py <repo> 2026-03-01 --output test_output.json

# Test error handling
python3 github_fetcher.py invalid/repo 2026-03-01  # Should show error
python3 github_fetcher.py <repo> invalid-date       # Should show date parse error
```

## Code Architecture

### Main Components

1. **GitHubFetcher Class** (lines 16-170): Core functionality for interacting with GitHub API
   - Handles authentication via token or GITHUB_TOKEN environment variable
   - Manages API requests with automatic pagination
   - Provides methods to fetch issues, issue comments, and pull request comments
   - Includes rate limit awareness (warning when no token provided)

2. **Date Parsing** (lines 172-206): `parse_datetime_string()` function
   - Supports multiple date formats: YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, ISO format
   - Returns timezone-aware datetime objects (defaults to UTC)

3. **Main Execution** (lines 208-289): `main()` function
   - Parses command-line arguments using argparse
   - Routes to appropriate fetch methods based on flags
   - Handles JSON output formatting and file writing

### Key Features
- Automatic pagination handling for GitHub API responses
- Separation of concerns: issues vs issue comments vs PR comments
- Filtering to exclude pull requests from issues endpoint (GitHub includes them)
- Flexible output: stdout or file
- Proper error handling for API requests and date parsing
- Type hints throughout for better code clarity

### Data Flow
1. Command line arguments parsed in `main()`
2. Date string converted to timezone-aware datetime via `parse_datetime_string()`
3. GitHubFetcher instance created with optional token
4. Appropriate fetch methods called based on flags:
   - `--issues-only`: Calls `get_issues_since()`
   - `--comments-only`: Calls `get_issue_comments_since()` + `get_pull_request_comments_since()`
   - Default: Calls `fetch_all_data()` which combines all three
5. Results formatted as JSON and output to specified destination

### Dependencies
- `requests`: For HTTP API calls to GitHub
- `python-dateutil`: Used implicitly through datetime.fromisoformat() (built-in in Python 3.7+)
- Standard library: `os`, `sys`, `json`, `argparse`, `datetime`, `typing`

## Best Practices for Development

### When Modifying the Code
- Maintain separation between API logic (`GitHubFetcher` class) and CLI interface (`main()` function)
- Keep date parsing logic centralized in `parse_datetime_string()`
- Preserve the pagination handling pattern in `_make_request()`
- Continue using type hints for function parameters and return values
- Maintain consistent error reporting to stderr for diagnostic information

### Adding New Features
- For new GitHub endpoints, follow the pattern in `_make_request()` and existing getter methods
- Consider adding new command-line flags in the argparse section if exposing new functionality
- Maintain backward compatibility with existing flag combinations
- Update docstrings and README.md when changing behavior