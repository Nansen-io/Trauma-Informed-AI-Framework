"""Model provider adapters. Each exposes complete(system, messages, temperature, max_tokens, images=None) -> (text, finish_reason).

messages: list of {"role": "user"|"assistant", "content": str}. images: list of PNG file paths attached to the
final user turn (used for D006). Keys are read from the environment variables named in config.env_keys.
"""
import base64, json, os, re, time

NON_TRANSIENT = (TypeError, KeyError, ValueError, FileNotFoundError)

def _retry(fn, tries=6):
    """Exponential backoff with jitter, honouring Retry-After; bad requests, bad keys, bad model ids and programming errors are not retried."""
    import random
    for i in range(tries):
        try:
            return fn()
        except NON_TRANSIENT:
            raise
        except Exception as e:  # noqa
            msg = str(e)
            if re.search(r"\b(400|401|403|404)\b|model_not_found|invalid_request|does not exist|authentication", msg, flags=re.I) and "429" not in msg:
                raise
            if i == tries - 1:
                raise
            wait = min(60, (2 ** i) + random.random() * 2)
            m = re.search(r"retry[- ]after[:\s]+(\d+)", msg, flags=re.I)
            if m:
                wait = max(wait, int(m.group(1)))
            time.sleep(wait)

def _b64(p):
    return base64.b64encode(open(p, "rb").read()).decode()

class Anthropic:
    def __init__(self, model, key_env="ANTHROPIC_API_KEY"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=os.environ[key_env]); self.model = model; self.sampling_note = None
    def complete(self, system, messages, temperature=0.0, max_tokens=1200, images=None):
        msgs = [dict(m) for m in messages]
        if images:
            parts = [{"type": "text", "text": msgs[-1]["content"]}]
            for p in images:
                parts.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(p)}})
            msgs[-1]["content"] = parts
        def go():
            kw = dict(model=self.model, system=system or "You are a helpful assistant.", messages=msgs, max_tokens=max_tokens)
            try:
                r = self.client.messages.create(temperature=temperature, **kw)
            except TypeError:  # SDK or model without a temperature parameter
                self.sampling_note = "temperature parameter not accepted; model default used"
                r = self.client.messages.create(**kw)
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            return text, getattr(r, "stop_reason", None)
        return _retry(go)

class OpenAI:
    """OpenAI and any OpenAI-compatible endpoint (xAI, Groq, local servers)."""
    def __init__(self, model, key_env="OPENAI_API_KEY", base_url=None, extra=None):
        import openai
        self.client = openai.OpenAI(api_key=os.environ[key_env], base_url=base_url); self.model = model
        self.extra = dict(extra or {})  # e.g. {"reasoning_effort": "low"} for reasoning models
        self.use_temperature = True; self.token_param = "max_completion_tokens"
    def complete(self, system, messages, temperature=0.0, max_tokens=1200, images=None):
        msgs = ([{"role": "system", "content": system}] if system else []) + [dict(m) for m in messages]
        if images:
            parts = [{"type": "text", "text": msgs[-1]["content"]}]
            for p in images:
                parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(p)}})
            msgs[-1]["content"] = parts
        def call(limit):
            for _ in range(4):  # adapt to what the endpoint accepts, remembering the result for later calls
                kw = dict(model=self.model, messages=msgs, **{self.token_param: limit}, **self.extra)
                if self.use_temperature:
                    kw["temperature"] = temperature
                try:
                    return self.client.chat.completions.create(**kw)
                except Exception as e:
                    msg = str(e)
                    if "429" in msg or "rate" in msg.lower():
                        raise
                    if "max_completion_tokens" in msg and self.token_param == "max_completion_tokens":
                        self.token_param = "max_tokens"; continue
                    if "reasoning" in msg and "reasoning_effort" in self.extra:
                        self.extra.pop("reasoning_effort"); continue
                    if "temperature" in msg and self.use_temperature:
                        self.use_temperature = False; continue
                    raise
            raise RuntimeError("could not find an accepted parameter set for " + self.model)
        def go():
            r = call(max_tokens)
            text = r.choices[0].message.content or ""
            fin = getattr(r.choices[0], "finish_reason", None)
            if not text.strip() and fin == "length":
                r = call(max_tokens * 6)  # reasoning models can spend the whole budget on hidden reasoning
                text = r.choices[0].message.content or ""; fin = getattr(r.choices[0], "finish_reason", None)
            if not text.strip():
                raise ValueError(f"empty completion (finish_reason={fin}); set extra.reasoning_effort or raise max_output_tokens for {self.model}")
            return text, fin
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
            fin = None
            try:
                fin = str(r.candidates[0].finish_reason)
            except Exception:
                pass
            return r.text or "", fin
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
            r = self.requests.post(self.cfg["url"], headers=headers, json=body, timeout=180); r.raise_for_status()
            out = r.json()
            for part in self.cfg.get("response_path", "text").split("."):
                out = out[int(part)] if isinstance(out, list) else out[part]
            return str(out), None
        return _retry(go)

def make(cfg, env_keys):
    p = cfg["provider"]
    if p == "anthropic":
        return Anthropic(cfg["model"], cfg.get("key_env") or env_keys.get("anthropic", "ANTHROPIC_API_KEY"))
    if p == "openai":
        return OpenAI(cfg["model"], cfg.get("key_env") or env_keys.get("openai", "OPENAI_API_KEY"), cfg.get("base_url"), cfg.get("extra"))
    if p == "xai":
        return OpenAI(cfg["model"], cfg.get("key_env") or env_keys.get("xai", "XAI_API_KEY"), cfg.get("base_url") or "https://api.x.ai/v1", cfg.get("extra"))
    if p == "groq":
        return OpenAI(cfg["model"], cfg.get("key_env") or env_keys.get("groq", "GROQ_API_KEY"), cfg.get("base_url") or "https://api.groq.com/openai/v1", cfg.get("extra"))
    if p == "google":
        return Google(cfg["model"], cfg.get("key_env") or env_keys.get("google", "GOOGLE_API_KEY"))
    if p == "http":
        return Http(cfg)
    raise ValueError(p)
