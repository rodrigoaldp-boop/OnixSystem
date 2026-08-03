"""Historico detalhado e extrato imprimivel de divida (contas a receber)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from sga_financeiro.models.conta_receber import ContaReceber, StatusContaReceber
from sga_financeiro.services.encargos_atraso_service import calcular_encargos_da_conta_receber

_SCHEMA_OK = False


def _q2(v: Any) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def garantir_schema_recebimento_eventos(db: Session) -> None:
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS conta_receber_recebimento_eventos (
                id SERIAL PRIMARY KEY,
                conta_receber_id INTEGER NOT NULL REFERENCES contas_receber(id) ON DELETE CASCADE,
                tipo VARCHAR(20) NOT NULL,
                data_evento DATE NOT NULL,
                criado_em TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                valor_recebido NUMERIC(14, 2) NOT NULL,
                abate_principal NUMERIC(14, 2) NOT NULL DEFAULT 0,
                abate_juros NUMERIC(14, 2) NOT NULL DEFAULT 0,
                abate_multa NUMERIC(14, 2) NOT NULL DEFAULT 0,
                principal_antes NUMERIC(14, 2) NOT NULL,
                principal_depois NUMERIC(14, 2) NOT NULL,
                multa_antes NUMERIC(14, 2) NOT NULL,
                multa_depois NUMERIC(14, 2) NOT NULL,
                juros_antes NUMERIC(14, 2) NOT NULL,
                juros_depois NUMERIC(14, 2) NOT NULL,
                total_antes NUMERIC(14, 2) NOT NULL,
                total_depois NUMERIC(14, 2) NOT NULL,
                dias_atraso INTEGER NOT NULL DEFAULT 0,
                conta_destino_id INTEGER NULL,
                movimentacao_ref VARCHAR(120) NULL,
                observacao TEXT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_cr_rec_eventos_conta
            ON conta_receber_recebimento_eventos (conta_receber_id, id)
            """
        )
    )
    db.commit()
    _SCHEMA_OK = True


def registrar_evento_recebimento(
    db: Session,
    *,
    conta: ContaReceber,
    tipo: str,
    data_evento: date,
    valor_recebido: Decimal,
    abate_principal: Decimal,
    abate_juros: Decimal,
    abate_multa: Decimal,
    principal_antes: Decimal,
    principal_depois: Decimal,
    multa_antes: Decimal,
    multa_depois: Decimal,
    juros_antes: Decimal,
    juros_depois: Decimal,
    total_antes: Decimal,
    total_depois: Decimal,
    dias_atraso: int,
    conta_destino_id: int | None,
    movimentacao_ref: str | None,
    observacao: str | None,
) -> None:
    garantir_schema_recebimento_eventos(db)
    db.execute(
        text(
            """
            INSERT INTO conta_receber_recebimento_eventos (
                conta_receber_id, tipo, data_evento, valor_recebido,
                abate_principal, abate_juros, abate_multa,
                principal_antes, principal_depois,
                multa_antes, multa_depois,
                juros_antes, juros_depois,
                total_antes, total_depois,
                dias_atraso, conta_destino_id, movimentacao_ref, observacao
            ) VALUES (
                :cid, :tipo, :data_evento, :valor_recebido,
                :abate_principal, :abate_juros, :abate_multa,
                :principal_antes, :principal_depois,
                :multa_antes, :multa_depois,
                :juros_antes, :juros_depois,
                :total_antes, :total_depois,
                :dias_atraso, :conta_destino_id, :movimentacao_ref, :observacao
            )
            """
        ),
        {
            "cid": int(conta.id),
            "tipo": str(tipo or "")[:20],
            "data_evento": data_evento,
            "valor_recebido": _q2(valor_recebido),
            "abate_principal": _q2(abate_principal),
            "abate_juros": _q2(abate_juros),
            "abate_multa": _q2(abate_multa),
            "principal_antes": _q2(principal_antes),
            "principal_depois": _q2(principal_depois),
            "multa_antes": _q2(multa_antes),
            "multa_depois": _q2(multa_depois),
            "juros_antes": _q2(juros_antes),
            "juros_depois": _q2(juros_depois),
            "total_antes": _q2(total_antes),
            "total_depois": _q2(total_depois),
            "dias_atraso": int(dias_atraso or 0),
            "conta_destino_id": int(conta_destino_id) if conta_destino_id else None,
            "movimentacao_ref": (movimentacao_ref or None),
            "observacao": (observacao or None),
        },
    )


def _nome_cliente(db: Session, conta: ContaReceber) -> str:
    try:
        from sga_financeiro.services.documentos_email_service import _nome_cliente_documento

        if conta.cliente_id:
            return str(_nome_cliente_documento(db, int(conta.cliente_id)) or "").strip()
    except Exception:
        pass
    return ""


def _situacao_atual(db: Session, conta: ContaReceber, *, ref: date | None = None) -> dict[str, Any]:
    hoje = ref or date.today()
    if conta.status == StatusContaReceber.RECEBIDO:
        return {
            "tipo": "atual",
            "rotulo": "Conta quitada",
            "data_referencia": hoje.isoformat(),
            "principal": _q2(0),
            "multa": _q2(0),
            "juros": _q2(0),
            "total": _q2(0),
            "dias_atraso": 0,
            "status": str(conta.status.value if hasattr(conta.status, "value") else conta.status),
            "data_recebimento": conta.data_recebimento.isoformat() if conta.data_recebimento else None,
        }
    enc = calcular_encargos_da_conta_receber(conta, data_recebimento=hoje)
    return {
        "tipo": "atual",
        "rotulo": "Situacao atual da divida",
        "data_referencia": hoje.isoformat(),
        "principal": _q2(enc["valor_principal"]),
        "multa": _q2(enc["multa"]),
        "juros": _q2(enc["juros"]),
        "total": _q2(enc["total_devido"]),
        "dias_atraso": int(enc.get("dias_atraso") or 0),
        "status": str(conta.status.value if hasattr(conta.status, "value") else conta.status),
        "valor_original": _q2(getattr(conta, "valor_original", None) or conta.valor or 0),
        "multa_fixada": bool(getattr(conta, "multa_fixada", None) is not None),
        "juros_acumulados": _q2(getattr(conta, "juros_acumulados", None) or 0),
        "juros_apos_data": (
            conta.juros_apos_data.isoformat()
            if getattr(conta, "juros_apos_data", None)
            else None
        ),
        "data_recebimento": None,
    }


def montar_extrato_divida(db: Session, conta_id: int) -> dict[str, Any]:
    garantir_schema_recebimento_eventos(db)
    conta = db.get(ContaReceber, int(conta_id))
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")

    rows = db.execute(
        text(
            """
            SELECT id, tipo, data_evento, criado_em, valor_recebido,
                   abate_principal, abate_juros, abate_multa,
                   principal_antes, principal_depois,
                   multa_antes, multa_depois,
                   juros_antes, juros_depois,
                   total_antes, total_depois,
                   dias_atraso, conta_destino_id, movimentacao_ref, observacao
            FROM conta_receber_recebimento_eventos
            WHERE conta_receber_id = :cid
            ORDER BY id ASC
            """
        ),
        {"cid": int(conta_id)},
    ).mappings().all()

    eventos: list[dict[str, Any]] = []
    for r in rows:
        tipo = str(r["tipo"] or "")
        eventos.append(
            {
                "id": int(r["id"]),
                "tipo": tipo,
                "rotulo": "Recebimento parcial" if tipo == "parcial" else (
                    "Recebimento total / quitacao" if tipo == "total" else tipo
                ),
                "data_evento": r["data_evento"].isoformat() if r["data_evento"] else None,
                "criado_em": r["criado_em"].isoformat(sep=" ", timespec="seconds") if r["criado_em"] else None,
                "valor_recebido": _q2(r["valor_recebido"]),
                "abate_principal": _q2(r["abate_principal"]),
                "abate_juros": _q2(r["abate_juros"]),
                "abate_multa": _q2(r["abate_multa"]),
                "principal_antes": _q2(r["principal_antes"]),
                "principal_depois": _q2(r["principal_depois"]),
                "multa_antes": _q2(r["multa_antes"]),
                "multa_depois": _q2(r["multa_depois"]),
                "juros_antes": _q2(r["juros_antes"]),
                "juros_depois": _q2(r["juros_depois"]),
                "total_antes": _q2(r["total_antes"]),
                "total_depois": _q2(r["total_depois"]),
                "dias_atraso": int(r["dias_atraso"] or 0),
                "conta_destino_id": int(r["conta_destino_id"]) if r["conta_destino_id"] else None,
                "movimentacao_ref": r["movimentacao_ref"],
                "observacao": r["observacao"],
            }
        )

    atual = _situacao_atual(db, conta)
    total_recebido = sum((Decimal(e["valor_recebido"]) for e in eventos), Decimal("0")).quantize(Decimal("0.01"))

    return {
        "conta": {
            "id": int(conta.id),
            "descricao": str(conta.descricao or ""),
            "cliente_id": int(conta.cliente_id) if conta.cliente_id else None,
            "cliente_nome": _nome_cliente(db, conta),
            "data_vencimento": conta.data_vencimento.isoformat() if conta.data_vencimento else None,
            "status": str(conta.status.value if hasattr(conta.status, "value") else conta.status),
            "valor_atual": _q2(conta.valor),
            "valor_original": _q2(getattr(conta, "valor_original", None) or conta.valor or 0),
            "venda_id": int(conta.venda_id) if conta.venda_id else None,
        },
        "gerado_em": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "total_recebido": total_recebido,
        "eventos": eventos,
        "situacao_atual": atual,
        "tem_historico": bool(eventos),
    }
