"""Minimal LLM chat client — OpenAI-compatible and Anthropic protocols.

Standard-library only (urllib): the frozen bundles gain no dependency.
Configuration lives in QSettings (same pattern as ngspice_locator):
provider / base URL / API key / model; an empty model disables every AI
feature in the GUI.  All HTTP goes through the single module-level
``_post_json`` — tests monkeypatch exactly that.
"""

import json
import os
import urllib.error
import urllib.request

PROVIDERS = ('openai', 'anthropic')

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
    """AI features need a model plus either a key or a custom endpoint
    (a local Ollama endpoint works without a key)."""
    cfg = cfg or get_config()
    return bool(cfg['model']) and bool(cfg['api_key'] or cfg['base_url'])


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


def chat(messages: list[dict], system: str | None = None,
         timeout: float = 120.0, max_tokens: int = 2048,
         cfg: dict | None = None) -> str:
    """One chat completion.  messages: [{'role': 'user'|'assistant',
    'content': str}, ...] (oldest first).  Returns the reply text."""
    cfg = cfg or get_config()
    if not configured(cfg):
        raise LLMError('LLM not configured — set model and API key/base '
                       'URL in Settings.')
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
