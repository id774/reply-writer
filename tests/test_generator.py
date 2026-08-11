#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_generator.py: Tests for reply_writer/generator.py
#
#  Description:
#  This test suite covers the generation core: the refusals it makes
#  before a request is spent, the one request it spends, and the
#  reading of the structured answer that comes back.
#
#  No request is made. The provider is replaced by a stub that records
#  what it was handed and returns a prepared answer, which is also what
#  keeps the suite honest about the layering: the core is exercised
#  with no SDK installed and no endpoint configured.
#
#  Two cases here guard an invariant rather than a feature. One is that
#  an answer is never taken apart by heuristic: an object buried in
#  prose is refused instead of being cut out, because that is the path
#  by which a remark from the model becomes part of a reply somebody
#  sends. The other is that nothing entered and nothing generated
#  reaches the log, at any level.
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
#      python -m unittest tests.test_generator
#
#  Test Cases:
#    - Refuse an empty message before a request is spent.
#    - Refuse a message longer than MAX_INPUT_CHARS.
#    - Refuse a direction longer than MAX_POLICY_CHARS.
#    - Accept a message with no direction.
#    - Carry the direction through to the prompt layer.
#    - Spend exactly one request for one generation.
#    - Carry the request id down to the provider.
#    - Read a reply that carries a subject.
#    - Read a reply that carries none, from null and from an absent field.
#    - Refuse a subject that is neither a string nor null.
#    - Clean the reply body through the formatter.
#    - Refuse an answer that is not JSON.
#    - Refuse an answer that is JSON but not an object.
#    - Refuse an answer with no body, and one whose body is blank.
#    - Refuse an answer whose body is not a string.
#    - Unwrap a fenced object under prompt-json.
#    - Unwrap a fenced object whose reply speaks of a fence.
#    - Refuse a body that is empty once its markup is removed.
#    - Refuse an object buried in prose rather than cut it out.
#    - Refuse a fenced object under json-object mode.
#    - Report the model the answer named.
#    - Let an upstream failure through unchanged.
#    - Import the whole core with no web framework available.
#    - Write no message, direction or reply to the log.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only (the provider is stubbed, the SDK unused)
#
#  Version History:
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from config import Config
from reply_writer.errors import (DirectionTooLongError, EmptyInputError,
                                 InputTooLongError, InvalidResponseError,
                                 UpstreamTimeoutError)
from reply_writer.generator import generate_reply
from reply_writer.providers import CompletionResult

# Invented material. No real correspondence is used as test data.
MESSAGE = "打ち合わせの候補日をお送りします。ご都合はいかがでしょうか。"
DIRECTION = "二番目の候補で受けること。"
REPLY = "ご連絡ありがとうございます。\n\n二番目の候補でお願いいたします。"
SUBJECT = "Re: 打ち合わせの候補日"


class StubProvider:
    """ A provider that records one call and returns a prepared answer. """

    def __init__(self, content, model="answering-model"):
        self.content = content
        self.model = model
        self.calls = []

    def complete(self, messages, config, request_id=""):
        """ Record the call and return the prepared answer. """
        self.calls.append({"messages": messages, "config": config,
                           "request_id": request_id})
        return CompletionResult(content=self.content, model=self.model)


class GeneratorTestCase(unittest.TestCase):
    """ Shared prompt directory, configuration and provider stubbing. """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.write("system.md", "POLICY")
        self.write("user.md", "D:{{direction}} M:{{message}}")

        self.config = Config(
            generation_backend="openai-compatible",
            generation_api_token="test-token",
            generation_base_url="https://api.example.test/v1",
            generation_model="configured-model",
            prompt_dir=self.directory.name,
        )

    def write(self, name, text):
        """ Write one prompt file into the temporary directory. """
        with open(os.path.join(self.directory.name, name), "w",
                  encoding="utf-8") as handle:
            handle.write(text)

    def answer(self, **fields):
        """ Return an answer carrying the given JSON fields. """
        return json.dumps(fields, ensure_ascii=False)

    def generate(self, content=None, message=MESSAGE, direction="",
                 request_id="", provider=None, **overrides):
        """ Generate one reply against a stubbed provider. """
        if provider is None:
            provider = StubProvider(
                content if content is not None
                else self.answer(subject=None, body=REPLY))
        self.provider = provider

        config = self.config
        for name, value in overrides.items():
            setattr(config, name, value)

        with mock.patch("reply_writer.generator.build_provider",
                        return_value=provider):
            return generate_reply(message, direction, config, request_id)


class InputValidationTest(GeneratorTestCase):
    """ Cover the refusals made before a request is spent. """

    def test_refuses_an_empty_message(self):
        """ Refuse an empty message without calling the provider. """
        provider = StubProvider("unused")
        for message in ("", "   ", "\n\n"):
            with self.assertRaises(EmptyInputError):
                self.generate(message=message, provider=provider)
        self.assertEqual(provider.calls, [])

    def test_refuses_a_message_that_is_too_long(self):
        """ Refuse a message beyond MAX_INPUT_CHARS, naming the limit. """
        provider = StubProvider("unused")
        with self.assertRaises(InputTooLongError) as refusal:
            self.generate(message="あ" * 21, provider=provider,
                          max_input_chars=20)
        self.assertIn("20", refusal.exception.user_message)
        self.assertEqual(provider.calls, [])

    def test_refuses_a_direction_that_is_too_long(self):
        """ Refuse a direction beyond MAX_POLICY_CHARS. """
        provider = StubProvider("unused")
        with self.assertRaises(DirectionTooLongError) as refusal:
            self.generate(direction="い" * 11, provider=provider,
                          max_policy_chars=10)
        self.assertIn("10", refusal.exception.user_message)
        self.assertEqual(provider.calls, [])


class GenerationTest(GeneratorTestCase):
    """ Cover one generation from the input to the draft. """

    def test_generates_without_a_direction(self):
        """ Generate a draft when no direction was given. """
        draft = self.generate(direction="")
        self.assertEqual(draft.body, REPLY)
        self.assertEqual(self.provider.calls[0]["messages"][1]["content"],
                         "D: M:{0}".format(MESSAGE))

    def test_carries_the_direction_to_the_prompt(self):
        """ Hand the direction to the prompt layer where there is one. """
        self.generate(direction=DIRECTION)
        self.assertEqual(self.provider.calls[0]["messages"][1]["content"],
                         "D:{0} M:{1}".format(DIRECTION, MESSAGE))

    def test_spends_one_request(self):
        """ Spend exactly one request for one generation. """
        self.generate()
        self.assertEqual(len(self.provider.calls), 1)

    def test_carries_the_request_id_to_the_provider(self):
        """ Let one generation be followed through the log by its id. """
        self.generate(request_id="abcd1234")
        self.assertEqual(self.provider.calls[0]["request_id"], "abcd1234")

    def test_reads_a_reply_with_a_subject(self):
        """ Keep a subject in its own field, apart from the body. """
        draft = self.generate(self.answer(subject=SUBJECT, body=REPLY))
        self.assertEqual(draft.subject, SUBJECT)
        self.assertEqual(draft.body, REPLY)
        self.assertNotIn(SUBJECT, draft.body)

    def test_reads_a_reply_without_a_subject(self):
        """ Read a null and an absent subject as no subject at all. """
        self.assertIsNone(self.generate(self.answer(subject=None,
                                                    body=REPLY)).subject)
        self.assertIsNone(self.generate(self.answer(body=REPLY)).subject)
        self.assertIsNone(self.generate(self.answer(subject="  ",
                                                    body=REPLY)).subject)

    def test_cleans_the_body_through_the_formatter(self):
        """ Clean the body mechanically before it reaches a screen. """
        draft = self.generate(self.answer(body="  one\r\n\n\n\ntwo  "))
        self.assertEqual(draft.body, "one\n\ntwo")

    def test_reports_the_model_the_answer_named(self):
        """ Report the model that answered, not only the one asked. """
        self.assertEqual(self.generate().model, "answering-model")
        self.assertEqual(
            self.generate(provider=StubProvider(
                self.answer(body=REPLY), model="")).model, "configured-model")

    def test_generated_at_is_recorded(self):
        """ Stamp the draft with the time it was generated. """
        self.assertTrue(self.generate().generated_at)


class InvalidAnswerTest(GeneratorTestCase):
    """ Cover the refusal of an answer that did not keep the contract. """

    def refuse(self, content, **overrides):
        """ Assert that the given answer is refused, and log the reason. """
        with self.assertLogs("reply_writer.generator", "ERROR"):
            with self.assertRaises(InvalidResponseError):
                self.generate(content, **overrides)

    def test_refuses_an_answer_that_is_not_json(self):
        """ Refuse prose where an object was asked for. """
        self.refuse("ご連絡ありがとうございます。")

    def test_refuses_json_that_is_not_an_object(self):
        """ Refuse a list or a bare string. """
        self.refuse('["a", "b"]')
        self.refuse('"a reply"')

    def test_refuses_an_answer_with_no_body(self):
        """ Refuse an answer missing the one required field. """
        self.refuse(self.answer(subject=SUBJECT))

    def test_refuses_a_blank_body(self):
        """ Refuse a body that carries no reply. """
        self.refuse(self.answer(subject=None, body="   "))

    def test_refuses_a_body_that_is_not_a_string(self):
        """ Refuse a body of the wrong type rather than coerce it. """
        self.refuse(self.answer(subject=None, body=["a"]))

    def test_refuses_a_subject_that_is_neither_a_string_nor_null(self):
        """ Refuse a subject of the wrong type rather than coerce it. """
        self.refuse(self.answer(subject=["Re:"], body=REPLY))

    def test_unwraps_a_fenced_object_under_prompt_json(self):
        """ Accept a whole answer wrapped in one fence in that mode. """
        fenced = "```json\n{0}\n```".format(self.answer(body=REPLY))
        draft = self.generate(fenced,
                              generation_response_mode="prompt-json")
        self.assertEqual(draft.body, REPLY)

    def test_unwraps_a_fenced_object_whose_reply_speaks_of_a_fence(self):
        """
        Read the object even where the reply mentions a fence.

        The answer is one JSON object, and a string in it holds no line
        break, so those characters inside the reply sit in the middle
        of a line and open no block. Refusing the answer on the
        characters alone would throw away a reply for what it says.
        """
        reply = "コードは ``` で囲んでお送りください。"
        fenced = "```json\n{0}\n```".format(
            self.answer(subject=None, body=reply))
        draft = self.generate(fenced,
                              generation_response_mode="prompt-json")
        self.assertEqual(draft.body, reply)

    def test_refuses_a_body_that_is_empty_once_cleaned(self):
        """
        Refuse a body holding nothing but the markup around it.

        A body of two fence lines passes the check for a blank field
        and leaves nothing behind once the fence is removed. An empty
        draft on the screen reads as a fault of the screen, so the
        answer is refused instead.
        """
        self.refuse(self.answer(subject=None, body="```\n```"))

    def test_refuses_an_object_buried_in_prose(self):
        """
        Refuse an object with prose around it, rather than cut it out.

        Cutting an object out of surrounding prose is the heuristic
        that lets a remark by the model become part of a reply. An
        endpoint that explains itself first is misconfigured, and
        reading past the explanation would hide that.
        """
        self.refuse("Here is the reply:\n{0}\nHope it helps.".format(
            self.answer(body=REPLY)))

    def test_refuses_a_fenced_object_under_json_object_mode(self):
        """
        Keep the configured mode, and do not try the other one.

        json-object asks the API itself for an object. An answer that
        arrives fenced under that mode means the mode is not working,
        and unwrapping it here would hide a misconfiguration that only
        the operator can fix.
        """
        fenced = "```json\n{0}\n```".format(self.answer(body=REPLY))
        self.refuse(fenced, generation_response_mode="json-object")

    def test_an_upstream_failure_passes_through(self):
        """ Let a provider failure travel to the caller unchanged. """
        class FailingProvider:
            def complete(self, messages, config, request_id=""):
                raise UpstreamTimeoutError()

        with self.assertRaises(UpstreamTimeoutError):
            self.generate(provider=FailingProvider())


class LayerSeparationTest(unittest.TestCase):
    """
    Guard the separation of the web layer from the generation core.

    The core is what the command line and the web application share.
    The moment it reaches for a request object or builds a page, the
    two stop being the same generation, and a fault found in one can no
    longer be reproduced in the other.
    """

    def test_the_core_imports_without_a_web_framework(self):
        """ Import the whole core with Flask and werkzeug blocked. """
        modules = ("reply_writer.generator", "reply_writer.prompts",
                   "reply_writer.formatter", "reply_writer.providers",
                   "reply_writer.errors", "config")
        source = (
            "import sys\n"
            "class Blocker:\n"
            "    def find_module(self, name, path=None):\n"
            "        if name.split('.')[0] in ('flask', 'werkzeug'):\n"
            "            return self\n"
            "    def load_module(self, name):\n"
            "        raise ImportError(name)\n"
            "sys.meta_path.insert(0, Blocker())\n"
            "import " + ", ".join(modules) + "\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", source],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


class LogPrivacyTest(GeneratorTestCase):
    """
    Guard the invariant that no text of a person's reaches the log.

    This case exists to protect the invariant rather than a feature. A
    log that carried the message, the direction or the reply would keep
    private correspondence on the server after the request that carried
    it had ended, which is exactly what the requirements forbid. It is
    not deleted to make a refactor pass.
    """

    def assert_nothing_entered_was_logged(self, records):
        """ Assert that no recorded line carries any of the text. """
        written = "\n".join(records)
        for text in (MESSAGE, DIRECTION, REPLY, SUBJECT):
            self.assertNotIn(text, written)

    def test_a_successful_generation_writes_no_text(self):
        """ Write no message, direction or reply on the ordinary path. """
        with self.assertLogs(logging.getLogger(), "DEBUG") as recorded:
            # One line of its own, so that assertLogs has something to
            # find even when the generation itself logs nothing.
            logging.getLogger("tests").info("generating")
            draft = self.generate(self.answer(subject=SUBJECT, body=REPLY),
                                  direction=DIRECTION)
        self.assertEqual(draft.body, REPLY)
        self.assert_nothing_entered_was_logged(recorded.output)

    def test_a_refused_answer_writes_no_text(self):
        """ Write none of it when the answer has to be refused either. """
        with self.assertLogs(logging.getLogger(), "DEBUG") as recorded:
            with self.assertRaises(InvalidResponseError):
                self.generate("ご連絡ありがとうございます。" + REPLY,
                              direction=DIRECTION)
        self.assert_nothing_entered_was_logged(recorded.output)

    def test_a_refused_input_writes_no_text(self):
        """ Write none of it when the input itself is refused. """
        with self.assertLogs(logging.getLogger(), "DEBUG") as recorded:
            logging.getLogger("tests").info("generating")
            with self.assertRaises(InputTooLongError):
                self.generate(direction=DIRECTION, max_input_chars=5)
        self.assert_nothing_entered_was_logged(recorded.output)


if __name__ == "__main__":
    unittest.main()
