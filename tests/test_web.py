#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_web.py: Tests for app.py
#
#  Description:
#  This test suite drives the Flask application through its test
#  client. It covers the three routes, the shape of the two screens,
#  and the refusals the web layer has to make: an empty message, one
#  longer than MAX_INPUT_CHARS, and a request larger than the server
#  limit, with what was typed kept on the page so that nothing is lost.
#
#  It also pins the error handling. Each failure is answered with its
#  own status, 404 for an unknown address and 405 for a method the
#  address does not accept included, and no page ever shows a
#  traceback, the requested path or the cause of an upstream failure.
#
#  Three cases guard invariants rather than features: the subject field
#  is absent from a page when the reply carries no subject, the API
#  token appears in no response, and no text a person entered or the
#  model generated reaches the log. They are not deleted to make a
#  refactor pass.
#
#  No request is made. generate_reply is replaced by a stub, and the
#  settings app.py validates while it is imported are set with
#  setdefault so that a real .env is left alone.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Running the tests:
#  Run the whole suite from the repository root:
#      python -m unittest discover -s tests
#  Run this module alone:
#      python -m unittest tests.test_web
#
#  Test Cases:
#    - Show the input screen, with the direction marked optional.
#    - Answer the liveness probe without calling the API.
#    - Return no setting and no personal data from the liveness probe.
#    - Generate a draft from a message with no direction.
#    - Carry the direction to the generation core where there is one.
#    - Show a subject apart from the body when the reply has one.
#    - Show no subject field at all when the reply has none.
#    - Keep what was typed on the page when the message is too long.
#    - Refuse an empty message with status 400.
#    - Refuse a request larger than the server limit with status 413.
#    - Hide the cause of a generation failure behind its own status.
#    - Map a timeout onto 504 and an unreachable endpoint onto 502.
#    - Show a request id on a failure that is not the person's to fix.
#    - Answer an unknown address with 404 rather than 500.
#    - Refuse a method the address does not accept with status 405.
#    - Hide the cause and the requested path of a routing failure.
#    - Still report an unexpected failure as a server error.
#    - Show no traceback and no internal path on any error page.
#    - Keep the API token out of every response.
#    - Write no message, direction or reply to the log.
#    - Request generation with POST, so nothing entered reaches a URL.
#    - Load no script and no style from another host.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Flask
#
#  Version History:
#  v1.0 2026-08-10
#       Initial release.
#
########################################################################

import logging
import os
import re
import unittest
from unittest import mock

# app.py validates the generation settings while it is imported, so a
# worker that cannot address an endpoint refuses to start. These values
# are what that check needs and nothing more: no request is ever made,
# and setdefault leaves a real .env alone when one is present.
os.environ.setdefault("GENERATION_BACKEND", "openai-compatible")
os.environ.setdefault("GENERATION_API_TOKEN", "test-token-value")
os.environ.setdefault("GENERATION_BASE_URL", "https://api.example.test/v1")
os.environ.setdefault("GENERATION_MODEL", "test-model")

import app as web  # noqa: E402  imported after the settings above
from reply_writer import ReplyDraft  # noqa: E402
from reply_writer.errors import (EmptyInputError,  # noqa: E402
                                 InputTooLongError, InternalError,
                                 UpstreamConnectionError, UpstreamTimeoutError)

TOKEN = web.config.generation_api_token

# Invented material. No real correspondence is used as test data.
MESSAGE = "打ち合わせの候補日をお送りします。ご都合はいかがでしょうか。"
DIRECTION = "二番目の候補で受けること。"
REPLY = "ご連絡ありがとうございます。二番目の候補でお願いいたします。"
SUBJECT = "Re: 打ち合わせの候補日"


def draft(body=REPLY, subject=None, notices=None):
    """ Return a draft the stubbed generation core hands back. """
    return ReplyDraft(body=body, subject=subject, model="test-model",
                      generated_at="2026-08-10T12:00:00+09:00",
                      notices=notices or [])


class WebTestCase(unittest.TestCase):
    """ Shared test client and stubbing of the generation core. """

    def setUp(self):
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def post(self, message=MESSAGE, direction="", result=None, **extra):
        """ Post one generation, with the generation core stubbed. """
        form = {"message": message, "direction": direction}
        form.update(extra)
        if result is None:
            result = draft()

        with mock.patch("app.generate_reply") as generate:
            if isinstance(result, Exception):
                generate.side_effect = result
            else:
                generate.return_value = result
            self.generate = generate
            return self.client.post("/generate", data=form)


class RouteTest(WebTestCase):
    """ Cover the three routes the initial version serves. """

    def test_shows_the_input_screen(self):
        """ Offer a message field, a direction field and a way to go. """
        response = self.client.get("/")
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="message"', page)
        self.assertIn('name="direction"', page)
        self.assertIn("(optional)", page)

    def test_liveness_probe_calls_no_api(self):
        """ Answer as a web application and do nothing else. """
        with mock.patch("app.generate_reply") as generate:
            response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})
        generate.assert_not_called()

    def test_liveness_probe_returns_no_setting(self):
        """ Return no setting and no personal data from the probe. """
        page = self.client.get("/healthz").get_data(as_text=True)
        for secret in (TOKEN, web.config.generation_base_url,
                       web.config.generation_model):
            self.assertNotIn(secret, page)

    def test_generates_without_a_direction(self):
        """ Generate a draft when the direction was left empty. """
        response = self.post(direction="")
        self.assertEqual(response.status_code, 200)
        self.assertIn(REPLY, response.get_data(as_text=True))
        self.assertEqual(self.generate.call_args[0][1], "")

    def test_carries_the_direction_to_the_core(self):
        """ Hand the direction to the generation core where given. """
        self.post(direction=DIRECTION)
        self.assertEqual(self.generate.call_args[0][0], MESSAGE)
        self.assertEqual(self.generate.call_args[0][1], DIRECTION)

    def test_generation_is_a_post(self):
        """ Keep what was entered out of a URL, a log and a history. """
        self.assertEqual(self.client.get("/generate").status_code, 405)


class ResultScreenTest(WebTestCase):
    """ Cover what the draft screen shows and what it copies. """

    def test_shows_a_subject_apart_from_the_body(self):
        """ Offer the subject and the body as two separate copies. """
        page = self.post(result=draft(subject=SUBJECT)).get_data(as_text=True)
        self.assertIn(SUBJECT, page)
        self.assertIn('data-copy-target="reply-subject"', page)
        self.assertIn('data-copy-target="reply-body"', page)

    def test_shows_no_subject_field_when_there_is_none(self):
        """
        Leave the subject out of the page, rather than show it empty.

        LINE, SMS and chat have no subject. An empty field on the page
        invites one to be pasted into a medium that has none, which is
        a visible mistake in the message somebody sends.
        """
        page = self.post(result=draft(subject=None)).get_data(as_text=True)
        self.assertNotIn("reply-subject", page)
        self.assertNotIn("Copy the subject", page)

    def test_shows_a_notice_apart_from_the_reply(self):
        """ Keep a notice outside the element that is copied. """
        page = self.post(result=draft(
            notices=["A code fence wrapping the reply was removed."]
        )).get_data(as_text=True)
        self.assertIn("code fence", page)
        body_field = page.split('id="reply-body"')[1].split("</textarea>")[0]
        self.assertNotIn("code fence", body_field)

    def test_shows_no_operational_setting(self):
        """ Keep the model, the endpoint and the backend off the page. """
        page = self.post().get_data(as_text=True)
        for setting in (web.config.generation_base_url,
                        web.config.generation_backend, TOKEN):
            self.assertNotIn(setting, page)


class RefusalTest(WebTestCase):
    """ Cover the refusals and the failures the screens report. """

    def test_refuses_an_empty_message(self):
        """ Refuse an empty message with a status of its own. """
        response = self.post(message="", result=EmptyInputError())
        self.assertEqual(response.status_code, 400)

    def test_keeps_what_was_typed_when_the_message_is_too_long(self):
        """ Return the person to the input screen with their text. """
        response = self.post(direction=DIRECTION,
                             result=InputTooLongError(20))
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn(MESSAGE, page)
        self.assertIn(DIRECTION, page)
        self.assertIn("20", page)

    def test_refuses_a_request_larger_than_the_server_limit(self):
        """ Refuse an oversized request without parsing its form. """
        oversized = "あ" * (web.app.config["MAX_CONTENT_LENGTH"] + 1)
        response = self.client.post("/generate", data={"message": oversized})
        self.assertEqual(response.status_code, 413)

    def test_hides_the_cause_of_a_generation_failure(self):
        """ Answer with a status and a sentence, and nothing internal. """
        response = self.post(result=UpstreamConnectionError())
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("Traceback", page)
        self.assertNotIn(web.config.generation_base_url, page)

    def test_maps_a_timeout_and_an_unreachable_endpoint(self):
        """ Keep the status of each failure the basic design fixes. """
        self.assertEqual(self.post(result=UpstreamTimeoutError()).status_code,
                         504)
        self.assertEqual(
            self.post(result=UpstreamConnectionError()).status_code, 502)

    def test_shows_a_request_id_on_a_failure(self):
        """ Give the person something to quote to the operator. """
        with self.assertLogs(logging.getLogger("app"), "ERROR") as recorded:
            page = self.post(result=InternalError()).get_data(as_text=True)
        recorded_id = "\n".join(recorded.output).split("(request ")[1][:8]
        self.assertIn(recorded_id, page)

    def test_shows_no_request_id_on_an_ordinary_refusal(self):
        """ Say nothing about an id for a message the person can fix. """
        page = self.post(result=EmptyInputError()).get_data(as_text=True)
        self.assertNotIn("(request ", page)

    def test_answers_an_unknown_address_with_404(self):
        """ Report a page that is not there as a page that is not there. """
        for path in ("/nowhere", "/favicon.ico"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("Traceback", response.get_data(as_text=True))

    def test_hides_the_requested_path_of_a_routing_failure(self):
        """ Reflect nothing the visitor asked for back onto the page. """
        page = self.client.get("/nowhere-at-all").get_data(as_text=True)
        self.assertNotIn("nowhere-at-all", page)

    def test_reports_an_unexpected_failure_as_a_server_error(self):
        """ Report a failure of ours as ours, without its detail. """
        with self.assertLogs(logging.getLogger("app"), "ERROR"):
            response = self.post(result=RuntimeError("some internal detail"))
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("some internal detail", page)
        self.assertNotIn("Traceback", page)
        self.assertNotIn(os.path.dirname(os.path.abspath(web.__file__)), page)


class InvariantTest(WebTestCase):
    """
    Guard the invariants the requirements attach to the web layer.

    These cases exist to protect an invariant rather than a feature:
    the API token never reaches the browser, and no text a person
    entered or the model generated reaches the log. They are not
    deleted to make a refactor pass.
    """

    def test_the_token_reaches_no_response(self):
        """ Keep the credential inside the server process. """
        responses = [
            self.client.get("/"),
            self.client.get("/healthz"),
            self.client.get("/nowhere"),
            self.post(),
            self.post(result=UpstreamConnectionError()),
            self.post(message="", result=EmptyInputError()),
        ]
        for response in responses:
            self.assertNotIn(TOKEN, response.get_data(as_text=True))
            self.assertNotIn(TOKEN, str(response.headers))

    def test_no_page_loads_anything_from_another_host(self):
        """
        Fetch no font, script, style or beacon from elsewhere.

        Every reference a page makes has to stay inside this
        application. A stylesheet, a script or an image fetched from
        another host tells that host who is using the system and when,
        and a script fetched from one can read what is on the screen.
        """
        for page in (self.client.get("/").get_data(as_text=True),
                     self.post(result=draft(subject=SUBJECT))
                     .get_data(as_text=True)):
            for reference in re.findall(r'(?:src|href)="([^"]*)"', page):
                self.assertTrue(reference.startswith("/"),
                                "off-site reference: " + reference)

    def assert_nothing_entered_was_logged(self, records):
        """ Assert that no recorded line carries any of the text. """
        written = "\n".join(records)
        for text in (MESSAGE, DIRECTION, REPLY, SUBJECT):
            self.assertNotIn(text, written)

    def test_a_generation_writes_no_text_to_the_log(self):
        """ Write no message, direction or reply on the ordinary path. """
        with self.assertLogs(logging.getLogger(), "DEBUG") as recorded:
            logging.getLogger("tests").info("generating")
            self.post(direction=DIRECTION, result=draft(subject=SUBJECT))
        self.assert_nothing_entered_was_logged(recorded.output)

    def test_a_refusal_writes_no_text_to_the_log(self):
        """ Write none of it when the request is refused either. """
        with self.assertLogs(logging.getLogger(), "DEBUG") as recorded:
            self.post(direction=DIRECTION, result=InputTooLongError(20))
            self.post(direction=DIRECTION, result=UpstreamTimeoutError())
        self.assert_nothing_entered_was_logged(recorded.output)


if __name__ == "__main__":
    unittest.main()
