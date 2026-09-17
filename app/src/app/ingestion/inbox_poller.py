"""Polls the email simulator for new messages and kicks off the pipeline.

TODO(phase-1):
  1. GET {EMAIL_SIMULATOR_URL}/messages?since=<cursor>
  2. For each new message, write an EmailMessage row
  3. Run classify -> extract -> match -> propose
  4. Write ExtractionResult + ProposedAction rows
  5. Advance the cursor

Run this as a simple asyncio loop on app startup, or trigger it on demand
from a POST /ingest/poll route for the demo — a loop with a fixed
interval is enough for a portfolio project; a real deployment would use
the simulator's (or a real inbox's) webhook instead of polling.
"""
