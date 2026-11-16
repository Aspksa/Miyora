"""Minimal Cloud.ru chat completions with strict request validation."""
from __future__ import annotations
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from app.core import cloudru

MAX_MESSAGES = 30
MAX_CONTENT = 12000

def complete(messages: object) -> dict:
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise cloudru.CloudError("invalid_messages")
    validated = []
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] not in ("user", "assistant")
                or not isinstance(message["content"], str)
                or not 1 <= len(message["content"]) <= MAX_CONTENT):
            raise cloudru.CloudError("invalid_messages")
        validated.append({"role": message["role"], "content": message["content"]})
    if validated[-1]["role"] != "user":
        raise cloudru.CloudError("last_message_must_be_user")
    key = cloudru._read_key()
    model = cloudru._setting()
    if not key:
        raise cloudru.CloudError("api_key_required")
    if not model:
        raise cloudru.CloudError("model_required")
    payload = json.dumps({"model": model, "messages": validated, "stream": False},
                         ensure_ascii=False).encode("utf-8")
    request = Request(cloudru.BASE_URL + "/chat/completions", data=payload, method="POST",
                      headers={"Authorization": "Bearer " + key,
                               "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=65) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise cloudru.CloudError("response_too_large")
        data = json.loads(raw)
    except HTTPError as exc:
        raise cloudru.CloudError("cloudru_auth_failed" if exc.code in (401, 403)
                                 else "cloudru_http_" + str(exc.code)) from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise cloudru.CloudError("cloudru_unavailable") from exc
    try:
        answer = data["choices"][0]["message"]["content"]
        if not isinstance(answer, str):
            raise ValueError("not text")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise cloudru.CloudError("invalid_chat_response") from exc
    return {"message": answer, "model": model}

def stream(messages: object):
    """Yield text deltas from the provider's OpenAI-compatible SSE endpoint."""
    if not isinstance(messages,list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise cloudru.CloudError("invalid_messages")
    validated=[]
    for item in messages:
        if (not isinstance(item,dict) or set(item)!={"role","content"}
            or item["role"] not in ("user","assistant")
            or not isinstance(item["content"],str)
            or not 1 <= len(item["content"]) <= MAX_CONTENT):
            raise cloudru.CloudError("invalid_messages")
        validated.append(item)
    if validated[-1]["role"]!="user": raise cloudru.CloudError("last_message_must_be_user")
    key=cloudru._read_key()
    model=cloudru._setting()
    if not key: raise cloudru.CloudError("api_key_required")
    if not model: raise cloudru.CloudError("model_required")
    request=Request(cloudru.BASE_URL+"/chat/completions",
        data=json.dumps({"model":model,"messages":validated,"stream":True},ensure_ascii=False).encode("utf-8"),
        method="POST",headers={"Authorization":"Bearer "+key,
                               "Content-Type":"application/json","Accept":"text/event-stream"})
    try:
        with urlopen(request,timeout=65) as response:
            for raw in response:
                if len(raw)>1024*1024: raise cloudru.CloudError("response_too_large")
                line=raw.decode("utf-8").strip()
                if not line.startswith("data:"): continue
                payload=line[5:].strip()
                if payload=="[DONE]": break
                event=json.loads(payload)
                delta=event.get("choices",[{}])[0].get("delta",{}).get("content")
                if isinstance(delta,str) and delta: yield delta
    except HTTPError as exc:
        raise cloudru.CloudError("cloudru_auth_failed" if exc.code in (401,403) else "cloudru_http_"+str(exc.code)) from None
    except (URLError,TimeoutError,OSError,ValueError,UnicodeError) as exc:
        raise cloudru.CloudError("cloudru_unavailable") from exc
