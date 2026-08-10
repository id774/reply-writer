#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# reply_writer/providers/__init__.py: Choice of the generation transport
#
#  Description:
#  This package holds everything that knows how a generation endpoint
#  is spoken to: the SDK, the authentication, the base URL, the shape
#  of a request and the exceptions the client raises. Nothing above it
#  does. generator.py hands over a message list and receives a
#  CompletionResult, so adding a second wire protocol later leaves the
#  writing policy and the validation of a reply untouched.
#
#  The backend is chosen by name, from GENERATION_BACKEND, and only
#  from there. A value this version does not know is refused before a
#  request is made rather than read as the one backend that does exist,
#  because a system that guesses which endpoint was meant will
#  eventually guess wrong and send a private message somewhere nobody
#  chose. For the same reason there is no fallback: whatever went wrong
#  on the configured route is reported on it.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only; a provider module brings its own client
#
#  Version History:
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol

from config import Config
from reply_writer.errors import InternalError

logger = logging.getLogger(__name__)


@dataclass
class CompletionResult:
    """
    One answer, normalized away from the client that produced it.

    Only content is required. A compatible endpoint may report no usage
    and no request id, and a reply is still usable without them, so a
    missing count is carried as None rather than treated as a failure.

    elapsed_seconds is measured on this side rather than read from the
    answer, so it is present whatever the endpoint reports.
    """

    content: str
    model: str = ""
    finish_reason: str = ""
    upstream_request_id: str = ""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    elapsed_seconds: Optional[float] = None


class GenerationProvider(Protocol):
    """
    The interface generator.py depends on.

    A provider turns a message list into a CompletionResult, spending
    exactly one request, and raises the Upstream* errors of
    reply_writer.errors for a failure the user may be told about. It
    never inspects the JSON inside the answer: what a reply has to look
    like is not a property of the wire protocol.
    """

    def complete(self, messages: List[Dict[str, str]], config: Config,
                 request_id: str) -> CompletionResult:
        ...


def _openai_compatible() -> Callable[[], GenerationProvider]:
    """ Import the OpenAI compatible provider on demand. """
    from reply_writer.providers.openai_compatible import \
        OpenAICompatibleProvider
    return OpenAICompatibleProvider


# Backends this version can speak, by the name GENERATION_BACKEND takes.
# The values are loaders rather than classes, so that importing this
# package does not import an SDK a deployment may not need.
BACKENDS: Dict[str, Callable[[], Callable[[], GenerationProvider]]] = {
    "openai-compatible": _openai_compatible,
}


def build_provider(config: Config) -> GenerationProvider:
    """
    Return the provider named by GENERATION_BACKEND.

    Raises:
        InternalError: The backend is unknown.
            config.validate_generation_config() refuses that earlier
            and with a better message; reaching here means the two
            lists disagree, which is a fault of this repository and not
            of the operator.
    """
    loader = BACKENDS.get(config.generation_backend)
    if loader is None:
        logger.error("GENERATION_BACKEND '%s' has no provider; known: %s",
                     config.generation_backend, ", ".join(sorted(BACKENDS)))
        raise InternalError("unknown generation backend")
    return loader()()


def log_response(config: Config, result: CompletionResult,
                 request_id: str) -> None:
    """
    Record the shape of one answer, and none of its content.

    The received message, the direction, the assembled prompts, the
    generated reply and the token stay out of the log at every level.
    What is left is what an operator needs to follow one generation and
    to match a run against the usage counted by the provider.

    The elapsed seconds are part of that shape. A run that succeeded in
    almost the whole of GENERATION_TIMEOUT is the same event as the
    timeout that follows it, seen one moment earlier, and only a log
    that records the successful ones can show that the margin was
    already gone.
    """
    logger.info(
        "generation response: request_id=%s backend=%s endpoint_host=%s "
        "upstream_request_id=%s model=%s finish_reason=%s prompt_tokens=%s "
        "completion_tokens=%s total_tokens=%s elapsed=%s timeout=%s",
        request_id or "-",
        config.generation_backend,
        config.endpoint_host,
        result.upstream_request_id or "-",
        result.model or "-",
        result.finish_reason or "-",
        result.prompt_tokens,
        result.completion_tokens,
        result.total_tokens,
        result.elapsed_seconds if result.elapsed_seconds is not None else "-",
        config.generation_timeout,
    )
