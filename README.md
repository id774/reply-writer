# reply-writer

## Contents

1. [Overview](#overview)
2. [What it does](#what-it-does)
3. [What it does not do](#what-it-does-not-do)
4. [Requirements](#requirements)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [Usage](#usage)
8. [The writing policy](#the-writing-policy)
9. [When something fails](#when-something-fails)
10. [Tests](#tests)
11. [Deployment](#deployment)
12. [Repository structure](#repository-structure)
13. [Documents](#documents)
14. [The Japanese that stays](#the-japanese-that-stays)
15. [Not implemented](#not-implemented)
16. [Contribution](#contribution)
17. [License](#license)

## Overview

**reply-writer** turns a received message into a draft reply. A person pastes in the mail or message they have to answer, adds a few lines of direction where they want the reply to say something in particular, and gets back a Japanese draft they can copy and send.

Everyday correspondence is often answered adequately by a formulaic or half formulaic reply, and explaining to a language model, every time, how that reply should be written is most of the work. This system holds that explanation as its prompts, so what the person supplies is the message and — only where it is needed — the direction.

It is not a mail client. Mail, LINE, SMS and chat are all just text that was copied from somewhere, and the reply goes back the same way: the person copies it, returns to the service the message came from, reads it once more and sends it. There is no code path to any messaging service and no place to hand it a credential. That is a line drawn in the design, not a feature left for later.

The phone is the environment this is built for. Its main use is the few minutes away from a desk when a reply is owed.

```text
paste the message
↓
write a direction, where one is needed
↓
generate
↓
copy
↓
read it once more and send it yourself
```

## What it does

- Takes the body of a received message, from mail, LINE, SMS, chat or anything else whose text can be copied.
- Takes an optional direction of a few lines: the intent, a constraint, the answer to give, what to mention, what to leave alone.
- Produces a natural Japanese reply through a generation API named by the configuration.
- Carries a subject where the medium has one, and leaves the field off the screen entirely where it does not.
- Shows the draft so that it can be copied as it stands, with no remark or annotation from the model mixed into it.
- Invents no fact that the message and the direction did not carry.
- Keeps what is entered and what is generated out of storage and out of the logs.
- Offers the same generation from a command line, for adjusting the prompts and checking a connection.

## What it does not do

- Send mail, a message, an SMS or a chat post — by any route, including a browser driven by the system.
- Fetch messages, register drafts, choose recipients or touch an address book.
- Hold a credential of Gmail, Outlook, LINE or any other messaging service.
- Search the web or look anything up to fill a gap in the input.
- Treat an instruction found inside a received message as an instruction to itself.
- Fall back to a second generation endpoint when the first one fails.

Checking the final text and sending it stay with the person. Section 13 of the requirements states the boundary, and section 33 lists what the initial version leaves out.

## Requirements

- Python 3.9 or later.
- An account with an OpenAI-compatible Chat Completions endpoint, and its token, base URL and model name.
- For a server deployment: Apache and systemd. See [doc/DEPLOYMENT.md](doc/DEPLOYMENT.md).

Runtime dependencies, each pinned to a compatible range in `requirements.txt`:

| Package | What for |
| --- | --- |
| Flask | the web application |
| gunicorn | the application server |
| openai | the OpenAI-compatible API client |
| python-dotenv | reading `.env` |

The `openai` package is the client. It is not the choice of an endpoint: which service answers is decided by `GENERATION_BASE_URL` alone.

## Installation

```bash
git clone https://github.com/id774/reply-writer.git
cd reply-writer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Then edit `.env`. The required settings are identified in the
[Configuration](#configuration) table and have no defaults, so nothing runs
until all required values are filled in.

Check the installation:

```bash
.venv/bin/python -m unittest discover -s tests
```

The suite makes no request and needs no token.

## Configuration

Every setting is read from the environment, or from a `.env` file beside the application. None of them appears on a screen: they belong to whoever runs the system.

| Variable | Required | Default | What it decides |
| --- | :---: | --- | --- |
| `GENERATION_BACKEND` | yes | — | How the endpoint is spoken to. `openai-compatible` is the only accepted value. |
| `GENERATION_API_TOKEN` | yes | — | The credential of the endpoint. |
| `GENERATION_BASE_URL` | yes | — | The endpoint, https only, with the version path and without the resource name. |
| `GENERATION_MODEL` | yes | — | The model used for generation. |
| `GENERATION_RESPONSE_MODE` | no | `prompt-json` | How a structured answer is asked for: `prompt-json` or `json-object`. |
| `GENERATION_TIMEOUT` | no | `120` | Seconds allowed for one request. |
| `GENERATION_MAX_RETRIES` | no | `0` | Retries left to the SDK. |
| `GENERATION_TEMPERATURE` | no | unset | Sent only when set. |
| `MAX_OUTPUT_TOKENS` | no | `2000` | Upper bound of one response. |
| `MAX_INPUT_CHARS` | no | `8000` | Upper bound of the received message. |
| `MAX_POLICY_CHARS` | no | `2000` | Upper bound of the direction. |
| `PROMPT_DIR` | no | `prompts` | Directory holding the prompt files. |
| `LOG_LEVEL` | no | `INFO` | Level of the application log. |
| `PORT` | no | `8091` | Port of the development server and of gunicorn. |

### Choosing an endpoint

`GENERATION_BACKEND`, `GENERATION_API_TOKEN`, `GENERATION_BASE_URL`, and
`GENERATION_MODEL` are the required settings listed above. Their runtime
validation is implemented in `config.py`; this README documents how an
operator supplies them. With one of them missing, the process refuses to start rather than picking a service for you, because a private message that leaves for an endpoint nobody named is worse than an application that will not run.

An unknown `GENERATION_BACKEND` is refused rather than coerced to a supported
value. Accepted backend values are defined in `config.py` and documented in
the Configuration table. A base URL that is plain `http`, carries user information, a query or a fragment, or already ends in `/chat/completions` is refused as well: the SDK appends the resource path itself.

### One action, one request

`GENERATION_MAX_RETRIES` defaults to `0`, so one press of the generate button is one request to the endpoint. Raising it is an explicit operational decision, and it multiplies the worst case wait by the same factor.

A failure is never a reason to try somewhere else. An unreachable host, a timeout, a rejected credential, a rate limit, a failure of the API itself and an unreadable answer are all reported on the route that was configured. For one generation, exactly one API receives what was entered.

### Asking for JSON

The answer is one JSON object, so that the subject and the body arrive as separate fields:

```json
{"subject": null, "body": "the reply body"}
```

`prompt-json` asks for it in the prompt alone, which works with an endpoint or a model that rejects the parameter. `json-object` asks the API itself, with `response_format`.

Neither mode falls back to the other. A configured mode that the endpoint does not support is an error, because retrying under the other would spend a second request nobody asked for.

### Timeouts that agree with each other

```text
GENERATION_TIMEOUT (120)  <  gunicorn --timeout (240)  <  Apache ProxyTimeout (300)
```

Changing one means revisiting the other two.

## Usage

### The web screens

```bash
.venv/bin/python app.py
```

It listens on `http://127.0.0.1:8091/`. In production gunicorn serves it behind Apache; see [doc/DEPLOYMENT.md](doc/DEPLOYMENT.md).

| Route | What it does |
| --- | --- |
| `GET /` | The input screen: the message, the optional direction, and a way to generate. |
| `POST /generate` | Generates one draft and shows it. |
| `GET /healthz` | Says the process is up. It calls no API and returns no setting. |

The input screen carries two fields and one button. The direction is marked optional and may be left empty, which is the ordinary case. The result screen shows the reply with a copy control beside it, and the subject with a copy control of its own where the reply carries one. Where it carries none, the subject field is not on the page at all.

### From the command line

The command line calls the same generation core, the same prompts and the same provider as the web application. It exists so that a prompt can be adjusted and an endpoint verified without a browser in the way.

```bash
python cli.py generate --message message.txt
python cli.py generate --message message.txt --direction direction.txt
pbpaste | python cli.py generate --message -
python cli.py generate --message message.txt --json
python cli.py --help
python cli.py --version
```

The message and the direction are read from a file or from standard input, never from an argument, and there is no option for the API token or the base URL: a command line is readable by every user of the host.

`--model`, `--prompt-dir` and `--timeout` each replace the setting they name, for one run.

| Exit code | Meaning |
| ---: | --- |
| 0 | The draft was generated. Also what `--help` and `--version` return. |
| 1 | A setting or an option was refused, the message could not be read, or no usable draft came back. |
| 2 | The command line was rejected. |

## The writing policy

How a reply reads is decided by the prompts under `prompts/`, not by the code. Adjusting the register, the length, the formulae or the repetition is editing a file there; it never requires a change to Python. `reply_writer/formatter.py` touches whitespace, line endings and a code fence, and nothing else.

The received message is untrusted data. It reaches the model inside a block marked as the text being replied to, and a sentence inside it that reads as an instruction to a model is answered as the correspondent's words rather than obeyed.

[doc/PROMPTS.md](doc/PROMPTS.md) states what each file is for, what its output has to satisfy, and how a change to one is made.

## When something fails

The screen shows a sentence the person can act on, and on a failure that is not theirs to fix, a request id. It never shows a traceback, the API token, the endpoint, the body of the API response or an internal path.

The log carries the other half: the request id, the backend, the host of the endpoint, the model, the HTTP status, the finish reason, the token counts, the elapsed seconds beside the limit, and the class of the error. A person reporting a fault quotes the request id, and the log is read at that id.

What the log never carries, at any level, is the received message, the direction, the assembled prompts, the generated reply, the body of the API response, the API token or the `Authorization` header. Raising `LOG_LEVEL` reveals none of it, and there is no setting that turns it back on.

## Tests

```bash
python -m unittest discover -s tests
```

No test makes a request, needs a token or reads a `.env`. The provider is replaced by a stub and the `openai` package is stood in for, so the suite runs with neither the dependency nor a network.

The suite guards invariants as well as features, including: that the API token appears in no response and no rendered page, and that no text a person entered or the model generated reaches the log. They are not deleted to make a refactor pass.

All test data is invented. No real mail, message, conversation, personal name, company or matter appears in this repository.

## Deployment

gunicorn behind Apache, managed by systemd, published under `/reply/` over HTTPS:

```text
Browser → HTTPS → Apache → 127.0.0.1:8091 → gunicorn → Flask → Generation Core → Provider → the configured API
```

`deploy/reply-writer.service` and `deploy/reply-writer.conf` are examples to copy and adjust. Neither carries a hostname, a certificate or a credential.

Private correspondence passes through this system, so it is not published to anyone who finds the address. Access control belongs to the web server in front of it — Basic authentication, an IP restriction, a VPN — and no account system is introduced into the application to provide it.

The whole procedure is in [doc/DEPLOYMENT.md](doc/DEPLOYMENT.md).

## Repository structure

```text
app.py                 the Flask application: routes, screens, error pages
cli.py                 the command line, calling the same core
config.py              every setting, read from the environment or .env
requirements.txt       the runtime dependencies, in compatible ranges
Procfile               the gunicorn command line
.env.example           the settings to copy, with no value that chooses an endpoint

reply_writer/
├── __init__.py        the draft that carries one result, and the request id
├── errors.py          the errors the user may be shown, and their statuses
├── prompts.py         reading the prompts and assembling the messages
├── generator.py       the generation core: validate, ask, read, verify
├── formatter.py       mechanical post processing that changes no meaning
├── providers/         everything that knows how an endpoint is spoken to
└── web/               the templates, the stylesheet and the clipboard script

prompts/               the writing policy, outside the code
tests/                 the suite, which reaches no network
deploy/                the systemd unit and the Apache virtual host
doc/                   the requirements, the design, the policy and the rest
```

The dependency runs one way. The generation core imports no Flask, reads no request object and builds no HTML, which is what lets the command line and the web application be the same generation. The provider layer keeps the SDK inside it, and the prompt layer decides what the model is told; neither decides the other's business.

## Documents

- Requirements: [doc/REQUIREMENTS.md](doc/REQUIREMENTS.md)
- Basic design: [doc/BASIC_DESIGN.md](doc/BASIC_DESIGN.md)
- The prompts: [doc/PROMPTS.md](doc/PROMPTS.md)
- Deployment: [doc/DEPLOYMENT.md](doc/DEPLOYMENT.md)
- Implementation policy: [doc/POLICY.md](doc/POLICY.md)
- Release history: [doc/VERSIONS](doc/VERSIONS)

Each of them stands on its own. What this repository needs is written in this repository, and no document here is completed by one kept somewhere else.

## The Japanese that stays

The repository is written in English — the code, the comments, the screens, the documents and the prompts. The generated reply is Japanese, because the correspondence is, and so is the message the person pastes in.

Where a document or a prompt has to quote a Japanese string as the specification — a formula the reply must not fall into, a phrase it must not add — the string is quoted literally, because an English translation of it would match nothing.

## Not implemented

By design, and not as a gap to be filled later: any connector to Gmail, Outlook, LINE or an SMS service; fetching or sending messages; registering a draft; choosing a recipient; browser automation; a database, a history or a session store; an account system; learning from past replies; RAG; web search; analytics over message content; scheduled or automatic sending.

Should one of them become necessary, the requirements change first and the design follows.

## Contribution

Contributions are welcome. The useful ones are the ones that keep the path short: paste, direct where needed, generate, copy.

Please follow the style used in this repository: English comments and documents, the module header each file carries, and documentation updated together with the code. [doc/POLICY.md](doc/POLICY.md) states the rules a change is judged by.

## License

This repository is dual licensed under the [GPL version 3](https://www.gnu.org/licenses/gpl-3.0.html) or the [LGPL version 3](https://www.gnu.org/licenses/lgpl-3.0.html), at your option.
For full details, please refer to [doc/LICENSE.md](doc/LICENSE.md). See also [doc/COPYING](doc/COPYING) and [doc/COPYING.LESSER](doc/COPYING.LESSER) for the complete license texts.
