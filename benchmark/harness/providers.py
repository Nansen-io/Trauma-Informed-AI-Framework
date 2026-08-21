"""Model provider adapters. Each exposes complete(system, messages, temperature, max_tokens, images=None) -> str.

messages: list of {"role": "user"|"assistant", "content": str}. images: list of PNG file paths attached to the
final user turn (used for D006). Keys are read from the environment variables named in config.env_keys.
"""
import base64, json, os, re, time

def _retry(fn, tries=5):
    for i in range(tries):
        try:
            return fn()
        except (TypeError, KeyError, ValueError):
            raise  # programming or configuration errors are not transient
        except Exception as e:  # noqa
            if i == tries - 1:
                raise
            time.sleep(2 ** i)

class Anthropic:
    def __init__(self, model, key_env="ANTHROPIC_API_KEY"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=os.environ[key_env]); self.model = model
    def complete(self, system, messages, temperature=0.0, max_tokens=1200, images=None):
        msgs = [dict(m) for m in messages]
        if images:
            parts = [{"type": "text", "text": msgs[-1]["content"]}]
            for p in images:
                parts.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(open(p, "rb").read()).decode()}})
            msgs[-1]["content"] = parts
        def go():
            kw = dict(model=self.model, system=system or "You are a helpful assistant.", messages=msgs, max_tokens=max_tokens)
            try:
                r = self.client.messages.create(temperature=temperature, **kw)
            except TypeError:  # SDK or model without a temperature parameter: run at the model default and record it
                self.sampling_note = "temperature parameter not accepted; model default used"
                r = self.client.messages.create(**kw)
            return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return _retry(go)

class OpenAI:
    def __init__(self, model, key_env="OPENAI_API_KEY", base_url=None):
        import openai
        self.client = openai.OpenAI(api_key=os.environ[key_env], base_url=base_url); self.model = model
    def complete(self, system, messages, temperature=0.0, max_tokens=1200, images=None):
        msgs = ([{"role": "system", "content": system}] if system else []) + [dict(m) for m in messages]
        if not images and not msgs:
            msgs = [{"role": "user", "content": ""}]
        if images:
            parts = [{"type": "text", "text": msgs[-1]["content"]}]
            for p in images:
                parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()}})
            msgs[-1]["content"] = parts
        def go():
            kw = dict(model=self.model, messages=msgs, max_completion_tokens=max_tokens)
            try:
                r = self.client.chat.completions.create(temperature=temperature, **kw)
            except Exception as e:
                msg = str(e)
                if "max_completion_tokens" in msg or "max_tokens" in msg:
                    kw = dict(model=self.model, messages=msgs, max_tokens=max_tokens)
                if "temperature" in msg or "max_completion_tokens" in msg or "max_tokens" in msg:  # some endpoints reject parameters
                    r = self.client.chat.completions.create(**kw)
                else:
                    raise
            return r.choices[0].message.content or ""
        return _retry(go)

class Google:
    def __init__(self, model, key_env="GOOGLE_API_KEY"):
        from google import genai
        self.client = genai.Client(api_key=os.environ[key_env]); self.model = model
    def complete(self, system, messages, temperature=0.0, max_tokens=1200, images=None):
        from google.genai import types
        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
        if images:
            for p in images:
                contents[-1].parts.append(types.Part.from_bytes(data=open(p, "rb").read(), mime_type="image/png"))
        def go():
            r = self.client.models.generate_content(model=self.model, contents=contents,
                config=types.GenerateContentConfig(system_instruction=system or None, temperature=temperature, max_output_tokens=max_tokens))
            return r.text or ""
        return _retry(go)

class Http:
    """Generic adapter for a deployed product API (e.g. the 'joliro' entry in config)."""
    def __init__(self, cfg):
        import requests
        self.requests = requests; self.cfg = cfg
    def _sub(self, obj, ctx):
        if isinstance(obj, str):
            for k, v in ctx.items():
                if obj == "${%s}" % k:
                    return v
            return re.sub(r"\$\{(\w+)\}", lambda m: str(ctx.get(m.group(1), os.environ.get(m.group(1), ""))), obj)
        if isinstance(obj, dict):
            return {k: self._sub(v, ctx) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._sub(v, ctx) for v in obj]
        return obj
    def complete(self, system, messages, temperature=0.0, max_tokens=1200, images=None):
        ctx = {"messages": messages, "system": system, "prompt": messages[-1]["content"]}
        body = self._sub(self.cfg.get("body_template", {"messages": "${messages}"}), ctx)
        headers = self._sub(self.cfg.get("headers", {}), {})
        def go():
            r = self.requests.post(self.cfg["url"], headers=headers, json=body, timeout=120); r.raise_for_status()
            out = r.json()
            for part in self.cfg.get("response_path", "text").split("."):
                out = out[int(part)] if isinstance(out, list) else out[part]
            return str(out)
        return _retry(go)

def make(cfg, env_keys):
    p = cfg["provider"]
    if p == "anthropic":
        return Anthropic(cfg["model"], cfg.get("key_env") or env_keys.get("anthropic", "ANTHROPIC_API_KEY"))
    if p == "openai":
        return OpenAI(cfg["model"], cfg.get("key_env") or env_keys.get("openai", "OPENAI_API_KEY"), cfg.get("base_url"))
    if p == "xai":
        return OpenAI(cfg["model"], cfg.get("key_env") or env_keys.get("xai", "XAI_API_KEY"), cfg.get("base_url") or "https://api.x.ai/v1")
    if p == "groq":
        return OpenAI(cfg["model"], cfg.get("key_env") or env_keys.get("groq", "GROQ_API_KEY"), cfg.get("base_url") or "https://api.groq.com/openai/v1")
    if p == "google":
        return Google(cfg["model"], env_keys.get("google", "GOOGLE_API_KEY"))
    if p == "http":
        return Http(cfg)
    raise ValueError(p)
