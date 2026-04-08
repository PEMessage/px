#!/bin/bash
# px.sh - Shell wrapper for px proxy tool
#
# Principle:
#   Execute both eval and echo subcommands for all modes:
#     - eval: generates commands that modify shell environment
#     - echo: generates content to display (configs, comments, etc.)
#
#   Safety mechanism:
#     - Only eval if px returns exit 0
#     - Otherwise print error and preserve exit code
#
# Usage:
#   source px.sh       # Load functions
#   px                 # Auto-detect IP and set proxy
#   unpx               # Unset proxy

# Config: px script path (overridable via environment variable)

# Core: call px to execute eval and echo
_px() {
    local eval_output
    local exit_code

    # Capture eval output and exit code
    # Use PX_CMD from environment if set, otherwise use px.py relative to this script
    local PX_CMD="${PX_CMD:-px.py}"
    if ! command -v "$PX_CMD" > /dev/null ; then
        echo "$PX_CMD not found"
        return 1
    fi
    eval_output="$("$PX_CMD" eval "$@" 2>&1)"
    exit_code=$?

    # Check exit code, don't eval if non-zero
    if ((exit_code != 0)); then
        echo "$eval_output" >&2
        return $exit_code
    fi

    # Execute eval when exit 0
    if [[ -n "$eval_output" ]]; then
        eval "$eval_output"
    fi

    # Execute echo subcommand (display configs)
    "$PX_CMD" echo "$@"
}

# Command definitions
px()   { _px shell -a set "$@"; }
unpx() { _px shell -a unset "$@"; }
