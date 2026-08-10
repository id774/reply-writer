#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_prompts.py: Tests for reply_writer/prompts.py
#
#  Description:
#  This test suite covers the prompt layer: reading the files, refusing
#  one that is missing or empty, and assembling the two messages handed
#  to the API. The concerns it pins are the ones the requirements
#  attach to a prompt rather than to a file operation: the message
#  being replied to and the direction reach the model in separate
#  blocks, an absent direction still yields a valid prompt, and text
#  substituted for one placeholder is never read as another.
#
#  The prompts shipped in prompts/ are checked for structure only. What
#  they say is the subject of doc/PROMPTS.md, and pinning their wording
#  in a test would make every adjustment to the writing a test to
#  rewrite.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Running the tests:
#  Run the whole suite from the repository root:
#      python -m unittest discover -s tests
#  Run this module alone:
#      python -m unittest tests.test_prompts
#
#  Test Cases:
#    - Read a prompt file and strip its surrounding whitespace.
#    - Refuse a prompt file that is missing.
#    - Refuse a prompt file that is empty or only whitespace.
#    - Keep the file name out of what the user is shown.
#    - Put the writing policy first and the data after it.
#    - Place the message and the direction in their own blocks.
#    - Build a valid prompt when no direction was given.
#    - Substitute a brace written in a prompt without escaping it.
#    - Read no placeholder out of substituted text.
#    - Ship a system prompt and a user prompt that are not empty.
#    - Carry both placeholders in the shipped user prompt.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import os
import tempfile
import unittest

from reply_writer.errors import InternalError, ReplyWriterError
from reply_writer.prompts import build_reply_messages, load_prompt

REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPPED_PROMPTS = os.path.join(REPOSITORY, "prompts")

# Invented material. No real correspondence is used as test data.
MESSAGE = "打ち合わせの候補日をお送りします。"
DIRECTION = "二番目の候補で受けること。"


class PromptDirectory:
    """ A temporary prompt directory holding the two files. """

    def __init__(self, system="POLICY", user="D:{{direction}} M:{{message}}"):
        self.directory = tempfile.TemporaryDirectory()
        self.write("system.md", system)
        self.write("user.md", user)

    def write(self, name, text):
        """ Write one prompt file into the temporary directory. """
        path = os.path.join(self.directory.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    @property
    def path(self):
        """ Return the directory the prompts were written into. """
        return self.directory.name

    def cleanup(self):
        """ Remove the temporary directory. """
        self.directory.cleanup()


class LoadPromptTest(unittest.TestCase):
    """ Cover reading one prompt file. """

    def setUp(self):
        self.prompts = PromptDirectory()
        self.addCleanup(self.prompts.cleanup)

    def test_reads_a_prompt_and_strips_it(self):
        """ Return the text of a prompt without its outer whitespace. """
        self.prompts.write("system.md", "\n  Write a reply.\n\n")
        self.assertEqual(load_prompt("system.md", self.prompts.path),
                         "Write a reply.")

    def test_refuses_a_missing_prompt(self):
        """ Refuse a prompt file that is not there. """
        with self.assertLogs("reply_writer.prompts", "ERROR"):
            with self.assertRaises(InternalError):
                load_prompt("absent.md", self.prompts.path)

    def test_refuses_an_empty_prompt(self):
        """ Refuse an empty prompt rather than generate without one. """
        self.prompts.write("system.md", "   \n\n")
        with self.assertLogs("reply_writer.prompts", "ERROR"):
            with self.assertRaises(InternalError):
                load_prompt("system.md", self.prompts.path)

    def test_keeps_the_path_out_of_the_user_message(self):
        """ Keep an internal path off the screen, and in the log only. """
        with self.assertLogs("reply_writer.prompts", "ERROR") as recorded:
            try:
                load_prompt("absent.md", self.prompts.path)
            except ReplyWriterError as error:
                self.assertNotIn(self.prompts.path, error.user_message)
            else:
                self.fail("a missing prompt was not refused")
        self.assertIn(self.prompts.path, "\n".join(recorded.output))


class BuildReplyMessagesTest(unittest.TestCase):
    """ Cover the assembly of the messages handed to the API. """

    def setUp(self):
        self.prompts = PromptDirectory()
        self.addCleanup(self.prompts.cleanup)

    def build(self, message=MESSAGE, direction=DIRECTION):
        """ Assemble the messages from the temporary prompts. """
        return build_reply_messages(message, direction, self.prompts.path)

    def test_policy_comes_first(self):
        """ Hand over the writing policy before the data. """
        messages = self.build()
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "POLICY")
        self.assertEqual(messages[1]["role"], "user")

    def test_message_and_direction_go_to_their_own_places(self):
        """ Keep the two apart, each where the prompt puts it. """
        self.assertEqual(self.build()[1]["content"],
                         "D:{0} M:{1}".format(DIRECTION, MESSAGE))

    def test_an_absent_direction_still_builds_a_prompt(self):
        """ Build a valid prompt when no direction was given. """
        content = self.build(direction="")[1]["content"]
        self.assertEqual(content, "D: M:{0}".format(MESSAGE))

    def test_a_brace_in_a_prompt_needs_no_escaping(self):
        """ Substitute literally, so a prompt may carry a brace. """
        self.prompts.write("user.md", '{"subject": null} {{message}}')
        content = self.build()[1]["content"]
        self.assertEqual(content, '{"subject": null} ' + MESSAGE)

    def test_substituted_text_is_not_scanned_again(self):
        """
        Read no placeholder out of text that was substituted.

        A message is untrusted data. One carrying the literal
        '{{direction}}' must not decide where the direction lands, and
        a direction carrying '{{message}}' must not pull the message
        into its own block.
        """
        content = self.build(message="{{direction}}",
                             direction="{{message}}")[1]["content"]
        self.assertEqual(content, "D:{{message}} M:{{direction}}")


class ShippedPromptsTest(unittest.TestCase):
    """ Cover the structure of the prompts the repository ships. """

    def test_both_prompts_are_present_and_not_empty(self):
        """ Ship a system prompt and a user prompt that carry text. """
        for name in ("system.md", "user.md"):
            self.assertTrue(load_prompt(name, SHIPPED_PROMPTS).strip())

    def test_the_user_prompt_carries_both_placeholders(self):
        """ Carry the message and the direction into the user prompt. """
        user = load_prompt("user.md", SHIPPED_PROMPTS)
        self.assertIn("{{message}}", user)
        self.assertIn("{{direction}}", user)

    def test_the_shipped_prompts_assemble(self):
        """ Leave no placeholder behind once the two are substituted. """
        messages = build_reply_messages(MESSAGE, DIRECTION, SHIPPED_PROMPTS)
        self.assertNotIn("{{message}}", messages[1]["content"])
        self.assertNotIn("{{direction}}", messages[1]["content"])
        self.assertIn(MESSAGE, messages[1]["content"])
        self.assertIn(DIRECTION, messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
