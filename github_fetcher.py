#!/usr/bin/env python3
"""
Script to fetch GitHub issues, issue comments, and pull request comments
newer than a given timestamp.

Uses the `gh` CLI for GitHub API access, eliminating the need for
manual token management via .env files.
"""

import os
import sys
import json
import argparse
import subprocess
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


class GitHubFetcher:
    def __init__(self):
        """
        Initialize the GitHub fetcher.

        Uses the `gh` CLI for authentication and API access.
        Requires `gh` to be installed and authenticated (`gh auth login`).
        """
        # Verify gh is available
        try:
            subprocess.run(
                ['gh', 'auth', 'status'],
                capture_output=True, text=True, check=True
            )
        except FileNotFoundError:
            print("Error: 'gh' CLI is not installed. Install it from https://cli.github.com/", file=sys.stderr)
            sys.exit(1)
        except subprocess.CalledProcessError:
            print("Error: 'gh' CLI is not authenticated. Run 'gh auth login' first.", file=sys.stderr)
            sys.exit(1)

    def _gh_api(self, endpoint: str, params: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """
        Make a paginated request to the GitHub API via `gh api`.

        Args:
            endpoint: The API endpoint path (e.g., 'repos/owner/repo/issues')
            params: Query parameters

        Returns:
            List of items from all pages
        """
        if params is None:
            params = {}

        cmd = ['gh', 'api', '--method', 'GET', '--paginate', endpoint]

        for key, value in params.items():
            cmd.extend(['-f', f'{key}={value}'])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Error fetching {endpoint}: {e.stderr}", file=sys.stderr)
            return []

        if not result.stdout.strip():
            return []

        # gh api --paginate may return multiple JSON arrays concatenated;
        # parse them all and merge into one list.
        items = []
        decoder = json.JSONDecoder()
        text = result.stdout.strip()
        pos = 0
        while pos < len(text):
            # Skip whitespace
            while pos < len(text) and text[pos] in ' \t\n\r':
                pos += 1
            if pos >= len(text):
                break
            obj, end = decoder.raw_decode(text, pos)
            if isinstance(obj, list):
                items.extend(obj)
            else:
                items.append(obj)
            pos = end

        return items

    def get_issues_since(self, repo: str, since: datetime) -> List[Dict[str, Any]]:
        """
        Get issues newer than the given timestamp.

        Args:
            repo: Repository in format 'owner/repo'
            since: Datetime object (timezone aware)

        Returns:
            List of issue dictionaries (only open issues)
        """
        endpoint = f"repos/{repo}/issues"
        params = {
            'since': since.isoformat(),
            'state': 'open'
        }

        issues = self._gh_api(endpoint, params)

        # Filter out pull requests (GitHub API includes them in issues endpoint)
        issues_only = [issue for issue in issues if 'pull_request' not in issue]

        return issues_only

    def get_issue_comments_since(self, repo: str, since: datetime) -> List[Dict[str, Any]]:
        """
        Get comments on issues newer than the given timestamp.

        Args:
            repo: Repository in format 'owner/repo'
            since: Datetime object (timezone aware)

        Returns:
            List of issue comment dictionaries
        """
        endpoint = f"repos/{repo}/issues/comments"
        params = {
            'since': since.isoformat()
        }

        return self._gh_api(endpoint, params)

    def get_pull_request_comments_since(self, repo: str, since: datetime) -> List[Dict[str, Any]]:
        """
        Get comments on pull requests newer than the given timestamp.

        Args:
            repo: Repository in format 'owner/repo'
            since: Datetime object (timezone aware)

        Returns:
            List of pull request comment dictionaries
        """
        endpoint = f"repos/{repo}/pulls/comments"
        params = {
            'since': since.isoformat()
        }

        return self._gh_api(endpoint, params)

    def fetch_all_data(self, repo: str, since: datetime) -> Dict[str, Any]:
        """
        Fetch all requested data types.

        Args:
            repo: Repository in format 'owner/repo'
            since: Datetime object (timezone aware)

        Returns:
            Dictionary containing all fetched data
        """
        print(f"Fetching data for {repo} since {since.isoformat()}...")

        issues = self.get_issues_since(repo, since)
        issue_comments = self.get_issue_comments_since(repo, since)
        pr_comments = self.get_pull_request_comments_since(repo, since)

        print(f"Found {len(issues)} issues, {len(issue_comments)} issue comments, "
              f"and {len(pr_comments)} pull request comments.")

        return {
            'issues': issues,
            'issue_comments': issue_comments,
            'pull_request_comments': pr_comments,
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'repository': repo,
            'since': since.isoformat()
        }


def parse_datetime_string(date_str: str) -> datetime:
    """
    Parse a datetime string into a timezone-aware datetime object.

    Supports formats like:
    - YYYY-MM-DD
    - YYYY-MM-DD HH:MM:SS
    - ISO format strings

    Args:
        date_str: Date string to parse

    Returns:
        Timezone-aware datetime object
    """
    try:
        # Try parsing as ISO format first
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except ValueError:
        try:
            # Try parsing as YYYY-MM-DD HH:MM:SS
            dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                # Try parsing as YYYY-MM-DD
                dt = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                raise ValueError(f"Unable to parse date string: {date_str}")

    # Make timezone aware if it isn't already
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def main():
    parser = argparse.ArgumentParser(
        description='Fetch GitHub issues, issue comments, and pull request comments newer than a given time'
    )
    parser.add_argument(
        'repo',
        help='GitHub repository in format "owner/repo"'
    )
    parser.add_argument(
        'since',
        help='Timestamp to fetch data newer than (formats: YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, or ISO format)'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output file path (default: stdout)',
        default=None
    )
    parser.add_argument(
        '--issues-only',
        action='store_true',
        help='Fetch only issues (not comments)'
    )
    parser.add_argument(
        '--comments-only',
        action='store_true',
        help='Fetch only comments (both issue and PR comments)'
    )

    args = parser.parse_args()

    try:
        since_dt = parse_datetime_string(args.since)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    fetcher = GitHubFetcher()

    if args.comments_only:
        # Fetch only comments
        issue_comments = fetcher.get_issue_comments_since(args.repo, since_dt)
        pr_comments = fetcher.get_pull_request_comments_since(args.repo, since_dt)

        result = {
            'issue_comments': issue_comments,
            'pull_request_comments': pr_comments,
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'repository': args.repo,
            'since': args.since
        }
    elif args.issues_only:
        # Fetch only issues
        issues = fetcher.get_issues_since(args.repo, since_dt)

        result = {
            'issues': issues,
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'repository': args.repo,
            'since': args.since
        }
    else:
        # Fetch everything
        result = fetcher.fetch_all_data(args.repo, since_dt)

    # Output the result
    output_json = json.dumps(result, indent=2, default=str)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_json)
        print(f"Data saved to {args.output}")
    else:
        print(output_json)


if __name__ == '__main__':
    main()
