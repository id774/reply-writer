#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# reply_writer/errors.py: Error hierarchy of reply-writer
#
#  Description:
#  Every failure the user is allowed to see is represented here as an
#  exception carrying a message and an HTTP status code. The screen
#  shows user_message only: the exception text, the traceback, the
#  endpoint URL and the model name stay in the server log, so that an
#  error page cannot leak internal information.
#
#  An exception belonging to an API library never reaches the web
#  layer. The provider maps one onto the classes below, and the status
#  codes are the ones the basic design fixes, written here once so that
#  no route can invent a status of its own.
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


class ReplyWriterError(Exception):
    """ Base of every error the user is allowed to see. """

    user_message = "The request could not be completed."
    status_code = 500


class EmptyInputError(ReplyWriterError):
    """ Raised when the received message is empty or blank. """

    user_message = "Paste the message you are replying to first."
    status_code = 400


class InputTooLongError(ReplyWriterError):
    """ Raised when the received message exceeds MAX_INPUT_CHARS. """

    status_code = 400

    def __init__(self, limit: int) -> None:
        self.user_message = (
            "The message is too long. Keep it within {0} characters, or "
            "paste the part you are replying to.".format(limit))
        super().__init__(self.user_message)


class DirectionTooLongError(ReplyWriterError):
    """ Raised when the direction exceeds MAX_POLICY_CHARS. """

    status_code = 400

    def __init__(self, limit: int) -> None:
        self.user_message = (
            "The direction is too long. Keep it within {0} "
            "characters.".format(limit))
        super().__init__(self.user_message)


class UpstreamConnectionError(ReplyWriterError):
    """ Raised when the endpoint cannot be reached. """

    user_message = "The generation service could not be reached. Try again in a while."
    status_code = 502


class UpstreamTimeoutError(ReplyWriterError):
    """
    Raised when one request exceeds GENERATION_TIMEOUT.

    The message asks for another attempt and nothing else. Shortening
    the message is not advised, because the wait is the time the
    endpoint spends writing the reply, and a limit only the operator
    can change is not something the person can act on.
    """

    user_message = "Generation took too long and was stopped. Generate it once more, or try again in a while."
    status_code = 504


class UpstreamStatusError(ReplyWriterError):
    """ Raised on a 4xx or 5xx answer, including auth and rate limits. """

    user_message = "The generation service answered with an error. Try again in a while."
    status_code = 502


class InvalidResponseError(ReplyWriterError):
    """ Raised when the answer cannot be read as the expected result. """

    user_message = "The reply could not be read. Generate it once more."
    status_code = 502


class InternalError(ReplyWriterError):
    """ Raised for every unexpected failure inside the server. """

    user_message = "The server failed to handle the request."
    status_code = 500
