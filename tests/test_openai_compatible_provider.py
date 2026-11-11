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
#  elapsed seconds appear next to the timeout on a success and on a
#  timeout alike, as context only: the timeout is the SDK's HTTP timeout
#  for each wait, so the total says nothing certain about the cause.
#
#  Author: id774 (More info: https://id774.net)
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
#    - Send MAX_OUTPUT_TOKENS as max_tokens by default.
#    - Send it as max_completion_tokens through extra_body when configured.
#    - Ask for a JSON object under json-object mode.
#    - Send no response format under prompt-json mode.
#    - Refuse a hand-built Config carrying an unknown response mode before
#      a request is spent.
#    - Send no temperature unless it is set, and send it when it is.
#    - Never stream.
#    - Hand the SDK an HTTP client that follows no redirect, and keep the
#      token, the base URL, the timeout and the retries as configured.
#    - Release the client after a call, whether it succeeded or failed.
#    - Refuse 301, 302, 303, 307 and 308 as an upstream error, to the same
#      host or another, without a second request and without the Location.
#    - Keep a 3xx from being retried into a success, even when it carries
#      an x-should-retry header and retries are enabled.
#    - Normalize a well formed answer, including the usage counters.
#    - Measure how long the one request took.
#    - Accept an answer that carries no usage.
#    - Fall back to the configured model name when the answer names none.
#    - Refuse an answer without a choice.
#    - Refuse an empty content, and a content that is not a string.
#    - Refuse an answer cut off by the output limit.
#    - Refuse an answer with a missing, blank or non-string finish reason.
#    - Accept and preserve an unknown but non-empty finish reason, rather
#      than guess it means a truncation.
#    - Trim the finish reason before it is carried in the result.
#    - Map a timeout onto UpstreamTimeoutError.
#    - Map a connection failure onto UpstreamConnectionError.
#    - Map 401, 403, 429 and 500 onto one user facing error.
#    - Map any remaining SDK error onto one of our own.
#    - Try no second endpoint when the first one fails.
#    - Record the shape of an answer without its content or the token.
#    - Record the request id of the generation on both lines.
#    - Record the wait next to the limit on an answer and on a timeout.
#    - Keep the token and the reply out of a failure diagnostic.
#    - Log no failure at this layer. The entry point owns that log, and
#      the success path's response log is unaffected.
#    - Raise InternalError for an unknown backend in build_provider(),
#      without logging at the provider-registry layer either.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only (the openai package is stubbed, never imported)
#
#  Version History:
#  v1.1 2026-09-21
#       Covered finish-reason validation, sanitized diagnostics and single-owner
#       failure logging across provider selection and generation.
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import logging
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

from config import Config
from reply_writer.errors import (InternalError, InvalidResponseError,
                                 UpstreamConnectionError, UpstreamStatusError,
                                 UpstreamTimeoutError)
from reply_writer.providers import build_provider
from reply_writer.providers.openai_compatible import OpenAICompatibleProvider

PROVIDER_LOGGER = logging.getLogger(
    "reply_writer.providers.openai_compatible")
REGISTRY_LOGGER = logging.getLogger("reply_writer.providers")

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


class FakeHttpClient:
    """ Stands in for the SDK's default HTTP client and its redirect rule. """

    def __init__(self, **arguments):
        self.arguments = arguments
        # The SDK's own default follows redirects. Only an explicit
        # argument turns that off.
        self.follow_redirects = arguments.get("follow_redirects", True)


class FakeSDK:
    """ A stand-in openai module recording what the provider does. """

    def __init__(self, result=None, error=None, redirect=None):
        self.result = result if result is not None else answer()
        self.error = error
        # A (status, location) pair: the endpoint answers with that
        # redirect, and the stand-in client follows it, as the real one
        # would, unless it was built not to.
        self.redirect = redirect
        self.client_arguments = None
        self.http_client = None
        self.closed = 0
        self.followed = []
        self.request = None

    def install(self, test):
        """ Put the stand-in in sys.modules for the duration of a test. """
        module = ModuleType("openai")
        module.APITimeoutError = FakeTimeoutError
        module.APIConnectionError = FakeConnectionError
        module.APIStatusError = FakeStatusError
        module.APIError = FakeError
        module.OpenAI = self._client
        module.DefaultHttpxClient = self._http_client
        test.addCleanup(sys.modules.pop, "openai", None)
        sys.modules["openai"] = module

    def _http_client(self, **arguments):
        """ Record how the HTTP client was built and return a stand-in. """
        self.http_client = FakeHttpClient(**arguments)
        return self.http_client

    def _client(self, **arguments):
        """ Record how the client was built and return a stand-in. """
        self.client_arguments = arguments
        completions = SimpleNamespace(create=self._create)
        return SimpleNamespace(
            chat=SimpleNamespace(completions=completions),
            close=self._close)

    def _close(self):
        """ Count the releases of the client. """
        self.closed += 1

    def _create(self, **request):
        """ Record the one request and answer it. """
        if self.request is not None:
            raise AssertionError("more than one request was spent")
        self.request = request
        if self.redirect is not None:
            status, location = self.redirect
            if self.client_arguments["http_client"].follow_redirects:
                self.followed.append(location)
                return self.result
            raise FakeStatusError("redirect", status_code=status)
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
        """
        Run one call that fails, and return the raised error.

        The provider logs no failure of its own: it raises with a
        sanitized diagnostic instead, and the entry point that owns the
        failure log is the one that records it.
        """
        with self.assertRaises(Exception) as raised:
            self.complete(FakeSDK(error=error))
        return raised.exception


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
        config.py rejects an empty value earlier. This keeps the
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


    def test_hands_the_sdk_a_client_that_follows_no_redirect(self):
        """ Never let the endpoint name another address for the input. """
        self.complete(settings=config(generation_timeout=45.0,
                                      generation_max_retries=1))
        arguments = dict(self.sdk.http_client.arguments)
        hooks = arguments.pop("event_hooks")
        self.assertEqual(arguments, {"follow_redirects": False})
        self.assertEqual(list(hooks), ["response"])
        self.assertEqual(len(hooks["response"]), 1)
        self.assertIs(self.sdk.client_arguments["http_client"],
                      self.sdk.http_client)
        self.assertEqual(self.sdk.client_arguments["api_key"], TOKEN)
        self.assertEqual(self.sdk.client_arguments["base_url"],
                         "https://api.example.test/v1")
        self.assertEqual(self.sdk.client_arguments["timeout"], 45.0)
        self.assertEqual(self.sdk.client_arguments["max_retries"], 1)

    def test_releases_the_client_after_a_call(self):
        """ Close the client whether the call succeeded or failed. """
        self.complete()
        self.assertEqual(self.sdk.closed, 1)
        self.fail_with(FakeTimeoutError("timed out"))
        self.assertEqual(self.sdk.closed, 1)


class RequestTest(ProviderTestCase):
    """ Cover the one request the provider assembles. """

    def test_sends_the_model_and_the_messages(self):
        """ Send what one generation needs and nothing more. """
        self.complete()
        self.assertEqual(self.sdk.request["model"], "configured-model")
        self.assertEqual(self.sdk.request["messages"], MESSAGES)

    def test_sends_max_tokens_by_default(self):
        """ Carry MAX_OUTPUT_TOKENS as max_tokens without configuration. """
        self.complete()
        self.assertEqual(self.sdk.request["max_tokens"], 2000)
        self.assertNotIn("extra_body", self.sdk.request)

    def test_sends_max_completion_tokens_when_configured(self):
        """ Carry MAX_OUTPUT_TOKENS through extra_body when selected. """
        self.complete(settings=config(
            generation_output_token_parameter="max_completion_tokens"))
        self.assertNotIn("max_tokens", self.sdk.request)
        self.assertEqual(self.sdk.request["extra_body"],
                         {"max_completion_tokens": 2000})

    def test_refuses_an_unknown_output_token_parameter_before_a_request(self):
        """ Refuse a hand-built Config before spending a request on it. """
        with mock.patch.object(PROVIDER_LOGGER, "error") as error_log:
            with self.assertRaises(InternalError) as raised:
                self.complete(settings=config(
                    generation_output_token_parameter="automatic"))
        self.assertIsNone(self.sdk.request)
        error_log.assert_not_called()
        self.assertIn("automatic", raised.exception.diagnostic)

    def test_asks_for_a_json_object_under_json_object_mode(self):
        """ Ask the API itself for an object in that mode. """
        self.complete(settings=config(generation_response_mode="json-object"))
        self.assertEqual(self.sdk.request["response_format"],
                         {"type": "json_object"})

    def test_sends_no_response_format_under_prompt_json_mode(self):
        """ Leave the contract to the prompt in that mode. """
        self.complete(settings=config(generation_response_mode="prompt-json"))
        self.assertNotIn("response_format", self.sdk.request)

    def test_refuses_an_unknown_response_mode_before_a_request(self):
        """
        Refuse a hand-built Config before spending a request on it.

        load_config() already refuses an unknown GENERATION_RESPONSE_MODE.
        This guards a Config built by hand from being read as prompt-json
        by default instead of being refused the same way the unknown
        output-token parameter is.
        """
        with mock.patch.object(PROVIDER_LOGGER, "error") as error_log:
            with self.assertRaises(InternalError) as raised:
                self.complete(settings=config(
                    generation_response_mode="automatic"))
        self.assertIsNone(self.sdk.request)
        error_log.assert_not_called()
        self.assertIn("unknown response mode: automatic",
                      raised.exception.diagnostic)

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

    def refuse(self, sdk, diagnostic=None):
        """
        Assert that the given answer is refused, with a safe diagnostic.

        The provider logs no failure of its own: it raises
        InvalidResponseError carrying a sanitized diagnostic instead.
        """
        with self.assertRaises(InvalidResponseError) as raised:
            self.complete(sdk)
        if diagnostic is not None:
            self.assertIn(diagnostic, raised.exception.diagnostic)
        return raised.exception

    def test_refuses_an_answer_without_a_choice(self):
        """ Refuse an answer carrying nothing to read. """
        self.refuse(FakeSDK(SimpleNamespace(choices=[], model="m", usage=None,
                                            id="")),
                    "answer carries no choice")

    def test_refuses_an_unusable_content(self):
        """ Refuse an empty content and one of the wrong type. """
        self.refuse(FakeSDK(answer(content="   ")),
                    "answer carries no usable content")
        self.refuse(FakeSDK(answer(content=None)),
                    "answer carries no usable content")

    def test_refuses_an_answer_cut_off_by_the_limit(self):
        """
        Refuse a truncated answer rather than offer half a reply.

        Half a sentence pasted into a message is worse than no reply,
        and the diagnostic names the setting to raise.
        """
        for reason in ("length", "max_tokens"):
            error = self.refuse(FakeSDK(answer(finish_reason=reason)))
            self.assertIn(
                "output was cut off (finish_reason={0}); raise "
                "MAX_OUTPUT_TOKENS".format(reason), error.diagnostic)

    def test_refuses_a_missing_or_blank_finish_reason(self):
        """
        Refuse an answer that does not say how the generation ended.

        A missing or blank finish reason is not read as an ordinary
        stop: an endpoint that leaves it out has said nothing about
        whether the answer is complete.
        """
        for finish_reason in (None, "", "   "):
            self.refuse(FakeSDK(answer(finish_reason=finish_reason)),
                        "answer carries no usable finish reason")

    def test_refuses_a_non_string_finish_reason(self):
        """ Refuse a finish reason of the wrong type rather than coerce it. """
        self.refuse(FakeSDK(answer(finish_reason=404)),
                    "answer carries no usable finish reason")

    def test_accepts_and_preserves_an_unknown_non_empty_finish_reason(self):
        """
        Keep an unrecognized but non-empty finish reason, not guess at it.

        A compatible endpoint may use a name of its own for an ordinary
        stop. Such a reason is neither in TRUNCATED_REASONS nor assumed
        to mean the same as one that is: it is carried through as the
        endpoint reported it.
        """
        result = self.complete(FakeSDK(answer(finish_reason="end_turn")))
        self.assertEqual(result.finish_reason, "end_turn")

    def test_trims_the_finish_reason(self):
        """ Keep the stripped value, as the diagnostic and the field. """
        result = self.complete(FakeSDK(answer(finish_reason="  stop  ")))
        self.assertEqual(result.finish_reason, "stop")


    def test_invalid_response_diagnostic_carries_safe_metadata(self):
        """ Carry request metadata and the fixed reason, nothing else. """
        cases = (
            (SimpleNamespace(choices=[], model="m", usage=None, id="u"),
             "answer carries no choice"),
            (answer(finish_reason=None),
             "answer carries no usable finish reason"),
            (answer(content=""), "answer carries no usable content"),
            (answer(finish_reason="length"),
             "output was cut off (finish_reason=length); raise "
             "MAX_OUTPUT_TOKENS"),
        )
        for response, detail in cases:
            with self.subTest(detail=detail):
                sdk = FakeSDK(response)
                sdk.install(self)
                with self.assertLogs(PROVIDER_LOGGER, "DEBUG") as logged:
                    PROVIDER_LOGGER.debug("sentinel")
                    with self.assertRaises(InvalidResponseError) as raised:
                        OpenAICompatibleProvider().complete(
                            MESSAGES, config(), "abcd1234")
                diagnostic = raised.exception.diagnostic
                self.assertTrue(diagnostic.startswith(
                    "generation invalid response: request_id=abcd1234 "
                    "backend=openai-compatible endpoint_host=api.example.test "
                    "model=configured-model detail=" + detail + " elapsed="))
                self.assertRegex(diagnostic, r" elapsed=\d+(\.\d+)? timeout=")
                self.assertNotIn(TOKEN, diagnostic)
                self.assertNotIn(REPLY, diagnostic)
                for message in MESSAGES:
                    self.assertNotIn(message["content"], diagnostic)
                self.assertEqual(len(logged.output), 1)
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)
                self.assertIsNotNone(sdk.request)
                sys.modules.pop("openai", None)


class FailureTest(ProviderTestCase):
    """ Cover the mapping of an SDK failure onto our own errors. """

    def test_maps_a_timeout(self):
        """ Report a timeout as a timeout. """
        error = self.fail_with(FakeTimeoutError("timed out"))
        self.assertIsInstance(error, UpstreamTimeoutError)

    def test_refuses_every_redirect_without_a_second_request(self):
        """ Treat a 3xx as an upstream error and follow it nowhere. """
        locations = ("https://other.example.test/v1/chat/completions",
                     "https://api.example.test/v1/elsewhere")
        for status in (301, 302, 303, 307, 308):
            for location in locations:
                with self.subTest(status=status, location=location):
                    sdk = FakeSDK(redirect=(status, location))
                    with self.assertRaises(UpstreamStatusError) as raised:
                        self.complete(sdk)
                    diagnostic = raised.exception.diagnostic
                    self.assertEqual(sdk.followed, [])
                    self.assertIsNotNone(sdk.request)
                    self.assertEqual(sdk.closed, 1)
                    self.assertIn("status={0}".format(status), diagnostic)
                    self.assertNotIn("example.test/v1/elsewhere", diagnostic)
                    self.assertNotIn("other.example.test", diagnostic)
                    self.assertNotIn(location, diagnostic)
                    self.assertNotIn(TOKEN, diagnostic)
                    self.assertNotIn(MESSAGES[1]["content"], diagnostic)
                    self.assertEqual(raised.exception.status_code, 502)

    def test_redirect_hook_removes_the_retry_override_only_from_a_3xx(self):
        """ Never let x-should-retry turn a redirect into a retried call. """
        self.complete()
        hook = self.sdk.http_client.arguments["event_hooks"]["response"][0]
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                response = SimpleNamespace(
                    status_code=status,
                    headers={"x-should-retry": "true", "location": "x"})
                hook(response)
                self.assertNotIn("x-should-retry", response.headers)
                self.assertIn("location", response.headers)
        for status in (200, 429, 500, 503):
            with self.subTest(status=status):
                response = SimpleNamespace(
                    status_code=status, headers={"x-should-retry": "true"})
                hook(response)
                self.assertEqual(response.headers["x-should-retry"], "true")

    def test_a_followed_redirect_would_have_gone_elsewhere(self):
        """ Show that the stand-in does follow when not told otherwise. """
        sdk = FakeSDK(redirect=(307, "https://other.example.test/v1"))
        sdk.install(self)
        client = sdk._client(http_client=FakeHttpClient())
        client.chat.completions.create(model="m", messages=[])
        self.assertEqual(sdk.followed, ["https://other.example.test/v1"])

    def test_maps_a_connection_failure(self):
        """ Report an unreachable endpoint as one. """
        error = self.fail_with(FakeConnectionError("unreachable"))
        self.assertIsInstance(error, UpstreamConnectionError)

    def test_maps_every_error_status_onto_one_user_facing_error(self):
        """ Tell the person one thing, and carry the status in the diagnostic. """
        for status in (401, 403, 429, 500):
            error = self.fail_with(
                FakeStatusError("refused", status_code=status))
            self.assertIsInstance(error, UpstreamStatusError)
            self.assertIn("status={0}".format(status), error.diagnostic)

    def test_maps_any_remaining_sdk_error(self):
        """
        Map an error of the SDK that is none of the three cases.

        The package raises more than a timeout, a lost connection and a
        refused status: an answer it cannot validate is one example.
        Such an error is mapped here as well, because a class of the
        client library reaching the web layer is what the error
        hierarchy exists to prevent.
        """
        error = self.fail_with(FakeError("unreadable answer"))
        self.assertIsInstance(error, InvalidResponseError)
        self.assertNotIn(TOKEN, error.diagnostic)

    def test_tries_no_second_endpoint(self):
        """
        Spend one request on the configured route, whatever happened.

        A failure of the generation API is no reason to send private
        correspondence somewhere else. The stand-in raises on a second
        create(), so a retry of our own would fail this test.
        """
        sdk = FakeSDK(error=FakeConnectionError("unreachable"))
        with self.assertRaises(UpstreamConnectionError):
            self.complete(sdk)
        self.assertIsNotNone(sdk.request)


    def test_masks_sdk_request_id_and_invalid_status_in_diagnostic(self):
        """ Keep raw upstream ids and odd statuses out of the diagnostic. """
        error = FakeStatusError("PRIVATE_EXCEPTION_MESSAGE", status_code=503)
        error.request_id = "PRIVATE_ERROR_UPSTREAM_ID"
        failed = self.fail_with(error)
        self.assertIsInstance(failed, UpstreamStatusError)
        self.assertIn("status=503", failed.diagnostic)
        self.assertIn("upstream_request_id=present", failed.diagnostic)
        self.assertNotIn("PRIVATE_ERROR_UPSTREAM_ID", failed.diagnostic)
        self.assertNotIn("PRIVATE_EXCEPTION_MESSAGE", failed.diagnostic)
        self.assertIsNotNone(self.sdk.request)

        odd = FakeStatusError("PRIVATE_EXCEPTION_MESSAGE",
                              status_code="PRIVATE_STATUS_STRING")
        failed = self.fail_with(odd)
        self.assertIn("status=-", failed.diagnostic)
        self.assertNotIn("PRIVATE_STATUS_STRING", failed.diagnostic)
        self.assertNotIn("PRIVATE_EXCEPTION_MESSAGE", failed.diagnostic)
        self.assertIsNotNone(self.sdk.request)


class LogTest(ProviderTestCase):
    """ Cover what a log line carries, and what it must never carry. """

    def test_records_the_shape_of_an_answer_and_not_its_content(self):
        """ Record the exchange without the reply or the token. """
        with self.assertLogs("reply_writer.providers", "INFO") as recorded:
            self.complete()
        line = "\n".join(recorded.output)

        self.assertIn("backend=openai-compatible", line)
        self.assertIn("endpoint_host=api.example.test", line)
        self.assertIn("model=configured-model", line)
        self.assertIn("total_tokens=33", line)
        self.assertNotIn(TOKEN, line)
        self.assertNotIn(REPLY, line)
        self.assertNotIn(MESSAGES[1]["content"], line)

    def test_refuses_upstream_string_metadata_in_success_log(self):
        """ Keep free-form upstream strings out of the success log. """
        markers = ("PRIVATE_MODEL_TEXT", "PRIVATE_FINISH_TEXT",
                   "PRIVATE_UPSTREAM_ID_TEXT", "PRIVATE_PROMPT_COUNT")
        usage = SimpleNamespace(prompt_tokens="PRIVATE_PROMPT_COUNT",
                                completion_tokens=True, total_tokens=-1)
        sdk = FakeSDK(answer(model="PRIVATE_MODEL_TEXT",
                             finish_reason="PRIVATE_FINISH_TEXT",
                             identifier="PRIVATE_UPSTREAM_ID_TEXT",
                             usage=usage))
        with self.assertLogs("reply_writer.providers", "INFO") as recorded:
            result = self.complete(sdk)
        line = "\n".join(recorded.output)
        self.assertEqual(result.model, "PRIVATE_MODEL_TEXT")
        self.assertEqual(result.finish_reason, "PRIVATE_FINISH_TEXT")
        self.assertEqual(result.upstream_request_id,
                         "PRIVATE_UPSTREAM_ID_TEXT")
        self.assertEqual(result.prompt_tokens, "PRIVATE_PROMPT_COUNT")
        self.assertIs(result.completion_tokens, True)
        self.assertEqual(result.total_tokens, -1)
        self.assertIn("model=configured-model", line)
        self.assertIn("finish_reason=other", line)
        self.assertIn("upstream_request_id=present", line)
        for count in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.assertIn(count + "=None", line)
        for marker in markers:
            self.assertNotIn(marker, line)
        self.assertIsNotNone(sdk.request)

        with self.subTest(case="multibyte and line breaks"):
            sdk = FakeSDK(answer(model="PRIVATE_秘密\nMODEL",
                                 finish_reason="PRIVATE_日本語\nFINISH",
                                 identifier="PRIVATE_機密\nID"))
            with self.assertLogs("reply_writer.providers", "INFO") as again:
                self.complete(sdk)
            line = "\n".join(again.output)
            for raw in ("PRIVATE", "秘密", "日本語", "機密"):
                self.assertNotIn(raw, line)
            self.assertEqual(len(again.output), 1)
            self.assertIn("model=configured-model", line)
            self.assertIn("finish_reason=other", line)
            self.assertIn("upstream_request_id=present", line)

        with self.subTest(case="ordinary values"):
            sdk = FakeSDK(answer(identifier=""))
            with self.assertLogs("reply_writer.providers", "INFO") as normal:
                self.complete(sdk)
            line = "\n".join(normal.output)
            self.assertIn("finish_reason=stop", line)
            self.assertIn("upstream_request_id=-", line)
            self.assertIn("prompt_tokens=11", line)
            self.assertIn("completion_tokens=22", line)
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

        failed = self.fail_with(FakeTimeoutError("timed out"))
        self.assertIn("elapsed=", failed.diagnostic)
        self.assertIn("timeout=", failed.diagnostic)

    def test_keeps_the_token_and_the_messages_out_of_a_failure_diagnostic(self):
        """ Carry no credential or input in a failure diagnostic. """
        with self.assertRaises(UpstreamStatusError) as raised:
            self.complete(FakeSDK(error=FakeStatusError("refused", 401)))
        self.assertNotIn(TOKEN, raised.exception.diagnostic)
        self.assertNotIn(MESSAGES[1]["content"], raised.exception.diagnostic)

    def test_keeps_an_upstream_response_body_out_of_a_failure_diagnostic(self):
        """ Carry no exception text that may hold an upstream body. """
        response_body = "private text echoed by the endpoint"
        with self.assertRaises(UpstreamStatusError) as raised:
            self.complete(FakeSDK(error=FakeStatusError(response_body, 400)))
        diagnostic = raised.exception.diagnostic
        self.assertIn("error=FakeStatusError", diagnostic)
        self.assertIn("status=400", diagnostic)
        self.assertNotIn(response_body, diagnostic)

    def test_the_failure_path_logs_nothing_at_this_layer(self):
        """
        Log no failure here: the entry point owns that log.

        The provider raises with a sanitized diagnostic instead of
        logging and re-raising, so a failure produces one log line at
        the entry point rather than one per layer it passed through.
        The success path is unaffected: log_response() still records
        the shape of an answer, as covered above.
        """
        with mock.patch.object(PROVIDER_LOGGER, "error") as error_log:
            with self.assertRaises(UpstreamConnectionError):
                self.complete(FakeSDK(error=FakeConnectionError("unreachable")))
        error_log.assert_not_called()


class ProviderSelectionTest(unittest.TestCase):
    """
    Cover build_provider(), which chooses the provider by backend name.

    An unknown backend is an internal invariant failure rather than an
    ordinary configuration error: validate_generation_config() already
    refuses it earlier, in the normal environment path. This covers the
    registry's own local guard for a hand-built Config that reaches it
    unvalidated, and pins that the failure is raised rather than logged
    here, so the entry point that receives it remains the single owner
    of the failure log.
    """

    def test_unknown_backend_raises_without_logging_at_provider_layer(self):
        """ Raise InternalError for an unknown backend, and log nothing. """
        with mock.patch.object(REGISTRY_LOGGER, "error") as error_log:
            with self.assertRaises(InternalError) as raised:
                build_provider(config(generation_backend="unknown-backend"))
        self.assertEqual(raised.exception.diagnostic,
                         "unknown generation backend")
        error_log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
