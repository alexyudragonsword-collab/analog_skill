"""Minimal LLM chat client — OpenAI-compatible, Anthropic, Claude Code.

Standard-library only (urllib + subprocess): the frozen bundles gain no
dependency.  Configuration lives in QSettings (same pattern as
ngspice_locator): provider / base URL / API key / model; an empty model
disables every AI feature in the GUI.

Two transports, one chokepoint each, and the tests monkeypatch exactly
those: ``_post_json`` for the two HTTP protocols, ``_run_cli`` for Claude
Code.  Everything above them sees one `chat()` with one signature.
"""

import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid

#: 'claude_code' drives the locally installed Claude Code CLI, which uses
#: the user's own login rather than an API key — see _chat_claude_code.
PROVIDERS = ('openai', 'anthropic', 'claude_code')

#: QSettings keys
KEY_PROVIDER = 'llm/provider'
KEY_BASE_URL = 'llm/base_url'
KEY_API_KEY = 'llm/api_key'
KEY_MODEL = 'llm/model'

#: An API key put here wins over the stored one, so the key never has to
#: reach disk.  QSettings is plain text — the registry on Windows, an ini
#: file elsewhere — which is defensible for a key the user pasted in
#: themselves on their own machine, and not defensible on a shared one.
#: A `keyring` dependency would fix that properly but has to survive three
#: freezing toolchains on two platforms; this costs nothing and gives the
#: shared-machine case an answer today.  See ROADMAP.md for the open half.
ENV_API_KEY = 'ANALOG_LLM_API_KEY'

#: default endpoint per provider (base_url left empty in Settings)
DEFAULT_BASE = {
    'openai': 'https://api.openai.com/v1',
    'anthropic': 'https://api.anthropic.com',
}

ANTHROPIC_VERSION = '2023-06-01'


class LLMError(RuntimeError):
    """Readable failure (bad config, HTTP error, timeout, bad payload)."""


def get_config() -> dict:
    """Current LLM settings, with $ANALOG_LLM_API_KEY overriding the stored
    key.  `api_key_from_env` tells the Settings dialog not to write that key
    back to disk — saving it there would undo the point of setting it.
    """
    from PySide6.QtCore import QSettings
    s = QSettings()
    provider = str(s.value(KEY_PROVIDER, 'openai') or 'openai')
    env_key = os.environ.get(ENV_API_KEY, '').strip()
    return {
        'provider': provider if provider in PROVIDERS else 'openai',
        'base_url': str(s.value(KEY_BASE_URL, '') or '').strip(),
        'api_key': env_key or str(s.value(KEY_API_KEY, '') or '').strip(),
        'api_key_from_env': bool(env_key),
        'model': str(s.value(KEY_MODEL, '') or '').strip(),
    }


def set_config(provider: str, base_url: str, api_key: str, model: str,
               store_api_key: bool = True):
    """Persist the settings.  With store_api_key False the key is left
    untouched on disk — used when it came from the environment, where
    writing it back would put it in plain text after all.
    """
    from PySide6.QtCore import QSettings
    s = QSettings()
    s.setValue(KEY_PROVIDER, provider)
    pairs = [(KEY_BASE_URL, base_url.strip()), (KEY_MODEL, model.strip())]
    if store_api_key:
        pairs.append((KEY_API_KEY, api_key.strip()))
    for key, val in pairs:
        if val:
            s.setValue(key, val)
        else:
            s.remove(key)


def configured(cfg: dict | None = None) -> bool:
    """AI features need a model plus a way to reach one.

    For the HTTP providers that means a key or a custom endpoint (a local
    Ollama endpoint works without a key).  For Claude Code it means the CLI
    is installed — there is no key to hold.  The check stays a PATH lookup:
    this runs on button clicks, and running the binary to find out would
    put a second or two into every one of them.
    """
    cfg = cfg or get_config()
    if not cfg['model']:
        return False
    if cfg['provider'] == 'claude_code':
        from app.core import claude_locator
        return claude_locator.resolve() is not None
    return bool(cfg['api_key'] or cfg['base_url'])


def not_configured_error(cfg: dict | None = None) -> 'LLMError':
    """The right thing to tell someone whose AI features are switched off.

    Provider-specific on purpose: telling a Claude Code user to set an API
    key sends them looking for something that does not exist, when what
    they need is to install the CLI.
    """
    cfg = cfg or get_config()
    if cfg.get('provider') == 'claude_code':
        if not cfg.get('model'):
            return LLMError('No model set — put "sonnet" (or another model) '
                            'in Settings to enable the AI features.')
        from app.core import claude_locator
        return LLMError(claude_locator.INSTALL_HINT)
    return LLMError('LLM not configured — set model and API key/base URL '
                    'in Settings.')


def _post_json(url: str, headers: dict, payload: dict,
               timeout: float) -> dict:
    """POST JSON, return decoded JSON.  The single transport chokepoint."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = ''
        try:
            body = exc.read().decode(errors='replace')[:300]
        except Exception:
            pass
        raise LLMError(f'HTTP {exc.code} from {url}: {body}') from exc
    except urllib.error.URLError as exc:
        raise LLMError(f'cannot reach {url}: {exc.reason}') from exc
    except (TimeoutError, OSError) as exc:
        raise LLMError(f'request to {url} failed: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise LLMError(f'non-JSON response from {url}') from exc


#: Flags that turn the CLI into a text-completion endpoint instead of a
#: coding agent loose on the user's machine.  Every one is load-bearing:
#:
#: * --restricted drops the tools that run commands or code, and WebFetch.
#: * --disallowed-tools takes away the file tools that remain, so a reply
#:   cannot read or rewrite anything even if the model decides to try.
#: * --setting-sources '' and --strict-mcp-config keep the user's *own*
#:   CLAUDE.md, hooks and MCP servers out of a transistor-sizing prompt.
#:   Their project instructions have no business steering this, and some
#:   of them spawn processes of their own.
#: * --system-prompt (passed separately) replaces the coding-agent persona
#:   rather than appending to it.
#:
#: Measured against claude 2.1.270.  Not passing --dangerously-skip-
#: permissions or --permission-mode bypassPermissions is the other half:
#: with neither, a tool that wants permission is denied rather than
#: prompting a user who is looking at a different window entirely.
_CLI_SAFE_FLAGS = (
    '--restricted',
    '--setting-sources', '',
    '--strict-mcp-config',
    '--disallowed-tools',
    'Read,Write,Edit,MultiEdit,NotebookEdit,Glob,Grep,WebSearch,WebFetch,'
    'Task,Agent,TodoWrite,Skill,SlashCommand,Bash,BashOutput,KillShell',
)

#: The CLI is a whole agent starting up, not a socket, and the calls this
#: app makes are not small.  Measured 2026-09-14 on amp_hoilee_affc — a
#: 7.4 kB prompt asking for 4 candidate sizings over 33 variables, which is
#: an ordinary round of the LLM algorithm, not a worst case:
#:
#:     with a JSON schema     88 s
#:     without one           112 s
#:
#: chat()'s own default is 120 s, an HTTP-shaped number.  Left at that, a
#: round on any wide circuit times out, retries (another two minutes), and
#: then falls back to Sobol — so the LLM algorithm would quietly stop being
#: the LLM algorithm.  The floor only ever raises a caller's timeout; a
#: five-second call still returns in five seconds.
CLI_MIN_TIMEOUT = 300.0

#: Rough seconds per guided round — the LLM call itself, not the
#: simulations it triggers — used only to keep the Sizing tab's time
#: estimate from being wrong by an order of magnitude.  The claude_code
#: figure is the measurement above; the default is a deliberately loose
#: stand-in for the HTTP providers, which have not been measured here.
ROUND_SECONDS = {'claude_code': 100.0}
DEFAULT_ROUND_SECONDS = 15.0


def round_seconds(cfg: dict | None = None) -> float:
    """Seconds one LLM-guided round costs before any ngspice runs."""
    cfg = cfg or get_config()
    return ROUND_SECONDS.get(cfg.get('provider'), DEFAULT_ROUND_SECONDS)


def _as_prompt(messages: list[dict]) -> str:
    """Flatten a chat history into one prompt.

    Claude Code takes a single prompt, not a message array.  That is no
    loss: `chat()` is stateless and the HTTP providers are re-sent the
    whole history on every call too, so this is the same conversation by
    another spelling.  The CLI's own --resume would be faster, but it
    would make chat() stateful, and every caller here rebuilds the history
    itself (see llm_sizing.run_loop).
    """
    out = []
    for m in messages:
        role = 'Assistant' if m.get('role') == 'assistant' else 'User'
        out.append(f"{role}: {m.get('content', '')}")
    return '\n\n'.join(out)


def _run_cli(argv: list[str], prompt: str, timeout: float) -> dict:
    """Run the CLI and return its decoded JSON.  The chokepoint tests fake.

    Runs in an empty scratch directory: the file tools are disallowed
    above, and this makes sure there is nothing to reach even if that ever
    stops being true.
    """
    from app.core import claude_locator
    with tempfile.TemporaryDirectory(prefix='analog-llm-') as cwd:
        try:
            r = subprocess.run(argv, input=prompt, capture_output=True,
                               text=True, timeout=timeout, cwd=cwd,
                               **claude_locator._no_window())
        except subprocess.TimeoutExpired as exc:
            raise LLMError(
                f'Claude Code did not answer within {timeout:.0f}s') from exc
        except OSError as exc:
            raise LLMError(f'could not run Claude Code: {exc}') from exc
    if not (r.stdout or '').strip():
        err = (r.stderr or '').strip().splitlines()
        raise LLMError('Claude Code produced no output'
                       + (f' (exit {r.returncode}): {err[-1][:200]}'
                          if err else f' (exit {r.returncode})'))
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        raise LLMError('Claude Code returned non-JSON output: '
                       f'{r.stdout[:200]!r}') from exc


def _chat_claude_code(messages: list[dict], system: str | None,
                      timeout: float, cfg: dict,
                      schema: dict | None = None) -> str:
    """One completion through the locally installed Claude Code CLI.

    This is the subscription path: the CLI uses the login the user already
    has, so there is no API key to store or leak.  `max_tokens` has no
    equivalent flag and is ignored — the CLI's own limit applies.

    A `schema` becomes --json-schema, which the CLI enforces at decode
    time: the reply comes back as bare JSON with no prose and no ``` fence.
    It goes on the command line, so it must stay small — the sizing schema
    for the widest circuit (56 variables) is ~7 kB against Windows' ~32 kB
    argv limit, and the prompt itself travels on stdin.
    """
    from app.core import claude_locator
    exe = claude_locator.resolve()
    if exe is None:
        raise LLMError(claude_locator.INSTALL_HINT)
    argv = [exe, '-p', '--output-format', 'json',
            '--model', cfg['model'],
            # a fresh id every call: without one the CLI can join a session
            # it inherits from the environment (it does when Analog Studio
            # is launched from inside a Claude Code session)
            '--session-id', str(uuid.uuid4()),
            '--system-prompt', system or 'You are a helpful assistant.',
            *_CLI_SAFE_FLAGS]
    if schema is not None:
        argv += ['--json-schema', json.dumps(schema)]
    data = _run_cli(argv, _as_prompt(messages),
                    max(timeout, CLI_MIN_TIMEOUT))
    if data.get('is_error'):
        raise LLMError('Claude Code reported an error: '
                       f"{str(data.get('result'))[:300]}")
    result = data.get('result')
    if not isinstance(result, str):
        raise LLMError(f'unexpected Claude Code reply: {str(data)[:200]}')
    denials = data.get('permission_denials') or []
    if denials:
        # not fatal — the answer still came back — but it means the model
        # tried to use a tool, which is worth seeing in the log panel
        print(f'claude code: {len(denials)} tool use(s) denied')
    return result


def chat(messages: list[dict], system: str | None = None,
         timeout: float = 120.0, max_tokens: int = 2048,
         cfg: dict | None = None, schema: dict | None = None) -> str:
    """One chat completion.  messages: [{'role': 'user'|'assistant',
    'content': str}, ...] (oldest first).  Returns the reply text.

    `schema` is a JSON Schema the reply should conform to.  It is a
    **request, not a guarantee**: a provider that can enforce it does, and
    one that cannot ignores it silently.  Callers must therefore keep
    parsing defensively — `extract_json` still has to work — because the
    same code runs against every provider.  Today only Claude Code
    enforces it; the HTTP providers have their own mechanisms
    (response_format, tool use) and can be taught later without any caller
    changing.
    """
    cfg = cfg or get_config()
    if not configured(cfg):
        raise not_configured_error(cfg)
    if cfg['provider'] == 'claude_code':
        return _chat_claude_code(messages, system, timeout, cfg, schema)
    base = (cfg['base_url'] or DEFAULT_BASE[cfg['provider']]).rstrip('/')
    if cfg['provider'] == 'anthropic':
        data = _post_json(
            f'{base}/v1/messages',
            {'x-api-key': cfg['api_key'],
             'anthropic-version': ANTHROPIC_VERSION},
            {'model': cfg['model'], 'max_tokens': max_tokens,
             'messages': messages,
             **({'system': system} if system else {})},
            timeout)
        try:
            return ''.join(b.get('text', '') for b in data['content']
                           if b.get('type') == 'text')
        except (KeyError, TypeError) as exc:
            raise LLMError(f'unexpected Anthropic reply: {data}') from exc
    # OpenAI-compatible (OpenAI / DeepSeek / Qwen / Ollama / vLLM ...)
    full = ([{'role': 'system', 'content': system}] if system else []) \
        + messages
    headers = {}
    if cfg['api_key']:
        headers['Authorization'] = f"Bearer {cfg['api_key']}"
    data = _post_json(f'{base}/chat/completions', headers,
                      {'model': cfg['model'], 'messages': full,
                       'max_tokens': max_tokens},
                      timeout)
    try:
        return data['choices'][0]['message']['content'] or ''
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f'unexpected reply shape: {data}') from exc


def test_connection(cfg: dict | None = None) -> str:
    """Tiny round-trip; returns a human-readable success line."""
    cfg = cfg or get_config()
    reply = chat([{'role': 'user', 'content': 'Reply with exactly: OK'}],
                 timeout=15.0, max_tokens=8, cfg=cfg)
    return f"{cfg['model']} responded: {reply.strip()[:60]}"


def extract_json(text: str):
    """Best-effort JSON extraction from an LLM reply: direct parse, then
    fenced ```json blocks, then the first balanced {...} or [...] span.
    Raises LLMError if nothing parses."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if '```' in text:
        for chunk in text.split('```')[1::2]:      # fenced blocks
            chunk = chunk.strip()
            if chunk.startswith('json'):
                chunk = chunk[4:].strip()
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                continue
    for opener, closer in (('{', '}'), ('[', ']')):
        start = text.find(opener)
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == opener:
                    depth += 1
                elif text[i] == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find(opener, start + 1)
    raise LLMError(f'no JSON found in LLM reply: {text[:200]!r}')
