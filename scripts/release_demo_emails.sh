#!/usr/bin/env bash
# Stages the demo inbox in acts. The simulator serves every JSON file in its
# fixtures folder, so the follow-up emails (which need records created by
# approving the first ones) are kept aside and released on cue.
#
#   scripts/release_demo_emails.sh act2    # follow-ups: update instead of duplicate
#   scripts/release_demo_emails.sh act3    # edge cases: off-topic + vague -> escalate
#   scripts/release_demo_emails.sh reset   # back to act 1 only
#
# Act 1 (the first support request and sales inquiry) is always live.
set -euo pipefail

cd "$(dirname "$0")/../email-simulator"
LIVE=src/email_simulator/fixtures
STAGED=demo-scenarios

case "${1:-}" in
  act2|act3)
    cp "$STAGED/$1"/*.json "$LIVE/"
    echo "Released $1: $(ls "$STAGED/$1" | tr '\n' ' ')"
    ;;
  reset)
    for f in "$STAGED"/act*/*.json; do rm -f "$LIVE/$(basename "$f")"; done
    echo "Reset: only act 1 emails are live."
    ;;
  *)
    echo "usage: $0 act2|act3|reset" >&2
    exit 1
    ;;
esac
