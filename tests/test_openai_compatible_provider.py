#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_openai_compatible_provider.py: Tests for the OpenAI compatible provider
#
#  Description:
#  This test suite covers the one provider the application ships with.
#  It pins what reaches the SDK, namely the token, the base URL, the
#  retry count and the timeout on the client, and the model, the
#  messages, the output limit, the response format per mode and the
#  temperature on the request. It covers the normalization of an answer
#  into a CompletionResult, the refusal of an answer that carries no
#  usable content, and the mapping of a timeout, a connection failure
#  and an error status onto the error hierarchy.
#
#  The openai package is never imported. A stand-in module is installed
#  in sys.modules for the duration of a call, so the suite needs
#  neither the dependency nor a network. Its exception classes are
#  defined once at module level rather than per call, because the
#  provider catches them by identity.
#
#  The log cases are part of the contract rather than an extra: a line
#  records the shape of an exchange and never its content, and the
#  elapsed seconds appear next to the limit on a success and on a
#  timeout alike, because only that pair says whether the limit was
#  reached or the connection died well short of it.
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
#      python -m unittest tests.test_openai_compatible_provider
#
#  Test Cases:
#    - Hand the token and the base URL to the SDK.
#    - Pass the base URL even when it is empty, so the SDK never falls back.
#    - Spend one request by default, with the configured timeout.
#    - Send the model, the messages and the output limit.
#    - Ask for a JSON object under json-object mode.
#    - Send no response format under prompt-json mode.
#    - Send no temperature unless it is set, and send it when it is.
#    - Never stream.
#    - Normalize a well formed answer, including the usage counters.
#    - Measure how long the one request took.
#    - Accept an answer that carries no usage.
#    - Fall back to the configured model name when the answer names none.
#    - Refuse an answer without a choice.
#    - Refuse an empty content, and a content that is not a string.
#    - Refuse an answer cut off by the output limit.
#    - Map a timeout onto UpstreamTimeoutError.
#    - Map a connection failure onto UpstreamConnectionError.
#    - Map 401, 403, 429 and 500 onto one user facing error.
#    - Map any remaining SDK error onto one of our own.
#    - Try no second endpoint when the first one fails.
#    - Record the shape of an answer without its content or the token.
#    - Record the request id of the generation on both lines.
#    - Record the wait next to the limit on an answer and on a timeout.
#    - Keep the token and the reply out of a failure line.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only (the openai package is stubbed, never imported)
#
#  Version History:
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import sys
import unittest
from types import ModuleType, SimpleNamespace

from config import Config
from reply_writer.errors import (InvalidResponseError, UpstreamConnectionError,
                                 UpstreamStatusError, UpstreamTimeoutError)
from reply_writer.providers.openai_compatible import OpenAICompatibleProvider

TOKEN = "00000000-0000-0000-0000-000000000000:secret-value"

# Invented material. No real correspondence is used as test data.
REPLY = '{"subject": null, "body": "ご連絡ありがとうございます。"}'
MESSAGES = [
    {"role": "system", "content": "POLICY"},
    {"role": "user", "content": "D: M:打ち合わせの候補日をお送りします。"},
]


class FakeError(Exception):
    """
    Base of the exception classes the stand-in SDK raises.

    It stands in for openai.APIError as well, which is the base the
    real classes share. A stand-in raised as itself is therefore an
    error of the SDK that belongs to none of the three cases told
    apart, which is what the provider has to map on its own.
    """


class FakeTimeoutError(FakeError):
    """ Stands in for openai.APITimeoutError. """


class FakeConnectionError(FakeError):
    """ Stands in for openai.APIConnectionError. """


class FakeStatusError(FakeError):
    """ Stands in for openai.APIStatusError. """

    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.status_code = status_code


def answer(content=REPLY, model="answering-model", finish_reason="stop",
           usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22,
                                 total_tokens=33), identifier="upstream-1"):
    """ Return a stand-in for one Chat Completions response. """
    choice = SimpleNamespace(finish_reason=finish_reason,
                             message=SimpleNamespace(content=content))
    return SimpleNamespace(choices=[choice], model=model, usage=usage,
                           id=identifier)


def config(**overrides) -> Config:
    """ Return a configuration that can address an endpoint. """
    values = {
        "generation_backend": "openai-compatible",
        "generation_api_token": TOKEN,
        "generation_base_url": "https://api.example.test/v1",
        "generation_model": "configured-model",
        "max_output_tokens": 2000,
    }
    values.update(overrides)
    return Config(**values)


class FakeSDK:
    """ A stand-in openai module recording what the provider does. """

    def __init__(self, result=None, error=None):
        self.result = result if result is not None else answer()
        self.error = error
        self.client_arguments = None
        self.request = None

    def install(self, test):
        """ Put the stand-in in sys.modules for the duration of a test. """
        module = ModuleType("openai")
        module.APITimeoutError = FakeTimeoutError
        module.APIConnectionError = FakeConnectionError
        module.APIStatusError = FakeStatusError
        module.APIError = FakeError
        module.OpenAI = self._client
        test.addCleanup(sys.modules.pop, "openai", None)
        sys.modules["openai"] = module

    def _client(self, **arguments):
        """ Record how the client was built and return a stand-in. """
        self.client_arguments = arguments
        completions = SimpleNamespace(create=self._create)
        return SimpleNamespace(
            chat=SimpleNamespace(completions=completions))

    def _create(self, **request):
        """ Record the one request and answer it. """
        if self.request is not None:
            raise AssertionError("more than one request was spent")
        self.request = request
        if self.error is not None:
            raise self.error
        return self.result


class ProviderTestCase(unittest.TestCase):
    """ Shared installation of the stand-in SDK. """

    def complete(self, sdk=None, settings=None, request_id="abcd1234"):
        """ Run one complete() call against the stand-in SDK. """
        self.sdk = sdk if sdk is not None else FakeSDK()
        self.sdk.install(self)
        self.config = settings if settings is not None else config()
        return OpenAICompatibleProvider().complete(
            MESSAGES, self.config, request_id)

    def fail_with(self, error):
        """ Run one call that fails, and return the error and the log. """
        with self.assertLogs("reply_writer.providers.openai_compatible",
                             "ERROR") as recorded:
            with self.assertRaises(Exception) as raised:
                self.complete(FakeSDK(error=error))
        return raised.exception, recorded.output


class ClientTest(ProviderTestCase):
    """ Cover what reaches the SDK when the client is built. """

    def test_hands_the_token_and_the_base_url_to_the_sdk(self):
        """ Address the endpoint the configuration names, with its token. """
        self.complete()
        self.assertEqual(self.sdk.client_arguments["api_key"], TOKEN)
        self.assertEqual(self.sdk.client_arguments["base_url"],
                         "https://api.example.test/v1")

    def test_passes_the_base_url_even_when_it_is_empty(self):
        """
        Pass the base URL unconditionally.

        An omitted base_url lets the SDK fall back to the endpoint
        compiled into it, which is the one thing this design refuses.
        config.py rejects an empty value earlier; this keeps the
        guarantee local as well.
        """
        self.complete(settings=config(generation_base_url=""))
        self.assertEqual(self.sdk.client_arguments["base_url"], "")

    def test_spends_one_request_with_the_configured_timeout(self):
        """ Leave the SDK no retry, and give it an explicit timeout. """
        self.complete(settings=config(generation_timeout=45.0))
        self.assertEqual(self.sdk.client_arguments["max_retries"], 0)
        self.assertEqual(self.sdk.client_arguments["timeout"], 45.0)

    def test_passes_a_retry_count_an_operator_chose(self):
        """ Leave the count where an operator can see it. """
        self.complete(settings=config(generation_max_retries=2))
        self.assertEqual(self.sdk.client_arguments["max_retries"], 2)


class RequestTest(ProviderTestCase):
    """ Cover the one request the provider assembles. """

    def test_sends_the_model_the_messages_and_the_limit(self):
        """ Send what one generation needs and nothing more. """
        self.complete()
        self.assertEqual(self.sdk.request["model"], "configured-model")
        self.assertEqual(self.sdk.request["messages"], MESSAGES)
        self.assertEqual(self.sdk.request["max_tokens"], 2000)

    def test_asks_for_a_json_object_under_json_object_mode(self):
        """ Ask the API itself for an object in that mode. """
        self.complete(settings=config(generation_response_mode="json-object"))
        self.assertEqual(self.sdk.request["response_format"],
                         {"type": "json_object"})

    def test_sends_no_response_format_under_prompt_json_mode(self):
        """ Leave the contract to the prompt in that mode. """
        self.complete(settings=config(generation_response_mode="prompt-json"))
        self.assertNotIn("response_format", self.sdk.request)

    def test_sends_a_temperature_only_when_it_is_set(self):
        """ Keep the endpoint default unless a temperature was chosen. """
        self.complete()
        self.assertNotIn("temperature", self.sdk.request)

        self.complete(settings=config(generation_temperature=0.4))
        self.assertEqual(self.sdk.request["temperature"], 0.4)

    def test_never_streams(self):
        """ Ask for the whole answer at once. """
        self.complete()
        self.assertNotIn("stream", self.sdk.request)


class ResultTest(ProviderTestCase):
    """ Cover the normalization of an answer. """

    def test_normalizes_a_well_formed_answer(self):
        """ Carry the content, the model and the counters through. """
        result = self.complete()
        self.assertEqual(result.content, REPLY)
        self.assertEqual(result.model, "answering-model")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.upstream_request_id, "upstream-1")
        self.assertEqual(result.prompt_tokens, 11)
        self.assertEqual(result.completion_tokens, 22)
        self.assertEqual(result.total_tokens, 33)

    def test_measures_the_one_request(self):
        """ Report how long the wait on the endpoint was. """
        result = self.complete()
        self.assertIsNotNone(result.elapsed_seconds)
        self.assertGreaterEqual(result.elapsed_seconds, 0.0)

    def test_accepts_an_answer_without_usage(self):
        """ Accept an endpoint that counts nothing. """
        result = self.complete(FakeSDK(answer(usage=None)))
        self.assertIsNone(result.prompt_tokens)
        self.assertEqual(result.content, REPLY)

    def test_falls_back_to_the_configured_model_name(self):
        """ Name the model asked for when the answer names none. """
        result = self.complete(FakeSDK(answer(model="")))
        self.assertEqual(result.model, "configured-model")

    def refuse(self, sdk):
        """ Assert that the given answer is refused, with a logged reason. """
        with self.assertLogs("reply_writer.providers.openai_compatible",
                             "ERROR"):
            with self.assertRaises(InvalidResponseError):
                self.complete(sdk)

    def test_refuses_an_answer_without_a_choice(self):
        """ Refuse an answer carrying nothing to read. """
        self.refuse(FakeSDK(SimpleNamespace(choices=[], model="m", usage=None,
                                            id="")))

    def test_refuses_an_unusable_content(self):
        """ Refuse an empty content and one of the wrong type. """
        self.refuse(FakeSDK(answer(content="   ")))
        self.refuse(FakeSDK(answer(content=None)))

    def test_refuses_an_answer_cut_off_by_the_limit(self):
        """
        Refuse a truncated answer rather than offer half a reply.

        Half a sentence pasted into a message is worse than no reply,
        and the log names the setting to raise.
        """
        for reason in ("length", "max_tokens"):
            self.refuse(FakeSDK(answer(finish_reason=reason)))


class FailureTest(ProviderTestCase):
    """ Cover the mapping of an SDK failure onto our own errors. """

    def test_maps_a_timeout(self):
        """ Report a timeout as a timeout. """
        error, _ = self.fail_with(FakeTimeoutError("timed out"))
        self.assertIsInstance(error, UpstreamTimeoutError)

    def test_maps_a_connection_failure(self):
        """ Report an unreachable endpoint as one. """
        error, _ = self.fail_with(FakeConnectionError("unreachable"))
        self.assertIsInstance(error, UpstreamConnectionError)

    def test_maps_every_error_status_onto_one_user_facing_error(self):
        """ Tell the person one thing, and the log which status it was. """
        for status in (401, 403, 429, 500):
            error, recorded = self.fail_with(
                FakeStatusError("refused", status_code=status))
            self.assertIsInstance(error, UpstreamStatusError)
            self.assertIn("status={0}".format(status), "\n".join(recorded))

    def test_maps_any_remaining_sdk_error(self):
        """
        Map an error of the SDK that is none of the three cases.

        The package raises more than a timeout, a lost connection and a
        refused status: an answer it cannot validate is one example.
        Such an error is mapped here as well, because a class of the
        client library reaching the web layer is what the error
        hierarchy exists to prevent.
        """
        error, recorded = self.fail_with(FakeError("unreadable answer"))
        self.assertIsInstance(error, InvalidResponseError)
        self.assertNotIn(TOKEN, "\n".join(recorded))

    def test_tries_no_second_endpoint(self):
        """
        Spend one request on the configured route, whatever happened.

        A failure of the generation API is no reason to send private
        correspondence somewhere else. The stand-in raises on a second
        create(), so a retry of our own would fail this test.
        """
        sdk = FakeSDK(error=FakeConnectionError("unreachable"))
        with self.assertLogs("reply_writer.providers.openai_compatible",
                             "ERROR"):
            with self.assertRaises(UpstreamConnectionError):
                self.complete(sdk)
        self.assertIsNotNone(sdk.request)


class LogTest(ProviderTestCase):
    """ Cover what a log line carries, and what it must never carry. """

    def test_records_the_shape_of_an_answer_and_not_its_content(self):
        """ Record the exchange without the reply or the token. """
        with self.assertLogs("reply_writer.providers", "INFO") as recorded:
            self.complete()
        line = "\n".join(recorded.output)

        self.assertIn("backend=openai-compatible", line)
        self.assertIn("endpoint_host=api.example.test", line)
        self.assertIn("model=answering-model", line)
        self.assertIn("total_tokens=33", line)
        self.assertNotIn(TOKEN, line)
        self.assertNotIn(REPLY, line)
        self.assertNotIn(MESSAGES[1]["content"], line)

    def test_records_the_request_id_of_the_generation(self):
        """ Let one generation be followed by the id the web layer gave. """
        with self.assertLogs("reply_writer.providers", "INFO") as recorded:
            self.complete(request_id="abcd1234")
        self.assertIn("request_id=abcd1234", "\n".join(recorded.output))

    def test_records_the_wait_next_to_the_limit(self):
        """ Record both, so a timeout can be told from a lost connection. """
        with self.assertLogs("reply_writer.providers", "INFO") as recorded:
            self.complete(settings=config(generation_timeout=45.0))
        self.assertIn("timeout=45.0", "\n".join(recorded.output))
        self.assertIn("elapsed=", "\n".join(recorded.output))

        _, failed = self.fail_with(FakeTimeoutError("timed out"))
        self.assertIn("elapsed=", "\n".join(failed))
        self.assertIn("timeout=", "\n".join(failed))

    def test_keeps_the_token_and_the_messages_out_of_a_failure_line(self):
        """ Record a failure without the credential or the input. """
        with self.assertLogs("reply_writer.providers.openai_compatible",
                             "ERROR") as recorded:
            with self.assertRaises(UpstreamStatusError):
                self.complete(FakeSDK(error=FakeStatusError("refused", 401)))
        line = "\n".join(recorded.output)
        self.assertNotIn(TOKEN, line)
        self.assertNotIn(MESSAGES[1]["content"], line)


if __name__ == "__main__":
    unittest.main()
