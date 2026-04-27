"""Integracao simples com provedores de LLM (OpenAI e Gemini)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from sga_financeiro.config import settings


@dataclass
class ToolCall:
    """Representa um pedido de execucao de ferramenta retornado pelo LLM."""

    id: str
    nome: str
    argumentos: dict[str, Any]


@dataclass
class LlmMessage:
    """Resposta padrao da API de chat completions."""

    content: str
    tool_calls: list[ToolCall]


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=data, method="POST", headers=headers)
    try:
        with request.urlopen(req, timeout=settings.AI_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Falha na API de IA ({exc.code}): {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Falha de rede ao chamar IA: {exc.reason}") from exc


def _post_chat_openai(payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.AI_API_KEY:
        raise RuntimeError("AI_API_KEY nao configurada.")

    url = f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.AI_API_KEY}",
    }
    return _post_json(url=url, payload=payload, headers=headers)


def _post_chat_gemini(payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.AI_API_KEY:
        raise RuntimeError("AI_API_KEY nao configurada.")
    base = settings.AI_BASE_URL.rstrip("/")
    model = settings.AI_MODEL.strip()
    query_key = parse.urlencode({"key": settings.AI_API_KEY})
    url = f"{base}/models/{model}:generateContent?{query_key}"
    headers = {"Content-Type": "application/json"}
    return _post_json(url=url, payload=payload, headers=headers)


def _parse_message_openai(raw: dict[str, Any]) -> LlmMessage:
    choice = (raw.get("choices") or [{}])[0]
    message = choice.get("message") or {}

    tool_calls: list[ToolCall] = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        raw_args = fn.get("arguments") or "{}"
        try:
            parsed_args = json.loads(raw_args)
        except json.JSONDecodeError:
            parsed_args = {}
        tool_calls.append(
            ToolCall(
                id=call.get("id") or "",
                nome=fn.get("name") or "",
                argumentos=parsed_args if isinstance(parsed_args, dict) else {},
            )
        )

    return LlmMessage(content=message.get("content") or "", tool_calls=tool_calls)


def _parse_message_gemini(raw: dict[str, Any]) -> LlmMessage:
    candidates = raw.get("candidates") or []
    if not candidates:
        return LlmMessage(content="", tool_calls=[])
    content = (candidates[0].get("content") or {})
    parts = content.get("parts") or []
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for idx, part in enumerate(parts):
        text = part.get("text")
        if text:
            text_parts.append(text)
        fn_call = part.get("functionCall")
        if fn_call:
            args = fn_call.get("args") or {}
            tool_calls.append(
                ToolCall(
                    id=f"gemini_call_{idx}",
                    nome=fn_call.get("name") or "",
                    argumentos=args if isinstance(args, dict) else {},
                )
            )
    return LlmMessage(content="\n".join(text_parts).strip(), tool_calls=tool_calls)


def _to_gemini_tools(ferramentas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for item in ferramentas:
        fn = item.get("function") or {}
        if fn:
            declarations.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {"type": "object"}),
                }
            )
    return [{"functionDeclarations": declarations}] if declarations else []


def _parse_message(raw: dict[str, Any]) -> LlmMessage:
    provider = settings.AI_PROVIDER.lower().strip()
    if provider == "gemini":
        return _parse_message_gemini(raw)
    return _parse_message_openai(raw)


def _post_chat(payload: dict[str, Any]) -> dict[str, Any]:
    provider = settings.AI_PROVIDER.lower().strip()
    if provider == "gemini":
        return _post_chat_gemini(payload)
    return _post_chat_openai(payload)


def pedir_acao(mensagem_usuario: str, ferramentas: list[dict[str, Any]]) -> LlmMessage:
    """Pede ao modelo uma resposta e possiveis tool calls."""
    system_prompt = (
        "Voce e o assistente do Onix System. "
        "Se precisar executar uma acao no sistema, use apenas as ferramentas disponiveis. "
        "Para escrita em banco, sempre deixe claro que exige confirmacao do usuario."
    )
    provider = settings.AI_PROVIDER.lower().strip()
    if provider == "gemini":
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": mensagem_usuario}]}],
            "generationConfig": {"temperature": 0.2},
            "tools": _to_gemini_tools(ferramentas),
        }
    else:
        payload = {
            "model": settings.AI_MODEL,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": mensagem_usuario},
            ],
            "tools": ferramentas,
            "tool_choice": "auto",
        }
    raw = _post_chat(payload)
    return _parse_message(raw)


def resposta_final(mensagem_usuario: str, historico: list[dict[str, Any]]) -> str:
    """Gera resposta final ao usuario apos a execucao de ferramentas."""
    provider = settings.AI_PROVIDER.lower().strip()
    if provider == "gemini":
        resumo_historico = json.dumps(historico, ensure_ascii=True)
        payload = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": "Responda em portugues de forma objetiva e com proximos passos quando necessario."
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": f"Mensagem original: {mensagem_usuario}\nResultado das ferramentas: {resumo_historico}"
                        }
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.2},
        }
    else:
        payload = {
            "model": settings.AI_MODEL,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": "Responda em portugues de forma objetiva e com proximos passos quando necessario.",
                },
                {"role": "user", "content": mensagem_usuario},
                *historico,
            ],
        }
    raw = _post_chat(payload)
    parsed = _parse_message(raw)
    return parsed.content or "Acao concluida."
