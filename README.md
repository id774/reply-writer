# reply-writer

## Contents

1. [Overview](#overview)
2. [Status](#status)
3. [What it does](#what-it-does)
4. [What it does not do](#what-it-does-not-do)
5. [Documents](#documents)
6. [The Japanese that stays](#the-japanese-that-stays)
7. [Contribution](#contribution)
8. [License](#license)

## Overview

**reply-writer** turns a received message into a draft reply. A person pastes in the mail or message they have to answer, adds a few lines of direction where they want the reply to say something in particular, and gets back a Japanese draft they can copy and send.

Everyday correspondence is often answered adequately by a formulaic or half formulaic reply, and explaining to a language model, every time, how that reply should be written is most of the work. This system holds that explanation as its prompts, so what the person supplies is the message and — only where it is needed — the direction.

It is not a mail client. Mail, LINE, SMS and chat are all just text that was copied from somewhere, and the reply goes back the same way: the person copies it, returns to the service the message came from, reads it once more and sends it. There is no code path to any messaging service and no place to hand it a credential. That is a line drawn in the design, not a feature left for later.

The phone is the environment this is built for. Its main use is the few minutes away from a desk when a reply is owed.

## Status

Requirements and basic design. Nothing is implemented yet.

[doc/REQUIREMENTS.md](doc/REQUIREMENTS.md) is settled, [doc/BASIC_DESIGN.md](doc/BASIC_DESIGN.md) takes it down to the modules, the settings, the routes and the deployment layout that implementation follows, and [doc/POLICY.md](doc/POLICY.md) states the rules that implementation is written under. The prompt specification and the deployment guide come next; this README will grow the installation, configuration and usage sections once there is something to install.

## What it does

- Takes the body of a received message, from mail, LINE, SMS, chat or anything else whose text can be copied.
- Takes an optional direction of a few lines: the intent, a constraint, the answer to give, what to mention, what to leave alone.
- Produces a natural Japanese reply through a generation API named by the configuration.
- Shows the draft so that it can be copied as it stands, with no remark or annotation from the model mixed into it.
- Invents no fact that the message and the direction did not carry.
- Keeps what is entered and what is generated out of storage and out of the logs.

## What it does not do

- Send mail, a message, an SMS or a chat post — by any route, including a browser driven by the system.
- Fetch messages, register drafts, choose recipients or touch an address book.
- Hold a credential of Gmail, Outlook, LINE or any other messaging service.
- Search the web or look anything up to fill a gap in the input.
- Treat an instruction found inside a received message as an instruction to itself.

Checking the final text and sending it stay with the person. Section 13 of the requirements states the boundary, and section 33 lists what the initial version leaves out.

## Documents

- Requirements: [doc/REQUIREMENTS.md](doc/REQUIREMENTS.md)
- Basic design: [doc/BASIC_DESIGN.md](doc/BASIC_DESIGN.md)
- The prompts: `doc/PROMPTS.md` (not written yet)
- Deployment: `doc/DEPLOYMENT.md` (not written yet)
- Implementation policy: [doc/POLICY.md](doc/POLICY.md)
- Release history: [doc/VERSIONS](doc/VERSIONS)

Each of them stands on its own. What this repository needs is written in this repository, and no document here is completed by one kept somewhere else.

## The Japanese that stays

The repository is written in English — the code, the comments, the screens, the documents and the prompts. The generated reply is Japanese, because the correspondence is, and so is the message the person pastes in.

Where a document or a prompt has to quote a Japanese string as the specification — a formula the reply must not fall into, a phrase it must not add — the string is quoted literally, because an English translation of it would match nothing.

## Contribution

Contributions are welcome. Until there is an implementation, the useful ones are against the requirements: a case the boundaries do not cover, a requirement that contradicts another, a form of use the initial version would fail.

Please follow the style used in this repository: English comments and documents, and documentation updated together with the code.

## License

This repository is dual licensed under the [GPL version 3](https://www.gnu.org/licenses/gpl-3.0.html) or the [LGPL version 3](https://www.gnu.org/licenses/lgpl-3.0.html), at your option.
For full details, please refer to [doc/LICENSE.md](doc/LICENSE.md). See also [doc/COPYING](doc/COPYING) and [doc/COPYING.LESSER](doc/COPYING.LESSER) for the complete license texts.
