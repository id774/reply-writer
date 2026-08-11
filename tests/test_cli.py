#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_cli.py: Tests for cli.py
#
#  Description:
#  This test suite covers the command line. It pins the exit codes, the
#  reading of the message and the direction from a file or from
#  standard input, the overrides that name the setting they replace,
#  and the refusals that happen before a request is spent.
#
#  Two of the cases are about the shape of the interface rather than
#  its behaviour: --help and --version exit 0 without any setting, and
#  neither the API token nor the base URL has an option, because a
#  command line is readable by every user of the host through ps.
#
#  No request is made. The generation core is replaced by a stub, and
#  the environment is controlled so that a .env on the host cannot
#  decide what a test sees.
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
#      python -m unittest tests.test_cli
#
#  Test Cases:
#    - Print the version and exit 0 without any setting.
#    - Print the usage and exit 0.
#    - Exit 2 when the command line is rejected.
#    - Take no option for the API token or the base URL.
#    - Generate a draft from a message file.
#    - Read the message from standard input.
#    - Generate without a direction, which is an ordinary case.
#    - Read the direction from a file where one is given.
#    - Use the same generation core as the web application.
#    - Print a subject only where the reply carries one.
#    - Print the notices apart from the reply.
#    - Print the draft as JSON on request.
#    - Override GENERATION_MODEL, PROMPT_DIR and GENERATION_TIMEOUT.
#    - Refuse a timeout that is not positive, before a request.
#    - Refuse a timeout that is not finite, before a request.
#    - Refuse a configuration that cannot address an endpoint, exiting 1.
#    - Exit 1 on an unreadable message file.
#    - Exit 1 on an empty message, and on an upstream failure.
#    - Write no message, direction or reply to the log.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only (the generation core is stubbed)
#
#  Version History:
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import io
import json
import logging
import os
import tempfile
import unittest
from unittest import mock

import cli
from reply_writer import ReplyDraft, __version__
from reply_writer.errors import UpstreamTimeoutError

# Invented material. No real correspondence is used as test data.
MESSAGE = "打ち合わせの候補日をお送りします。ご都合はいかがでしょうか。"
DIRECTION = "二番目の候補で受けること。"
REPLY = "ご連絡ありがとうございます。二番目の候補でお願いいたします。"
SUBJECT = "Re: 打ち合わせの候補日"

SETTINGS = {
    "GENERATION_BACKEND": "openai-compatible",
    "GENERATION_API_TOKEN": "test-token-value",
    "GENERATION_BASE_URL": "https://api.example.test/v1",
    "GENERATION_MODEL": "configured-model",
    "GENERATION_RESPONSE_MODE": "",
    "GENERATION_TIMEOUT": "",
    "GENERATION_MAX_RETRIES": "",
    "GENERATION_TEMPERATURE": "",
    "MAX_OUTPUT_TOKENS": "",
    "MAX_INPUT_CHARS": "",
    "MAX_POLICY_CHARS": "",
    "PROMPT_DIR": "",
    "LOG_LEVEL": "",
    "PORT": "",
}


def draft(body=REPLY, subject=None, notices=None):
    """ Return a draft the stubbed generation core hands back. """
    return ReplyDraft(body=body, subject=subject, model="test-model",
                      generated_at="2026-08-10T12:00:00+09:00",
                      notices=notices or [])


class CliTestCase(unittest.TestCase):
    """ Shared temporary files, environment and stubbing. """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.message_file = self.write("message.txt", MESSAGE)

    def write(self, name, text):
        """ Write one file into the temporary directory. """
        path = os.path.join(self.directory.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def run_cli(self, arguments, result=None, stdin="", settings=None):
        """ Run one command with the generation core stubbed. """
        if result is None:
            result = draft()

        environment = dict(SETTINGS)
        environment.update(settings or {})

        self.out = io.StringIO()
        self.err = io.StringIO()
        self.log = io.StringIO()

        # The handler is attached before main() runs, so that the
        # basicConfig() call inside it finds the root logger already
        # configured and does not bind a handler to the standard error
        # this test replaced.
        handler = logging.StreamHandler(self.log)
        root = logging.getLogger()
        root.addHandler(handler)
        self.addCleanup(root.removeHandler, handler)

        with mock.patch.dict("os.environ", environment, clear=True), \
                mock.patch("config.load_dotenv", None), \
                mock.patch("sys.argv", ["cli.py"] + arguments), \
                mock.patch("sys.stdin", io.StringIO(stdin)), \
                mock.patch("sys.stdout", self.out), \
                mock.patch("sys.stderr", self.err), \
                mock.patch("cli.generate_reply") as generate:
            if isinstance(result, Exception):
                generate.side_effect = result
            else:
                generate.return_value = result
            self.generate = generate
            return cli.main()

    @property
    def printed(self) -> str:
        """ Return what the command wrote to standard output. """
        return self.out.getvalue()

    @property
    def logged(self) -> str:
        """ Return what the command wrote to the log. """
        return self.log.getvalue()


class InterfaceTest(CliTestCase):
    """ Cover help, version and the shape of the command line. """

    def test_version_exits_zero_without_any_setting(self):
        """ Answer --version with no token and no endpoint configured. """
        out = io.StringIO()
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("sys.stdout", out):
            with self.assertRaises(SystemExit) as exit_status:
                cli.build_parser().parse_args(["--version"])
        self.assertEqual(exit_status.exception.code, 0)
        self.assertIn(__version__, out.getvalue())

    def test_help_exits_zero(self):
        """ Answer --help to a user who asked for it. """
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            with self.assertRaises(SystemExit) as exit_status:
                cli.build_parser().parse_args(["--help"])
        self.assertEqual(exit_status.exception.code, 0)
        self.assertIn("generate", out.getvalue())

    def test_a_rejected_command_line_exits_two(self):
        """ Leave argparse to refuse an unknown option. """
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as exit_status:
                cli.build_parser().parse_args(["generate", "--nowhere"])
        self.assertEqual(exit_status.exception.code, 2)

    def test_no_option_carries_a_credential_or_an_endpoint(self):
        """
        Take neither the token nor the base URL on the command line.

        A command line is readable by every user of the host through
        ps. The token is a secret, and the endpoint is a decision of
        the deployment rather than of one run.
        """
        usage = cli.build_parser().format_help()
        for option in ("--token", "--api-token", "--base-url", "--port"):
            self.assertNotIn(option, usage)


class GenerationTest(CliTestCase):
    """ Cover one generation from the command line. """

    def test_generates_from_a_message_file(self):
        """ Read the message from a file and print the reply. """
        status = self.run_cli(["generate", "--message", self.message_file])
        self.assertEqual(status, 0)
        self.assertIn(REPLY, self.printed)
        self.assertEqual(self.generate.call_args[0][0], MESSAGE)

    def test_reads_the_message_from_standard_input(self):
        """ Read the message from standard input when asked with '-'. """
        status = self.run_cli(["generate", "--message", "-"], stdin=MESSAGE)
        self.assertEqual(status, 0)
        self.assertEqual(self.generate.call_args[0][0], MESSAGE)

    def test_generates_without_a_direction(self):
        """ Treat an absent direction as ordinary, not as a failure. """
        status = self.run_cli(["generate", "--message", self.message_file])
        self.assertEqual(status, 0)
        self.assertEqual(self.generate.call_args[0][1], "")

    def test_reads_the_direction_from_a_file(self):
        """ Read the direction from a file where one is named. """
        path = self.write("direction.txt", DIRECTION)
        self.run_cli(["generate", "--message", self.message_file,
                      "--direction", path])
        self.assertEqual(self.generate.call_args[0][1], DIRECTION)

    def test_uses_the_same_generation_core_as_the_web_application(self):
        """
        Call the one core, so the two interfaces cannot diverge.

        cli.py imports the one generation core, the same function
        app.py calls. Nothing here reimplements a step of it, and the
        core is reached without Flask being importable at all.
        """
        from reply_writer import generator
        self.assertIs(cli.generate_reply, generator.generate_reply)

    def test_prints_a_subject_only_when_there_is_one(self):
        """ Print no subject line for a medium that has no subject. """
        self.run_cli(["generate", "--message", self.message_file])
        self.assertNotIn("Subject:", self.printed)

        self.run_cli(["generate", "--message", self.message_file],
                     result=draft(subject=SUBJECT))
        self.assertIn("Subject: " + SUBJECT, self.printed)

    def test_prints_the_notices_apart_from_the_reply(self):
        """ Keep a notice off standard output, where the reply goes. """
        self.run_cli(["generate", "--message", self.message_file],
                     result=draft(notices=["A code fence was removed."]))
        self.assertNotIn("code fence", self.printed)
        self.assertIn("code fence", self.err.getvalue())

    def test_prints_the_draft_as_json_on_request(self):
        """ Print the whole draft as JSON for a pipe. """
        self.run_cli(["generate", "--message", self.message_file, "--json"],
                     result=draft(subject=SUBJECT))
        payload = json.loads(self.printed)
        self.assertEqual(payload["body"], REPLY)
        self.assertEqual(payload["subject"], SUBJECT)


class OverrideTest(CliTestCase):
    """ Cover the options that replace a named setting. """

    def config_used(self):
        """ Return the configuration the generation core was handed. """
        return self.generate.call_args[0][2]

    def test_overrides_the_model(self):
        """ Replace GENERATION_MODEL for this invocation. """
        self.run_cli(["generate", "--message", self.message_file,
                      "--model", "another-model"])
        self.assertEqual(self.config_used().generation_model,
                         "another-model")

    def test_overrides_the_prompt_directory(self):
        """ Replace PROMPT_DIR, so a prompt can be tried in place. """
        self.run_cli(["generate", "--message", self.message_file,
                      "--prompt-dir", self.directory.name])
        self.assertEqual(self.config_used().prompt_dir, self.directory.name)

    def test_overrides_the_timeout(self):
        """ Replace GENERATION_TIMEOUT for this invocation. """
        self.run_cli(["generate", "--message", self.message_file,
                      "--timeout", "30"])
        self.assertEqual(self.config_used().generation_timeout, 30.0)

    def test_an_absent_option_changes_nothing(self):
        """ Leave every setting as configured when no option is given. """
        self.run_cli(["generate", "--message", self.message_file])
        config = self.config_used()
        self.assertEqual(config.generation_model, "configured-model")
        self.assertEqual(config.generation_timeout, 120.0)
        self.assertEqual(config.prompt_dir, "prompts")

    def test_refuses_a_timeout_that_is_not_positive(self):
        """ Refuse it here too, before a request is spent. """
        status = self.run_cli(["generate", "--message", self.message_file,
                               "--timeout", "0"])
        self.assertEqual(status, 1)
        self.generate.assert_not_called()

    def test_refuses_a_timeout_that_is_not_finite(self):
        """
        Refuse nan and infinity, which argparse reads as numbers.

        A comparison against nan is false whichever way it is written,
        so the test for a positive number lets it through on its own
        and the value would reach the SDK as the limit of a request.
        """
        # Written as one argument, because a value beginning with a
        # minus sign reads as another option on its own.
        for value in ("nan", "inf", "-inf"):
            status = self.run_cli(["generate", "--message",
                                   self.message_file,
                                   "--timeout={0}".format(value)])
            self.assertEqual(status, 1)
            self.generate.assert_not_called()


class FailureTest(CliTestCase):
    """ Cover the exit codes of the failures the command reports. """

    def test_refuses_a_configuration_that_cannot_address_an_endpoint(self):
        """ Report the setting at fault and spend no request. """
        status = self.run_cli(["generate", "--message", self.message_file],
                              settings={"GENERATION_BASE_URL": ""})
        self.assertEqual(status, 1)
        self.assertIn("GENERATION_BASE_URL", self.logged)
        self.generate.assert_not_called()

    def test_refuses_an_unknown_backend(self):
        """ Refuse a backend this version has no provider for. """
        status = self.run_cli(["generate", "--message", self.message_file],
                              settings={"GENERATION_BACKEND": "unknown"})
        self.assertEqual(status, 1)
        self.generate.assert_not_called()

    def test_exits_one_on_an_unreadable_message_file(self):
        """ Report a file that cannot be read, without a traceback. """
        status = self.run_cli(["generate", "--message",
                               os.path.join(self.directory.name, "absent")])
        self.assertEqual(status, 1)
        self.assertNotIn("Traceback", self.logged)

    def test_exits_one_on_an_upstream_failure(self):
        """ Report a failed generation as a failed command. """
        status = self.run_cli(["generate", "--message", self.message_file],
                              result=UpstreamTimeoutError())
        self.assertEqual(status, 1)
        self.assertIn("UpstreamTimeoutError", self.logged)


class LogPrivacyTest(CliTestCase):
    """
    Guard the invariant that no text of a person's reaches the log.

    The command line writes to the same log as the web application, and
    the same rule holds there: a message, a direction and a reply are
    never recorded. This case is not deleted to make a refactor pass.
    """

    def test_no_text_reaches_the_log(self):
        """ Write no message, direction or reply, on either path. """
        path = self.write("direction.txt", DIRECTION)
        with self.assertLogs(logging.getLogger(), "DEBUG") as recorded:
            logging.getLogger("tests").info("generating")
            self.run_cli(["generate", "--message", self.message_file,
                          "--direction", path],
                         result=draft(subject=SUBJECT))
            self.run_cli(["generate", "--message", self.message_file,
                          "--direction", path],
                         result=UpstreamTimeoutError())

        written = "\n".join(recorded.output)
        for text in (MESSAGE, DIRECTION, REPLY, SUBJECT):
            self.assertNotIn(text, written)


if __name__ == "__main__":
    unittest.main()
