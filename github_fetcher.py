#!/usr/bin/env python3
"""
Script to fetch GitHub issues, issue comments, and pull request comments
newer than a given timestamp.
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
import requests
from typing import List, Dict, Any, Optional


class GitHubFetcher:
    def __init__(self, token: Optional[str] = None):
        """
        Initialize the GitHub fetcher.

        Args:
            token: GitHub personal access token. If not provided, will try to get from GITHUB_TOKEN env var.
        """
        self.token = token or os.getenv('GITHUB_TOKEN')
        if not self.token:
            print("Warning: No GitHub token provided. Rate limits will be limited.", file=sys.stderr)

        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-Fetcher-Script'
        }
        if self.token:
            self.headers['Authorization'] = f'token {self.token}'

        self.base_url = 'https://api.github.com'

    def _make_request(self, url: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Make a request to the GitHub API and handle pagination.

        Args:
            url: The API endpoint URL
            params: Query parameters

        Returns:
            List of items from all pages
        """
        if params is None:
            params = {}

        all_items = []
        page = 1
        per_page = 100  # Maximum allowed by GitHub

        while True:
            params.update({
                'page': page,
                'per_page': per_page
            })

            response = requests.get(url, headers=self.headers, params=params)

            if response.status_code != 200:
                print(f"Error fetching {url}: {response.status_code} - {response.text}", file=sys.stderr)
                break

            items = response.json()
            if not items:
                break

            all_items.extend(items)

            # Check if there are more pages
            if len(items) < per_page:
                break

            page += 1

        return all_items

    def get_issues_since(self, repo: str, since: datetime) -> List[Dict[str, Any]]:
        """
        Get issues newer than the given timestamp.

        Args:
            repo: Repository in format 'owner/repo'
            since: Datetime object (timezone aware)

        Returns:
            List of issue dictionaries
        """
        url = f"{self.base_url}/repos/{repo}/issues"
        params = {
            'since': since.isoformat(),
            'state': 'all'  # Get both open and closed issues
        }

        issues = self._make_request(url, params)

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
        url = f"{self.base_url}/repos/{repo}/issues/comments"
        params = {
            'since': since.isoformat()
        }

        return self._make_request(url, params)

    def get_pull_request_comments_since(self, repo: str, since: datetime) -> List[Dict[str, Any]]:
        """
        Get comments on pull requests newer than the given timestamp.

        Args:
            repo: Repository in format 'owner/repo'
            since: Datetime object (timezone aware)

        Returns:
            List of pull request comment dictionaries
        """
        # Get review comments on pull requests
        url = f"{self.base_url}/repos/{repo}/pulls/comments"
        params = {
            'since': since.isoformat()
        }

        return self._make_request(url, params)

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
        '-t', '--token',
        help='GitHub personal access token (can also be set via GITHUB_TOKEN env var)',
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

    fetcher = GitHubFetcher(token=args.token)

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