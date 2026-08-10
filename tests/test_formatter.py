#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_formatter.py: Tests for reply_writer/formatter.py
#
#  Description:
#  This test suite covers the post processing of a generated reply. The
#  cases are of two kinds. Some pin what the formatter does: line
#  endings, a code fence wrapping the whole reply, trailing spaces and
#  runs of blank lines. The rest pin what it must not do, which is
#  everything else: no word of a reply is rewritten here, because a
#  correction applied in Python would be invisible to whoever is
#  adjusting the prompt that produced it.
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
#      python -m unittest tests.test_formatter
#
#  Test Cases:
#    - Strip the whitespace surrounding a reply.
#    - Reduce a carriage return to a single line feed.
#    - Collapse a run of blank lines to one.
#    - Remove trailing spaces from every line.
#    - Remove a code fence wrapping the whole reply, and say so.
#    - Leave a fence inside a reply alone.
#    - Raise no notice for an ordinary reply.
#    - Change no word of the reply.
#    - Fold a subject onto one line.
#    - Report an empty subject as no subject at all.
#    - Carry no subject through as no subject.
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

import unittest

from reply_writer.formatter import normalize_body, normalize_subject

# Invented material. No real correspondence is used as test data.
REPLY = "ご連絡ありがとうございます。\n\n二番目の候補でお願いいたします。"


class NormalizeBodyTest(unittest.TestCase):
    """ Cover the mechanical cleaning of a reply body. """

    def test_strips_the_surrounding_whitespace(self):
        """ Return the reply without the whitespace around it. """
        body, notices = normalize_body("\n\n  " + REPLY + "  \n\n")
        self.assertTrue(body.startswith("ご連絡"))
        self.assertTrue(body.endswith("お願いいたします。"))
        self.assertEqual(notices, [])

    def test_normalizes_line_endings(self):
        """ Reduce every line ending to a single line feed. """
        body, _ = normalize_body("one\r\ntwo\rthree")
        self.assertEqual(body, "one\ntwo\nthree")

    def test_collapses_a_run_of_blank_lines(self):
        """ Leave at most one blank line between two paragraphs. """
        body, _ = normalize_body("one\n\n\n\n\ntwo")
        self.assertEqual(body, "one\n\ntwo")

    def test_removes_trailing_spaces(self):
        """ Remove the trailing spaces a copy would otherwise carry. """
        body, _ = normalize_body("one   \ntwo\t\nthree")
        self.assertEqual(body, "one\ntwo\nthree")

    def test_removes_a_fence_wrapping_the_whole_reply(self):
        """ Remove an outer code fence and report that it was there. """
        body, notices = normalize_body("```\n" + REPLY + "\n```")
        self.assertEqual(body, REPLY)
        self.assertEqual(len(notices), 1)
        self.assertIn("fence", notices[0])

    def test_leaves_a_fence_inside_a_reply_alone(self):
        """ Touch no fence that is part of what the reply says. """
        quoted = "こちらの記録です。\n\n```\nstatus=ok\n```\n\n以上です。"
        body, notices = normalize_body(quoted)
        self.assertEqual(body, quoted)
        self.assertEqual(notices, [])

    def test_raises_no_notice_for_an_ordinary_reply(self):
        """ Say nothing about a reply that needed no cleaning. """
        body, notices = normalize_body(REPLY)
        self.assertEqual(body, REPLY)
        self.assertEqual(notices, [])

    def test_changes_no_word_of_the_reply(self):
        """
        Rewrite nothing the reply says.

        The formatter is mechanical. A phrase that reads as too
        formulaic, too long or too polite is a prompt to adjust, and
        the text arrives here exactly as the model wrote it.
        """
        wordy = "いつもお世話になっております。何卒よろしくお願い申し上げます。"
        body, notices = normalize_body(wordy)
        self.assertEqual(body, wordy)
        self.assertEqual(notices, [])


class NormalizeSubjectTest(unittest.TestCase):
    """ Cover the cleaning of a subject, where a reply carries one. """

    def test_folds_a_subject_onto_one_line(self):
        """ Fold whitespace, because a subject field takes one line. """
        self.assertEqual(normalize_subject("Re:\n 打ち合わせの件 "),
                         "Re: 打ち合わせの件")

    def test_an_empty_subject_is_no_subject(self):
        """ Read a blank subject as the absence of one. """
        for value in ("", "   ", "\n\n"):
            self.assertIsNone(normalize_subject(value))

    def test_no_subject_stays_no_subject(self):
        """ Carry an absent subject through unchanged. """
        self.assertIsNone(normalize_subject(None))


if __name__ == "__main__":
    unittest.main()
