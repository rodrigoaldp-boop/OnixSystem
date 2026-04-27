"""Endpoints de dashboard e relatorios."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.schemas.movimentacao import MovimentacaoOut
from sga_financeiro.services.relatorio_service import fluxo_caixa, resumo_dashboard, total_por_centro_custos, total_por_parte

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("")
def dashboard(db: Session = Depends(get_db)) -> dict:
    dados = resumo_dashboard(db)
    dados["ultimos_lancamentos"] = [MovimentacaoOut.model_validate(item).model_dump() for item in dados["ultimos_lancamentos"]]
    return dados


@router.get("/totais/centros-custos")
def totais_centros_custos(db: Session = Depends(get_db)) -> list[dict]:
    return total_por_centro_custos(db)


@router.get("/totais/partes")
def totais_partes(db: Session = Depends(get_db)) -> dict:
    return total_por_parte(db)


@router.get("/fluxo-caixa")
def relatorio_fluxo_caixa(data_inicio: date, data_fim: date, db: Session = Depends(get_db)) -> dict:
    return fluxo_caixa(db, data_inicio, data_fim)
