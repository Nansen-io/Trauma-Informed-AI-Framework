#!/usr/bin/env python3
"""Print the model identifiers each configured provider exposes, and optionally write them into .env as comments
next to each *_MODEL line so the file documents what the key can reach.

Usage: python list_models.py            # print
       python list_models.py --write-env  # also rewrite the nearest .env with '# available: ...' comments
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run import load_dotenv
ENV = load_dotenv()
import openai

PROVIDERS = [("OPENAI", "OPENAI_API_KEY", None), ("XAI", "XAI_API_KEY", "https://api.x.ai/v1"), ("GROQ", "GROQ_API_KEY", "https://api.groq.com/openai/v1")]
found = {}
for name, key, base in PROVIDERS:
    if not os.environ.get(key):
        print(f"{name}: no key"); continue
    try:
        ids = sorted(m.id for m in openai.OpenAI(api_key=os.environ[key], base_url=base).models.list().data)
        found[name] = ids; print(f"{name} ({len(ids)}): {', '.join(ids)}")
    except Exception as e:
        print(f"{name}: {e}")
if os.environ.get("ANTHROPIC_API_KEY"):
    try:
        import anthropic
        ids = sorted(m.id for m in anthropic.Anthropic().models.list().data)
        found["ANTHROPIC"] = ids; print(f"ANTHROPIC ({len(ids)}): {', '.join(ids)}")
    except Exception as e:
        print("ANTHROPIC:", e)

# flag configured models that the provider does not list
for name in found:
    cur = os.environ.get(f"{name}_MODEL")
    if cur and cur not in found[name]:
        print(f"WARNING: {name}_MODEL={cur} is not in the provider's model list")

if "--write-env" in sys.argv and ENV:
    lines = open(ENV, encoding="utf-8").read().splitlines()
    out = []
    for line in lines:
        if line.startswith("# available "):
            continue  # replace old comments
        m = re.match(r"^(\w+)_MODEL=", line)
        if m and m.group(1) in found:
            out.append(f"# available {m.group(1)} models ({len(found[m.group(1)])}): " + ", ".join(found[m.group(1)]))
        out.append(line)
    open(ENV, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"wrote model comments into {ENV}")
