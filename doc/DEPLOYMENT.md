# Deployment

`reply-writer` runs as a small web application on a server: gunicorn behind Apache, managed by systemd, reachable over HTTPS from a phone.

This document is the whole of what installing and running it takes. The composition it follows is fixed by [`BASIC_DESIGN.md`](BASIC_DESIGN.md) sections 3 to 6 and 29 to 31; the settings are listed in [`../.env.example`](../.env.example) and in the README.

Nothing in this repository carries a hostname, a certificate or a credential of any environment. The examples under `deploy/` are examples, and the values in them are replaced.

## What it will and will not touch

The only host the application contacts is the generation endpoint `GENERATION_BASE_URL` names. It holds no credential of Gmail, Outlook, LINE or any other messaging service, opens no connection to one, and sends nothing anywhere on its own. Whoever deploys it is not being asked to provide a mail account.

## Before you begin

- A Debian or Ubuntu server, or anything close enough.
- Python 3.9 or later.
- Apache with `proxy`, `proxy_http`, `headers` and `ssl` enabled.
- A certificate for the host, from whatever the environment already uses.
- An account with the generation endpoint, and its token, base URL and model name.

## Install the service

Create the service user and the directory:

```bash
sudo adduser --system --group --home /opt/reply-writer reply
sudo -u reply git clone https://github.com/id774/reply-writer.git /opt/reply-writer
```

Create the virtual environment and install the dependencies:

```bash
cd /opt/reply-writer
sudo -u reply python3 -m venv .venv
sudo -u reply .venv/bin/pip install -r requirements.txt
```

Configure the settings:

```bash
sudo -u reply cp .env.example .env
sudo -u reply chmod 600 .env
sudoedit -u reply /opt/reply-writer/.env
```

Four of them are required and have no defaults, so the process refuses to start until they are set:

```text
GENERATION_BACKEND
GENERATION_API_TOKEN
GENERATION_BASE_URL
GENERATION_MODEL
```

That refusal is the design working. A message that leaves for an endpoint nobody named is worse than an application that will not start, so no setting falls back to a service of its own.

`.env` holds the API token, so it stays readable by the service user alone. It is listed in `.gitignore` and is never committed.

Check the installation before anything is published:

```bash
sudo -u reply .venv/bin/python -m unittest discover -s tests
```

The suite makes no request and needs no token. A pass says the installation is sound; only an actual generation says the endpoint is reachable.

## Start the application

Install the unit:

```bash
sudo cp deploy/reply-writer.service /etc/systemd/system/
sudoedit /etc/systemd/system/reply-writer.service
sudo systemctl daemon-reload
sudo systemctl enable --now reply-writer
```

Adjust the user, the paths and the port in the unit before enabling it. It starts by itself after a reboot.

```bash
sudo systemctl status reply-writer
sudo systemctl restart reply-writer
sudo journalctl -u reply-writer -f
```

gunicorn listens on `127.0.0.1:8091` and is never exposed to the internet. Check it locally:

```bash
curl -s http://127.0.0.1:8091/healthz
```

`/healthz` answers as the web application and does nothing else. It calls no API, so it says the process is up and says nothing about the endpoint.

A worker that cannot address an endpoint refuses to start, and the journal carries a line naming the setting at fault. That is where to look first when the service will not come up.

## Configure Apache and TLS

```bash
sudo cp deploy/reply-writer.conf /etc/apache2/sites-available/
sudoedit /etc/apache2/sites-available/reply-writer.conf
sudo a2enmod proxy proxy_http headers ssl
sudo a2ensite reply-writer
sudo apachectl configtest && sudo systemctl reload apache2
```

Replace the `ServerName` and the certificate paths with those of the environment.

The application is published under `/reply/`:

```text
https://<host>/reply/
        ↓
http://127.0.0.1:8091/
```

It listens at its own root, so `X-Forwarded-Prefix` is what tells it the path it is published under, and its links and form actions come back through the same prefix. The header is set by Apache on every request, so a value from outside cannot survive it. Publishing at the root instead means dropping both the header and the `RedirectMatch`, and proxying `/` straight through.

## Restrict access

Private correspondence passes through this system, so it is not published to anyone who finds the address.

Access control belongs to the web server, and any of these serves: Basic authentication, an IP restriction, a VPN, or whatever the environment already uses. The commented blocks in `deploy/reply-writer.conf` show the first two.

No account system is introduced into the application for this, and in particular no account belonging to a messaging service. Being usable from a phone away from a desk and being unusable by a stranger hold together, and they hold together in front of the application.

## The timeouts

A generation API answers more slowly than ordinary web traffic, so the limits widen from the inside outwards:

| Layer | Setting | Value |
| --- | --- | ---: |
| Generation API client | `GENERATION_TIMEOUT` | 120 s |
| gunicorn | `--timeout` | 240 s |
| Apache | `ProxyTimeout` | 300 s |

```text
GENERATION_TIMEOUT  <  gunicorn --timeout  <  Apache ProxyTimeout
```

Raising one means revisiting the other two. An inner limit above an outer one means the person is shown a proxy error while the application is still waiting, and the log then shows a generation that succeeded into a connection nobody was left holding.

`GENERATION_MAX_RETRIES` multiplies the worst case wait by the same factor, so raising it means revisiting the outer limits as well. It is 0 by default: one action by the person is one request.

## Verify the complete path

From a phone, or from anything with a browser:

1. Open `https://<host>/reply/` and pass whatever access control is in front of it.
2. Paste a message into the first field. Leave the direction empty.
3. Generate a draft.
4. Copy the reply.

That is the whole path the system is for. If it works from a phone on a mobile network, the deployment is done.

## Routine operations

```bash
sudo systemctl restart reply-writer          # after a settings change
sudo journalctl -u reply-writer --since today
```

Update the installation:

```bash
cd /opt/reply-writer
sudo -u reply git pull
sudo -u reply .venv/bin/pip install -r requirements.txt
sudo -u reply .venv/bin/python -m unittest discover -s tests
sudo systemctl restart reply-writer
```

The prompts are read from disk on every generation, so adjusting one takes effect on the next generation. Replacing the files while the service runs is still followed by a restart, so that no request lands halfway through the change.

## What the log holds

The journal carries the shape of each exchange and none of its content: the request id, the backend, the host of the endpoint, the model, the finish reason, the token counts, the elapsed seconds beside the limit, and the class of any error.

It never carries the received message, the direction, the generated reply, the assembled prompts, the API token or the `Authorization` header — at any log level. Raising `LOG_LEVEL` reveals no text of anybody's, and there is no setting that turns it back on.

That is why a person reporting a fault is asked for the request id shown on the error page rather than for what they were replying to. The id appears in the journal beside the failure, and nothing else has to be produced.

## When something fails

| What is seen | Where to look |
| --- | --- |
| The service will not start | The journal names the setting at fault. All four required settings must be in `.env`. |
| The screen reports an unreachable service | The endpoint host, the network, and whether the base URL is the one intended. |
| The screen reports an error from the service | The journal line carries the HTTP status: 401 a token to replace, 403 a plan that does not cover the model, 429 a rate limit. |
| Generation is stopped as too long | `GENERATION_TIMEOUT`, and the elapsed seconds in the journal beside it. A wait that ended well short of the limit is a connection lost, not a limit too low. |
| The result cannot be read | `GENERATION_RESPONSE_MODE`, and whether the model keeps the JSON contract. Nothing is cut out of an answer that arrived wrapped in prose. |
| An unexpected failure with a request id | The journal, at that id. |

The application falls back to no second endpoint for any of these. One generation uses the one route the configuration names, which is what keeps it possible to say afterwards where a message went.
