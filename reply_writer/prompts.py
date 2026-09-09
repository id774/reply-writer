#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# reply_writer/prompts.py: Prompt loading and message assembly
#
#  Description:
#  The writing policy lives in prompts/*.md, outside the Python
#  package, so that it can be adjusted without reinstalling the code
#  and replaced as a whole by pointing PROMPT_DIR elsewhere. This
#  module reads those files and assembles the message list handed to
#  the API. It performs no API call.
#
#  Two things are placed into the user prompt and kept plainly apart:
#  the message being replied to, which is untrusted data, and the
#  direction the person wrote, which governs the reply. Which is which
#  is stated by the prompt file, not inferred here.
#
#  The placeholders are {{message}} and {{direction}}, substituted
#  literally rather than through str.format(), so that a brace written
#  in a prompt does not have to be escaped. A direction that is empty
#  substitutes as empty: an absent direction is an ordinary case, and
#  the prompt file says what an empty block means. Supplying a
#  stand-in sentence here would move a decision about wording out of
#  the prompts and into Python.
#
#  Before substitution, the message and the direction are each framed
#  in a request-specific boundary: a BEGIN/END pair carrying a random
#  identifier that is regenerated until it occurs in neither the
#  prompt source nor the input. Boundary-looking text already present
#  in the input therefore cannot be mistaken for the active boundary.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.2 2026-09-09
#       Framed prompt inputs with collision-free request boundaries.
#  v1.1 2026-09-07
#       Refuse a prompt source that omits, duplicates or adds a
#       double-brace placeholder, before it is substituted.
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import logging
import os
import re
import secrets
from typing import Dict, List

from reply_writer.errors import InternalError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "system.md"
USER_PROMPT = "user.md"

# The placeholders the user prompt carries, matched in one pass.
PLACEHOLDER = re.compile(r"\{\{(message|direction)\}\}")

# Every double-brace token in a prompt source, reserved as placeholder
# syntax. Matched against the source text alone, never against data
# already substituted into it.
ANY_PLACEHOLDER = re.compile(r"\{\{.*?\}\}")

REQUIRED_USER_PLACEHOLDERS = ("{{message}}", "{{direction}}")

# How many locally generated boundary identifiers are tried before a
# generation is refused. Every attempt is a local comparison with no
# external side effect; none of them spends a request.
BOUNDARY_ATTEMPTS = 32

DIRECTION_LABEL = "DIRECTION FROM THE PERSON WRITING THE REPLY"
MESSAGE_LABEL = "MESSAGE TO REPLY TO"


def _validate_prompt_contract(name: str, path: str, text: str) -> None:
    """
    Refuse a prompt source that breaks the placeholder contract.

    system.md carries no double-brace placeholder at all. user.md
    carries {{message}} and {{direction}} exactly once each, and no
    other double-brace form. The check runs against the source text
    read from disk, before any substitution.
    """
    found = ANY_PLACEHOLDER.findall(text)

    if name == SYSTEM_PROMPT:
        if found:
            logger.error("The prompt file %s carries a placeholder", path)
            raise InternalError(
                "prompt file carries a placeholder: {0}".format(path))
        return

    counts: Dict[str, int] = {}
    for token in found:
        counts[token] = counts.get(token, 0) + 1

    for placeholder in REQUIRED_USER_PLACEHOLDERS:
        if counts.pop(placeholder, 0) != 1:
            logger.error(
                "The prompt file %s does not carry %s exactly once",
                path, placeholder)
            raise InternalError(
                "prompt file placeholder count invalid: {0}".format(path))

    if counts:
        logger.error("The prompt file %s carries an unknown placeholder",
                     path)
        raise InternalError(
            "prompt file carries an unknown placeholder: {0}".format(path))


def _new_boundary_id(*texts: str) -> str:
    """
    Return a boundary identifier that occurs in none of the given texts.

    Each candidate is generated locally and compared against the
    prompt source and the input; none of this spends a request. A
    candidate that collides with any of the texts is discarded and
    another is drawn, up to BOUNDARY_ATTEMPTS times.
    """
    for _ in range(BOUNDARY_ATTEMPTS):
        candidate = secrets.token_hex(16)
        if all(candidate not in text for text in texts):
            return candidate

    logger.error(
        "Could not create a prompt boundary without an input collision")
    raise InternalError("prompt boundary collision")


def _frame_input(label: str, text: str, boundary_id: str) -> str:
    """ Wrap text in a BEGIN/END pair carrying the given boundary id. """
    return (
        "===== BEGIN {0} {1} =====\n{2}\n"
        "===== END {0} {1} ====="
    ).format(label, boundary_id, text)


def load_prompt(name: str, prompt_dir: str) -> str:
    """ Read one prompt file, refuse a malformed one, and return its text. """
    path = os.path.join(prompt_dir, name)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError as error:
        logger.error("Cannot read the prompt file %s: %s", path, error)
        raise InternalError("prompt file missing: {0}".format(path))

    # An empty prompt file is refused rather than sent. A reply written
    # without the writing policy would look like any other reply, and
    # nothing downstream could tell that the policy never arrived.
    if not text:
        logger.error("The prompt file %s is empty", path)
        raise InternalError("prompt file empty: {0}".format(path))

    _validate_prompt_contract(name, path, text)
    return text


def build_reply_messages(message: str, direction: str,
                         prompt_dir: str) -> List[Dict[str, str]]:
    """
    Build the messages that ask for a reply to one received message.

    Args:
        message: The received message, as the person pasted it in.
        direction: What this particular reply is to observe. Empty
            where the person gave none, which is an ordinary case.
        prompt_dir: Directory the prompt files are read from.

    Returns:
        The message list handed to the generation API, the writing
        policy first and the data being replied to after it.
    """
    system = load_prompt(SYSTEM_PROMPT, prompt_dir)
    user = load_prompt(USER_PROMPT, prompt_dir)

    boundary_id = _new_boundary_id(system, user, message, direction)

    # One pass over the template, so that text substituted for one
    # placeholder is never scanned for another. Chained replaces would
    # let a message carrying the literal '{{direction}}' decide where
    # the other block lands. The replacement is the value itself: the
    # callable form of re.sub() expands no backreference in it.
    values = {
        "message": _frame_input(MESSAGE_LABEL, message, boundary_id),
        "direction": _frame_input(DIRECTION_LABEL, direction, boundary_id),
    }
    user = PLACEHOLDER.sub(lambda found: values[found.group(1)], user)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
