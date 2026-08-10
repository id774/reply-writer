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
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import logging
import os
import re
from typing import Dict, List

from reply_writer.errors import InternalError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "system.md"
USER_PROMPT = "user.md"

# The placeholders the user prompt carries, matched in one pass.
PLACEHOLDER = re.compile(r"\{\{(message|direction)\}\}")


def load_prompt(name: str, prompt_dir: str) -> str:
    """ Read one prompt file and return its text. """
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

    # One pass over the template, so that text substituted for one
    # placeholder is never scanned for another. Chained replaces would
    # let a message carrying the literal '{{direction}}' decide where
    # the other block lands. The replacement is the value itself: the
    # callable form of re.sub() expands no backreference in it.
    values = {"message": message, "direction": direction}
    user = PLACEHOLDER.sub(lambda found: values[found.group(1)], user)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
