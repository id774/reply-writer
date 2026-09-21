#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# reply_writer/generator.py: Generation core of reply-writer
#
#  Description:
#  This module validates the input, assembles the messages, spends one
#  request through the configured provider, reads the JSON object out
#  of the answer, validates it and returns a ReplyDraft. It knows
#  nothing about HTTP, Flask, the SDK, the token or the base URL: the
#  transport lives in reply_writer/providers/ and the web layer above
#  it, which is what lets cli.py and app.py be the same generation.
#
#  The answer is requested as JSON so that the subject and the body
#  arrive as separate fields. Guessing that the first line of a piece
#  of prose is the subject is the heuristic that lets a remark by the
#  model become part of a reply someone sends, and nothing here does
#  it. For the same reason nothing here digs a JSON object out of
#  surrounding prose: either the whole answer is the object — or, under
#  prompt-json, a single fenced block holding it — or the answer is
#  refused. An endpoint that explains itself first is misconfigured,
#  and reading past the explanation would hide that.
#
#  The received message is data being replied to and never an
#  instruction. It reaches the model inside the block the user prompt
#  marks out for it, and no sentence found in it is acted on here.
#
#  Author: id774 (More info: https://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only; the provider brings the client
#
#  Version History:
#  v1.1 2026-09-21
#       Matched input limits to textarea length and carried safe diagnostics.
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import Config
from reply_writer import ReplyDraft
from reply_writer.errors import (DirectionTooLongError, EmptyInputError,
                                 InputTooLongError, InvalidResponseError)
from reply_writer.formatter import normalize_body, normalize_subject
from reply_writer.prompts import build_reply_messages
from reply_writer.providers import build_provider


def _textarea_length(text: str) -> int:
    """
    Return the length of text as a browser textarea's value.length.

    A browser counts UTF-16 code units: CRLF and a lone CR each count
    as the one LF a textarea normalizes a line ending to, a character
    inside the Basic Multilingual Plane counts as one, and a character
    above it, which JavaScript represents as a surrogate pair, counts
    as two. MAX_INPUT_CHARS and MAX_POLICY_CHARS are enforced through
    this same count, on the web and on the CLI, so the limit shown in
    the browser and the one applied on the server never disagree.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return sum(
        2 if ord(character) > 0xffff else 1
        for character in normalized
    )


def _unwrap_fence(content: str) -> str:
    """
    Return the inside of an answer that is one fenced block, or the
    answer unchanged.

    Only a whole answer wrapped in a single fence is unwrapped. A fence
    with prose around it, or an answer holding more than one fence, is
    left as it is and fails to parse a moment later, which is the
    intended outcome: the model was asked for an object and returned
    something else.
    """
    text = content.strip()
    if not text.startswith("```") or not text.endswith("```"):
        return text

    lines = text.split("\n")
    if len(lines) < 3 or lines[-1].strip() != "```":
        return text
    # Anything but an info string on the opening line means the fence
    # is not the wrapper of the whole answer.
    if "`" in lines[0].strip()[3:]:
        return text

    inner = "\n".join(lines[1:-1])
    # A further fence is one that opens a line. The answer is a JSON
    # object, whose strings hold no line break, so a reply that speaks
    # of a fence carries those characters in the middle of a line and
    # is not a second fence: refusing on the characters alone would
    # throw away a well formed answer for what the reply says.
    if any(line.lstrip().startswith("```") for line in inner.split("\n")):
        return text
    return inner.strip()


def _payload(content: str, response_mode: str) -> Dict[str, Any]:
    """ Read the JSON object carried by the answer. """
    text = content.strip()
    if response_mode == "prompt-json":
        text = _unwrap_fence(text)

    try:
        payload = json.loads(text)
    except ValueError:
        # The answer itself, and the parser's own message, stay out of
        # the diagnostic: what is useful is that it was not JSON.
        raise InvalidResponseError("answer is not readable as JSON") from None

    if not isinstance(payload, dict):
        raise InvalidResponseError("answer is JSON but not an object")
    return payload


def _body(payload: Dict[str, Any]) -> str:
    """ Return the reply body the answer carries, or refuse the answer. """
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        raise InvalidResponseError("answer has no usable body")
    return body


def _subject(payload: Dict[str, Any]) -> Optional[str]:
    """
    Return the subject the answer carries, where it carries one.

    A medium without a subject is the ordinary case here, so null and
    an absent field both mean the reply has none. A value that is
    neither a string nor null is refused rather than coerced: it means
    the answer did not keep the contract, and the next field may not
    have kept it either.
    """
    subject = payload.get("subject")
    if subject is None:
        return None
    if not isinstance(subject, str):
        raise InvalidResponseError("answer subject is not a string or null")
    return subject


def _now() -> str:
    """ Return the current time in ISO 8601. """
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def validate_input(message: str, direction: str, config: Config) -> None:
    """
    Refuse an input that must not reach the endpoint.

    The limits are enforced before a request is spent rather than after
    it, so that an input nobody would accept costs nothing.

    Args:
        message: The received message, as it was pasted in.
        direction: What this reply is to observe. Empty is valid.
        config: The settings carrying MAX_INPUT_CHARS and
            MAX_POLICY_CHARS.

    Raises:
        EmptyInputError: There is no message to reply to.
        InputTooLongError: The message exceeds MAX_INPUT_CHARS.
        DirectionTooLongError: The direction exceeds MAX_POLICY_CHARS.
    """
    if not message.strip():
        raise EmptyInputError()
    if _textarea_length(message) > config.max_input_chars:
        raise InputTooLongError(config.max_input_chars)
    if _textarea_length(direction) > config.max_policy_chars:
        raise DirectionTooLongError(config.max_policy_chars)


def generate_reply(message: str, direction: str, config: Config,
                   request_id: str = "") -> ReplyDraft:
    """
    Generate a draft reply to one received message.

    Args:
        message: The received message, as the person pasted it in. It
            is untrusted data being replied to, never an instruction.
        direction: What this particular reply is to observe. Empty
            where the person gave none, which is an ordinary case and
            not a failure.
        config: The settings addressing the endpoint and bounding the
            input.
        request_id: Identifier this generation is followed by in the
            log. It carries nothing that was entered.

    Returns:
        The draft, with the body always present and the subject present
        only where the reply calls for one.
    """
    validate_input(message, direction, config)

    messages = build_reply_messages(message, direction, config.prompt_dir)
    result = build_provider(config).complete(messages, config, request_id)
    payload = _payload(result.content, config.generation_response_mode)

    body, notices = normalize_body(_body(payload))
    subject = normalize_subject(_subject(payload))

    # The body was answered and is empty once the markup around it has
    # gone, which leaves nothing to copy. It is refused here rather
    # than shown, because a blank draft on the screen reads as a fault
    # of the screen and tells the person nothing to do about it.
    if not body:
        raise InvalidResponseError(
            "answer carries no body outside its markup")

    return ReplyDraft(
        body=body,
        subject=subject,
        model=result.model or config.generation_model,
        generated_at=_now(),
        notices=notices,
    )
