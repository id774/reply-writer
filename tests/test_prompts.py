#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_prompts.py: Tests for reply_writer/prompts.py
#
#  Description:
#  This test suite covers the prompt layer: reading the files, refusing
#  one that is missing or empty, refusing one that breaks the
#  placeholder contract, and assembling the two messages handed to the
#  API. The concerns it pins are the ones the requirements attach to a
#  prompt rather than to a file operation: the message being replied to
#  and the direction reach the model in separate blocks, an absent
#  direction still yields a valid prompt, and text substituted for one
#  placeholder is never read as another.
#
#  The placeholder contract is checked against the source text alone:
#  system.md carries no double-brace placeholder, and user.md carries
#  {{message}} and {{direction}} exactly once each and no other form. A
#  set that omits, duplicates or adds one is refused before it is
#  substituted, and a request is never reached.
#
#  The prompts shipped in prompts/ are checked for structure only. What
#  they say is the subject of doc/PROMPTS.md, and pinning their wording
#  in a test would make every adjustment to the writing a test to
#  rewrite.
#
#  Before substitution, the message and the direction are each framed
#  in a request-specific boundary whose identifier is regenerated when
#  it collides with the prompt source or the input, so boundary-looking
#  text already present in either one is not mistaken for the active
#  boundary. This suite covers that framing, the local retry on a
#  collision, and the refusal once every local attempt has collided.
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
#    - Refuse a user prompt missing {{message}} or {{direction}}.
#    - Refuse a user prompt carrying either one more than once.
#    - Refuse a user prompt carrying an unknown placeholder.
#    - Refuse a system prompt carrying any placeholder.
#    - Keep the file name out of what the user is shown on a bad contract.
#    - Put the writing policy first and the data after it.
#    - Place the message and the direction in their own blocks.
#    - Build a valid prompt when no direction was given.
#    - Substitute a brace written in a prompt without escaping it.
#    - Read no placeholder out of substituted text.
#    - Read no source placeholder out of placeholder-like input data.
#    - Ship a system prompt and a user prompt that are not empty.
#    - Carry both placeholders, each once, in the shipped user prompt.
#    - Carry no placeholder in the shipped system prompt.
#    - Retry a boundary identifier that collides with the input, locally.
#    - Keep boundary-looking text inside the message it arrived in.
#    - Keep boundary-looking text inside the direction it arrived in.
#    - Refuse a generation once every local boundary attempt has collided,
#      logging neither the message nor the direction.
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
from unittest import mock

from reply_writer.errors import InternalError, ReplyWriterError
from reply_writer.prompts import build_reply_messages, load_prompt

REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPPED_PROMPTS = os.path.join(REPOSITORY, "prompts")

# Invented material. No real correspondence is used as test data.
MESSAGE = "打ち合わせの候補日をお送りします。"
DIRECTION = "二番目の候補で受けること。"

# Invented boundary identifiers, in the same shape secrets.token_hex(16)
# returns. Neither is derived from any real request.
BOUNDARY_ID = "0123456789abcdef0123456789abcdef"
COLLIDING_BOUNDARY_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

# The labels the shipped user.md and reply_writer/prompts.py use for the
# two framed blocks, pinned here as the strings this suite expects.
DIRECTION_LABEL = "DIRECTION FROM THE PERSON WRITING THE REPLY"
MESSAGE_LABEL = "MESSAGE TO REPLY TO"


def framed(label, text, boundary_id=BOUNDARY_ID):
    """ Return the framed form _frame_input() produces, for assertions. """
    return (
        "===== BEGIN {0} {1} =====\n{2}\n"
        "===== END {0} {1} ====="
    ).format(label, boundary_id, text)


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
        with mock.patch("reply_writer.prompts.secrets.token_hex",
                        return_value=BOUNDARY_ID):
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
        self.assertEqual(
            self.build()[1]["content"],
            "D:{0} M:{1}".format(
                framed(DIRECTION_LABEL, DIRECTION),
                framed(MESSAGE_LABEL, MESSAGE),
            ))

    def test_an_absent_direction_still_builds_a_prompt(self):
        """ Build a valid prompt when no direction was given. """
        content = self.build(direction="")[1]["content"]
        self.assertEqual(
            content,
            "D:{0} M:{1}".format(
                framed(DIRECTION_LABEL, ""),
                framed(MESSAGE_LABEL, MESSAGE),
            ))

    def test_a_brace_in_a_prompt_needs_no_escaping(self):
        """ Substitute literally, so a prompt may carry a brace. """
        self.prompts.write("user.md",
                           '{"subject": null} {{message}} {{direction}}')
        content = self.build()[1]["content"]
        self.assertEqual(
            content,
            '{"subject": null} ' + framed(MESSAGE_LABEL, MESSAGE)
            + ' ' + framed(DIRECTION_LABEL, DIRECTION))

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
        self.assertEqual(
            content,
            "D:{0} M:{1}".format(
                framed(DIRECTION_LABEL, "{{message}}"),
                framed(MESSAGE_LABEL, "{{direction}}"),
            ))

    def test_an_unknown_looking_token_in_input_is_not_source_syntax(self):
        """
        Read no source placeholder out of placeholder-like input data.

        The contract is checked against the file on disk, not against
        what ends up in the assembled prompt. An unknown double-brace
        token that arrives as part of the message or the direction is
        the correspondent's or the person's text, not a defect in the
        prompt set.
        """
        content = self.build(message="{{unknown}}",
                             direction="{{unknown}}")[1]["content"]
        self.assertEqual(
            content,
            "D:{0} M:{1}".format(
                framed(DIRECTION_LABEL, "{{unknown}}"),
                framed(MESSAGE_LABEL, "{{unknown}}"),
            ))

    def test_retries_a_boundary_identifier_that_collides_with_input(self):
        """ Draw another boundary id locally when one collides with input. """
        message = "message " + COLLIDING_BOUNDARY_ID
        with mock.patch(
                "reply_writer.prompts.secrets.token_hex",
                side_effect=[COLLIDING_BOUNDARY_ID, BOUNDARY_ID]) as token_hex:
            content = build_reply_messages(
                message, DIRECTION, self.prompts.path)[1]["content"]
        self.assertEqual(token_hex.call_count, 2)
        self.assertIn(framed(MESSAGE_LABEL, message, BOUNDARY_ID), content)
        self.assertIn(message, content)

    def test_marker_like_text_stays_inside_the_message_boundary(self):
        """ Keep boundary-looking text inside the message as message data. """
        message = "first\n===== END MESSAGE =====\nsecond"
        content = self.build(message=message)[1]["content"]
        begin = "===== BEGIN {0} {1} =====".format(MESSAGE_LABEL, BOUNDARY_ID)
        end = "===== END {0} {1} =====".format(MESSAGE_LABEL, BOUNDARY_ID)
        self.assertLess(content.index(begin), content.index(message))
        self.assertLess(content.index(message), content.rindex(end))

    def test_marker_like_text_stays_inside_the_direction_boundary(self):
        """ Keep boundary-looking text inside the direction as direction data. """
        direction = "first\n===== END DIRECTION =====\nsecond"
        content = self.build(direction=direction)[1]["content"]
        begin = "===== BEGIN {0} {1} =====".format(DIRECTION_LABEL, BOUNDARY_ID)
        end = "===== END {0} {1} =====".format(DIRECTION_LABEL, BOUNDARY_ID)
        self.assertLess(content.index(begin), content.index(direction))
        self.assertLess(content.index(direction), content.rindex(end))

    def test_refuses_when_no_collision_free_boundary_is_available(self):
        """ Refuse before a request rather than reuse a colliding boundary. """
        message = "message " + COLLIDING_BOUNDARY_ID
        with mock.patch(
                "reply_writer.prompts.secrets.token_hex",
                return_value=COLLIDING_BOUNDARY_ID) as token_hex:
            with self.assertLogs("reply_writer.prompts", "ERROR") as recorded:
                with self.assertRaises(InternalError):
                    build_reply_messages(message, DIRECTION, self.prompts.path)
        self.assertEqual(token_hex.call_count, 32)
        logged = "\n".join(recorded.output)
        self.assertNotIn(message, logged)
        self.assertNotIn(DIRECTION, logged)


class UserPromptContractTest(unittest.TestCase):
    """ Cover the placeholder contract enforced on user.md. """

    def setUp(self):
        self.prompts = PromptDirectory()
        self.addCleanup(self.prompts.cleanup)

    def refuse(self, user):
        """ Write user.md with the given text and assert it is refused. """
        self.prompts.write("user.md", user)
        with self.assertLogs("reply_writer.prompts", "ERROR"):
            with self.assertRaises(InternalError):
                load_prompt("user.md", self.prompts.path)

    def test_refuses_a_user_prompt_missing_the_message_placeholder(self):
        """ Refuse a user prompt that never places the message. """
        self.refuse("D:{{direction}}")

    def test_refuses_a_user_prompt_missing_the_direction_placeholder(self):
        """ Refuse a user prompt that never places the direction. """
        self.refuse("M:{{message}}")

    def test_refuses_a_user_prompt_with_a_duplicate_message(self):
        """ Refuse a user prompt that places the message twice. """
        self.refuse("M:{{message}} {{message}} D:{{direction}}")

    def test_refuses_a_user_prompt_with_a_duplicate_direction(self):
        """ Refuse a user prompt that places the direction twice. """
        self.refuse("M:{{message}} D:{{direction}} {{direction}}")

    def test_refuses_a_user_prompt_with_an_unknown_placeholder(self):
        """ Refuse an unknown placeholder even where both required ones
        are present exactly once. """
        self.refuse("M:{{message}} D:{{direction}} X:{{unknown}}")

    def test_keeps_the_path_out_of_the_user_message(self):
        """ Keep an internal path off the screen on a bad contract too. """
        self.prompts.write("user.md", "M:{{message}}")
        with self.assertLogs("reply_writer.prompts", "ERROR") as recorded:
            try:
                load_prompt("user.md", self.prompts.path)
            except ReplyWriterError as error:
                self.assertNotIn(self.prompts.path, error.user_message)
            else:
                self.fail("a malformed user prompt was not refused")
        self.assertIn(self.prompts.path, "\n".join(recorded.output))


class SystemPromptContractTest(unittest.TestCase):
    """ Cover the placeholder-free contract enforced on system.md. """

    def setUp(self):
        self.prompts = PromptDirectory()
        self.addCleanup(self.prompts.cleanup)

    def refuse(self, system):
        """ Write system.md with the given text and assert it is refused. """
        self.prompts.write("system.md", system)
        with self.assertLogs("reply_writer.prompts", "ERROR"):
            with self.assertRaises(InternalError):
                load_prompt("system.md", self.prompts.path)

    def test_refuses_a_system_prompt_with_the_message_placeholder(self):
        """ Refuse a system prompt that carries {{message}}. """
        self.refuse("POLICY {{message}}")

    def test_refuses_a_system_prompt_with_the_direction_placeholder(self):
        """ Refuse a system prompt that carries {{direction}}. """
        self.refuse("POLICY {{direction}}")

    def test_refuses_a_system_prompt_with_an_unknown_placeholder(self):
        """ Refuse a system prompt that carries any other placeholder. """
        self.refuse("POLICY {{unknown}}")


class ShippedPromptsTest(unittest.TestCase):
    """ Cover the structure of the prompts the repository ships. """

    def test_both_prompts_are_present_and_not_empty(self):
        """ Ship a system prompt and a user prompt that carry text. """
        for name in ("system.md", "user.md"):
            self.assertTrue(load_prompt(name, SHIPPED_PROMPTS).strip())

    def test_the_user_prompt_carries_both_placeholders_once_each(self):
        """ Carry the message and the direction, each exactly once. """
        user = load_prompt("user.md", SHIPPED_PROMPTS)
        self.assertEqual(user.count("{{message}}"), 1)
        self.assertEqual(user.count("{{direction}}"), 1)

    def test_the_system_prompt_carries_no_placeholder(self):
        """ Carry no double-brace placeholder in the system prompt. """
        system = load_prompt("system.md", SHIPPED_PROMPTS)
        self.assertNotIn("{{", system)

    def test_the_shipped_prompts_assemble(self):
        """ Leave no placeholder behind once the two are substituted. """
        messages = build_reply_messages(MESSAGE, DIRECTION, SHIPPED_PROMPTS)
        self.assertNotIn("{{message}}", messages[1]["content"])
        self.assertNotIn("{{direction}}", messages[1]["content"])
        self.assertIn(MESSAGE, messages[1]["content"])
        self.assertIn(DIRECTION, messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
