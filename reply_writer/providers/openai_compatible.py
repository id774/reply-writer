#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# reply_writer/providers/openai_compatible.py: Chat Completions provider
#
#  Description:
#  This module speaks the OpenAI compatible Chat Completions API
#  through the openai package. The package is the client; it is not the
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
#  counts, the request id — is carried as it comes; only an answer with
#  no usable text, or one cut off by the output limit, is refused.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - openai
#
#  Version History:
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import logging
import time
from typing import Any, Dict, List, Optional

from config import Config
from reply_writer.errors import (InternalError, InvalidResponseError,
                                 UpstreamConnectionError, UpstreamStatusError,
                                 UpstreamTimeoutError)
from reply_writer.providers import CompletionResult, log_response

logger = logging.getLogger(__name__)

# Finish reasons that mean the output hit its limit. A truncated reply
# is not offered as a draft: half a sentence pasted into a message is
# worse than no reply at all. The list is explicit, so that an unknown
# reason from a compatible endpoint is reported as itself and added
# here once a log has shown it, rather than guessed to mean the same.
TRUNCATED_REASONS = ("length", "max_tokens")


class OpenAICompatibleProvider:
    """ Provider for an OpenAI compatible Chat Completions endpoint. """

    def complete(self, messages: List[Dict[str, str]], config: Config,
                 request_id: str = "") -> CompletionResult:
        """ Send one chat completion request and normalize its answer. """
        client = self._client(config)
        request = self._request(messages, config)

        # The clock starts at the call and not at the top of the
        # method, so that what is reported is the wait on the endpoint
        # alone. Nothing here is streamed: the whole answer arrives at
        # the end, which makes this figure the wait the person actually
        # had, and the one to compare against GENERATION_TIMEOUT.
        started = time.monotonic()
        response = self._create(client, request, config, started, request_id)
        result = self._result(response, config)
        result.elapsed_seconds = self._elapsed(started)
        log_response(config, result, request_id)
        return result

    def _client(self, config: Config) -> Any:
        """ Build the client described by the configuration. """
        try:
            from openai import OpenAI
        except ImportError as error:
            logger.error("The openai package is not installed: %s", error)
            raise InternalError("openai package missing")

        # base_url is passed unconditionally. An empty value would let
        # the SDK fall back to its own endpoint, which is the one thing
        # this design refuses to allow; config.py has already rejected
        # that case, and this keeps the guarantee local as well.
        return OpenAI(
            api_key=config.generation_api_token,
            base_url=config.generation_base_url,
            timeout=config.generation_timeout,
            max_retries=config.generation_max_retries,
        )

    def _request(self, messages: List[Dict[str, str]],
                 config: Config) -> Dict[str, Any]:
        """ Assemble the keyword arguments of one create() call. """
        request: Dict[str, Any] = {
            "model": config.generation_model,
            "messages": messages,
            "max_tokens": config.max_output_tokens,
        }

        # Sent only when configured, so that a model refusing the
        # parameter still runs and the endpoint default stays in place.
        if config.generation_temperature is not None:
            request["temperature"] = config.generation_temperature

        # Only json-object asks the API for a structured answer.
        # prompt-json leaves the contract to the prompt, for a model or
        # an endpoint that rejects the parameter. Neither mode is tried
        # after the other: a configured mode that is unavailable is an
        # error, and retrying with the other would spend a second
        # request the person never asked for.
        if config.generation_response_mode == "json-object":
            request["response_format"] = {"type": "json_object"}

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
            self._log_failure(config, error, None, started, request_id)
            raise UpstreamTimeoutError()
        except openai.APIConnectionError as error:
            self._log_failure(config, error, None, started, request_id)
            raise UpstreamConnectionError()
        except openai.APIStatusError as error:
            self._log_failure(config, error,
                              getattr(error, "status_code", None), started,
                              request_id)
            raise UpstreamStatusError()
        except openai.APIError as error:
            self._log_failure(config, error,
                              getattr(error, "status_code", None), started,
                              request_id)
            raise InvalidResponseError()

    def _log_failure(self, config: Config, error: Exception,
                     status_code: Optional[int], started: float,
                     request_id: str) -> None:
        """
        Record a failed request without its input or its token.

        The status is worth its own line even though the user is never
        told it apart: 401 is a token to replace, 403 a plan that does
        not cover the model, 429 a rate limit or an exhausted
        allowance, and only the log can say which happened.

        The elapsed seconds sit next to the limit for the same reason.
        A timeout that fired at the limit is an endpoint slower than
        the time allowed, which raising GENERATION_TIMEOUT addresses;
        one that fired well short of it is a connection lost on the
        way, and raising the limit would change nothing.

        Record the exception class but not its message. An SDK may put
        the upstream response body into an exception message, and that
        body can contain text that must stay out of the log.
        """
        logger.error(
            "generation failure: request_id=%s backend=%s endpoint_host=%s "
            "model=%s error=%s status=%s upstream_request_id=%s elapsed=%s "
            "timeout=%s",
            request_id or "-",
            config.generation_backend,
            config.endpoint_host,
            config.generation_model,
            type(error).__name__,
            status_code if status_code is not None else "-",
            getattr(error, "request_id", None) or "-",
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
            logger.error("The answer carries no choice")
            raise InvalidResponseError()

        choice = choices[0]
        finish_reason = getattr(choice, "finish_reason", None) or ""
        if finish_reason in TRUNCATED_REASONS:
            logger.error(
                "The output was cut off (finish_reason=%s); raise "
                "MAX_OUTPUT_TOKENS", finish_reason)
            raise InvalidResponseError()

        content = getattr(getattr(choice, "message", None), "content", None)
        if not isinstance(content, str) or not content.strip():
            logger.error("The answer carries no usable content")
            raise InvalidResponseError()

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
