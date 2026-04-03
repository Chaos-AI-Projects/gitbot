#!/usr/bin/env python3
"""
Generate a chronological Markdown history of a GitHub repository.

Fetches issues, issue comments, PR events, and PR comments via the `gh` CLI
and renders them as a single interleaved timeline sorted by timestamp.

Supports incremental mode: use --since to fetch only newer events and --append
to add them to an existing history file.
"""

import sys
import json
import argparse
import subprocess
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


def gh_api(endpoint: str, params: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Make a paginated GitHub API request via `gh api`."""
    if params is None:
        params = {}

    cmd = ['gh', 'api', '--method', 'GET', '--paginate', endpoint]
    for key, value in params.items():
        cmd.extend(['-f', f'{key}={value}'])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        print("Error: 'gh' CLI is not installed.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching {endpoint}: {e.stderr}", file=sys.stderr)
        return []

    if not result.stdout.strip():
        return []

    items = []
    decoder = json.JSONDecoder()
    text = result.stdout.strip()
    pos = 0
    while pos < len(text):
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


def fetch_issues(repo: str, since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all issues (open and closed)."""
    params = {'state': 'all', 'per_page': '100'}
    if since:
        params['since'] = since
    items = gh_api(f"repos/{repo}/issues", params)
    # Filter out pull requests (GitHub includes them in issues endpoint)
    return [i for i in items if 'pull_request' not in i]


def fetch_issue_comments(repo: str, since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all issue comments."""
    params = {'per_page': '100'}
    if since:
        params['since'] = since
    return gh_api(f"repos/{repo}/issues/comments", params)


def fetch_issue_events(repo: str, issue_number: int) -> List[Dict[str, Any]]:
    """Fetch timeline events for a specific issue."""
    return gh_api(f"repos/{repo}/issues/{issue_number}/events")


def fetch_pulls(repo: str) -> List[Dict[str, Any]]:
    """Fetch all pull requests (open and closed)."""
    params = {'state': 'all', 'per_page': '100'}
    return gh_api(f"repos/{repo}/pulls", params)


def fetch_pr_comments(repo: str, since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all PR review comments."""
    params = {'per_page': '100'}
    if since:
        params['since'] = since
    return gh_api(f"repos/{repo}/pulls/comments", params)


def fetch_pr_issue_comments(repo: str, pr_number: int) -> List[Dict[str, Any]]:
    """Fetch general (non-review) comments on a PR via the issues endpoint."""
    return gh_api(f"repos/{repo}/issues/{pr_number}/comments")


def parse_ts(ts_str: str) -> datetime:
    """Parse an ISO timestamp string to a timezone-aware datetime."""
    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_ts(ts_str: str) -> str:
    """Format an ISO timestamp to a human-readable string."""
    dt = parse_ts(ts_str)
    return dt.strftime('%Y-%m-%d %H:%M UTC')


def build_timeline(repo: str, since: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Build a chronological list of all events.

    Each event is a dict with keys: timestamp, kind, text
    """
    events = []
    since_dt = parse_ts(since) if since else None

    print("Fetching issues...", file=sys.stderr)
    issues = fetch_issues(repo, since)
    issue_numbers = set()
    for issue in issues:
        issue_numbers.add(issue['number'])
        created = issue['created_at']
        if since_dt and parse_ts(created) < since_dt:
            # Issue was updated since, but created before -- we still want
            # close events, but skip the create event
            pass
        else:
            user = issue['user']['login']
            title = issue['title']
            labels = ', '.join(l['name'] for l in issue.get('labels', []))
            label_str = f" [{labels}]" if labels else ""
            events.append({
                'timestamp': created,
                'kind': 'issue_created',
                'text': f"## {fmt_ts(created)} -- Issue #{issue['number']} created by @{user}: \"{title}\"{label_str}\n"
            })
        if issue.get('closed_at'):
            closed = issue['closed_at']
            if not since_dt or parse_ts(closed) >= since_dt:
                events.append({
                    'timestamp': closed,
                    'kind': 'issue_closed',
                    'text': f"## {fmt_ts(closed)} -- Issue #{issue['number']} closed\n"
                })

    # Fetch events for issues to capture label/assign/milestone changes
    print("Fetching issue events...", file=sys.stderr)
    for num in issue_numbers:
        issue_evts = fetch_issue_events(repo, num)
        for evt in issue_evts:
            evt_type = evt.get('event', '')
            created = evt.get('created_at', '')
            if not created:
                continue
            if since_dt and parse_ts(created) < since_dt:
                continue
            actor = evt.get('actor', {}).get('login', 'unknown') if evt.get('actor') else 'unknown'
            if evt_type == 'labeled':
                label_name = evt.get('label', {}).get('name', '')
                events.append({
                    'timestamp': created,
                    'kind': 'issue_event',
                    'text': f"## {fmt_ts(created)} -- Issue #{num} labeled \"{label_name}\" by @{actor}\n"
                })
            elif evt_type == 'unlabeled':
                label_name = evt.get('label', {}).get('name', '')
                events.append({
                    'timestamp': created,
                    'kind': 'issue_event',
                    'text': f"## {fmt_ts(created)} -- Issue #{num} unlabeled \"{label_name}\" by @{actor}\n"
                })
            elif evt_type == 'assigned':
                assignee = evt.get('assignee', {}).get('login', 'unknown') if evt.get('assignee') else 'unknown'
                events.append({
                    'timestamp': created,
                    'kind': 'issue_event',
                    'text': f"## {fmt_ts(created)} -- Issue #{num} assigned to @{assignee} by @{actor}\n"
                })
            elif evt_type == 'milestoned':
                milestone = evt.get('milestone', {}).get('title', '') if evt.get('milestone') else ''
                events.append({
                    'timestamp': created,
                    'kind': 'issue_event',
                    'text': f"## {fmt_ts(created)} -- Issue #{num} added to milestone \"{milestone}\" by @{actor}\n"
                })
            elif evt_type in ('closed', 'reopened', 'renamed', 'locked', 'unlocked'):
                events.append({
                    'timestamp': created,
                    'kind': 'issue_event',
                    'text': f"## {fmt_ts(created)} -- Issue #{num} {evt_type} by @{actor}\n"
                })

    print("Fetching issue comments...", file=sys.stderr)
    comments = fetch_issue_comments(repo, since)
    for comment in comments:
        created = comment['created_at']
        user = comment['user']['login']
        body = comment['body']
        # Extract issue number from issue_url
        issue_num = comment['issue_url'].rstrip('/').split('/')[-1]
        events.append({
            'timestamp': created,
            'kind': 'issue_comment',
            'text': f"## {fmt_ts(created)} -- Issue #{issue_num} comment by @{user}\n\n````\n{body}\n````\n"
        })

    print("Fetching pull requests...", file=sys.stderr)
    pulls = fetch_pulls(repo)
    pr_numbers = set()
    for pr in pulls:
        pr_numbers.add(pr['number'])
        created = pr['created_at']
        if since_dt and parse_ts(created) < since_dt:
            pass
        else:
            user = pr['user']['login']
            title = pr['title']
            events.append({
                'timestamp': created,
                'kind': 'pr_created',
                'text': f"## {fmt_ts(created)} -- PR #{pr['number']} created by @{user}: \"{title}\"\n"
            })
        if pr.get('merged_at'):
            merged = pr['merged_at']
            if not since_dt or parse_ts(merged) >= since_dt:
                events.append({
                    'timestamp': merged,
                    'kind': 'pr_merged',
                    'text': f"## {fmt_ts(merged)} -- PR #{pr['number']} merged\n"
                })
        elif pr.get('closed_at'):
            closed = pr['closed_at']
            if not since_dt or parse_ts(closed) >= since_dt:
                events.append({
                    'timestamp': closed,
                    'kind': 'pr_closed',
                    'text': f"## {fmt_ts(closed)} -- PR #{pr['number']} closed\n"
                })

    print("Fetching PR review comments...", file=sys.stderr)
    pr_review_comments = fetch_pr_comments(repo, since)
    for comment in pr_review_comments:
        created = comment['created_at']
        user = comment['user']['login']
        body = comment['body']
        # Extract PR number from pull_request_url
        pr_num = comment['pull_request_url'].rstrip('/').split('/')[-1]
        events.append({
            'timestamp': created,
            'kind': 'pr_review_comment',
            'text': f"## {fmt_ts(created)} -- PR #{pr_num} review comment by @{user}\n\n````\n{body}\n````\n"
        })

    # Fetch general (non-review) comments on PRs via issues endpoint
    print("Fetching PR general comments...", file=sys.stderr)
    for pr_num in pr_numbers:
        pr_comments_list = fetch_pr_issue_comments(repo, pr_num)
        for comment in pr_comments_list:
            created = comment['created_at']
            if since_dt and parse_ts(created) < since_dt:
                continue
            user = comment['user']['login']
            body = comment['body']
            events.append({
                'timestamp': created,
                'kind': 'pr_comment',
                'text': f"## {fmt_ts(created)} -- PR #{pr_num} comment by @{user}\n\n````\n{body}\n````\n"
            })

    # Sort by timestamp
    events.sort(key=lambda e: e['timestamp'])

    return events


def render_markdown(repo: str, events: List[Dict[str, Any]]) -> str:
    """Render events as a Markdown document."""
    lines = [f"# History: {repo}\n"]
    for event in events:
        lines.append(event['text'])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Generate a chronological Markdown history of a GitHub repository'
    )
    parser.add_argument(
        'repo',
        help='GitHub repository in format "owner/repo"'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output file path (default: stdout)',
        default=None
    )
    parser.add_argument(
        '--since',
        help='Only fetch events after this timestamp (ISO format or YYYY-MM-DD)',
        default=None
    )
    parser.add_argument(
        '--append',
        action='store_true',
        help='Append to existing output file instead of overwriting'
    )

    args = parser.parse_args()

    # Validate --since format if provided
    since_iso = None
    if args.since:
        try:
            dt = parse_ts(args.since)
            since_iso = dt.isoformat()
        except (ValueError, AttributeError):
            # Try simple date format
            try:
                dt = datetime.strptime(args.since, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                since_iso = dt.isoformat()
            except ValueError:
                print(f"Error: Unable to parse --since date: {args.since}", file=sys.stderr)
                sys.exit(1)

    events = build_timeline(args.repo, since_iso)
    print(f"Collected {len(events)} events.", file=sys.stderr)

    if args.append and args.output:
        # Append mode: just add new events to the file
        new_content = '\n'.join(e['text'] for e in events)
        if new_content.strip():
            with open(args.output, 'a') as f:
                f.write('\n' + new_content + '\n')
            print(f"Appended {len(events)} events to {args.output}", file=sys.stderr)
        else:
            print("No new events to append.", file=sys.stderr)
    else:
        output = render_markdown(args.repo, events)
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            print(f"History saved to {args.output}", file=sys.stderr)
        else:
            print(output)


if __name__ == '__main__':
    main()
