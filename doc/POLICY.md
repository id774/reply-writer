# Implementation Policies

reply-writer is a single Python application, so this policy is stated directly
for Python rather than separating a shared section from per-language ones.

This document stands on its own. It is the whole implementation policy of this
repository, and no rule here is completed by a document kept somewhere else. A
subject it does not cover is a gap in this document, to be filled here rather
than looked up elsewhere.

The Invariants below decide over the rest of it. Some of what they forbid is
what a general policy would otherwise ask for: this system does not fall back
to a second endpoint when the first one fails, does not infer what a compatible
endpoint supports from a model name or a URL, does not keep what it was given
so that a fault can be reproduced later, and does not grow a path to the
service the message came from. Those are deliberate, and are not to be relaxed
to match a more general rule.

---

## 1. General Policy

### 1.1 Purpose and Scope
- This document decides how the repository is implemented: the coding rules,
  the responsibilities of the layers and the direction of dependency between
  them, the handling of settings and credentials, the security and privacy
  rules, the approach to tests and documentation, and the criteria by which a
  change is judged.
- It applies to everything committed here: the application modules, the
  templates, the stylesheet and the JavaScript, the prompts, the tests, the
  deployment files and the documents.
- What the system is for, what it accepts, what it produces and where its
  responsibility ends belong to the requirements. The composition of the
  system, the modules, the settings, the routes, the response format and the
  error mapping belong to the basic design. This document does not restate
  them; it decides how they are carried out.

### 1.2 Relation to the Requirements and the Basic Design
- [`REQUIREMENTS.md`](REQUIREMENTS.md) and [`BASIC_DESIGN.md`](BASIC_DESIGN.md)
  are the higher specification of this repository. This document is
  subordinate to both.
- Where this policy contradicts either of them, this policy is what is
  corrected. A requirement or a design decision is never bent to suit a rule
  written here.
- Behaviour the requirements or the basic design do not allow is introduced by
  changing those documents first. The implementation follows them; it does not
  lead them.
- Where this document is silent, the invariants of the basic design and the
  order of priorities in the requirements decide.
- [`PROMPTS.md`](PROMPTS.md) governs what the prompts say and what their output
  must satisfy. [`DEPLOYMENT.md`](DEPLOYMENT.md) governs how the system is
  installed and run. This document governs the code that sits between them.

### 1.3 Design Philosophy
- Prioritize clarity, portability, and explicit control over convenience.
- Favor predictable behavior and long-term maintainability.
- Avoid implicit behavior; make control flow, errors, and side effects explicit.
- Keep the generation core (`reply_writer/`) independent from Flask, so that
  `cli.py` and `app.py` exercise exactly the same code.
- Keep the quality of the writing in the prompts. How a reply reads is adjusted
  by editing a prompt file wherever that is possible, and not by adding a
  branch to Python.
- The measure of this application is that one path works: paste the message,
  write a direction where one is needed, generate, copy. A change that
  lengthens that path has to earn its place before anything else about it is
  discussed.

### 1.4 Invariants
These lines are not crossed by a setting or by an extension.

- Do not send a generated reply anywhere. The system ends at a draft on the
  screen; copying it, reading it once more and sending it are the person's.
- Do not open a path to a mail service, a chat service or a messaging service
  of any kind, whether to fetch a message, to send one or to register a draft.
  The only host this system contacts is the generation endpoint the
  configuration names.
- Do not accept a credential of a messaging service, neither as a setting nor
  as a form field.
- Do not depend on browser automation. `playwright` and `selenium` do not
  belong in `requirements.txt`.
- Do not store the received message, the direction or the generated reply. No
  database, no session store, no temporary file, no cache of what a person
  entered.
- Do not write the received message, the direction or the generated reply to
  the log.
- Do not let the API token leave the server process: not into a template, not
  into JavaScript, not into a URL, not into an error page.
- Do not treat a sentence found inside a received message as an instruction to
  the system.
- Do not mix an instruction to the model, a notice, or an account of how the
  reply was generated into the reply body. The screen separates the body from
  every other piece of information, structurally and not only visually.
- Do not render model output with `|safe`.

### 1.5 Deciding During Implementation
Where there are several ways to do something, the basic design fixes the order
in which they are weighed, and this policy applies it:

1. Do not store or send personal data that need not be.
2. Keep the line at which a person checks the text and sends it.
3. Carry the message and the direction to the model correctly.
4. Keep it always possible to say which generation API is being talked to.
5. Keep the phone actions simple.
6. Do not mix the responsibilities of the web layer, the generation core and
   the provider layer.
7. Do not put into Python what belongs to a prompt.
8. Introduce no persistence and no state management that is not needed.
9. Depend on no particular messaging service.
10. Add no feature that is not needed.

A decision that cannot be settled by reading this list is settled by the
requirements, and recorded here once it has been.

### 1.6 The Generation Endpoint
The settings decide where a private message is sent, so they are read strictly.

- Do not choose an endpoint implicitly. The backend, the token, the base URL
  and the model are required, and a missing one stops the process instead of
  being filled in with a default.
- Do not accept an unknown backend. A value the code has no provider for is
  refused before a request, never read as the one backend that does exist.
- Do not switch to a second endpoint when the first one fails. One generation
  uses one route, whatever went wrong on it: an unreachable host, a timeout, a
  rejected credential, a rate limit, a failure of the API itself and an invalid
  answer are all reported, and none of them is a reason to try somewhere else.
- Do not rewrite the URL the operator named. The code does not change its
  scheme, does not attach a host of its own and does not append a resource path
  the setting did not carry.
- Do not infer what a compatible endpoint supports from its model name or its
  URL. A difference in behavior, such as whether a structured answer can be
  requested of the API itself, is expressed as a named setting, and a mode that
  is configured and unavailable is an error rather than a reason to try the
  other one.
- Do not read a legacy setting as its successor. A renamed variable is refused
  by name, so that a stale value cannot decide where a message goes.
- Do not vary the number of API requests silently. Retries are the SDK's, and
  the count is a setting an operator can see. One action by the person is one
  request unless an operator has decided otherwise.
- Do not log the API token, the received message, the direction, the prompts or
  the generated reply. What a log line carries is the shape of the exchange:
  the backend, the endpoint host, the model, the request id, the HTTP status,
  the finish reason and the token counts.
- Do not accept part of an answer. A structured answer is the whole response,
  or the whole inside of one code fence; an object cut out of surrounding prose
  is refused, because that is the heuristic which lets a remark by the model
  become the first line of a reply.
- Do not send the endpoint anything the person did not enter, beyond the
  prompts. No retrieved document, no search result, no earlier generation.

### 1.7 The Layers and the Direction of Dependency
The layers of the basic design are also the layers of the code, and dependency
between them points one way:

```text
app.py  /  cli.py
        |
        v
reply_writer/generator.py ----> reply_writer/prompts.py ----> prompts/*.md
        |
        v
reply_writer/providers/
        |
        v
the configured generation API
```

- The generation core does not import Flask, does not read a request object,
  does not build HTML and does not know that a browser exists. That is what
  lets the command line and the web application be the same generation.
- The provider layer keeps whatever is peculiar to an API library inside it. An
  exception, a response object, a client or a type belonging to the SDK does
  not appear above it; what leaves it is the application's own error and the
  application's own values.
- The prompt layer decides what the model is told. The provider layer decides
  how the endpoint is spoken to. Neither decides the other's business, and a
  change of endpoint never requires the writing policy to be rewritten.
- Post processing is mechanical and changes no meaning: whitespace, line
  breaks, an excess of blank lines, plainly structural debris. A problem with
  how the reply reads is solved in the prompts.
- The settings are read at the entry point and passed down. A module below it
  does not reach for the environment on its own.
- A new responsibility goes to the layer that owns it. Where it appears to
  belong to two, the boundary is wrong and is corrected, rather than the code
  being written across it.

### 1.8 Prompts
- The prompts are files under `prompts/`, outside the Python package, and the
  directory is named by a setting.
- A change to how a reply reads is an edit to a prompt. Adding a rule about
  register, length, formulae or repetition to Python is the wrong place for it
  unless the rule is mechanical and cannot be expressed as an instruction.
- The prompt keeps the message being replied to plainly apart from the
  instructions given by the system and by the person, and says which is which.
- An empty direction still yields a valid prompt. The absence of a direction is
  a normal case, not an error and not a special path.
- Substitution into a prompt is textual and literal. A prompt is not treated as
  a format string, so a brace or a percent sign written in it needs no
  escaping.
- A prompt file that is missing, unreadable or empty is a configuration error,
  refused before a request is spent. The code ships no built-in text to fall
  back to, because a reply written by a fallback prompt would be
  indistinguishable from one written by the intended prompt.
- What each prompt is for, and the contract its output has to keep, are
  documented in [`PROMPTS.md`](PROMPTS.md), and the file and the document are
  changed together.

### 1.9 Untrusted Input and Prompt Injection
- The received message is untrusted data. It is the text being replied to, and
  nothing found inside it is an instruction to this system.
- None of these is obeyed when it appears in an input: an instruction to
  disregard what came before, to rewrite the system instructions, to answer in
  some other form, to reveal a setting or a credential, to address another
  host, or to do something other than write a reply.
- The direction comes from the person and governs the reply, but it governs the
  writing only. It does not select an endpoint, does not change a setting and
  does not reach anything outside the generation.
- The size limits on the message and on the direction are enforced before a
  request is spent, not after.
- The answer from the model is untrusted input as well. It is validated as data
  before it reaches a template, and one that does not validate is refused
  rather than repaired into something that passes.
- A generated reply is text and is used as text. It never becomes a path, a
  command, a URL, a request, or markup that is rendered unescaped.

### 1.10 Privacy
- What a person pastes in may be anything: personal data, contact details,
  business information, a private matter. What the system holds and what it
  forwards are therefore kept to the minimum that generating a reply takes.
- Only the configured generation endpoint receives it. No analytics, no
  advertising, no third-party script, no error reporting service, no remotely
  hosted font, stylesheet or library is added to a page or to a request.
- Nothing entered and nothing generated is written to disk, and no text
  outlives the request that carried it.
- A diagnostic added while a fault is being chased is removed before the change
  is committed. There is no setting that turns the text back on in the log, and
  raising the log level reveals no message and no reply.
- The documents, the tests and the examples in this repository use invented
  material. No real mail, message, conversation, personal name, company or
  matter appears in them.

### 1.11 Logging and Output
- Use the standard `logging` module. Obtain a module logger with
  `logging.getLogger(__name__)`; do not print status from library modules.
- Configure logging once, at the entry point, with `logging.basicConfig`
  writing to standard error, in the format
  `%(asctime)s %(levelname)s %(name)s: %(message)s`.
- Map severity to levels: `INFO` for normal progress, `WARNING` for a degraded
  but recoverable condition, and `ERROR` for a failure that ends the current
  command or request.
- Keep the log low-noise. One generation must not leave a trail of per-step
  lines at the default level.
- When a third-party logger, such as the HTTP client the SDK carries, adds
  nothing to a run, lower that logger rather than raising the global level, and
  make sure it is not the one that would print a request body.
- Every web request carries a request id, and the lines belonging to one
  generation carry it, so that a run can be followed without any of its text
  being kept. The id is generated by the application and derives from nothing
  that was entered.
- The screen shows `user_message` only. The cause, the endpoint, the model and
  the traceback stay in the log, next to the request id shown to the user.
- What may be recorded is the shape of the exchange: the request id, the start
  and end of processing, the backend, the endpoint host, the model, the HTTP
  status, the class of error, the elapsed time and whether the generation
  succeeded.
- What is never recorded, at any level, is the received message, the direction,
  the assembled prompts, the generated reply, the body of the API response, the
  API token and the `Authorization` header.

### 1.12 Control Flow Rules
- Reserve `sys.exit` for the process entry point. Commands and helpers return
  their status.
- Raise a `ReplyWriterError` subclass for every failure the user is allowed to
  see, and let the entry point map it to a screen or an exit code.
- Do not swallow an error with a bare `except:`. Where a broad
  `except Exception` is genuinely required, such as around a call whose failure
  modes are open-ended, log the reason before returning a failure.
- Keep no mutable state at module level. A generation is contained in the call
  that performs it, so that concurrent requests in one worker cannot see each
  other's text.

### 1.13 Error Handling and Exit Codes
- Detect an unmet prerequisite early. A misconfiguration is refused before a
  request is spent, not after.
- The web application validates its generation settings while it is imported,
  so that a worker which cannot address an endpoint refuses to start rather
  than accepting a message and failing on the request. The service manager
  reports the message, which names the setting at fault.
- Log the reason and the affected target when an error occurs.
- The classes of failure the application distinguishes, and the HTTP status
  each maps to, are fixed by the basic design. The mapping is written in one
  place, so that a route cannot invent a status of its own.
- The person is shown a sentence they can act on and, where it helps, the
  request id. They are never shown a traceback, the string of a Python
  exception, an internal path, the internals of a library, the API token, the
  body of the API response or the text they entered.
- Exit code semantics follow the usual UNIX/Linux conventions and stay
  consistent across the repository.

#### 1.13.1 Exit Code Conventions
- **0: Success**
  The command completed. This includes terminating after help or version
  output.
- **1: General failure**
  The default failure code: a refused setting, an unreadable prompt file, an
  API that could not be reached, or a generation that did not produce a draft.
- **2: The command line was rejected**
  What `argparse` returns for an unknown option, a missing subcommand or an
  argument it cannot convert. Do not raise it from application code.
- **126, 127, 128 and above**
  Reserved by the shell and by signal convention. Do not redefine them for
  application errors.

### 1.14 CLI Conventions
- The command line exists so that the prompts, the quality of what is
  generated, the API connection and a fault can be examined without a browser
  in the way. It implements no second generation path: it calls the same core,
  the same prompt layer and the same provider layer as the web application, and
  the output of the two does not diverge.
- A command line tool provides `-h`, `--help` for usage and `-v`, `--version`
  for the version, and both exit with code `0`: a user who asked for them got
  what they asked for.
- Build the parser with `argparse`. It provides `-h`/`--help`; `-v`/`--version`
  is declared explicitly.
- An invalid or unsupported option results in usage output.
- Exit codes are consistent and are documented in the module header.
- An option that replaces a setting names the setting it replaces, so that a
  reader of a command line sees which configured value it displaced. A
  credential never gets one, because a command line is readable by every user
  of the host, and neither does `PORT`.
- The received message and the direction are read from a file or from standard
  input rather than from an argument, for the same reason.
- An option that is left out changes nothing, so an existing service unit or a
  recorded command keeps behaving as before.
- An option value the pipeline cannot use is refused by the parser, before a
  request is spent.
- Subcommands carry the verbs of the tool. A new mode of operation becomes a
  subcommand; it does not become a flag that changes what an existing
  subcommand means.

### 1.15 Environment Differences
- Branch on what the environment provides, not on what it is called. A
  distribution name, a release number, a platform string or a Python build each
  answer a question the code is not asking. The question is whether the
  command, the file, the service or the format it needs is there.
- Keep that detection in one place. The same question answered separately in
  several places drifts apart as environments change.
- A capability the application can work without is detected where it is used,
  not declared as a requirement. Detection asks whether the capability is
  usable, not only whether it is present: a package can import while the
  backend it needs is absent.
- Decide in advance what an absent optional capability leads to: use the
  alternative, skip the step and say so once, or refuse the run.
- This section is about the host and the packages installed on it. It does not
  reach the generation endpoint, where the Invariants forbid choosing an
  alternative: one generation uses one route, whatever went wrong on it.

### 1.16 Restraint in Design
- Do not introduce an abstraction that has one implementation and no named
  second one. The provider layer is a boundary because a further backend is a
  real possibility that a setting selects; a base class for a single formatter,
  a single prompt loader or a single screen is not.
- No plugin mechanism, no registry beyond the one that maps a configured
  backend name to its provider, no dependency injection framework, no
  configuration language of our own.
- Do not add a setting for something no operator has to decide. A value that
  has one correct answer is a constant with a comment saying why.
- Do not add a route, a screen or a field that the main path does not use.
- Do not generalize for a requirement nobody has written down. When the
  requirement arrives, the requirements document changes first, and the design
  follows it.
- Do not keep unused code behind a flag. Deleting it is a change of its own,
  proposed as one.
- A feature that would need persistence, a session, an account system or a
  connection to a messaging service is not implemented as an experiment to see
  how it feels.

### 1.17 Judging a Change
Before a change is proposed, it answers these:

- Does it cross an Invariant? Then it is not made.
- Does it need the requirements or the basic design to say something they do
  not? Then those documents change first.
- Does it lengthen the path from pasting a message to copying a reply?
- Does it move a decision about how a reply reads out of the prompts and into
  Python?
- Does it widen what leaves the process, or what is kept after the request
  ends?
- Does it add a dependency, and does that dependency earn its place?
- Is it the smallest change that serves its purpose?
- Does a test fail without it?
- Which documents change with it: the module header, `.env.example`, the
  README, the prompt specification, `doc/VERSIONS`?

A change that is correct but cannot be explained by the requirements is a sign
that the requirements are incomplete, and that is where it is taken.

### 1.18 Pull Request Scope and History
A pull request presents the change it proposes, not the sequence of corrections
that produced it. It carries one purpose, and when the direction is revised part
way through a review, the branch is rewritten so that it reads as the change
finally intended, and merges as if it had been written that way.

#### 1.18.1 One Purpose to a Pull Request
- Changes that serve different purposes are proposed separately, as a rule,
  even when they touch one file and even when one was noticed while the other
  was being made. A pull request is accepted or rejected whole, and a mixed one
  leaves no way to take the part that is wanted.
- A change noticed in passing is proposed on a branch of its own. It is not
  carried along because the working tree happened to be open at it, and it does
  not enlarge the request already under review.
- Tidying, renaming and reformatting that the change does not require are a
  change of their own. Attached to something else, they bury the change the
  reviewer came to read.
- Work that cannot stand without the change is not a second purpose. Its
  `doc/VERSIONS` entry, the `Version History` entry in the header of the module
  it changes, the test that fails without it, and the README or `.env.example`
  line a change of behavior requires, belong to the change that requires them.
- Where the separation is genuinely artificial, because neither part is correct
  or reviewable without the other, they are proposed together and the request
  says why.

#### 1.18.2 Keeping a Branch to Its Change
- A branch that carries one coherent change carries it as one commit. That
  commit is amended and force pushed with `--force-with-lease`, rather than
  gaining a further commit for each remark received.
- Commits such as "fix review comment", "address feedback" or "resolve
  conflict" describe the review rather than the change, and do not belong in
  the history that is merged.
- A branch is split into several commits only when it genuinely carries several
  independent changes. The reasoning is the one that decides a `doc/VERSIONS`
  bullet: coherence, not chronology.

#### 1.18.3 Leaving No Trace of the Correction
- Each revision is read against the base branch, not against the revision
  before it, so that a correction leaves no residue in the diff that is merged.
- A correction withdraws what it replaces. Code, comments and wording
  introduced by an earlier revision and since abandoned are removed, not left
  standing beside their replacement.
- Conflicts with the base branch are resolved by rebasing onto it, so that no
  merge commit enters the branch.
- A rewritten branch invalidates the copies others have fetched. Force pushing
  is confined to the branch under review, and the rewrite is stated whenever
  the branch is shared.
- No commit message, branch name, pull request or test fixture quotes real
  correspondence. A defect is described by what it did, not by the message that
  triggered it.

---

## 2. Python Policy

### 2.1 Structure
- Python 3.9 or later. Every module states `Python Version: 3.9 or later` under
  `Requirements`, and no module states a minimum higher than the code needs.
- The shebang is `#!/usr/bin/env python`. Do not write `python3`.
- The encoding header `# -*- coding: utf-8 -*-` follows the shebang.
- Every module starts with the header block used across id774 repositories, in
  the order given under [Documentation and Versioning](#27-documentation-and-versioning).
- Comments are written in English, in the imperative, and stay short, avoiding
  a redundant lead-in such as `# Function to ...`.
- A comment says why, not what. Where a decision looks arbitrary, such as
  substituting into a prompt with `str.replace()` rather than a format call, or
  refusing an answer that is only part of a response, the comment gives the
  reason, so that a later change does not quietly undo it.
- Name a thing by what it is, not by a part of it. This application answers
  several kinds of correspondence, and the loss shows quickly there: mail,
  LINE, SMS and chat are the media a message arrived through, and none of them
  is the name of a message. The same happens wherever a shorthand reaches for
  the interface, the format or the container instead of the thing itself. This
  applies to the headers, the documents and the commit messages as much as to
  the comments.
- Type hints are used on the public functions of a module.
- Every public function, class and method carries a docstring stating what the
  call returns or does. A one-line docstring stays on one line, with a space
  inside each pair of quotes:
  `""" Return the reply body with the surrounding whitespace removed. """`. A
  longer one opens on the line after the quotes, and describes the non-obvious
  parameters under `Args:` and the result under `Returns:`.
- A docstring and a comment quote no message and no generated reply, not even
  an invented one long enough to read as a sample.
- Prefer `str.format()` over an f-string. Substitution into an external text
  such as a prompt is done with `str.replace()`, so that a brace written in the
  prompt does not need escaping.

### 2.2 Program Structure
- An executable defines `main() -> int` and terminates with `sys.exit(main())`.
- Use early returns rather than nesting the body of a function inside a
  condition.
- Group imports as standard library, third party, then local. Import a
  third-party package inside the function that needs it only when that package
  is optional, so that the module still imports without it, and name the
  package to install in the error raised when it is missing.

### 2.3 Configuration
- Every setting lives in `config.py`, in the `Config` dataclass, read from the
  environment or from `.env`. `config.py` performs no network access and
  touches no file beyond `.env`.
- A credential never gets a command line option: a command line is readable by
  every user of the host.
- Validation is in two stages. `load_config()` converts values and refuses one
  that is malformed on its own terms; `validate_generation_config()` refuses a
  configuration that cannot address an endpoint. Every path that reaches the
  API passes both; `cli.py --version` and the tests pass neither.
- The four settings that address the endpoint have no defaults. A limit, a
  timeout, a port and a log level may have one, and the default is written in
  the header of `config.py` beside the name.
- No error message quotes a secret. A token is reported as present or absent,
  and the token is kept out of `__repr__`.
- An empty or whitespace-only string setting reads as unset, so that a bare
  `NAME=` line in `.env` behaves exactly like the absent line.
- `.env.example` ships no placeholder credential. An empty value is honest
  about being unset; a fake token would pass a presence check and fail only
  after a generation has been spent.

### 2.4 Dependencies and I/O
- Runtime dependencies are declared in `requirements.txt` and pinned to a
  compatible range, so that a future major release cannot break a running
  service. Add a dependency only when it earns its place; prefer the standard
  library otherwise.
- Some dependencies are refused by what this application is, not by their
  quality: a browser automation package, a client of a mail or messaging
  service, a database driver or an object mapper, an analytics or error
  reporting agent. Each of them would be the first half of a path the
  Invariants forbid.
- The front end takes no build step, no bundler and no package manager of its
  own. What a page needs is served from the repository.
- Always pass `encoding="utf-8"` for a text file operation.
- Every outbound request carries an explicit timeout, which `GENERATION_TIMEOUT`
  supplies. There is no request without one: a request that hangs holds a web
  worker until the client gives up. The timeouts of the application server and
  of the web server sit outside it, in the order the basic design fixes, and
  changing one means revisiting the others.
- Treat the answer as untrusted input. It is validated before it reaches a
  template, and one that does not validate is refused rather than repaired into
  something that passes.

### 2.5 The Web Layer
- `app.py` receives the input, calls the generation core and renders the
  result. It holds no logic of its own for writing a reply, and no template
  decides anything about the generation.
- Jinja autoescaping stays on, and model output is never rendered with `|safe`.
  A reply that contains something resembling markup is shown as the text it is.
- The reply body reaches the page as a value of its own, and the element that
  holds it holds nothing else. What is copied is that text alone: no label, no
  notice, no model name, no time of generation, nothing internal. Copying never
  works by scraping rendered markup that also carries the interface.
- Where no subject exists the field is absent from the page, not present and
  empty, so that nothing invites a subject to be pasted into a medium that has
  none.
- Generation is requested with `POST`. Nothing a person entered goes into a
  query string, a cookie or a URL fragment, because those are recorded in
  places the application does not control.
- The stylesheet is written mobile first. No small fixed width, no horizontal
  scroll, no action that needs a hover, no navigation that is not needed, and a
  copy that is visibly confirmed. A desktop layout is what the mobile layout
  becomes when there is room, not the other way round.
- The JavaScript is as little as the screens can be built with — in the initial
  version, chiefly the clipboard. It issues no generation request: the token
  and the endpoint stay in the server process, and the traffic to the API
  always leaves from the server.
- Nothing on a page is fetched from another host: no font, no stylesheet, no
  library, no image, no beacon.
- A page shows no operational setting. The backend, the endpoint, the model,
  the temperature, the timeout, the retries and the token limits belong to
  whoever runs the system.
- The liveness route answers as the web application and does nothing else. It
  calls no API and returns no setting and no personal data.
- Authentication and access control belong to the web server in front of the
  application. No account system, and in particular no account system belonging
  to a messaging service, is introduced into the application to provide them.

### 2.6 Testing and Operation
- `tests/test_*.py`, `unittest` and `unittest.mock` only.
- No network access and no API call. The client is replaced by a stub, and the
  provider tests stub the API package itself rather than importing it.
- No test needs a token, a `.env` or a real endpoint.
- A test writes nothing outside a temporary directory.
- Run them with `python -m unittest discover -s tests`.
- The runner exits `0` only when every test passed, which is what a service
  check or a CI step reads. A passing suite says nothing about the endpoint
  being reachable; only an actual generation does.
- The suite keeps covering, at least: the configuration and its refusals, the
  assembly of the prompts, the generator, the formatter, the mapping of
  provider errors, the validation of the structured answer, the routes, an
  empty input, an input with a direction and one without, a result with a
  subject and one without, a timeout, an API error, invalid or partial output,
  and a missing required field.
- Two of the tests exist to guard the Invariants rather than a feature: that
  the API token appears in no response and no rendered page, and that no
  entered or generated text reaches the log. They are not deleted to make a
  refactor pass.
- A fix for a defect arrives with the test that fails without it.
- Test data is invented. No real mail, message, conversation, personal name,
  company or matter is used, and a defect found in real correspondence is
  reproduced with material written for the test.
- Assume unattended execution as a service by default. The process reads its
  configuration from the environment or `.env`, so every required variable is
  defined explicitly there rather than inherited from a login session.
- Anything that changes state on the host, the deployment steps included, is
  safe to run twice. Check the current state before changing it, rather than
  assuming the state a previous run left behind.
- The service runs with the privileges its work needs and no more. A step that
  needs a raised privilege takes it for that step; the process does not run its
  whole body under it.

### 2.7 Documentation and Versioning
- Every module must contain a structured header, in this order:
  `Description`, `Routes` (the web application only), the standard `Author`,
  `Source Code`, `License`, `Contact` block, `Usage` and `Options`
  (executables and modules that take options only), `Exit Codes` (a module
  that can end the process with more than one status), `Requirements`,
  `Environment Variables` (`config.py` only), `Version History`.
- `Routes` sits next to `Description` because it says what the module serves,
  which is part of what it is; `Usage`, `Options` and `Exit Codes` say how it
  is driven, and follow the identifying block.
- Every setting is documented in three places that must agree: the
  `Environment Variables` block of `config.py` (the name, what it decides,
  whether it is required, and the default when it has one), `.env.example` as a
  file to copy, and the README for a reader who is not editing code.
- "Test Cases" belong in the test code under `tests/`, never in the application
  modules.
- Documentation must be updated in sync with behavior changes. A change to what
  a prompt asks for updates the prompt specification in the same change.

#### 2.7.1 When to Bump a Module Version
- These rules apply to the `Version History` in each module header. Repository
  release versions and Git tags follow the separate rules below.
- Do not bump the version mechanically every time a file is touched. Decide
  based on the nature of the change:
  - Documentation-only, comment-only and formatting-only changes (help text,
    README/POLICY/VERSIONS wording, whitespace and layout, with no effect on
    behavior) do not bump the version.
  - Any change that affects code behavior (bug fixes, new options, and refactors
    that change observable behavior) bumps the version.
  - Multiple updates on the same date are consolidated into a single version
    entry; do not increment the version multiple times on the same date.
  - Finalizing only the release date of an entry that already exists, such as
    changing `TBD` to the actual date, is not by itself a change. Classify that
    entry by what it contains, not by the date edit.

#### 2.7.2 Module Version Numbering
- Versions use a two-level `major.minor` scheme.
- When incrementing `minor` would reach `10`, roll over instead: increment
  `major` by 1 and reset `minor` to `0` (for example `v0.9` -> `v1.0`,
  `v1.9` -> `v2.0`).
- Do not continue `minor` past `9` as in standard semantic versioning
  (do not use `v1.10`, `v1.11`, ...).
- A change that is not backward compatible bumps `major` and resets `minor` to
  `0`, whatever `minor` currently stands at. Reaching `10` is not the only
  reason to raise `major`. Removing or renaming an option or a setting,
  changing what an existing one means, and changing a default so that an
  unchanged invocation does something else are all incompatible changes.

#### 2.7.3 Repository Versioning
- Repository release versions are independent of individual module versions.
- Record repository release versions in `doc/VERSIONS` and use the same versions
  for Git tags.
- Repository release versions may use a three-level `major.minor.patch` scheme.
  The first release is v1.0 and the one after it is v1.0.1.
- Work that is not released yet takes no version of its own: it belongs to the
  entry already standing at the top of `doc/VERSIONS`.
- An unreleased entry carries `(Release Date: TBD)` until it ships. Replacing
  that with the actual date is the release itself, not a change to record.
- The package version exposed by `reply_writer.__version__` and
  `cli.py --version` tracks the application, and is bumped when a release
  warrants it, not on every change.

#### 2.7.4 doc/VERSIONS Structure
- `doc/VERSIONS` reads as a version-level summary of overall changes, not a raw
  commit log. It is a plain text document and follows the rules for one stated
  below, with the one exception of line length described here.
- Write one coherent change on one physical line. This is the rule, qualified
  once below for a file that has already settled on a form of its own. The file
  is read as a list and reviewed as a diff, and both are served by an entry that
  is not wrapped: one line is one change, added, removed or reworded as a whole.
- That rule comes before the roughly 80 columns a plain text document otherwise
  aims at. Near 100 columns is the usual target, and an entry that has to name
  a file, a command, a function, an option or a setting may run to about 120
  columns or beyond.
- These widths are a prompt to check whether an entry explains more than it
  needs to, not a limit to enforce.
- `doc/VERSIONS` carries these guidelines again at its foot, and an entry
  written into it follows the reasons recorded there.
- That qualification is this: where the file has settled on a width of its own,
  a new entry is wrapped to that width and balanced against the lines already
  standing, so that the version history stays of a piece, and that consistency
  comes before the one physical line asked for above. Holding to a form the
  file has established is how the rule is kept there, not a departure from it,
  and the entries already written are not reflowed or rebuilt to suit it.
- When an entry runs long, look first for what can be dropped or abstracted:
  the implementation detail, the example, the detailed reason, the secondary
  effect. Consider that before wrapping the line.
- Keep the changed target, the behavior visible from outside, the effect on
  compatibility, the effect on safety, and the identifiers that matter.
- An entry that is long because it names the identifiers it needs is not
  shortened for its length alone.
- Merge changes that serve one purpose. Related changes to the same file within
  one version are merged as a rule; changes to the same file that mean
  different things are left as separate entries rather than forced together.
- Place entries that touch the same feature, file or purpose near each other,
  and append an independent change to the end of that version. Reading well as
  a version comes before preserving the order the commits happened in.
- Use UTF-8.

#### 2.7.5 Document Format
- The format of a document is decided by what it is for and by the name it
  carries, not by whether part of its content happens to parse as Markdown.
- A document named with `.md` is written, displayed and maintained as Markdown.
- A document that carries no extension is a plain text document, and nothing in
  it assumes a Markdown renderer.
- Underlined headings, dashed lists, backquotes and bare URLs are readable as
  Markdown wherever they appear, and finding them in a plain text document does
  not make it one.
- The name states the format so that nobody has to infer it from the content.
  Reading a file to guess what it is gives a different answer to every reader
  and to every agent; the extension gives all of them the same answer.
- The two formats are kept apart because they are read in different places.
  Markdown is read rendered, in a browser, where the structure carries the
  meaning. Plain text is read raw, in a terminal, a pager or a diff, where the
  bytes are all there is. A rule that serves one damages the other, which is
  why the two sets of rules below are stated separately and are not merged.

#### 2.7.6 Markdown Documents
- A Markdown document may assume that it will be rendered.
- Use headings, lists, tables, code blocks, links and emphasis to make the
  structure of the document explicit.
- Name it with `.md`, so that the path states the format.
- `*.md diff=markdown` in `.gitattributes` gives it diff hunk headers that name
  the section, and that is there to be used.
- Both sides count: the structure after rendering, and how easy the source is
  to edit.
- Ordinary prose may be wrapped where that keeps the source readable, near the
  width the document already uses.
- The roughly 80 columns that plain text aims at is not a limit here, and is
  not applied to a Markdown document as one.
- A URL, a table row, a code block, a command, an identifier or a link
  construct may run long. Wrapping one of those costs a copyable line or a
  working table and buys nothing.
- Line length never justifies breaking the meaning of the markup or inserting a
  break the notation does not want.
- In a Markdown document the heading structure, the paragraph structure, the
  correctness of the notation and the rendered result come before the length of
  a physical line.

#### 2.7.7 Plain Text Documents
- A plain text document is read as it is, without any particular renderer and
  without any particular viewer.
- It stays readable on an old fixed-width terminal, under `less` or `cat`, in
  an editor and in a diff.
- Ordinary prose stays near 80 columns as far as it practically can.
- Near 80 columns is a guideline for readability on a terminal, not an absolute
  mechanical limit.
- A URL, a legal formula, a command, a required identifier, a table, or a line
  that is clearer left unbroken may exceed the usual width.
- Exceeding that width is not by itself a defect, and not by itself something
  that has to be corrected.
- Markdown-compatible headings and lists may be used to give such a document
  structure, but nothing in it assumes Markdown rendering.
- Judge it as raw text: how readable and how stable it is line by line, not
  what a renderer would make of it.

#### 2.7.8 Document File Naming
- A document written in Markdown takes a `.md` extension when it is newly
  created. This repository is new, so its Markdown documents carry the
  extension from the moment they are written: `doc/POLICY.md`,
  `doc/LICENSE.md`, and the requirement, design, prompt and deployment
  documents beside them.
- The licence texts keep the extensionless names by which they are recognised:
  `COPYING` and `COPYING.LESSER`.
- A document that is not Markdown takes no extension, or `.txt`.
- An existing document is not renamed to add or change an extension. A path
  here is a public URL that the README and pages outside this repository link
  to. Renaming breaks those links, and the ones outside can be neither found
  nor repaired.
- Rename only when the current name causes a failure that outweighs the links
  it breaks, and only after examining the references to it.
- `doc/VERSIONS` keeps its name. It is not Markdown, so rendering does not
  apply to it.
- A name is decided where it lives. Uniformity of naming is not on its own a
  reason to rename a document that is already published under a path.

#### 2.7.9 The Extensionless Documents Here
- `doc/VERSIONS` is the version history, plain text, without an extension.
- `doc/COPYING` and `doc/COPYING.LESSER` hold the official licence texts as
  plain text.
- None of the three is a `.md` document, and none of them is meant to be
  rendered as Markdown.
- Their official names, their legal wording and their published paths come
  first. Uniformity of form is not on its own a reason to rename them.
- `doc/LICENSE.md` carries `.md` because it is the Markdown document this
  repository presents to a reader.
- `LICENSE.md` and the `COPYING` texts have different roles, so having both is
  neither a duplicate nor an inconsistency.
- Do not rename `doc/VERSIONS`, `doc/COPYING` or `doc/COPYING.LESSER` to `.md`
  because they contain a symbol a Markdown renderer would accept.

#### 2.7.10 Document File Attributes
- What `.gitattributes` says about a diff does not decide the format of a
  document. It describes documents whose format their names have already
  settled.
- `.gitattributes` gives `diff=markdown` to `*.md`, so that a diff hunk header
  names the section it falls in. A document named with `.md` is covered by that
  line and needs no entry of its own.
- `doc/VERSIONS` is excluded. It is underlined plain text, and `diff=markdown`
  empties the hunk headers that otherwise name the version; leaving it out
  agrees with treating it as a plain text version history.
- `doc/COPYING` and `doc/COPYING.LESSER` are excluded as the licence texts,
  which agrees with their role as the official legal wording.
- No file is given `linguist-language`. Nothing in `.gitattributes` makes a
  document that carries no extension render as Markdown; that is what the `.md`
  names are for, and an extensionless document is not dressed up as Markdown.
- How a document appears when it is browsed is not a reason on its own to
  change its format or its attributes.

#### 2.7.11 Form and Role
- Bringing every document to one extension, one line width and one way of being
  displayed is not a goal in itself.
- Choose the form from the role of the document, where it is read, the path it
  is published under, what it must stay compatible with, and how it is edited.
- What is kept uniform is not the appearance of the documents but the criterion
  by which their form is chosen.
- Markdown documents and plain text documents living side by side in one
  repository is the intended design, not an untidiness to be resolved.
- Modernizing or unifying a format must not cost an existing path, a legal
  text, readability on a terminal, or the legibility of a diff.
- Before changing a file name or a line width, find out why the current form
  was chosen.

#### 2.7.12 The Language of the Repository
- The code, the comments, the identifiers, the documents, the screens and the
  prompts are written in English.
- What is generated is Japanese, because the correspondence is, and so is the
  message a person pastes in.
- Where a document or a prompt has to quote a Japanese string as the
  specification — a formula the reply must not fall into, a phrase it must not
  add — the string is quoted literally, because an English translation of it
  would match nothing.

### 2.8 License
- The repository is dual licensed under the GPL version 3 or the LGPL version
  3, at the user's option. The full texts live in `doc/LICENSE.md`,
  `doc/COPYING` and `doc/COPYING.LESSER`.
- Every module header repeats the license line of the standard identifying
  block, so that a file read on its own still states its terms.
- Add a dependency only when its license is compatible with that choice.
