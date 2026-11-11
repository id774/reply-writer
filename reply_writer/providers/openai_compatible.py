#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# reply_writer/providers/openai_compatible.py: Chat Completions provider
#
#  Description:
#  This module speaks the OpenAI compatible Chat Completions API
#  through the openai package. The package is the client. It is not the
#  choice of an endpoint. Which service answers is decided by
#  GENERATION_BASE_URL alone, and that value is always passed to the
#  SDK, so the default URL compiled into the client can never be
#  reached by leaving a setting empty.
#
#  One complete() call performs exactly one create() call. There is no
#  retry loop of our own, no second attempt with different parameters
#  and no other endpoint to try: retries belong to the SDK, where
#  GENERATION_MAX_RETRIES bounds them, so that one action by the person
#  costs a number of requests an operator can see.
#
#  The answer is normalized into a CompletionResult and nothing else is
#  read from it. Metadata a compatible endpoint may omit — the usage
#  counts, the request id — is carried as it comes. Only an answer with
#  no usable text, or one cut off by the output limit, is refused.
#
#  Author: id774 (More info: https://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - openai
#
#  Version History:
#  v1.4 2026-11-11
#       Refused to follow generation API redirects.
#  v1.3 2026-11-09
#       Sanitized invalid-response diagnostics and SDK error metadata.
#  v1.2 2026-09-21
#       Required a usable finish reason, carried sanitized failure diagnostics
#       and refused unknown response modes before a request.
#  v1.1 2026-09-12
#       Selected max_tokens or max_completion_tokens from configuration.
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import time
from typing import Any, Dict, List, Optional

from config import Config
from reply_writer.errors import (InternalError, InvalidResponseError,
                                 UpstreamConnectionError, UpstreamStatusError,
                                 UpstreamTimeoutError)
from reply_writer.providers import CompletionResult, log_response

# Finish reasons that mean the output hit its limit. A truncated reply
# is not offered as a draft: half a sentence pasted into a message is
# worse than no reply at all. The list is explicit, so that an unknown
# reason from a compatible endpoint is reported as itself and added
# here once a log has shown it, rather than guessed to mean the same.
TRUNCATED_REASONS = ("length", "max_tokens")


def _without_retry_override(response: Any) -> None:
    """
    Keep the SDK from retrying a redirect answer.

    The SDK retries any answer carrying 'x-should-retry: true', whatever
    its status. A 3xx must stay a refusal, so the header is dropped from
    it before the SDK reads it. Every other status is left alone, and
    the retries the operator configured apply to them as before.
    """
    if 300 <= response.status_code < 400:
        response.headers.pop("x-should-retry", None)


class OpenAICompatibleProvider:
    """ Provider for an OpenAI compatible Chat Completions endpoint. """

    def complete(self, messages: List[Dict[str, str]], config: Config,
                 request_id: str = "") -> CompletionResult:
        """ Send one chat completion request and normalize its answer. """
        client = self._client(config)
        try:
            return self._complete(client, messages, config, request_id)
        finally:
            # The client owns the connection pool built for this one
            # call. It is released whether the call succeeded or not.
            client.close()

    def _complete(self, client: Any, messages: List[Dict[str, str]],
                  config: Config, request_id: str) -> CompletionResult:
        """ Run the one request against the given client. """
        request = self._request(messages, config)

        # The clock starts at the call and not at the top of the
        # method, so that what is reported is the wait on the endpoint
        # alone. Nothing here is streamed: the whole answer arrives at
        # the end, which makes this figure the wait the person actually
        # had. GENERATION_TIMEOUT is the SDK's HTTP timeout and not a
        # limit on this figure, which can exceed it.
        started = time.monotonic()
        response = self._create(client, request, config, started, request_id)
        try:
            result = self._result(response, config)
        except InvalidResponseError as error:
            raise InvalidResponseError(self._invalid_response_diagnostic(
                config, error.diagnostic, started, request_id)) from None
        result.elapsed_seconds = self._elapsed(started)
        log_response(config, result, request_id)
        return result

    def _client(self, config: Config) -> Any:
        """ Build the client described by the configuration. """
        try:
            from openai import DefaultHttpxClient, OpenAI
        except ImportError:
            raise InternalError("openai package missing") from None

        # base_url is passed unconditionally. An empty value would let
        # the SDK fall back to its own endpoint, which is the one thing
        # this design refuses to allow. config.py has already rejected
        # that case, and this keeps the guarantee local as well.
        #
        # The SDK's own HTTP client follows redirects, and a 307 or a
        # 308 would send the received message and the direction on to
        # whatever address the endpoint names. The client handed over
        # here follows none, to the same host or to another, so a 3xx
        # answer is an error status like any other and no request is
        # made to an address the operator did not configure. The SDK's
        # retry rule would honour an x-should-retry header even on a
        # 3xx and could turn a later 200 into a success, so the hook
        # removes that header from a redirect: it is never retried.
        return OpenAI(
            api_key=config.generation_api_token,
            base_url=config.generation_base_url,
            timeout=config.generation_timeout,
            max_retries=config.generation_max_retries,
            http_client=DefaultHttpxClient(
                follow_redirects=False,
                event_hooks={"response": [_without_retry_override]}),
        )

    def _request(self, messages: List[Dict[str, str]],
                 config: Config) -> Dict[str, Any]:
        """ Assemble the keyword arguments of one create() call. """
        request: Dict[str, Any] = {
            "model": config.generation_model,
            "messages": messages,
        }

        # The wire field GENERATION_OUTPUT_TOKEN_PARAMETER selects. The
        # else branch is not reachable through load_config(), which
        # already refuses any other value. It guards a Config built by
        # hand from ever being sent as max_completion_tokens by mistake.
        if config.generation_output_token_parameter == "max_tokens":
            request["max_tokens"] = config.max_output_tokens
        elif config.generation_output_token_parameter == "max_completion_tokens":
            request["extra_body"] = {
                "max_completion_tokens": config.max_output_tokens,
            }
        else:
            raise InternalError(
                "unknown output token parameter: {0}".format(
                    config.generation_output_token_parameter))

        # Sent only when configured, so that a model refusing the
        # parameter still runs and the endpoint default stays in place.
        if config.generation_temperature is not None:
            request["temperature"] = config.generation_temperature

        # Only json-object asks the API for a structured answer.
        # prompt-json leaves the contract to the prompt, for a model or
        # an endpoint that rejects the parameter. Neither mode is tried
        # after the other: a configured mode that is unavailable is an
        # error, and retrying with the other would spend a second
        # request the person never asked for. The else branch is not
        # reachable through load_config(), which already refuses any
        # other value. It guards a Config built by hand from being read
        # as prompt-json by default instead of being refused.
        if config.generation_response_mode == "json-object":
            request["response_format"] = {"type": "json_object"}
        elif config.generation_response_mode == "prompt-json":
            pass
        else:
            raise InternalError(
                "unknown response mode: {0}".format(
                    config.generation_response_mode))

        return request

    def _create(self, client: Any, request: Dict[str, Any], config: Config,
                started: float, request_id: str) -> Any:
        """
        Perform the one API call and map its failures.

        The three cases told apart are the ones an operator acts on
        differently: a wait that ran out, a connection that never
        stood, and an answer the endpoint refused. Any remaining error
        of the SDK is mapped as well and last, because it is a subclass
        of none of them: leaving it to travel upwards would put a class
        of the client library in front of the person, which is what
        reply_writer.errors exists to prevent.
        """
        import openai

        try:
            return client.chat.completions.create(**request)
        except openai.APITimeoutError as error:
            raise UpstreamTimeoutError(self._failure_diagnostic(
                config, error, None, started, request_id)) from None
        except openai.APIConnectionError as error:
            raise UpstreamConnectionError(self._failure_diagnostic(
                config, error, None, started, request_id)) from None
        except openai.APIStatusError as error:
            raise UpstreamStatusError(self._failure_diagnostic(
                config, error, getattr(error, "status_code", None), started,
                request_id)) from None
        except openai.APIError as error:
            raise InvalidResponseError(self._failure_diagnostic(
                config, error, getattr(error, "status_code", None), started,
                request_id)) from None

    def _failure_diagnostic(self, config: Config, error: Exception,
                            status_code: Optional[int], started: float,
                            request_id: str) -> str:
        """
        Build a sanitized diagnostic for a failed request.

        The status is worth carrying even though the user is never told
        it apart: 401 is a token to replace, 403 a plan that does not
        cover the model, 429 a rate limit or an exhausted allowance, and
        only the diagnostic can say which happened.

        The elapsed seconds sit next to the timeout as context. They
        are not a diagnosis by themselves: GENERATION_TIMEOUT is the
        SDK's HTTP timeout for each wait, not a limit on the whole
        request, so comparing the total with it cannot tell a slow
        endpoint from a lost connection, and retries add to the total.

        Carry the exception class but not its message. An SDK may put
        the upstream response body into an exception message, and that
        body can contain text that must stay out of the diagnostic.
        """
        return (
            "generation failure: request_id={0} backend={1} "
            "endpoint_host={2} model={3} error={4} status={5} "
            "upstream_request_id={6} elapsed={7} timeout={8}"
        ).format(
            request_id or "-",
            config.generation_backend,
            config.endpoint_host,
            config.generation_model,
            type(error).__name__,
            (status_code if type(status_code) is int
             and 100 <= status_code <= 599 else "-"),
            ("present" if isinstance(getattr(error, "request_id", None), str)
             and getattr(error, "request_id", None) else "-"),
            self._elapsed(started),
            config.generation_timeout,
        )

    def _invalid_response_diagnostic(self, config: Config, reason: str,
                                     started: float,
                                     request_id: str) -> str:
        """
        Build a sanitized diagnostic for an unreadable answer.

        The reason is the fixed local validation text raised by
        _result(). No response body, prompt, credential or upstream
        exception message is carried.
        """
        return (
            "generation invalid response: request_id={0} backend={1} "
            "endpoint_host={2} model={3} detail={4} elapsed={5} timeout={6}"
        ).format(
            request_id or "-",
            config.generation_backend,
            config.endpoint_host,
            config.generation_model,
            reason,
            self._elapsed(started),
            config.generation_timeout,
        )

    def _elapsed(self, started: float) -> float:
        """
        Return the seconds spent since the given monotonic mark.

        monotonic() rather than time(): a clock adjusted while a
        request is in flight would otherwise report a wait that never
        happened.
        """
        return round(time.monotonic() - started, 1)

    def _result(self, response: Any, config: Config) -> CompletionResult:
        """ Read the answer into the shape generator.py works with. """
        choices = getattr(response, "choices", None)
        if not choices:
            raise InvalidResponseError("answer carries no choice")

        choice = choices[0]

        # A response is accepted only where the endpoint says how the
        # generation ended. A missing or blank finish reason is refused
        # rather than assumed to mean an ordinary stop: an endpoint
        # that leaves this out has told us nothing about whether the
        # answer is complete. An unknown but non-empty reason is not
        # guessed at either. It is kept, on the chance that a
        # compatible endpoint uses a name of its own for an ordinary
        # stop.
        raw_finish_reason = getattr(choice, "finish_reason", None)
        if not isinstance(raw_finish_reason, str) or not raw_finish_reason.strip():
            raise InvalidResponseError("answer carries no usable finish reason")
        finish_reason = raw_finish_reason.strip()

        if finish_reason in TRUNCATED_REASONS:
            raise InvalidResponseError(
                "output was cut off (finish_reason={0}); raise "
                "MAX_OUTPUT_TOKENS".format(finish_reason))

        content = getattr(getattr(choice, "message", None), "content", None)
        if not isinstance(content, str) or not content.strip():
            raise InvalidResponseError("answer carries no usable content")

        usage = getattr(response, "usage", None)
        return CompletionResult(
            content=content,
            model=getattr(response, "model", None) or config.generation_model,
            finish_reason=finish_reason,
            upstream_request_id=getattr(response, "id", None) or "",
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )
