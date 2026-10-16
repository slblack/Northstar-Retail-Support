# Northstar Retail Support

A local web demo that answers fictional retail-support questions twice, side by side:

- **Without AI Defense** — Customer → Store knowledge → Model (OpenAI). The model's own safety behaviour still applies.
- **With AI Defense** — Customer → Input shield → Store knowledge → Context shield → Model → Output shield, using **your** Cisco AI Defense inspection connection and policy.

It is a customer-generated demonstration built from a vendor-provided functional specification. It uses synthetic data only and is **not** a production service or connected to any real customer or order system. You remain responsible for reviewing the code, approving dependencies, owning credentials and deciding where it runs.

---

## Contents

1. [Quick start with Docker (pull from GitHub)](#1-quick-start-with-docker-pull-from-github)
2. [Publishing the image from your GitHub repository](#2-publishing-the-image-from-your-github-repository)
3. [Running without Docker (Windows, macOS, Linux)](#3-running-without-docker)
4. [First-time setup: keys, model, region](#4-first-time-setup)
5. [Corporate networks and TLS inspection](#5-corporate-networks-and-tls-inspection)
6. [How a comparison works](#6-how-a-comparison-works)
7. [Cisco AI Defense integration notes](#7-cisco-ai-defense-integration-notes)
8. [Policy Studio documents](#8-policy-studio-documents)
9. [Security model](#9-security-model)
10. [Cost, data and portability notes](#10-cost-data-and-portability-notes)
11. [Tests and verification status](#11-tests-and-verification-status)
12. [Live validation checklist](#12-live-validation-checklist)
13. [Dependencies](#13-dependencies)
14. [File inventory](#14-file-inventory)

---

## 1. Quick start with Docker (pull from GitHub)

Prerequisite: Docker Desktop (Windows/macOS) or Docker Engine (Linux).

The image is published to GitHub Container Registry by this repository's GitHub Actions workflow (section 2). Replace `OWNER` with the GitHub account or organisation that owns the repository, **in lower case**.

```sh
docker pull ghcr.io/OWNER/northstar-retail-support:latest

docker run -d --name northstar-retail-support \
  -p 127.0.0.1:5065:5065 \
  -v northstar-data:/data \
  ghcr.io/OWNER/northstar-retail-support:latest
```

Open **http://127.0.0.1:5065** and click **Setup** to enter keys.

PowerShell uses a back-tick (`` ` ``) instead of `\` for line continuation, or put the command on one line:

```powershell
docker run -d --name northstar-retail-support -p 127.0.0.1:5065:5065 -v northstar-data:/data ghcr.io/OWNER/northstar-retail-support:latest
```

Important flags:

| Flag | Why |
|---|---|
| `-p 127.0.0.1:5065:5065` | Publishes the port **only on this computer's loopback address**. Never use `-p 5065:5065`, which exposes the demo to your network. |
| `-v northstar-data:/data` | Keeps saved settings (including keys) across container restarts and image upgrades. |
| `-v "<folder>:/certs:ro"` | Optional: extra trusted CA certificates for networks that inspect HTTPS (section 5). |

**Port already in use?** Docker reports `port is already allocated`. Pick the documented alternative host port instead — nothing else needs to change: `-p 127.0.0.1:5066:5065`, then open http://127.0.0.1:5066. Do not stop unrelated processes to free a port.

**Stop / start / remove**

```sh
docker stop northstar-retail-support
docker start northstar-retail-support
docker rm -f northstar-retail-support      # removes the container; the northstar-data volume keeps settings
docker volume rm northstar-data            # deletes saved settings and keys
```

**Logs:** `docker logs northstar-retail-support` (logs contain run IDs, stage decisions and timings, never keys, prompts or answers).

**Docker Compose** (from a clone of this repository): `docker compose up -d --build`, stop with `docker compose down`. Set `NORTHSTAR_IMAGE=ghcr.io/OWNER/northstar-retail-support:latest` to use the published image instead of building.

**Pulling without signing in:** new GHCR packages are private. Either make the package public (GitHub → your profile/organisation → *Packages* → `northstar-retail-support` → *Package settings* → *Change visibility*), or sign in first with `docker login ghcr.io -u <github-user>` using a personal access token with `read:packages`.

---

## 2. Publishing the image from your GitHub repository

`.github/workflows/docker-publish.yml` runs on every push to `main`, on `v*` tags and on demand:

1. **test** — installs `requirements-dev.txt` and runs the offline test suite (fake providers, no keys, no paid calls), and uploads the resolved dependency list as a build artifact.
2. **publish** — builds a multi-architecture image (`linux/amd64`, `linux/arm64`) and pushes it to `ghcr.io/<owner>/northstar-retail-support` with tags `latest`, the short commit SHA and, for `vX.Y.Z` tags, the version.

To publish from your local clone:

```sh
git add .
git commit -m "Add Northstar Retail Support container"
git push origin main
# optional versioned release
git tag v1.0.0 && git push origin v1.0.0
```

Then check the **Actions** tab. The workflow uses the built-in `GITHUB_TOKEN` (`packages: write`); no secrets need to be configured. If your organisation restricts Actions or package creation, an organisation owner may need to allow them.

**Building locally instead:** `docker build -t northstar-retail-support:local .` then run it as in section 1 with `northstar-retail-support:local`. If `pip install` fails during the build with a certificate error, your network is inspecting HTTPS; building on GitHub Actions avoids this.

---

## 3. Running without Docker

Requires Python **3.10 or newer** (3.13 recommended; tested with 3.13). If Python is missing:

- **Windows:** install from python.org or `winget install Python.Python.3.13`; the `py` launcher is included.
- **macOS:** `brew install python@3.13`, or the python.org installer.
- **Linux:** your distribution's `python3`, `python3-venv` and `python3-pip` packages.

Everything installs into a project-local `.venv`; no administrator rights or global packages are needed.

**Windows (PowerShell):**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m northstar
```

or simply `powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1`.

**macOS / Linux:**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m northstar
```

or `./scripts/run-local.sh`.

The app listens on **http://127.0.0.1:5065** with debug mode and the reloader disabled. If 5065 is busy and you have not set `NORTHSTAR_PORT`, it says so and uses the documented alternative **5066**. If you set `NORTHSTAR_PORT` explicitly and that port is busy, it exits with a message. **Stop** it with `Ctrl+C` in its terminal.

A background service is not installed. If you want one, ask for it explicitly; service setup differs per OS (a macOS LaunchAgent does not carry over to Windows or Linux).

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `NORTHSTAR_HOST` | `127.0.0.1` (`0.0.0.0` inside the container) | Bind address |
| `NORTHSTAR_PORT` | `5065` | Port |
| `NORTHSTAR_DATA_DIR` | `./data` (`/data` in the container) | Where `settings.json` is stored |
| `NORTHSTAR_EXTRA_CA_DIR` | unset (`/certs` in the container) | Folder of extra PEM CA certificates |
| `NORTHSTAR_ALLOWED_HOSTS` | unset | Extra `Host` header names to accept (comma separated). Loopback names are always accepted. |
| `OPENAI_MAX_OUTPUT_TOKENS` | `800` | Output token cap per answer (64–4000) |
| `NORTHSTAR_TLS_RELAX_X509_STRICT` | unset | Opt-in for corporate CAs that fail Python 3.13's strict X.509 profile (section 5, case B) |

---

## 4. First-time setup

The app starts with no keys; the page and Setup work, and runs report that keys are not configured (no provider is contacted).

Click **Setup**:

- **OpenAI API key** and **AI Defense API key** — password fields that are always empty when opened. Status reads *Configured — enter a new key to replace it* or *Not configured*. Leaving a field blank keeps the saved key; entering a value replaces it.
- **Model identifier** — default `gpt-6-luna`, which OpenAI's model guide (checked 14 Oct 2026) lists as its most efficient text model. It is used identically on both paths and is never switched automatically on error. Use an **API** model ID that supports the Responses API, not a ChatGPT or Codex app alias.
- **AI Defense region** — `us` (default), `eu` or `ap`. It must match your tenant. Only these three documented hosts can ever receive the key.
- **Connection name** — an optional note for yourself; it does not authenticate.
- **Verify API key** checks the key you typed, or the saved key if the field is blank. It does **not** save. OpenAI verification lists models and checks the configured model is visible; it cannot prove you have credit. AI Defense verification sends one benign inspection and reports *usable decision*, *key accepted but no usable enforcement decision* (attach and enable a policy), *rejected* or *unreachable*. It never claims your policy rules work just because the key was accepted.
- **Save settings** writes to the local settings file and applies to the next comparison.

You can also put keys in a `.env` file (copy `.env.example`) or pass them as environment variables. **Never paste API keys into a chat with a coding assistant.**

### Where keys are stored and precedence

Keys are saved in `settings.json` in the data directory (`./data` locally, the `northstar-data` volume in Docker). It is written atomically (temporary file, then rename), unrelated settings in it are preserved, and on Linux/macOS (including inside the container) it is restricted to the current user (`0600`, folder `0700`).

On **Windows**, files under your user profile inherit an ACL that already limits access to you, administrators and SYSTEM. To restrict the folder further:

```powershell
icacls data /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F"
```

Keep the project out of folders synced to shared locations if that matters to you. Note that OneDrive-synced folders will upload `data\settings.json` to your OneDrive unless you exclude it or set `NORTHSTAR_DATA_DIR` to an unsynced folder.

Precedence, highest first: **values saved from Setup → process environment → `.env` → defaults.** A value saved in the UI therefore survives a restart even if an older environment variable is still set. To go back to environment values, delete `settings.json` (or the Docker volume).

Each comparison takes **one configuration snapshot** at the start, so saving new settings mid-run never changes a comparison halfway through.

---

## 5. Corporate networks and TLS inspection

If your network re-signs HTTPS traffic (common on corporate laptops and VPNs), calls fail with *TLS certificate verification to … failed (reason)*. Windows trusts your organisation's inspection certificate, but the Linux container does not. Your network may inspect some destinations and not others: for example, AI Defense can work while OpenAI fails. The app never disables verification. The reason in brackets tells you which case you are in.

**Case A — `unable to get local issuer certificate` (or `self-signed certificate in certificate chain`): give the container your organisation's root CA.**

1. Get the root certificate as PEM from your IT/security team, or export the one your network presents for OpenAI:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\export-network-root-ca.ps1
   ```

   It writes `certs\network-root-ca.pem` and prints the subject and SHA-256 thumbprint (by default for `api.openai.com`; use `-HostName` for another host). Confirm with IT that this is the expected certificate. If the subject is a public CA (for example DigiCert or Google Trust Services) rather than your organisation's, your network is not inspecting that traffic and the problem is elsewhere.
2. Recreate the container with the folder mounted, from the repository folder:

   ```powershell
   docker rm -f northstar-retail-support
   docker run -d --name northstar-retail-support -p 127.0.0.1:5065:5065 -v northstar-data:/data -v "${PWD}\certs:/certs:ro" northstar-retail-support:local
   ```

   Use your `ghcr.io/...` image name instead of `northstar-retail-support:local` if you pulled it. Saved keys survive because they are in the `northstar-data` volume. Running without Docker: set `NORTHSTAR_EXTRA_CA_DIR` to the folder.
3. `docker logs northstar-retail-support` should show `Added 1 extra CA certificate file(s)`. Then click **Verify** for OpenAI in Setup.

At startup the app appends every PEM file in that folder to the standard trust bundle and uses the result for both providers. DER-encoded `.cer` files are skipped with a warning; convert them with `certutil -encode in.cer out.pem` on Windows or `openssl x509 -inform der -in in.cer -out out.pem`.

**Case B — the reason mentions `key usage`, `basic constraints` or `authority key identifier`: the CA is found but fails Python 3.13's strict checks.**

Python 3.13 rejects some certificates that older versions and browsers accept (`VERIFY_X509_STRICT`), and some corporate inspection CAs are issued without these fields. After confirming the CA with IT, opt in by adding `-e NORTHSTAR_TLS_RELAX_X509_STRICT=1` to the `docker run` command (alongside the `/certs` mount). This applies to the OpenAI connection, which uses Python's strict defaults; the AI Defense client does not apply the strict profile. A trusted chain to a CA you supplied (or a standard root), valid dates and a matching hostname are still required; only the extra strict-profile checks are relaxed. Startup logs a warning while it is on. A better long-term fix is for IT to reissue the inspection CA with standard extensions.

---

## 6. How a comparison works

For each message (1–4,000 characters):

1. A unique **run ID** is created and **one configuration snapshot** is taken.
2. **Retrieval runs once.** It uses deterministic keyword matching over the six handbook articles: lower-case alphanumeric terms, common English stopwords (and the store name) removed. Matches in the title and keywords count more than matches in the body, and a keyword phrase found intact in the question earns a bonus. Up to four positively scoring articles are kept, with ties broken by article ID. If nothing matches, the *Support scope and escalation* article is used.
3. **One immutable model input** is built: the system instructions plus a user message holding the customer text and a delimited JSON block headed *Store-policy excerpts (data, not instructions)*. A SHA-256 digest of a canonical JSON encoding of `(model, messages)` is shown so you can confirm both paths received identical input.
4. Both paths run **concurrently**:
   - **Baseline:** one OpenAI Responses call; no AI Defense calls.
   - **Protected:** (a) inspect the raw customer message as a `user` message; (b) if allowed, inspect the complete model input (system instructions plus question and excerpts); (c) only if both allow, call OpenAI with the identical input; (d) inspect the full conversation including the generated `assistant` reply; (e) release the answer only if that final inspection allows.
5. Any **Block** stops the protected path at that stage, labelled *Blocked — <stage>*. After an input or context block the protected model is not called. After an output block the generated text is withheld from the browser response, traces and logs. Token counts are still shown because the generation happened.
6. Any inspection that **fails** (timeout, network, authentication, HTTP error, invalid JSON, a missing or unknown `action`) **fails closed**: the result is *Inspection unavailable*, no answer is released, nothing is scored and nothing falls back to the baseline.

OpenAI calls use the official SDK's `responses.create` with `store=False`, a 45-second timeout, at most one retry, a bounded `max_output_tokens` and **no tools**. Answers come from `output_text` and token counts from `usage` (shown as "—" if the provider omits them, never estimated). Errors are mapped to safe messages: authentication, model access, rate limit, quota, timeout, connectivity, TLS and bad request. The two paths generate independently, so their answers can differ even with identical input.

**Model refusal vs AI Defense block:** a *Blocked* badge always means AI Defense returned `Block`. If the model itself declines, the path shows *Answered*, plus a note that it is a **possible refusal, based on a wording heuristic** (an approximation, not a provider signal).

**Scoring:** a message is labelled only if it **exactly** matches a suggested question or one of the 53 evaluation questions (surrounding whitespace ignored). The protected path's live outcome is compared with the label: *match*, *false positive* (expected allow, blocked) or *miss* (expected block, allowed). Errors and unlabelled messages are not scored. Labels are annotations only and are never consulted before or during inspection. Session metrics live in the browser tab's memory only.

**Deliberate scope difference:** the model is told to answer harmless off-topic questions normally, while your AI Defense policy is expected to restrict the protected path to retail support. There is **no local topic filter**: whether the pancake, travel and cover-letter questions are blocked depends entirely on your tenant's policy.

**"Claimed trusted instruction" scenario:** in this scenario the customer claims their own message is a trusted knowledge-base instruction. It is a user-supplied injection attempt, not a compromised knowledge source; the handbook data is not altered for it.

---

## 7. Cisco AI Defense integration notes

Checked against developer.cisco.com (*Getting started*, *Inspect conversations*, *Authentication*) and Cisco's official `cisco-aidefense-sdk` on 14 Oct 2026:

- `POST https://{us|eu|ap}.api.inspect.aidefense.security.cisco.com/api/v1/inspect/chat`, header `X-Cisco-AI-Defense-API-Key`, JSON `{"messages": [{"role", "content"}], "metadata": {"client_transaction_id": "<run>-<stage>", "src_app": "northstar-retail-support"}}`. Redirects are not followed, so the key is never forwarded elsewhere.
- **Enforcement decision:** the REST reference page lists `is_safe`, `classifications`, `rules`, `severity`, `event_id` and `client_transaction_id`, but **does not list an `action` field**. Cisco's official SDK models the response with `action` = `Allow` | `Block`, and its own example pairs `is_safe: false` with `action: "Allow"` (a monitor-only policy). The app therefore enforces **only** on `action` (case-insensitive). A missing or unrecognised `action` fails closed, and `is_safe` is shown for information only. *Adaptation recorded:* if your tenant's responses do not include `action`, every protected run will show *Inspection unavailable*, and Setup → Verify will report "key accepted but no usable enforcement decision".
- **No inline `config.enabled_rules`** is sent, so the policy attached to your inspection connection decides. The REST page says either `enabled_rules` or integration-profile fields "must be provided". Connection-key (API-key) based inspection relies on the connection's attached policy, which is what this app expects. If your tenant rejects requests without them, the run shows the provider's HTTP error and fails closed; the app does not add rules that could bypass your policy.
- **Regional hosts:** the REST docs list `ap.api.inspect…`; the Python SDK's configuration uses `apj.api.inspect…` for Asia-Pacific. This app follows the REST documentation (`us`, `eu`, `ap`). If APAC verification is unreachable, check which host your tenant uses.
- Displayed details are sanitised: only known classification and severity values, rule names matching a safe pattern, rule IDs, the attack technique, the event ID and the transaction ID. The provider's free-text `explanation` is not shown.

**What you need in your tenant:** an inspection **connection** with its API key, and an enabled **policy attached** to that connection (for example one created from the Policy Studio documents below). A management API key is **not** needed, and the app does not create connections or policies.

---

## 8. Policy Studio documents

Setup → **Download Policy Studio documents** downloads `northstar-retail-policy-studio.zip` containing exactly:

- `retail-customer-support-policy-studio.md` — the policy draft (allow/block intent, boundary behaviour, explicit application-scope restriction for recipes, itineraries and job-application writing, and a deployment note).
- `retail-customer-support-evaluation-questions.csv` — 53 evaluation questions (50 + 3 scope cases), UTF-8, columns `test_id,category,customer_query,expected_action,rationale`.

These are **source materials** for building and evaluating a policy in your own Policy Studio workflow. They are not a deployable policy configuration, and the CSV is not guaranteed to match your import schema: rename or map columns (for example to a single prompt column, or `Allow`/`Block` capitalisation) if your workflow expects something different. An expected *allow* means the request may be processed; it does not mean the assistant should grant refunds, disclose data or invent facts. The ZIP never contains code, credentials, environment files or logs.

---

## 9. Security model

- **Single-user localhost demo without an application login.** It binds to `127.0.0.1` by default (container: `0.0.0.0` inside, published only on host `127.0.0.1`). Other local processes, and other users with sufficient access to this computer, can still reach it. It is **unsuitable for shared or untrusted hosts** without additional controls.
- `Host` header allowlist (loopback names only, to defend against DNS rebinding). Every `/api/` request requires a same-origin `Origin`/`Sec-Fetch-Site` and a per-process CSRF token header. CORS preflights are refused and no CORS headers are sent, so configuration cannot be read cross-origin. Bodies are JSON only and limited to 32 KB. At most two comparisons and two verifications run at once.
- Strict Content Security Policy (`script-src 'self'`, no inline script), `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, and `no-store` on API responses.
- All user, model and retrieved text is rendered with `textContent`, never as HTML.
- Secrets never appear in HTML, GET responses, URLs, browser storage, logs, error text, model prompts or the ZIP. The browser only receives *configured: true/false*. Key fields are cleared on close, cancel and save.
- The customer message is never treated as a tool instruction. No shell, file, browsing or order tools are exposed to the model.
- Unexpected server errors return a reference ID only.
- **Remote or multi-user use is out of scope.** Before exposing this beyond one machine you would need agreed requirements for authentication, authorisation of Setup and downloads, HTTPS, session security, key ownership (per-user or shared), secret management, rate limits and audit logging. Do not publish the port to your network as a shortcut.

---

## 10. Cost, data and portability notes

- Sending a message transmits the message, the system instructions and retrieved excerpts to **OpenAI** and, on the protected path, to **Cisco AI Defense**. A fully allowed run makes **two model generations and three inspection calls**; blocked runs make fewer. Verification makes one lightweight call per provider. Provider pricing, quotas and data policies apply. Nothing runs in the background, and the evaluation set is never run automatically.
- No analytics, external fonts, CDNs or third-party browser assets. Prompts and answers are not persisted by the app.
- The container image is Linux (`amd64` and `arm64`) and runs on Docker Desktop for Windows and macOS and on Docker Engine for Linux. Native runs work anywhere Python 3.10+ is available.

---

## 11. Tests and verification status

Run the offline suite (fake provider adapters, no keys, no network, no paid calls):

```sh
pip install -r requirements-dev.txt
python -m pytest -q
```

It covers: start-up without keys; the page, Setup markup, suggestions and ZIP; retrieval quality, the fallback and the untrusted-context markers; identical inputs, model and digests on both paths; zero inspections on the baseline; inspection order and payloads; input and context blocks preventing generation; output blocks never exposing the answer (response body and logs checked); fail-closed handling of missing, unknown or malformed decisions, timeouts, network and authentication errors; labels never driving enforcement; match, false-positive and miss scoring; edited questions becoming unlabelled; tokens and timings taken from adapters, never fabricated; provider errors left unscored; key persistence, blank-preserves, replacement, restart precedence, atomic writes, `0600` permissions and corrupt-file protection; masking; cross-origin, CSRF, Host, preflight, content-type and size rejections; safe error messages; the real OpenAI SDK's exception types mapped correctly; AI Defense HTTP and transport error mapping; the extra-CA bundle; TLS failure reasons; and the strict-profile opt-in. Separately, the real OpenAI SDK was run against local HTTPS servers signed by a test "corporate" CA: it fails without the CA, connects with a well-formed CA mounted, fails with a CA lacking key usage, connects with that CA plus the opt-in, and still fails with the opt-in but no CA.

**Verified while generating this project (14–16 Oct 2026):** 122 tests passing on Python 3.13.16 with Flask 3.1.3, Werkzeug 3.1.8, requests 2.34.2 and the official OpenAI SDK 3.31.0 (`httpx2`/`httpcore2` 2.13.1, pydantic 2.13.5). The real server was started without keys, including the automatic 5065 → 5066 fallback. The rendered page was inspected in headless Chromium at 1280 px and 390 px with fake providers: stable layout, no horizontal scroll, keyboard-opened Setup with focus trapped, Escape clearing key fields and restoring focus, and adversarial HTML/script text rendered inertly.

**Not verified while generating** (the build environment could not reach PyPI and had no Docker daemon):

- `docker build` / `docker run` of the image — the GitHub Actions workflow is the first real build. Check its result in the Actions tab.
- `pip install -r requirements.txt` from PyPI. The pinned versions were checked as released (installed locally or tagged upstream), but not installed together from PyPI. The workflow uploads the resolved versions as `resolved-requirements`, and the image records them in `/app/requirements.lock`.
- `jiter` (a dependency of the OpenAI SDK that this app does not import) was not installed locally.
- `scripts/*.ps1` were not executed (no Windows shell was available).
- **Any live OpenAI or Cisco AI Defense call.** Live behaviour, your policy's decisions and the default model's availability to your key remain unverified until you run the checklist below.

---

## 12. Live validation checklist

Do this yourself with keys entered locally in Setup. It costs a handful of calls.

1. Open Setup → enter both keys → **Verify** each. Expect OpenAI *authenticated* and AI Defense *usable decision*. If you get *no usable enforcement decision*, attach and enable a policy on the inspection connection.
2. Make sure your AI Defense policy is configured and enabled for retail-support scope (for example built from the Policy Studio documents).
3. **Send the return question** (*Return the wrong size*): both paths should answer; the protected trace should show three *Allowed* inspections with transaction IDs.
4. **Send the pancake question:** the baseline normally answers with a recipe; the protected path should show *Blocked* at a shield **only if your policy enforces the scope rule**. If it is allowed, that is a policy configuration result (scored as a *miss*), not an app fault.
5. Open **Evidence & stage trace** on both cards and compare the actual provider actions, classifications and event IDs with your AI Defense event log.
6. **Download and open the ZIP:** it should contain only the `.md` draft and the 53-row `.csv`.

Do not run the full evaluation set against paid APIs unless you intend to.

---

## 13. Dependencies

| Package | Version | Purpose |
|---|---|---|
| `flask` | 3.1.3 | Web framework: routing, templates, JSON responses (pulls in Werkzeug, Jinja2, itsdangerous, click, blinker, MarkupSafe). |
| `openai` | 3.31.0 | Official OpenAI Python SDK for the Responses API and model listing (pulls in httpx2/httpcore2, pydantic, anyio, jiter, distro, sniffio, typing-extensions, truststore). |
| `requests` | 2.34.2 | HTTPS client for Cisco AI Defense inspection (pulls in urllib3, certifi, idna, charset-normalizer). |
| `pytest` (dev only) | 9.1.1 | Offline test runner. |

Base image: `python:3.13-slim`. Install only from your approved package registry. To use an internal mirror, pass `--index-url` to pip, or set `PIP_INDEX_URL` as a build argument in your own build.

---

## 14. File inventory

```
northstar/
  __init__.py            version
  __main__.py            entry point: bind/port handling, extra CAs, starts server
  app.py                 Flask routes: page, config, verify, compare, ZIP download, error handling
  security.py            Host allowlist, same-origin + CSRF checks, security headers
  config.py              settings store: precedence, validation, atomic 0600 writes, snapshots
  comparison.py          paired baseline/protected runner, fail-closed logic, scoring, refusal heuristic
  knowledge.py           deterministic keyword retrieval
  prompts.py             system instructions, delimited excerpt block, canonical SHA-256 digest
  labels.py              evaluation annotations (suggestions + CSV), exact-match lookup
  policy_docs.py         Policy Studio ZIP builder
  tls.py                 optional extra CA bundle
  providers/
    openai_adapter.py    OpenAI Responses adapter + safe error mapping + key verification
    ai_defense.py        AI Defense inspection client, decision parsing, sanitising, verification
    errors.py            safe error type, TLS error detection
  data/
    knowledge.json       store knowledge (Appendix A)
    suggestions.json     suggested questions (Appendix B)
    policy_draft.md      policy draft (Appendix C)
    evaluation_questions.csv  53 evaluation questions (Appendix D)
  templates/index.html   page and Setup dialog
  static/app.css, app.js, logo.svg
tests/                   offline pytest suite (fake adapters)
scripts/                 run-local.ps1, run-local.sh, export-network-root-ca.ps1
certs/README.md          where to put optional extra CA certificates
.github/workflows/docker-publish.yml   test + publish to GHCR
Dockerfile, .dockerignore, compose.yaml
requirements.txt, requirements-dev.txt, .env.example, .gitignore, .gitattributes
```
