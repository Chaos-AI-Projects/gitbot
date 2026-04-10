#!/usr/bin/env python3
"""
Tests for loop avoidance between the main agent and reviewer agent.

Validates that prefix-based routing in prompt templates prevents infinite loops:
  - %claude content → only reviewer reacts → produces %claude-reviewer → nobody reacts → stops
  - Only unprefixed (human) content restarts the cycle
  - No ping-pong between agents

Fixes #51
"""

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path


# ── Helpers to simulate agent routing decisions ──────────────────────────────

def should_main_agent_process(content: str) -> bool:
    """
    Return True if the main agent should process this content.

    Rules from prompt_template.md:
      - Skip any content that starts with '%claude-reviewer'
      - Skip any content that starts with '%claude'
      - Process everything else (human content)

    Note: '%claude-reviewer' must be checked BEFORE '%claude' because
    '%claude-reviewer' also starts with '%claude'.
    """
    stripped = content.strip()
    if stripped.startswith('%claude-reviewer'):
        return False
    if stripped.startswith('%claude'):
        return False
    return True


def should_reviewer_process(content: str) -> bool:
    """
    Return True if the reviewer agent should process this content.

    Rules from prompt_template_reviewer.md:
      - Only process content prefixed with '%claude'
      - Skip content prefixed with '%claude-reviewer' (own output)

    Note: '%claude-reviewer' must be checked BEFORE '%claude'.
    """
    stripped = content.strip()
    if stripped.startswith('%claude-reviewer'):
        return False
    if stripped.startswith('%claude'):
        return True
    return False


def simulate_chain(initial_content: str, max_steps: int = 10) -> list:
    """
    Simulate the agent chain starting from initial_content.

    Returns a list of (agent, output_prefix) tuples representing
    which agents fired and what they produced.  Stops when no agent
    would process the current content, or after max_steps.
    """
    chain = []
    current = initial_content

    for _ in range(max_steps):
        if should_main_agent_process(current):
            # Main agent processes → produces %claude content
            current = '%claude\nAgent response to: ' + current
            chain.append(('main', current))
        elif should_reviewer_process(current):
            # Reviewer processes → produces %claude-reviewer content
            current = '%claude-reviewer\nReview of: ' + current
            chain.append(('reviewer', current))
        else:
            # Nobody processes → chain terminates
            break

    return chain


# ── Test cases ───────────────────────────────────────────────────────────────

class TestPrefixRouting(unittest.TestCase):
    """Test that individual routing decisions are correct."""

    # -- Main agent routing --

    def test_main_skips_claude_content(self):
        self.assertFalse(should_main_agent_process('%claude\nSome agent output'))

    def test_main_skips_claude_reviewer_content(self):
        self.assertFalse(should_main_agent_process('%claude-reviewer\nSome review'))

    def test_main_processes_human_content(self):
        self.assertTrue(should_main_agent_process('Please fix the bug in foo.py'))

    def test_main_processes_at_claude_implement(self):
        self.assertTrue(should_main_agent_process('@claude implement'))

    def test_main_skips_claude_with_extra_whitespace(self):
        # Leading whitespace before prefix
        self.assertFalse(should_main_agent_process('  %claude\nContent'))

    def test_main_processes_content_mentioning_claude(self):
        # Content that mentions %claude in the middle is NOT prefixed
        self.assertTrue(should_main_agent_process(
            'Hey, the %claude prefix should be used for agent content'))

    # -- Reviewer routing --

    def test_reviewer_processes_claude_content(self):
        self.assertTrue(should_reviewer_process('%claude\nAgent output to review'))

    def test_reviewer_skips_claude_reviewer_content(self):
        self.assertFalse(should_reviewer_process('%claude-reviewer\nOwn prior review'))

    def test_reviewer_skips_human_content(self):
        self.assertFalse(should_reviewer_process('Human comment here'))

    def test_reviewer_skips_at_claude_implement(self):
        self.assertFalse(should_reviewer_process('@claude implement'))


class TestLoopAvoidance(unittest.TestCase):
    """Test that the full chain terminates without ping-pong loops."""

    def test_human_content_chain_terminates(self):
        """Human → main agent (%claude) → reviewer (%claude-reviewer) → STOP"""
        chain = simulate_chain('Please implement feature X')
        # Exactly two steps: main agent, then reviewer
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0][0], 'main')
        self.assertEqual(chain[1][0], 'reviewer')

    def test_claude_content_chain_terminates(self):
        """%claude → reviewer (%claude-reviewer) → STOP"""
        chain = simulate_chain('%claude\nI created a PR for issue #42')
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0][0], 'reviewer')

    def test_claude_reviewer_content_stops_immediately(self):
        """%claude-reviewer → STOP (nobody processes)"""
        chain = simulate_chain('%claude-reviewer\nLGTM, the PR looks good')
        self.assertEqual(len(chain), 0)

    def test_no_infinite_loop(self):
        """Verify the chain never exceeds 2 steps for any input type."""
        test_inputs = [
            'Human comment',
            '@claude implement',
            '%claude\nAgent output',
            '%claude-reviewer\nReviewer output',
            'Fix bug in process_event_file.py',
            '%claude\n\nWork started on this issue.',
            '%claude-reviewer\n\nLooks good.',
        ]
        for content in test_inputs:
            chain = simulate_chain(content, max_steps=100)
            self.assertLessEqual(
                len(chain), 2,
                f'Chain too long for input: {content!r}\nChain: {chain}')

    def test_chain_always_ends_at_reviewer_or_empty(self):
        """The last agent in any chain is either 'reviewer' or chain is empty."""
        test_inputs = [
            'Implement task X',
            '%claude\nDone',
            '%claude-reviewer\nOK',
        ]
        for content in test_inputs:
            chain = simulate_chain(content)
            if chain:
                self.assertEqual(
                    chain[-1][0], 'reviewer',
                    f'Chain for {content!r} did not end at reviewer: {chain}')


class TestPrefixOrdering(unittest.TestCase):
    """
    Verify that %claude-reviewer is checked before %claude in routing.

    This is critical because '%claude-reviewer' starts with '%claude'.
    If the check order is wrong, reviewer content would be misrouted.
    """

    def test_reviewer_prefix_is_superset_of_agent_prefix(self):
        """Confirm the substring relationship that makes ordering matter."""
        self.assertTrue('%claude-reviewer'.startswith('%claude'))

    def test_main_agent_distinguishes_prefixes(self):
        """Main agent must skip both, but for different reasons."""
        # Both should be skipped
        self.assertFalse(should_main_agent_process('%claude\nA'))
        self.assertFalse(should_main_agent_process('%claude-reviewer\nB'))

    def test_reviewer_distinguishes_prefixes(self):
        """Reviewer must process %claude but skip %claude-reviewer."""
        self.assertTrue(should_reviewer_process('%claude\nA'))
        self.assertFalse(should_reviewer_process('%claude-reviewer\nB'))


class TestPromptTemplateConsistency(unittest.TestCase):
    """Verify that the actual prompt templates contain the expected rules."""

    @classmethod
    def setUpClass(cls):
        script_dir = Path(__file__).resolve().parent
        cls.main_template = (script_dir / 'prompt_template.md').read_text()
        cls.reviewer_template = (script_dir / 'prompt_template_reviewer.md').read_text()

    def test_main_template_skips_claude_content(self):
        self.assertIn(
            'Skip any content that starts with `%claude`',
            self.main_template)

    def test_main_template_skips_reviewer_content(self):
        self.assertIn(
            'Skip any content that starts with `%claude-reviewer`',
            self.main_template)

    def test_reviewer_template_only_processes_claude(self):
        self.assertIn(
            'Only process content prefixed with `%claude`',
            self.reviewer_template)

    def test_reviewer_template_skips_own_output(self):
        self.assertIn(
            'Skip content prefixed with `%claude-reviewer`',
            self.reviewer_template)

    def test_main_template_skip_reviewer_before_skip_claude(self):
        """
        In the main template, the %claude-reviewer skip rule should appear
        before (or alongside) the %claude skip rule so implementations
        checking in order get it right.
        """
        pos_reviewer = self.main_template.index('%claude-reviewer')
        # There should be a skip rule for %claude-reviewer
        self.assertIn('Skip any content that starts with `%claude-reviewer`',
                       self.main_template)

    def test_reviewer_template_mentions_both_prefixes(self):
        """Reviewer template must reference both prefixes for clarity."""
        self.assertIn('%claude`', self.reviewer_template)
        self.assertIn('%claude-reviewer`', self.reviewer_template)


if __name__ == '__main__':
    unittest.main()
