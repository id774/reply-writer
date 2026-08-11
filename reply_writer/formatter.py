#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# reply_writer/formatter.py: Post processing of the generated reply
#
#  Description:
#  This module turns the model output into text that can be pasted into
#  the application the message came from. It rewrites only what can be
#  decided mechanically: line endings, a code fence wrapping the whole
#  reply, trailing spaces, and runs of blank lines.
#
#  Nothing here touches what the reply says. There is no rule about
#  register, length, politeness, a formula or repetition in this file,
#  because a rule of that kind is an instruction to the model and lives
#  in prompts/system.md. A reply that reads wrongly is a prompt to
#  edit, not a branch to add here: a correction applied in Python would
#  be invisible to whoever is adjusting the prompt.
#
#  Where a mechanical change was made and is worth a human look, it is
#  reported as a notice. A notice is shown apart from the reply and
#  never enters what is copied.
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

import re
from typing import List, Optional, Tuple

FENCE = re.compile(r"^\s*```")


def _normalize_newlines(text: str) -> str:
    """ Reduce every line ending to a single line feed. """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_outer_fence(text: str) -> Tuple[str, bool]:
    """
    Remove a code fence wrapping the whole reply.

    Only a fence around the whole of it is removed. A reply carrying
    two fenced blocks of its own, with text between them, begins and
    ends with a fence as well, and dropping its first and last lines
    would leave the markup in the middle broken. Where a fence stands
    inside, the text is left as it is.
    """
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return text.strip(), False
    if not FENCE.match(lines[0]) or not FENCE.match(lines[-1]):
        return text.strip(), False
    if any(FENCE.match(line) for line in lines[1:-1]):
        return text.strip(), False
    return "\n".join(lines[1:-1]).strip(), True


def normalize_body(text: str) -> Tuple[str, List[str]]:
    """
    Clean the reply body and report what deserves a human look.

    Args:
        text: The body as the model returned it.

    Returns:
        The cleaned body and the notices raised while cleaning it. The
        notices belong to the screen and never to what is copied.
    """
    notices: List[str] = []

    body = _normalize_newlines(text)
    body, fenced = _strip_outer_fence(body)
    if fenced:
        # A fence is markup the medium does not want, and a reply
        # pasted into a chat with one is visibly wrong. Removing it
        # changes no word of the reply, but it is worth saying that the
        # answer arrived in a shape it was not asked for.
        notices.append("A code fence wrapping the reply was removed.")

    # Trailing spaces survive a copy and show up as stray whitespace at
    # the end of a line in the application the reply is pasted into.
    body = "\n".join(line.rstrip() for line in body.split("\n"))

    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body, notices


def normalize_subject(subject: Optional[str]) -> Optional[str]:
    """
    Clean a subject, or report that the reply carries none.

    A subject is one line by nature: a medium that has a subject field
    accepts no line break in it. Folding the whitespace is therefore
    mechanical, and a subject that is empty once folded is the same
    thing as no subject at all.
    """
    if subject is None:
        return None

    folded = " ".join(_normalize_newlines(subject).split())
    return folded or None
