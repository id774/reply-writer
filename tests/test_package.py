#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_package.py: Tests for reply_writer/__init__.py
#
#  Description:
#  This test suite covers what the package root carries: the draft that
#  one generation produces, the request id a run is followed by, and
#  the configuration of the log.
#
#  The log cases guard an invariant rather than a feature. The API
#  client records its request options at DEBUG, and those options carry
#  the assembled prompts, so raising LOG_LEVEL to chase a fault would
#  otherwise write a person's message into the journal. Lowering those
#  loggers is what keeps the promise that no text is recorded at any
#  level, and it is not removed to make a refactor pass.
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
#      python -m unittest tests.test_package
#
#  Test Cases:
#    - Carry a body, and no subject unless the reply has one.
#    - Return a different request id each time.
#    - Derive a request id from nothing that was entered.
#    - Apply the configured level to the application log.
#    - Read an unknown level as INFO rather than refuse to run.
#    - Apply a level again once the settings have been read.
#    - Keep the client loggers quiet, even at DEBUG.
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

import logging
import unittest

from reply_writer import (QUIET_LOGGERS, ReplyDraft, configure_logging,
                          new_request_id)


class ReplyDraftTest(unittest.TestCase):
    """ Cover the result one generation produces. """

    def test_a_draft_needs_only_a_body(self):
        """ Carry a reply, and no subject unless there is one. """
        draft = ReplyDraft(body="ご連絡ありがとうございます。")
        self.assertIsNone(draft.subject)
        self.assertEqual(draft.notices, [])

    def test_notices_are_not_shared_between_drafts(self):
        """ Give each draft its own list of notices. """
        first = ReplyDraft(body="one")
        first.notices.append("a notice")
        self.assertEqual(ReplyDraft(body="two").notices, [])


class RequestIdTest(unittest.TestCase):
    """ Cover the identifier one generation is followed by. """

    def test_each_request_id_differs(self):
        """ Tell one run apart from another in the log. """
        self.assertEqual(len({new_request_id() for _ in range(50)}), 50)

    def test_a_request_id_is_a_short_hexadecimal_string(self):
        """
        Carry nothing that was entered.

        The id is random rather than derived from the message, so that
        an identifier printed on a screen and written to a journal
        holds no part of private correspondence.
        """
        request_id = new_request_id()
        self.assertTrue(request_id)
        int(request_id, 16)


class ConfigureLoggingTest(unittest.TestCase):
    """ Cover the configuration of the application log. """

    def setUp(self):
        root = logging.getLogger()
        level = root.level
        self.addCleanup(root.setLevel, level)
        for name in QUIET_LOGGERS:
            quiet = logging.getLogger(name)
            self.addCleanup(quiet.setLevel, quiet.level)

    def test_applies_the_configured_level(self):
        """ Set the application log to the level LOG_LEVEL names. """
        configure_logging("WARNING")
        self.assertEqual(logging.getLogger().level, logging.WARNING)

    def test_reads_an_unknown_level_as_info(self):
        """ Refuse no run over a misspelled level. """
        configure_logging("VERBOSE")
        self.assertEqual(logging.getLogger().level, logging.INFO)

    def test_applies_a_level_on_a_second_call(self):
        """
        Take effect the second time as well.

        An entry point calls this twice: once before the settings are
        read, so a refused setting is reported in the usual format, and
        once after. basicConfig() does nothing on the second call, so
        the level is applied explicitly.
        """
        configure_logging("INFO")
        configure_logging("ERROR")
        self.assertEqual(logging.getLogger().level, logging.ERROR)

    def test_keeps_the_client_loggers_quiet_at_debug(self):
        """
        Lower the loggers that would print the exchange itself.

        The API client records its request options at DEBUG, and those
        options carry the assembled prompts. Raising LOG_LEVEL to chase
        a fault must not turn a person's message into a journal entry.
        """
        configure_logging("DEBUG")
        self.assertEqual(logging.getLogger().level, logging.DEBUG)
        for name in QUIET_LOGGERS:
            self.assertEqual(logging.getLogger(name).level, logging.WARNING)
            self.assertFalse(logging.getLogger(name).isEnabledFor(
                logging.DEBUG))


if __name__ == "__main__":
    unittest.main()
