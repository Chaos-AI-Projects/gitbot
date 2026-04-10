#!/usr/bin/env bash
#
# gitbot-run.sh — Main automation loop for GitBot.
# Polls for new GitHub activity and invokes the Claude agent on each result.
#
# Usage: gitbot-run.sh [jobs_dir] [--branch BRANCH] [--interval SECONDS]
#
# Solves issues #22 and #23.

set -euo pipefail

# ── Script directory (all Python scripts live here) ──────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Defaults ──────────────────────────────────────────────────────────────────
JOBS_DIR=".jobs"
POLL_INTERVAL=300
DEFAULT_BRANCH=""

# ── Argument parsing ─────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: gitbot-run.sh [jobs_dir] [--branch BRANCH] [--interval SECONDS]

Arguments:
  jobs_dir              Directory containing .done/.json files (default: .jobs)

Options:
  --branch BRANCH       Override the default git branch (default: auto-detect)
  --interval SECONDS    Poll interval in seconds (default: 300)
  -h, --help            Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch)
            DEFAULT_BRANCH="$2"
            shift 2
            ;;
        --interval)
            POLL_INTERVAL="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            echo "Error: Unknown option '$1'" >&2
            usage >&2
            exit 1
            ;;
        *)
            JOBS_DIR="$1"
            shift
            ;;
    esac
done

# ── Logging ──────────────────────────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ── Pre-flight checks ───────────────────────────────────────────────────────
preflight() {
    local ok=true

    # Check gh CLI
    if ! command -v gh &>/dev/null; then
        echo "Error: 'gh' (GitHub CLI) is not installed or not on PATH." >&2
        echo "Install it from https://cli.github.com/" >&2
        ok=false
    elif ! gh auth status &>/dev/null; then
        echo "Error: 'gh' is not authenticated. Run 'gh auth login' first." >&2
        ok=false
    fi

    # Check claude CLI
    if ! command -v claude &>/dev/null; then
        echo "Error: 'claude' CLI is not installed or not on PATH." >&2
        echo "Install it from https://docs.anthropic.com/en/docs/claude-code" >&2
        ok=false
    fi

    # Check we're in a git repo
    if ! git rev-parse --git-dir &>/dev/null; then
        echo "Error: Current directory is not a git repository." >&2
        ok=false
    fi

    # Check Python scripts exist in SCRIPT_DIR
    if [[ ! -f "$SCRIPT_DIR/process_event_file.py" ]]; then
        echo "Error: 'process_event_file.py' not found in $SCRIPT_DIR." >&2
        ok=false
    fi
    if [[ ! -f "$SCRIPT_DIR/claude_agent.py" ]]; then
        echo "Error: 'claude_agent.py' not found in $SCRIPT_DIR." >&2
        ok=false
    fi

    # Check jobs directory
    if [[ ! -d "$JOBS_DIR" ]]; then
        echo "Error: Jobs directory '$JOBS_DIR' does not exist." >&2
        echo "Create it with: mkdir $JOBS_DIR" >&2
        echo "You may want to add it to .gitignore: echo '${JOBS_DIR}/' >> .gitignore" >&2
        ok=false
    fi

    if [[ "$ok" != true ]]; then
        exit 1
    fi
}

# ── Default branch detection (solves #23) ────────────────────────────────────
detect_default_branch() {
    if [[ -n "$DEFAULT_BRANCH" ]]; then
        log "Using user-specified default branch: $DEFAULT_BRANCH"
        return
    fi

    # Try to detect from remote HEAD
    if DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||'); then
        if [[ -n "$DEFAULT_BRANCH" ]]; then
            log "Auto-detected default branch: $DEFAULT_BRANCH"
            return
        fi
    fi

    # Fallback: check if main or master exists
    if git show-ref --verify --quiet refs/heads/main 2>/dev/null; then
        DEFAULT_BRANCH="main"
    elif git show-ref --verify --quiet refs/heads/master 2>/dev/null; then
        DEFAULT_BRANCH="master"
    else
        echo "Error: Could not detect default branch. Use --branch to specify it." >&2
        exit 1
    fi

    log "Fallback default branch: $DEFAULT_BRANCH"
}

# ── Signal handling ──────────────────────────────────────────────────────────
RUNNING=true

cleanup() {
    log "Shutting down..."
    RUNNING=false
}

trap cleanup SIGINT SIGTERM

# ── Main ─────────────────────────────────────────────────────────────────────
preflight
detect_default_branch
export GITBOT_DEFAULT_BRANCH="$DEFAULT_BRANCH"

log "GitBot automation started"
log "  Jobs directory: $JOBS_DIR"
log "  Default branch: $DEFAULT_BRANCH"
log "  Poll interval:  ${POLL_INTERVAL}s"
log "Press Ctrl-C to stop."

while $RUNNING; do
    log "Polling for new activity..."
    python3 "$SCRIPT_DIR/process_event_file.py" "$JOBS_DIR" || {
        log "Warning: process_event_file.py exited with error, continuing..."
    }

    # Check for .json files
    json_files=()
    for f in "$JOBS_DIR"/*.json; do
        [[ -e "$f" ]] && json_files+=("$f")
    done

    if [[ ${#json_files[@]} -eq 0 ]]; then
        log "No new activity to process."
    else
        log "Found ${#json_files[@]} JSON file(s) to process."

        # Checkout default branch and pull latest
        if ! git checkout "$DEFAULT_BRANCH" 2>/dev/null; then
            log "Warning: Could not checkout $DEFAULT_BRANCH (uncommitted changes?). Skipping agent run."
        else
            if ! git pull 2>/dev/null; then
                log "Warning: git pull failed. Continuing with current state."
            fi

            for json_file in "${json_files[@]}"; do
                $RUNNING || break
                log "Processing: $json_file"
                if python3 "$SCRIPT_DIR/claude_agent.py" "$json_file" --repo-dir "$(pwd)"; then
                    # Main agent succeeded — run reviewer pass (best-effort)
                    done_file="${json_file%.json}.done"
                    if [[ -f "$done_file" ]]; then
                        # Ensure we're back on default branch before reviewer
                        git checkout "$DEFAULT_BRANCH" 2>/dev/null || true
                        log "Running reviewer on: $done_file"
                        python3 "$SCRIPT_DIR/claude_agent.py" "$done_file" --reviewer --repo-dir "$(pwd)" || {
                            log "Warning: reviewer pass failed for $done_file (non-blocking)"
                        }
                    fi
                else
                    log "Warning: claude_agent.py failed for $json_file"
                fi
            done
        fi
    fi

    $RUNNING || break
    log "Sleeping ${POLL_INTERVAL}s..."
    sleep "$POLL_INTERVAL" || break
done

log "GitBot automation stopped."
