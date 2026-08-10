#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# cli.py: Command line entry point of reply-writer
#
#  Description:
#  This script calls the same generation core as the web application,
#  without starting Flask. It exists so that the prompts can be
#  adjusted, the quality of a draft judged and an endpoint verified
#  from a terminal, which is where all three are settled before any
#  screen is involved. It implements no second generation path.
#
#  It ends at a draft on standard output, as the web application ends
#  at a draft on the screen. Nothing here sends a reply anywhere.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Usage:
#      python cli.py generate --message message.txt
#      python cli.py generate --message - --direction direction.txt
#      python cli.py generate --message message.txt [--model NAME] [--json]
#      python cli.py -h | --help
#      python cli.py -v | --version
#
#  Options:
#  - generate
#      Generate a draft reply to a received message.
#  - --message FILE
#      File holding the received message. '-' reads standard input.
#      Required. The message is read from a file rather than from an
#      argument because a command line is readable by every user of the
#      host through ps, and private correspondence has no business
#      there.
#  - --direction FILE
#      File holding the direction for this reply. Optional, for the
#      same reason. Leaving it out is an ordinary case.
#  - --model NAME / --prompt-dir DIR / --timeout SECONDS
#      Override GENERATION_MODEL, PROMPT_DIR and GENERATION_TIMEOUT for
#      this invocation. --timeout is held to the rule
#      GENERATION_TIMEOUT follows, a number greater than zero. The API
#      token and the base URL have no option on purpose: the token is a
#      secret, and the endpoint is a decision of the deployment.
#  - --json
#      Print the draft as JSON instead of as text.
#
#  Exit Codes:
#  - 0: The draft was generated and printed. Also what -h and -v
#       return.
#  - 1: The command failed: a setting or an option was refused, the
#       generation settings cannot address an endpoint, the message
#       could not be read or was empty, or the endpoint did not return
#       a usable draft.
#  - 2: The command line was rejected by argparse, for example an
#       unknown option, a missing subcommand, or --timeout given
#       something that is not a number.
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

import argparse
import dataclasses
import json
import logging
import sys
from typing import Optional

from config import ConfigError, load_config, validate_generation_config
from reply_writer import (ReplyDraft, __version__, configure_logging,
                          new_request_id)
from reply_writer.errors import ReplyWriterError
from reply_writer.generator import generate_reply

logger = logging.getLogger("cli")


def build_parser() -> argparse.ArgumentParser:
    """ Describe the commands and the options they accept. """
    parser = argparse.ArgumentParser(
        description="Draft a reply to a received message.")
    parser.add_argument("-v", "--version", action="version",
                        version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser(
        "generate", help="Generate a draft reply to a received message.")
    generate.add_argument("--message", required=True,
                          help="File holding the received message, or '-'.")
    generate.add_argument("--direction",
                          help="File holding the direction for this reply.")
    generate.add_argument("--model", help="Override GENERATION_MODEL.")
    generate.add_argument("--prompt-dir", help="Override PROMPT_DIR.")
    generate.add_argument("--timeout", type=float,
                          help="Override GENERATION_TIMEOUT, in seconds.")
    generate.add_argument("--json", action="store_true",
                          help="Print the draft as JSON.")

    return parser


def read_text(path: Optional[str]) -> str:
    """
    Return the contents of one file, standard input, or nothing.

    Args:
        path: The file to read, '-' for standard input, or None when
            the option was left out.

    Returns:
        The text, or an empty string where no file was named. An option
        that is left out changes nothing, and an absent direction is an
        ordinary case rather than a failure.
    """
    if path is None:
        return ""
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def report(draft: ReplyDraft, as_json: bool) -> None:
    """ Print the draft for a person, or as JSON for a pipe. """
    if as_json:
        print(json.dumps(dataclasses.asdict(draft), ensure_ascii=False,
                         indent=2))
        return

    if draft.subject:
        print("Subject: {0}".format(draft.subject))
        print()
    print(draft.body)

    # The notices go to standard error, so that redirecting standard
    # output gives the reply and nothing that was said about it.
    for notice in draft.notices:
        print("\n[notice] {0}".format(notice), file=sys.stderr)


def main() -> int:
    """ Run one command and return its exit status. """
    arguments = build_parser().parse_args()

    # Configured before the settings are read, so that a refused
    # setting is reported in the same format as everything else. The
    # level LOG_LEVEL asks for is applied as soon as it is known.
    configure_logging("INFO")

    try:
        config = load_config()
    except ConfigError as error:
        logger.error("%s", error)
        return 1

    configure_logging(config.log_level)

    if arguments.model:
        config.generation_model = arguments.model
    if arguments.prompt_dir:
        config.prompt_dir = arguments.prompt_dir

    # Repeat the check load_config() performs on GENERATION_TIMEOUT.
    # The override lands after it has run, so a value refused there
    # would otherwise reach the SDK through the option instead.
    if arguments.timeout is not None:
        if arguments.timeout <= 0:
            logger.error("--timeout is %s; expected a positive number.",
                         arguments.timeout)
            return 1
        config.generation_timeout = arguments.timeout

    # After the overrides, so that --model can stand in for a missing
    # GENERATION_MODEL, and before the message is read, so that a
    # misconfiguration is reported without spending a request.
    try:
        validate_generation_config(config)
    except ConfigError as error:
        logger.error("%s", error)
        return 1

    try:
        message = read_text(arguments.message)
        direction = read_text(arguments.direction)
        draft = generate_reply(message, direction, config, new_request_id())
    except ReplyWriterError as error:
        # Fall back to user_message. Most of these carry no text of
        # their own, so the class name alone would say nothing.
        logger.error("%s: %s", type(error).__name__,
                     str(error) or error.user_message)
        return 1
    except OSError as error:
        logger.error("Cannot read the input: %s", error)
        return 1

    report(draft, arguments.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
