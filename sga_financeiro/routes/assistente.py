"""Rotas do assistente com IA para operar o sistema de forma controlada."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from sga_financeiro.config import settings
from sga_financeiro.database import get_db
from sga_financeiro.models.conta_pagar import ContaPagar, StatusContaPagar
from sga_financeiro.models.fornecedor import Fornecedor
from sga_financeiro.services.assistente_ia_service import pedir_acao, resposta_final

router = APIRouter(prefix="/assistente", tags=["Assistente IA"])


class AssistenteChatIn(BaseModel):
    mensagem: str = Field(min_length=2)
    confirmar_execucao: bool = False


class AssistenteChatOut(BaseModel):
    resposta: str
    acao_executada: Optional[str] = None
    resultado_acao: Optional[dict[str, Any]] = None


def _ferramentas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "listar_contas_pagar_pendentes",
                "description": "Lista contas a pagar pendentes ou vencidas para os proximos dias.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dias": {"type": "integer", "minimum": 1, "maximum": 60},
                        "limite": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "criar_fornecedor",
                "description": "Cria um novo fornecedor no cadastro.",
                "parameters": {
                    "type": "object",
                    "required": ["nome"],
                    "properties": {
                        "nome": {"type": "string"},
                        "cnpj_cpf": {"type": "string"},
                        "email": {"type": "string"},
                        "telefone": {"type": "string"},
                    },
                },
            },
        },
    ]


def _listar_contas_pendentes(db: Session, dias: int = 15, limite: int = 20) -> dict[str, Any]:
    data_limite = date.today() + timedelta(days=dias)
    query = (
        select(ContaPagar)
        .where(ContaPagar.status.in_([StatusContaPagar.PENDENTE, StatusContaPagar.VENCIDO]))
        .where(ContaPagar.data_vencimento <= data_limite)
        .order_by(ContaPagar.data_vencimento.asc())
        .limit(limite)
    )
    rows = db.execute(query).scalars().all()
    itens = [
        {
            "id": c.id,
            "descricao": c.descricao,
            "valor": float(c.valor if isinstance(c.valor, Decimal) else c.valor),
            "vencimento": c.data_vencimento.isoformat(),
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
        }
        for c in rows
    ]
    return {"total": len(itens), "itens": itens}


def _resposta_listagem_contas(dias: int, resultado: dict[str, Any]) -> str:
    total = int(resultado.get("total") or 0)
    itens = resultado.get("itens") or []
    if total <= 0:
        return f"Nao foram encontradas contas a pagar pendentes/vencidas para os proximos {dias} dias."

    linhas = [f"Foram encontradas {total} conta(s) para os proximos {dias} dias:"]
    for item in itens[:10]:
        valor = float(item.get("valor") or 0)
        linhas.append(
            f"- ID {item.get('id')}: {item.get('descricao')} | "
            f"Venc.: {item.get('vencimento')} | Valor: R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
    if total > 10:
        linhas.append(f"... e mais {total - 10} conta(s).")
    return "\n".join(linhas)


def _extrair_dias_da_mensagem(mensagem: str, padrao: int = 15) -> int:
    match = re.search(r"(\d+)\s*dias?", mensagem.lower())
    if not match:
        return padrao
    try:
        valor = int(match.group(1))
    except ValueError:
        return padrao
    return max(1, min(60, valor))


def _fallback_sem_ia(mensagem: str, db: Session) -> Optional[AssistenteChatOut]:
    texto = mensagem.lower()
    if "contas a pagar" in texto or "conta a pagar" in texto:
        dias = _extrair_dias_da_mensagem(mensagem, padrao=15)
        resultado = _listar_contas_pendentes(db, dias=dias, limite=100)
        return AssistenteChatOut(
            resposta=_resposta_listagem_contas(dias=dias, resultado=resultado),
            acao_executada="listar_contas_pagar_pendentes",
            resultado_acao=resultado,
        )
    return None


def _criar_fornecedor(db: Session, args: dict[str, Any], confirmar_execucao: bool) -> dict[str, Any]:
    if not confirmar_execucao:
        return {
            "pendente_confirmacao": True,
            "mensagem": "Acao de escrita bloqueada. Reenvie com confirmar_execucao=true para gravar.",
            "preview": {
                "nome": args.get("nome"),
                "cnpj_cpf": args.get("cnpj_cpf"),
                "email": args.get("email"),
                "telefone": args.get("telefone"),
            },
        }

    nome = str(args.get("nome") or "").strip()
    if not nome:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome do fornecedor obrigatorio.")

    fornecedor = Fornecedor(
        nome=nome,
        cnpj_cpf=(args.get("cnpj_cpf") or None),
        email=(args.get("email") or None),
        telefone=(args.get("telefone") or None),
    )
    db.add(fornecedor)
    db.commit()
    db.refresh(fornecedor)
    return {"id": fornecedor.id, "nome": fornecedor.nome, "status": "criado"}


@router.post("/chat", response_model=AssistenteChatOut)
def chat_assistente(payload: AssistenteChatIn, db: Session = Depends(get_db)) -> AssistenteChatOut:
    """Conversa com IA e executa acoes permitidas no backend."""
    if not settings.AI_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistente IA desativado. Configure AI_ENABLED=true no .env.",
        )
    if not settings.AI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI_API_KEY nao configurada no .env.",
        )

    try:
        primeira_resposta = pedir_acao(payload.mensagem, _ferramentas())
    except RuntimeError as exc:
        fallback = _fallback_sem_ia(payload.mensagem, db)
        if fallback is not None:
            return fallback
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if not primeira_resposta.tool_calls:
        texto = primeira_resposta.content or "Nao foi necessario executar acoes."
        return AssistenteChatOut(resposta=texto)

    chamada = primeira_resposta.tool_calls[0]
    resultado: dict[str, Any]
    texto_deterministico: Optional[str] = None

    if chamada.nome == "listar_contas_pagar_pendentes":
        try:
            dias = int(chamada.argumentos.get("dias", 15))
        except (TypeError, ValueError):
            dias = 15
        try:
            limite = int(chamada.argumentos.get("limite", 20))
        except (TypeError, ValueError):
            limite = 20
        dias = max(1, min(60, dias))
        limite = max(1, min(100, limite))
        resultado = _listar_contas_pendentes(db, dias=dias, limite=limite)
        texto_deterministico = _resposta_listagem_contas(dias=dias, resultado=resultado)
    elif chamada.nome == "criar_fornecedor":
        resultado = _criar_fornecedor(db, chamada.argumentos, payload.confirmar_execucao)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ferramenta nao suportada: {chamada.nome}",
        )

    historico = [
        {
            "role": "assistant",
            "content": primeira_resposta.content or "",
            "tool_calls": [
                {
                    "id": chamada.id,
                    "type": "function",
                    "function": {"name": chamada.nome, "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": chamada.id,
            "content": str(resultado),
        },
    ]

    if texto_deterministico is not None:
        texto_final = texto_deterministico
    else:
        try:
            texto_final = resposta_final(payload.mensagem, historico)
        except RuntimeError:
            texto_final = "Acao processada com sucesso."

    return AssistenteChatOut(
        resposta=texto_final,
        acao_executada=chamada.nome,
        resultado_acao=resultado,
    )
