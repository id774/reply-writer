#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# reply_writer/__init__.py: Package root of reply-writer
#
#  Description:
#  This module holds the data class that carries one generation result
#  through the whole system, the request id every run is followed by,
#  the configuration of the log, and the package version. It imports
#  nothing beyond the standard library, so every other module can
#  import it without pulling in Flask or the API client.
#
#  The log is configured here rather than in each entry point because
#  one rule of it is an invariant: no text a person entered and no
#  reply the model wrote is recorded, at any level. Keeping that in one
#  place is what stops app.py and cli.py from drifting apart on it.
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
import secrets
from dataclasses import dataclass, field
from typing import List, Optional

__version__ = "1.0"

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Loggers that would record the exchange itself rather than its shape.
# The API client writes its request options at DEBUG, and those options
# carry the assembled prompts, which carry the received message. These
# are lowered rather than the global level being held down, so that
# LOG_LEVEL=DEBUG stays usable for chasing a fault without any text of
# a person's reaching the log.
QUIET_LOGGERS = ("openai", "httpx", "httpcore")


@dataclass
class ReplyDraft:
    """ One generation result: the reply body and, where used, a subject. """

    body: str
    subject: Optional[str] = None
    model: str = ""
    generated_at: str = ""
    notices: List[str] = field(default_factory=list)


def configure_logging(level: str) -> None:
    """
    Configure the application log at an entry point.

    Args:
        level: The name of a level, as LOG_LEVEL carries it. One the
            standard module does not know reads as INFO, because a
            misspelled level is no reason to refuse to run.
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    # basicConfig does nothing once the root logger has a handler, and
    # an entry point calls this twice: once before the settings are
    # read, so that a refused setting is reported in this format, and
    # once after, so the level LOG_LEVEL asks for takes effect.
    logging.getLogger().setLevel(getattr(logging, level, logging.INFO))

    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def new_request_id() -> str:
    """
    Return an identifier for one generation, for the log.

    It is random rather than derived from anything the person entered,
    so that the id which appears on a screen and in the log carries no
    part of a private message.
    """
    return secrets.token_hex(4)
