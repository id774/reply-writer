#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# app.py: Flask application of reply-writer
#
#  Description:
#  This module serves the input screen, calls the generation core and
#  renders the draft. It keeps no server side state: the message and
#  the direction travel with the form and are gone when the response
#  has been written, so any worker can answer any request and a restart
#  loses nothing belonging to anybody.
#
#  It holds no logic of its own for writing a reply, and it ends at the
#  draft. Nothing here sends a reply anywhere: the person copies it,
#  reads it once more and sends it from the application the message
#  came from. The only host contacted is the one named by
#  GENERATION_BASE_URL, and the API token stays in the server process:
#  it reaches neither the templates nor the error pages.
#
#  Every request carries a request id, which is shown on an unexpected
#  failure and written to the log, so that a fault can be found without
#  any of the text being kept.
#
#  The generation settings are validated while this module is imported,
#  so a worker that cannot address an endpoint refuses to start instead
#  of accepting a message and failing on the request. systemd reports
#  the message, which names the setting at fault.
#
#  Routes:
#      /            input screen
#      /generate    generate a draft reply
#      /healthz     liveness probe; it calls no API
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Usage:
#      python app.py
#      gunicorn app:app --bind 127.0.0.1:${PORT} --timeout 240
#
#  Options:
#  - None. Every setting comes from the environment or .env, through
#    config.py.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Flask 3.x
#
#  Version History:
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import logging

from flask import Flask, g, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from config import load_config, validate_generation_config
from reply_writer import configure_logging, new_request_id
from reply_writer.errors import InternalError, ReplyWriterError
from reply_writer.generator import generate_reply
from reply_writer.web import STATIC_DIR, TEMPLATE_DIR

config = load_config()

configure_logging(config.log_level)
logger = logging.getLogger(__name__)

# Refuse the process rather than the request. A screen offering to
# generate for someone whose server cannot reach an endpoint wastes the
# message they pasted; the operator sees the setting named in the
# journal instead.
validate_generation_config(config)

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

# The application is served under a path of the web server's choosing,
# /reply/ in the deployment the basic design describes, while it listens
# at its own root. X-Forwarded-Prefix is what carries that path in, so
# that a link and a form action come back through the same prefix.
# Only the prefix is taken: the address and the scheme of the client are
# the web server's business, and trusting more headers than are needed
# widens what a request can claim about itself. Nothing here is exposed
# directly, so the header can only come from the proxy in front.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=0, x_prefix=1)

# What the screen says about an address the application does not serve.
# The wording is ours rather than the one werkzeug carries, which
# advises checking the spelling of a URL the visitor never typed.
HTTP_MESSAGES = {
    404: "That page does not exist.",
    405: "That address does not accept this kind of request.",
}


def _request_id() -> str:
    """ Return the id of the current request, assigning one if needed. """
    if not hasattr(g, "request_id"):
        g.request_id = new_request_id()
    return g.request_id


def _screen_values() -> dict:
    """
    Return what every screen needs, including what was typed.

    An input screen shown after a failure keeps the message and the
    direction, so that a refusal does not cost the person the text they
    pasted. The values travel with the form and are held nowhere else.
    """
    return {
        "message": request.form.get("message", ""),
        "direction": request.form.get("direction", ""),
        "max_input_chars": config.max_input_chars,
        "max_policy_chars": config.max_policy_chars,
    }


@app.before_request
def assign_request_id() -> None:
    """ Give the request an id to be followed by in the log. """
    g.request_id = new_request_id()


@app.route("/")
def index():
    """ Render the input screen. """
    return render_template("index.html", message="", direction="",
                           max_input_chars=config.max_input_chars,
                           max_policy_chars=config.max_policy_chars)


@app.route("/generate", methods=["POST"])
def generate():
    """ Generate one draft reply and render it. """
    values = _screen_values()
    draft = generate_reply(values["message"], values["direction"], config,
                           _request_id())
    return render_template("result.html", draft=draft, **values)


@app.route("/healthz")
def healthz():
    """ Answer that the process is alive without calling the API. """
    return {"status": "ok"}


@app.errorhandler(ReplyWriterError)
def handle_known_error(error: ReplyWriterError):
    """ Show the message meant for the user and log the cause. """
    request_id = _request_id()
    # An input the person can correct is not a failure of the server.
    level = logging.INFO if error.status_code == 400 else logging.ERROR
    logger.log(level, "%s (request %s): %s", type(error).__name__, request_id,
               error)

    # A refusal the person can act on returns them to the input screen
    # with what they typed still there. Anything else is not theirs to
    # fix, and says so on a page of its own.
    template = "index.html" if error.status_code == 400 else "error.html"

    # The id is shown where the person has to quote it to whoever runs
    # the system. A message they can act on by themselves does not need
    # one, and printing an identifier beside it only makes an ordinary
    # refusal look like a fault.
    page = render_template(
        template,
        error=error.user_message,
        request_id=None if error.status_code == 400 else request_id,
        **_screen_values())
    return page, error.status_code


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(error: RequestEntityTooLarge):
    """ Refuse an oversized request without parsing its form again. """
    request_id = _request_id()
    logger.info("RequestEntityTooLarge (request %s): %s", request_id, error)
    page = render_template(
        "error.html",
        error="The request is too large. Reduce its contents and try again.",
        request_id=request_id,
        max_input_chars=config.max_input_chars,
        max_policy_chars=config.max_policy_chars,
    )
    return page, error.code


@app.errorhandler(HTTPException)
def handle_http_error(error: HTTPException):
    """
    Answer an address the application does not serve.

    Flask looks an error handler up along the class hierarchy of the
    exception, and every HTTPException is an Exception. Without this
    handler a routing failure would reach the one below, which logs a
    traceback and answers 500: a browser asking for /favicon.ico would
    be reported as a server that had broken. A page that is not there
    is not a failure of the server, so it keeps its own status and is
    logged as a note.
    """
    request_id = _request_id()
    level = logging.INFO if error.code < 500 else logging.ERROR
    logger.log(level, "%s (request %s): %s %s", type(error).__name__,
               request_id, error.code, request.path)

    page = render_template(
        "error.html",
        error=HTTP_MESSAGES.get(error.code,
                                "The request could not be completed."),
        request_id=request_id,
        max_input_chars=config.max_input_chars,
        max_policy_chars=config.max_policy_chars,
    )
    return page, error.code


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    """ Report an unexpected failure without exposing its detail. """
    logger.exception("Unexpected failure (request %s): %s", _request_id(),
                     type(error).__name__)
    return handle_known_error(InternalError())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=config.port)
