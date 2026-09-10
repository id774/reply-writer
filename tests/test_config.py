#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_config.py: Tests for config.py
#
#  Description:
#  This test suite covers the two stages of configuration handling.
#  load_config() converts the environment and refuses a value that is
#  malformed on its own terms; validate_generation_config() refuses a
#  configuration that cannot address an endpoint. The suite also pins
#  the documented defaults and the reading of a blank value as unset.
#
#  A recurring concern of its own is that the API token never leaves
#  the process: it must appear in no repr and in no error message,
#  whichever setting was the one refused.
#
#  Author: id774 (More info: https://id774.net)
#  Source Code: https://github.com/id774/reply-writer
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Running the tests:
#  Run the whole suite from the repository root:
#      python -m unittest discover -s tests
#  Run this module alone:
#      python -m unittest tests.test_config
#
#  Test Cases:
#    - Load the documented defaults for every setting that has one.
#    - Default the port to 8091.
#    - Spend one request unless GENERATION_MAX_RETRIES says otherwise.
#    - Treat a blank or whitespace-only value as unset.
#    - Send no temperature unless GENERATION_TEMPERATURE is set.
#    - Refuse a value that is not a number, naming the setting.
#    - Refuse a value float() reads as nan or as infinity.
#    - Refuse a timeout that is not positive.
#    - Refuse a negative retry count.
#    - Refuse an unknown response mode, naming the accepted ones.
#    - Refuse a character limit of zero.
#    - Refuse a port outside the valid range.
#    - Keep the API token out of repr while leaving the value readable.
#    - Report the host of the base URL.
#    - Accept a complete generation configuration.
#    - Refuse a missing backend, and an unknown one by name.
#    - Refuse a missing token, and one carrying a line break.
#    - Refuse a missing, plain http or relative base URL.
#    - Refuse a base URL carrying user information or a query.
#    - Refuse a base URL that already holds the resource path.
#    - Accept a base URL whose host is a bracketed IPv6 literal.
#    - Refuse a base URL with no hostname, a malformed IPv6 authority, an
#      invalid port, or whitespace in the hostname.
#    - Refuse a missing model.
#    - Keep the token out of every refusal message.
#    - Trim a nonblank --model / --prompt-dir override, as the setting is.
#    - Treat a blank or whitespace-only --model override as unset.
#    - Fall back a blank or whitespace-only --prompt-dir override to the default.
#    - Accept a positive finite --timeout override, refuse anything else.
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

import unittest
from unittest import mock

from config import (BASE_URL_SHAPE_ERROR, Config, ConfigError, load_config,
                    override_model, override_prompt_dir, override_timeout,
                    validate_generation_config)

TOKEN = "00000000-0000-0000-0000-000000000000:secret-value"

# Every variable config.py reads, so that a test starts from a known
# environment rather than from whatever the host happens to export.
SETTINGS = (
    "GENERATION_BACKEND",
    "GENERATION_API_TOKEN",
    "GENERATION_BASE_URL",
    "GENERATION_MODEL",
    "GENERATION_RESPONSE_MODE",
    "GENERATION_TIMEOUT",
    "GENERATION_MAX_RETRIES",
    "GENERATION_TEMPERATURE",
    "MAX_OUTPUT_TOKENS",
    "MAX_INPUT_CHARS",
    "MAX_POLICY_CHARS",
    "PROMPT_DIR",
    "LOG_LEVEL",
    "PORT",
)


def environment(**overrides):
    """ Return an environment holding only the given settings. """
    values = {name: "" for name in SETTINGS}
    values.update(overrides)
    return values


def usable_config(**overrides) -> Config:
    """ Return a configuration that can address an endpoint. """
    values = {
        "generation_backend": "openai-compatible",
        "generation_api_token": TOKEN,
        "generation_base_url": "https://api.example.test/v1",
        "generation_model": "test-model",
    }
    values.update(overrides)
    return Config(**values)


class LoadConfigTest(unittest.TestCase):
    """ Cover the conversion of the environment into a Config. """

    def load(self, **overrides) -> Config:
        """ Load a configuration from a controlled environment. """
        # load_dotenv is disabled so that a .env on the host cannot
        # decide what a test sees.
        with mock.patch.dict("os.environ", environment(**overrides),
                             clear=True):
            with mock.patch("config.load_dotenv", None):
                return load_config()

    def test_defaults(self):
        """ Load the documented defaults for every optional setting. """
        config = self.load()
        self.assertEqual(config.generation_response_mode, "prompt-json")
        self.assertEqual(config.generation_timeout, 120.0)
        self.assertEqual(config.max_output_tokens, 2000)
        self.assertEqual(config.max_input_chars, 8000)
        self.assertEqual(config.max_policy_chars, 2000)
        self.assertEqual(config.prompt_dir, "prompts")
        self.assertEqual(config.log_level, "INFO")

    def test_default_port_is_8091(self):
        """ Default the port to the one the basic design fixes. """
        self.assertEqual(self.load().port, 8091)

    def test_one_request_by_default(self):
        """ Leave the SDK no retry unless an operator asked for one. """
        self.assertEqual(self.load().generation_max_retries, 0)
        self.assertEqual(self.load(GENERATION_MAX_RETRIES="2")
                         .generation_max_retries, 2)

    def test_blank_value_reads_as_unset(self):
        """ Treat a whitespace-only value exactly like an absent one. """
        config = self.load(PROMPT_DIR="   ", GENERATION_MODEL="  ")
        self.assertEqual(config.prompt_dir, "prompts")
        self.assertEqual(config.generation_model, "")

    def test_temperature_is_sent_only_when_set(self):
        """ Carry no temperature unless the setting names one. """
        self.assertIsNone(self.load().generation_temperature)
        self.assertEqual(self.load(GENERATION_TEMPERATURE="0.4")
                         .generation_temperature, 0.4)

    def test_refuses_a_value_that_is_not_a_number(self):
        """ Name the setting and the value when a number is expected. """
        with self.assertRaises(ConfigError) as refusal:
            self.load(GENERATION_TIMEOUT="soon")
        self.assertIn("GENERATION_TIMEOUT", str(refusal.exception))
        self.assertIn("soon", str(refusal.exception))

    def test_refuses_a_value_that_is_not_finite(self):
        """
        Refuse nan and infinity, which float() accepts as numbers.

        Each of these settings bounds something, and neither value can
        bound anything: nan compares false against any limit, and
        infinity cannot become the whole number a count of characters
        or a port has to be. Refusing them here names the setting at
        fault instead of failing later inside arithmetic.
        """
        for name in ("GENERATION_TIMEOUT", "GENERATION_TEMPERATURE",
                     "MAX_INPUT_CHARS", "MAX_POLICY_CHARS",
                     "MAX_OUTPUT_TOKENS", "GENERATION_MAX_RETRIES", "PORT"):
            for value in ("nan", "inf", "-inf", "1e400"):
                with self.assertRaises(ConfigError) as refusal:
                    self.load(**{name: value})
                self.assertIn(name, str(refusal.exception))

    def test_refuses_a_timeout_that_is_not_positive(self):
        """ Refuse a limit no request could ever run inside. """
        for value in ("0", "-1"):
            with self.assertRaises(ConfigError):
                self.load(GENERATION_TIMEOUT=value)

    def test_refuses_a_negative_retry_count(self):
        """ Refuse a retry count below zero. """
        with self.assertRaises(ConfigError):
            self.load(GENERATION_MAX_RETRIES="-1")

    def test_refuses_an_unknown_response_mode(self):
        """ Name the modes that exist when one is misspelled. """
        with self.assertRaises(ConfigError) as refusal:
            self.load(GENERATION_RESPONSE_MODE="json")
        self.assertIn("prompt-json", str(refusal.exception))
        self.assertIn("json-object", str(refusal.exception))

    def test_refuses_a_character_limit_of_zero(self):
        """ Refuse a limit that would leave no room for any input. """
        for name in ("MAX_INPUT_CHARS", "MAX_POLICY_CHARS",
                     "MAX_OUTPUT_TOKENS"):
            with self.assertRaises(ConfigError):
                self.load(**{name: "0"})

    def test_refuses_a_port_outside_the_valid_range(self):
        """ Refuse a port no socket could be bound to. """
        for value in ("0", "70000"):
            with self.assertRaises(ConfigError):
                self.load(PORT=value)


class ConfigValueTest(unittest.TestCase):
    """ Cover what a Config exposes once it has been built. """

    def test_repr_hides_the_token(self):
        """ Keep the token out of repr while leaving it readable. """
        config = usable_config()
        self.assertNotIn(TOKEN, repr(config))
        self.assertEqual(config.generation_api_token, TOKEN)

    def test_endpoint_host(self):
        """ Report the host of the base URL, for the log. """
        self.assertEqual(usable_config().endpoint_host, "api.example.test")
        self.assertEqual(Config().endpoint_host, "")


class ValidateGenerationConfigTest(unittest.TestCase):
    """ Cover the refusal of a configuration that cannot be used. """

    def test_accepts_a_complete_configuration(self):
        """ Accept a configuration that can address an endpoint. """
        validate_generation_config(usable_config())

    def test_refuses_a_missing_backend(self):
        """ Refuse to run while it is unclear how to speak. """
        with self.assertRaises(ConfigError) as refusal:
            validate_generation_config(usable_config(generation_backend=""))
        self.assertIn("GENERATION_BACKEND", str(refusal.exception))

    def test_refuses_an_unknown_backend_by_name(self):
        """ Refuse an unknown backend rather than read it as the one. """
        with self.assertRaises(ConfigError) as refusal:
            validate_generation_config(
                usable_config(generation_backend="anthropic-messages"))
        self.assertIn("openai-compatible", str(refusal.exception))

    def test_refuses_a_missing_token(self):
        """ Refuse to run without a credential for the endpoint. """
        with self.assertRaises(ConfigError) as refusal:
            validate_generation_config(usable_config(generation_api_token=""))
        self.assertIn("GENERATION_API_TOKEN", str(refusal.exception))

    def test_refuses_a_token_carrying_whitespace(self):
        """ Refuse a token no Authorization header could carry. """
        with self.assertRaises(ConfigError):
            validate_generation_config(
                usable_config(generation_api_token="broken\ntoken"))

    def test_refuses_a_base_url_that_cannot_be_addressed(self):
        """ Refuse a missing, plain http or relative base URL. """
        for url in ("", "http://api.example.test/v1", "api.example.test/v1"):
            with self.assertRaises(ConfigError) as refusal:
                validate_generation_config(
                    usable_config(generation_base_url=url))
            self.assertIn("GENERATION_BASE_URL", str(refusal.exception))

    def test_refuses_a_base_url_carrying_more_than_an_endpoint(self):
        """ Refuse user information, a query and a fragment in the URL. """
        for url in ("https://user:pass@api.example.test/v1",
                    "https://api.example.test/v1?key=value",
                    "https://api.example.test/v1#part"):
            with self.assertRaises(ConfigError):
                validate_generation_config(
                    usable_config(generation_base_url=url))

    def test_refuses_a_base_url_holding_the_resource_path(self):
        """ Refuse a URL the SDK would append the resource path to. """
        with self.assertRaises(ConfigError) as refusal:
            validate_generation_config(usable_config(
                generation_base_url="https://api.example.test/v1/chat/completions"))
        self.assertIn("chat/completions", str(refusal.exception))

    def test_refuses_a_missing_model(self):
        """ Refuse to run without knowing which model to ask. """
        with self.assertRaises(ConfigError) as refusal:
            validate_generation_config(usable_config(generation_model=""))
        self.assertIn("GENERATION_MODEL", str(refusal.exception))

    def test_accepts_an_ipv6_base_url(self):
        """ Accept a bracketed IPv6 literal carrying a valid port. """
        validate_generation_config(usable_config(
            generation_base_url="https://[2001:db8::1]:443/v1"))

    def test_refuses_a_base_url_without_a_hostname(self):
        """ Refuse a base URL whose authority carries no host. """
        with self.assertRaises(ConfigError) as refusal:
            validate_generation_config(
                usable_config(generation_base_url="https://:443/v1"))
        self.assertEqual(str(refusal.exception), BASE_URL_SHAPE_ERROR)

    def test_refuses_a_base_url_with_an_invalid_port(self):
        """ Refuse a non-numeric port and a port outside 1..65535. """
        for url in ("https://api.example.test:notaport/v1",
                    "https://api.example.test:0/v1",
                    "https://api.example.test:65536/v1"):
            with self.assertRaises(ConfigError) as refusal:
                validate_generation_config(
                    usable_config(generation_base_url=url))
            self.assertEqual(str(refusal.exception), BASE_URL_SHAPE_ERROR)

    def test_refuses_a_malformed_ipv6_base_url(self):
        """ Refuse an IPv6 authority whose closing bracket is missing. """
        with self.assertRaises(ConfigError) as refusal:
            validate_generation_config(usable_config(
                generation_base_url="https://[2001:db8::1/v1"))
        self.assertEqual(str(refusal.exception), BASE_URL_SHAPE_ERROR)

    def test_refuses_whitespace_in_the_base_url_hostname(self):
        """ Refuse a hostname that carries whitespace. """
        with self.assertRaises(ConfigError) as refusal:
            validate_generation_config(usable_config(
                generation_base_url="https://api example.test/v1"))
        self.assertEqual(str(refusal.exception), BASE_URL_SHAPE_ERROR)

    def test_no_refusal_quotes_the_token(self):
        """ Keep the token out of every message, whatever was refused. """
        broken = (
            usable_config(generation_backend=""),
            usable_config(generation_backend="unknown-backend"),
            usable_config(generation_base_url=""),
            usable_config(generation_base_url="http://api.example.test/v1"),
            usable_config(generation_model=""),
        )
        for config in broken:
            with self.assertRaises(ConfigError) as refusal:
                validate_generation_config(config)
            self.assertNotIn(TOKEN, str(refusal.exception))


class OverrideTest(unittest.TestCase):
    """
    Cover the helpers cli.py calls for an explicit CLI override.

    Each helper is held to the same normalization GENERATION_MODEL,
    PROMPT_DIR and GENERATION_TIMEOUT are held to when they come from
    the environment, so a setting means the same thing whichever path
    it was given through.
    """

    def test_override_model_trims_a_nonblank_value(self):
        """ Trim surrounding whitespace, exactly as GENERATION_MODEL is. """
        config = usable_config(generation_model="configured-model")
        override_model(config, "  another-model  ")
        self.assertEqual(config.generation_model, "another-model")

    def test_override_model_of_a_blank_value_is_unset(self):
        """ Treat a blank or whitespace-only --model as unset. """
        for value in ("", "   "):
            config = usable_config(generation_model="configured-model")
            override_model(config, value)
            self.assertEqual(config.generation_model, "")
            with self.assertRaises(ConfigError) as refusal:
                validate_generation_config(config)
            self.assertIn("GENERATION_MODEL", str(refusal.exception))

    def test_override_prompt_dir_trims_a_nonblank_value(self):
        """ Trim surrounding whitespace, exactly as PROMPT_DIR is. """
        config = usable_config(prompt_dir="prompts")
        override_prompt_dir(config, "  custom/path  ")
        self.assertEqual(config.prompt_dir, "custom/path")

    def test_override_prompt_dir_of_a_blank_value_falls_back_to_default(self):
        """ Fall back to 'prompts', even where a custom value was loaded. """
        for value in ("", "   "):
            config = usable_config(prompt_dir="custom/path")
            override_prompt_dir(config, value)
            self.assertEqual(config.prompt_dir, "prompts")

    def test_override_timeout_accepts_a_positive_finite_value(self):
        """ Accept a valid override in place of GENERATION_TIMEOUT. """
        config = usable_config()
        override_timeout(config, 30.0)
        self.assertEqual(config.generation_timeout, 30.0)

    def test_override_timeout_refuses_a_value_that_is_not_positive(self):
        """ Refuse a limit no request could ever run inside. """
        for value in (0.0, -1.0, float("nan"), float("inf"), float("-inf")):
            config = usable_config()
            with self.assertRaises(ConfigError):
                override_timeout(config, value)


if __name__ == "__main__":
    unittest.main()
