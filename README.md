# GitHub Fetcher Script

This script fetches GitHub issues, issue comments, and pull request comments newer than a given timestamp.

## Usage

```bash
python3 github_fetcher.py <repo> <since> [options]
```

### Arguments

- `repo`: GitHub repository in format "owner/repo" (e.g., "torvalds/linux")
- `since`: Timestamp to fetch data newer than (formats: YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, or ISO format)

### Options

- `-o, --output`: Output file path (default: stdout)
- `-t, --token`: GitHub personal access token (can also be set via GITHUB_TOKEN env var)
- `--issues-only`: Fetch only issues (not comments)
- `--comments-only`: Fetch only comments (both issue and PR comments)

### Examples

Fetch all data newer than March 1, 2026:
```bash
python3 github_fetcher.py torvalds/linux 2026-03-01
```

Fetch only issues newer than March 15, 2026 at 10:30 AM:
```bash
python3 github_fetcher.py torvalds/linux "2026-03-15 10:30:00" --issues-only
```

Fetch comments newer than March 10, 2026 and save to file:
```bash
python3 github_fetcher.py torvalds/linux 2026-03-10 --comments-only --output comments.json
```

With GitHub token (recommended to avoid rate limits):
```bash
export GITHUB_TOKEN=your_token_here
python3 github_fetcher.py torvalds/linux 2026-03-01
```

Or provide token directly:
```bash
python3 github_fetcher.py torvalds/linux 2026-03-01 --token your_token_here
```

## Output

The script outputs JSON containing:
- `issues`: Array of issue objects (excluding pull requests)
- `issue_comments`: Array of issue comment objects
- `pull_request_comments`: Array of pull request review comment objects
- `fetched_at`: Timestamp when data was fetched
- `repository`: The repository that was queried
- `since`: The since timestamp used for filtering

## Requirements

- Python 3.6+
- requests library (>=2.25.1)
- python-dateutil library (>=2.8.0)

Install dependencies with:
```bash
pip install -r requirements.txt
```