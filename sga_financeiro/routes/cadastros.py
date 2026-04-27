"""Endpoints de cadastro geral."""

import json
import urllib.error
import urllib.request
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.cadastro_geral import CadastroGeral
from sga_financeiro.schemas.cadastro_geral import CadastroGeralCreate, CadastroGeralOut, CadastroGeralUpdate, CnpjConsultaOut

router = APIRouter(prefix="/cadastros-gerais", tags=["Cadastros Gerais"])


def _normalizar_cnpj(cnpj: str) -> str:
    return "".join(c for c in cnpj if c.isdigit())


def _cnpj_em_uso(db: Session, cnpj: str, contexto: str, ignore_id: Optional[int] = None) -> bool:
    cnpj_limpo = _normalizar_cnpj(cnpj)
    registros = db.query(CadastroGeral).filter(CadastroGeral.contexto == contexto).all()
    for registro in registros:
        if ignore_id is not None and registro.id == ignore_id:
            continue
        if _normalizar_cnpj(registro.cnpj) == cnpj_limpo:
            return True
    return False


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OnixSystem/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


@router.get("", response_model=list[CadastroGeralOut])
def listar(contexto: str = Query("pessoas"), db: Session = Depends(get_db)) -> list[CadastroGeral]:
    query = db.query(CadastroGeral)
    if contexto != "todos":
        query = query.filter(CadastroGeral.contexto == contexto)
    return query.order_by(CadastroGeral.id.desc()).all()


@router.get("/buscar", response_model=list[CadastroGeralOut])
def buscar_por_texto(q: str = Query(..., min_length=2), contexto: str = Query("pessoas"), db: Session = Depends(get_db)) -> list[CadastroGeral]:
    termo = q.strip()
    query = db.query(CadastroGeral)
    if contexto != "todos":
        query = query.filter(CadastroGeral.contexto == contexto)
    return (
        query.filter(
            or_(
                CadastroGeral.razao_social.ilike(f"%{termo}%"),
                CadastroGeral.nome_fantasia.ilike(f"%{termo}%"),
                CadastroGeral.cnpj.ilike(f"%{termo}%"),
            )
        )
        .order_by(CadastroGeral.id.desc())
        .all()
    )


@router.get("/consultar-cnpj/{cnpj}", response_model=CnpjConsultaOut)
def consultar_cnpj(cnpj: str) -> CnpjConsultaOut:
    """Consulta CNPJ em base publica (SEFAZ/Receita via integracao aberta)."""
    cnpj_limpo = _normalizar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CNPJ invalido.")

    data: Optional[dict] = None
    # Fonte 1
    try:
        data = _fetch_json(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CNPJ nao encontrado.") from exc
    except Exception:
        data = None

    # Fonte 2 (fallback)
    if not data:
        try:
            data = _fetch_json(f"https://www.receitaws.com.br/v1/cnpj/{cnpj_limpo}")
            if data.get("status") == "ERROR":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=data.get("message", "CNPJ nao encontrado."))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Nao foi possivel consultar CNPJ agora. Tente novamente em instantes.",
            ) from exc

    rua = data.get("logradouro", "") or ""
    numero = data.get("numero", "") or ""
    bairro = data.get("bairro", "") or ""
    cidade = data.get("municipio", "") or data.get("cidade", "") or ""
    uf = data.get("uf", "") or ""
    endereco = ", ".join(part for part in [rua, numero] if part)
    if bairro:
        endereco = f"{endereco} - {bairro}" if endereco else bairro
    if cidade or uf:
        cidade_uf = "/".join(part for part in [cidade, uf] if part)
        endereco = f"{endereco} - {cidade_uf}" if endereco else cidade_uf

    return CnpjConsultaOut(
        cnpj=cnpj_limpo,
        razao_social=data.get("razao_social", "") or data.get("nome", ""),
        cidade_uf="/".join(part for part in [cidade, uf] if part) or None,
        nome_fantasia=data.get("nome_fantasia") or data.get("fantasia"),
        endereco=endereco,
        telefone=data.get("ddd_telefone_1") or data.get("telefone"),
        cep=data.get("cep"),
    )


@router.post("", response_model=CadastroGeralOut, status_code=status.HTTP_201_CREATED)
def criar(payload: CadastroGeralCreate, db: Session = Depends(get_db)) -> CadastroGeral:
    data = payload.model_dump()
    data["cnpj"] = _normalizar_cnpj(data["cnpj"])
    contexto = data.get("contexto", "pessoas")
    if _cnpj_em_uso(db, data["cnpj"], contexto=contexto):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ja existe cadastro com este CNPJ.")

    cadastro = CadastroGeral(**data)
    db.add(cadastro)
    db.commit()
    db.refresh(cadastro)
    return cadastro


@router.put("/{cadastro_id}", response_model=CadastroGeralOut)
def atualizar(cadastro_id: int, payload: CadastroGeralUpdate, db: Session = Depends(get_db)) -> CadastroGeral:
    cadastro = db.get(CadastroGeral, cadastro_id)
    if not cadastro:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cadastro nao encontrado.")
    data = payload.model_dump()
    data["cnpj"] = _normalizar_cnpj(data["cnpj"])
    contexto = data.get("contexto", cadastro.contexto)
    if _cnpj_em_uso(db, data["cnpj"], contexto=contexto, ignore_id=cadastro_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ja existe cadastro com este CNPJ.")

    for campo, valor in data.items():
        setattr(cadastro, campo, valor)
    db.commit()
    db.refresh(cadastro)
    return cadastro


@router.get("/{cadastro_id}", response_model=CadastroGeralOut)
def buscar(cadastro_id: int, db: Session = Depends(get_db)) -> CadastroGeral:
    cadastro = db.get(CadastroGeral, cadastro_id)
    if not cadastro:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cadastro nao encontrado.")
    return cadastro


@router.delete("/{cadastro_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(cadastro_id: int, db: Session = Depends(get_db)) -> None:
    cadastro = db.get(CadastroGeral, cadastro_id)
    if not cadastro:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cadastro nao encontrado.")
    db.delete(cadastro)
    db.commit()
