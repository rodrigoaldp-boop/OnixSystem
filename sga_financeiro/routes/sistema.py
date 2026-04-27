"""Rotas utilitarias de sistema (backup e restauracao)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import shutil
import tempfile
import re
import tarfile
import zipfile
import subprocess
import urllib.request
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives.serialization import pkcs12

from sga_financeiro.config import settings
from sga_financeiro.database import engine, get_db
from sga_financeiro.local_config import load_local_config, local_config_path, montar_database_url, save_local_config
from sga_financeiro.services.exclusao_historico_service import excluir_historicos_liquidados

router = APIRouter(prefix="/sistema", tags=["Sistema"])


class ConfirmarExclusaoHistorico(BaseModel):
    confirmar: bool = False


class NfeHomologacaoStatusOut(BaseModel):
    pronto: bool
    ambiente: str
    uf: str
    cnpj_emitente: str
    ie_emitente: str
    certificado: dict[str, Any]
    faltando: list[str]
    autorizacao_implantada: bool = True


class NfeConfigIn(BaseModel):
    enabled: bool = False
    ambiente: str = "homologacao"
    uf: str = "PR"
    cert_path: str = ""
    cert_password: str = ""
    cnpj_emitente: str = ""
    ie_emitente: str = ""
    cnae_principal: str = ""
    cnaes_secundarios: str = ""
    crt: str = "simples"
    serie: int = 1
    cfop_padrao: str = "5102"
    csosn_padrao: str = "0102"
    id_csrt: str = ""
    csrt: str = ""
    cnpj_responsavel_tecnico: str = ""


class NfeConfigOut(BaseModel):
    enabled: bool
    ambiente: str
    uf: str
    cert_path: str
    cert_password: str
    cnpj_emitente: str
    ie_emitente: str
    cnae_principal: str
    cnaes_secundarios: str
    crt: str
    serie: int
    cfop_padrao: str
    csosn_padrao: str
    id_csrt: str
    csrt: str
    cnpj_responsavel_tecnico: str


class NfeUploadCertOut(BaseModel):
    ok: bool
    cert_path: str


class SistemaVersaoOut(BaseModel):
    app: str
    versao: str


class SistemaAtualizacaoCheckOut(BaseModel):
    versao_atual: str
    versao_disponivel: str
    tem_atualizacao: bool
    obrigatoria: bool = False
    changelog: str = ""
    pacote_url: str = ""


class SistemaAtualizacaoAplicarIn(BaseModel):
    versao_alvo: str = ""


class SistemaAtualizacaoRollbackIn(BaseModel):
    atualizacao_id: int


class SistemaBancoConfigIn(BaseModel):
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str


def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D+", "", valor or "")


def _inspecionar_certificado_a1() -> dict[str, Any]:
    cert_path = (settings.NFE_CERT_PATH or "").strip()
    senha = (settings.NFE_CERT_PASSWORD or "").strip()
    if not cert_path:
        return {"ok": False, "erro": "NFE_CERT_PATH nao configurado."}
    path = Path(cert_path)
    if not path.exists():
        return {"ok": False, "erro": f"Arquivo de certificado nao encontrado: {cert_path}"}
    if not senha:
        return {"ok": False, "erro": "NFE_CERT_PASSWORD nao configurado."}
    try:
        blob = path.read_bytes()
        private_key, cert, extras = pkcs12.load_key_and_certificates(blob, senha.encode("utf-8"))
        if not private_key or not cert:
            return {"ok": False, "erro": "Certificado invalido ou sem chave privada."}
        subject = cert.subject.rfc4514_string()
        issuer = cert.issuer.rfc4514_string()
        return {
            "ok": True,
            "arquivo": str(path),
            "subject": subject,
            "issuer": issuer,
            "validade_inicio": cert.not_valid_before.isoformat(),
            "validade_fim": cert.not_valid_after.isoformat(),
            "cadeia_extra_qtd": len(extras or []),
        }
    except Exception as exc:
        return {"ok": False, "erro": f"Falha ao carregar certificado A1: {exc}"}


def _nfe_config_file() -> Path:
    return Path(__file__).resolve().parents[1] / "nfe_config.json"


def _default_nfe_config() -> dict[str, Any]:
    return {
        "enabled": bool(settings.NFE_ENABLED),
        "ambiente": (settings.NFE_AMBIENTE or "homologacao").strip().lower(),
        "uf": (settings.NFE_UF or "PR").strip().upper(),
        "cert_path": (settings.NFE_CERT_PATH or "").strip(),
        "cert_password": (settings.NFE_CERT_PASSWORD or "").strip(),
        "cnpj_emitente": _somente_digitos(settings.NFE_CNPJ_EMITENTE),
        "ie_emitente": (settings.NFE_IE_EMITENTE or "").strip(),
        "cnae_principal": (settings.NFE_CNAE_PRINCIPAL or "").strip(),
        "cnaes_secundarios": (settings.NFE_CNAES_SECUNDARIOS or "").strip(),
        "crt": (settings.NFE_CRT or "simples").strip().lower(),
        "serie": int(settings.NFE_SERIE or 1),
        "cfop_padrao": (settings.NFE_CFOP_PADRAO or "5102").strip(),
        "csosn_padrao": (settings.NFE_CSOSN_PADRAO or "0102").strip(),
        "id_csrt": "",
        "csrt": "",
        "cnpj_responsavel_tecnico": "",
    }


def _load_nfe_config() -> dict[str, Any]:
    path = _nfe_config_file()
    base = _default_nfe_config()
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return base
        base.update({k: raw.get(k, base[k]) for k in base.keys()})
        base["cnpj_emitente"] = _somente_digitos(str(base.get("cnpj_emitente", "")))
        base["uf"] = str(base.get("uf", "PR")).upper()
        base["ambiente"] = str(base.get("ambiente", "homologacao")).lower()
        base["crt"] = str(base.get("crt", "simples")).lower()
        try:
            base["serie"] = int(base.get("serie", 1) or 1)
        except Exception:
            base["serie"] = 1
        return base
    except Exception:
        return base


def _save_nfe_config(cfg: dict[str, Any]) -> None:
    path = _nfe_config_file()
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _nfe_cert_dir() -> Path:
    path = Path(__file__).resolve().parents[1] / "certs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _update_manifest_file() -> Path:
    return Path(__file__).resolve().parents[1] / "update_manifest.json"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _servico_nome() -> str:
    return "onixsystem.service"


def _backup_app_dir() -> Path:
    path = _project_root() / "restore-points" / "app-update-backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_semver(valor: str) -> tuple[int, int, int]:
    raw = (valor or "").strip().lstrip("vV")
    parts = raw.split(".")
    nums: list[int] = []
    for i in range(3):
        try:
            nums.append(int(parts[i]))
        except Exception:
            nums.append(0)
    return (nums[0], nums[1], nums[2])


def _load_update_manifest() -> dict[str, Any]:
    path = _update_manifest_file()
    if not path.exists():
        return {
            "latest_version": settings.APP_VERSION,
            "required": False,
            "changelog": "Sem atualizacoes publicadas ainda.",
            "package_url": "",
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("manifest invalido")
        return {
            "latest_version": str(raw.get("latest_version") or settings.APP_VERSION).strip() or settings.APP_VERSION,
            "required": bool(raw.get("required", False)),
            "changelog": str(raw.get("changelog") or "").strip(),
            "package_url": str(raw.get("package_url") or "").strip(),
        }
    except Exception:
        return {
            "latest_version": settings.APP_VERSION,
            "required": False,
            "changelog": "Falha ao ler manifesto de atualizacoes.",
            "package_url": "",
        }


def _baixar_pacote_atualizacao(url: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("http://") or url.startswith("https://"):
        with urllib.request.urlopen(url, timeout=60) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Falha no download do pacote (HTTP {resp.status}).")
            destino.write_bytes(resp.read())
        return
    origem = Path(url).expanduser().resolve()
    if not origem.exists() or not origem.is_file():
        raise RuntimeError("Pacote de atualizacao nao encontrado no caminho informado.")
    shutil.copy2(origem, destino)


def _snapshot_sga_financeiro(versao_alvo: str) -> Path:
    raiz = _project_root()
    pasta_app = raiz / "sga_financeiro"
    if not pasta_app.exists():
        raise RuntimeError("Pasta da aplicacao nao encontrada para snapshot.")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"snapshot_pre_update_{versao_alvo}_{timestamp}.tar.gz"
    out = _backup_app_dir() / nome
    with tarfile.open(out, "w:gz") as tf:
        tf.add(pasta_app, arcname="sga_financeiro")
    return out


def _extrair_zip_para_temp(pacote: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="onix_update_"))
    with zipfile.ZipFile(pacote, "r") as zf:
        zf.extractall(temp_dir)
    return temp_dir


def _copiar_arvore(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        destino = dst / item.name
        if item.is_dir():
            shutil.copytree(item, destino, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destino)


def _aplicar_pacote_zip(pacote_zip: Path) -> None:
    raiz = _project_root()
    temp_extraido = _extrair_zip_para_temp(pacote_zip)
    try:
        _copiar_arvore(temp_extraido, raiz)
    finally:
        shutil.rmtree(temp_extraido, ignore_errors=True)


def _reiniciar_servico_agendado(segundos: int = 2) -> None:
    servico = _servico_nome()
    atraso = max(0, int(segundos))
    cmd = f"sleep {atraso} && systemctl restart {servico}"
    subprocess.Popen(
        ["bash", "-lc", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _rollback_snapshot(snapshot: Path) -> None:
    raiz = _project_root()
    pasta_app = raiz / "sga_financeiro"
    if pasta_app.exists():
        shutil.rmtree(pasta_app, ignore_errors=True)
    with tarfile.open(snapshot, "r:gz") as tf:
        tf.extractall(raiz)


def _sqlite_db_path() -> Path:
    url = settings.DATABASE_URL.strip()
    if not url.startswith("sqlite:///"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Backup/restauracao automatica disponivel apenas para SQLite neste ambiente.",
        )
    rel = url.replace("sqlite:///", "", 1)
    path = (Path.cwd() / rel).resolve()
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo de banco nao encontrado.")
    return path


def _banco_cfg_saida(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "db_host": str(cfg.get("db_host") or ""),
        "db_port": int(cfg.get("db_port") or 5432),
        "db_name": str(cfg.get("db_name") or ""),
        "db_user": str(cfg.get("db_user") or ""),
        "db_password": "",
        "config_path": str(local_config_path()),
    }


def _testar_conexao_postgres(db_url: str) -> None:
    test_engine = sa_create_engine(
        db_url,
        future=True,
        connect_args={"connect_timeout": 8},
        pool_pre_ping=True,
    )
    try:
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        test_engine.dispose()


def _ajustar_schema_atualizacoes() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sistema_atualizacoes (
                    id INTEGER PRIMARY KEY,
                    iniciado_em TIMESTAMP NOT NULL DEFAULT NOW(),
                    finalizado_em TIMESTAMP NULL,
                    versao_origem VARCHAR(40) NOT NULL,
                    versao_alvo VARCHAR(40) NOT NULL,
                    status VARCHAR(30) NOT NULL,
                    mensagem TEXT NOT NULL DEFAULT '',
                    snapshot_path TEXT NOT NULL DEFAULT '',
                    pacote_url TEXT NOT NULL DEFAULT '',
                    pacote_local TEXT NOT NULL DEFAULT '',
                    rollback_disponivel BOOLEAN NOT NULL DEFAULT FALSE,
                    rollback_executado BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
        )


def _nova_atualizacao_historico(versao_origem: str, versao_alvo: str, pacote_url: str) -> int:
    _ajustar_schema_atualizacoes()
    with engine.begin() as conn:
        next_id = int(conn.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM sistema_atualizacoes")).scalar() or 1)
        conn.execute(
            text(
                """
                INSERT INTO sistema_atualizacoes (
                    id, versao_origem, versao_alvo, status, mensagem, pacote_url
                ) VALUES (
                    :id, :versao_origem, :versao_alvo, :status, :mensagem, :pacote_url
                )
                """
            ),
            {
                "id": next_id,
                "versao_origem": versao_origem,
                "versao_alvo": versao_alvo,
                "status": "iniciada",
                "mensagem": "Atualizacao iniciada.",
                "pacote_url": pacote_url,
            },
        )
    return next_id


def _atualizar_historico(
    atualizacao_id: int,
    status_txt: str,
    mensagem: str,
    *,
    pacote_local: Optional[str] = None,
    snapshot_path: Optional[str] = None,
    rollback_disponivel: Optional[bool] = None,
    rollback_executado: Optional[bool] = None,
    finalizar: bool = False,
) -> None:
    partes = ["status = :status", "mensagem = :mensagem"]
    params: dict[str, Any] = {
        "id": int(atualizacao_id),
        "status": status_txt,
        "mensagem": mensagem,
    }
    if pacote_local is not None:
        partes.append("pacote_local = :pacote_local")
        params["pacote_local"] = pacote_local
    if snapshot_path is not None:
        partes.append("snapshot_path = :snapshot_path")
        params["snapshot_path"] = snapshot_path
    if rollback_disponivel is not None:
        partes.append("rollback_disponivel = :rollback_disponivel")
        params["rollback_disponivel"] = bool(rollback_disponivel)
    if rollback_executado is not None:
        partes.append("rollback_executado = :rollback_executado")
        params["rollback_executado"] = bool(rollback_executado)
    if finalizar:
        partes.append("finalizado_em = NOW()")
    sql = f"UPDATE sistema_atualizacoes SET {', '.join(partes)} WHERE id = :id"
    with engine.begin() as conn:
        conn.execute(text(sql), params)


@router.get("/backup")
def baixar_backup() -> FileResponse:
    """Baixa uma copia do arquivo de banco atual."""
    db_path = _sqlite_db_path()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"backup_onix_system_{timestamp}.db"
    return FileResponse(path=str(db_path), filename=out_name, media_type="application/octet-stream")


@router.post("/restaurar")
def restaurar_backup(arquivo: UploadFile = File(...)) -> dict:
    """Restaura banco SQLite a partir de um arquivo enviado."""
    if not arquivo.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo invalido.")
    if not arquivo.filename.lower().endswith(".db"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Envie um arquivo .db.")

    db_path = _sqlite_db_path()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        temp_path = Path(tmp.name)
        content = arquivo.file.read()
        if not content:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")
        tmp.write(content)

    safety_backup = db_path.with_name(f"{db_path.stem}_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")

    try:
        engine.dispose()
        shutil.copy2(db_path, safety_backup)
        shutil.copy2(temp_path, db_path)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao restaurar backup.") from exc
    finally:
        temp_path.unlink(missing_ok=True)
        arquivo.file.close()

    return {"status": "ok", "mensagem": "Backup restaurado com sucesso.", "arquivo_seguranca": str(safety_backup)}


@router.get("/versao", response_model=SistemaVersaoOut)
def sistema_versao() -> SistemaVersaoOut:
    return SistemaVersaoOut(app=settings.APP_NAME, versao=settings.APP_VERSION)


@router.get("/config-banco")
def sistema_config_banco_get() -> dict[str, Any]:
    cfg = load_local_config()
    return _banco_cfg_saida(cfg)


@router.post("/config-banco/testar")
def sistema_config_banco_testar(payload: SistemaBancoConfigIn) -> dict[str, Any]:
    cfg = payload.model_dump()
    db_url = montar_database_url(cfg)
    if not db_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dados de conexao incompletos.")
    try:
        _testar_conexao_postgres(db_url)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Falha ao conectar no banco: {exc}") from exc
    # Validacao adicional: se senha errada tambem conecta, o servidor nao esta exigindo senha (trust/peer).
    senha = str(cfg.get("db_password") or "")
    if senha:
        cfg_senha_errada = dict(cfg)
        cfg_senha_errada["db_password"] = senha + "__senha_teste_errada__"
        db_url_errada = montar_database_url(cfg_senha_errada)
        try:
            _testar_conexao_postgres(db_url_errada)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "O servidor aceitou conexao mesmo com senha incorreta. "
                    "A autenticacao atual do PostgreSQL parece estar em trust/peer. "
                    "Ajuste pg_hba.conf para scram-sha-256/md5 para validar senha."
                ),
            )
        except HTTPException:
            raise
        except Exception:
            # esperado: falhar com senha incorreta
            pass
    return {"ok": True, "mensagem": "Conexao testada com sucesso."}


@router.post("/config-banco/salvar")
def sistema_config_banco_salvar(payload: SistemaBancoConfigIn) -> dict[str, Any]:
    cfg = payload.model_dump()
    db_url = montar_database_url(cfg)
    if not db_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dados de conexao incompletos.")
    # valida antes de persistir
    try:
        _testar_conexao_postgres(db_url)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Falha ao conectar no banco: {exc}") from exc
    senha = str(cfg.get("db_password") or "")
    if senha:
        cfg_senha_errada = dict(cfg)
        cfg_senha_errada["db_password"] = senha + "__senha_teste_errada__"
        db_url_errada = montar_database_url(cfg_senha_errada)
        try:
            _testar_conexao_postgres(db_url_errada)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Nao foi possivel salvar: o PostgreSQL aceitou conexao com senha incorreta. "
                    "Configure autenticacao por senha (scram-sha-256/md5) no servidor."
                ),
            )
        except HTTPException:
            raise
        except Exception:
            pass

    save_local_config(cfg)
    return {
        "ok": True,
        "mensagem": "Configuracao salva com sucesso. Reinicie o sistema para usar o novo banco.",
        "config_path": str(local_config_path()),
    }


@router.get("/atualizacao/check", response_model=SistemaAtualizacaoCheckOut)
def sistema_atualizacao_check() -> SistemaAtualizacaoCheckOut:
    atual = settings.APP_VERSION
    manifest = _load_update_manifest()
    disponivel = str(manifest.get("latest_version") or atual).strip() or atual
    tem = _parse_semver(disponivel) > _parse_semver(atual)
    return SistemaAtualizacaoCheckOut(
        versao_atual=atual,
        versao_disponivel=disponivel,
        tem_atualizacao=tem,
        obrigatoria=bool(manifest.get("required", False)),
        changelog=str(manifest.get("changelog") or ""),
        pacote_url=str(manifest.get("package_url") or ""),
    )


@router.post("/atualizacao/aplicar")
def sistema_atualizacao_aplicar(payload: SistemaAtualizacaoAplicarIn) -> dict[str, Any]:
    alvo = (payload.versao_alvo or "").strip()
    if not alvo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe a versao alvo para atualizar.")
    check = sistema_atualizacao_check()
    if _parse_semver(alvo) <= _parse_semver(check.versao_atual):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A versao alvo deve ser maior que a versao atual.")
    if not check.pacote_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Manifesto sem package_url. Publique o pacote da nova versao e tente novamente.",
        )
    if alvo != check.versao_disponivel:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A versao alvo deve ser a mesma versao disponivel no manifesto.",
        )

    raiz = _project_root()
    updates_dir = raiz / "restore-points" / "updates-downloads"
    updates_dir.mkdir(parents=True, exist_ok=True)
    pacote_local = updates_dir / f"update_{alvo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    atualizacao_id = _nova_atualizacao_historico(check.versao_atual, alvo, check.pacote_url)
    snapshot = None
    try:
        _atualizar_historico(atualizacao_id, "baixando", "Baixando pacote de atualizacao...")
        _baixar_pacote_atualizacao(check.pacote_url, pacote_local)
        _atualizar_historico(
            atualizacao_id,
            "snapshot",
            "Pacote baixado. Gerando snapshot de seguranca...",
            pacote_local=str(pacote_local),
        )
        snapshot = _snapshot_sga_financeiro(alvo)
        _atualizar_historico(
            atualizacao_id,
            "aplicando",
            "Snapshot criado. Aplicando pacote de atualizacao...",
            snapshot_path=str(snapshot),
            rollback_disponivel=True,
        )
        _aplicar_pacote_zip(pacote_local)
        _atualizar_historico(atualizacao_id, "reiniciando", "Pacote aplicado. Reiniciando servico...")
        _reiniciar_servico_agendado(2)
        _atualizar_historico(
            atualizacao_id,
            "concluida",
            f"Atualizacao {alvo} aplicada com sucesso. Reinicio agendado.",
            pacote_local=str(pacote_local),
            snapshot_path=str(snapshot) if snapshot else "",
            rollback_disponivel=bool(snapshot),
            finalizar=True,
        )
        return {
            "ok": True,
            "status": "aplicada",
            "mensagem": f"Atualizacao {alvo} aplicada. Reinicio do servico agendado automaticamente.",
            "atualizacao_id": atualizacao_id,
            "versao_atual": check.versao_atual,
            "versao_alvo": alvo,
            "snapshot": str(snapshot) if snapshot else "",
            "pacote_local": str(pacote_local),
        }
    except Exception as exc:
        rollback_ok = False
        rollback_erro = ""
        if snapshot and Path(snapshot).exists():
            try:
                _rollback_snapshot(Path(snapshot))
                _reiniciar_servico_agendado(1)
                rollback_ok = True
            except Exception as rb_exc:
                rollback_erro = str(rb_exc)
        detalhe = f"Falha ao aplicar atualizacao: {exc}"
        if rollback_ok:
            detalhe += " | Rollback executado com sucesso."
        elif snapshot:
            detalhe += f" | Rollback falhou: {rollback_erro or 'erro desconhecido'}."
        _atualizar_historico(
            atualizacao_id,
            "erro",
            detalhe,
            pacote_local=str(pacote_local),
            snapshot_path=str(snapshot) if snapshot else "",
            rollback_disponivel=bool(snapshot),
            rollback_executado=rollback_ok,
            finalizar=True,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detalhe) from exc


@router.get("/atualizacao/historico")
def sistema_atualizacao_historico() -> list[dict[str, Any]]:
    _ajustar_schema_atualizacoes()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    id, iniciado_em, finalizado_em, versao_origem, versao_alvo,
                    status, mensagem, snapshot_path, pacote_url, pacote_local,
                    rollback_disponivel, rollback_executado
                FROM sistema_atualizacoes
                ORDER BY id DESC
                LIMIT 30
                """
            )
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/atualizacao/rollback")
def sistema_atualizacao_rollback(payload: SistemaAtualizacaoRollbackIn) -> dict[str, Any]:
    _ajustar_schema_atualizacoes()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, status, snapshot_path, rollback_disponivel, rollback_executado
                FROM sistema_atualizacoes
                WHERE id = :id
                """
            ),
            {"id": int(payload.atualizacao_id)},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Atualizacao nao encontrada.")
    if not bool(row.get("rollback_disponivel")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Atualizacao sem snapshot para rollback.")
    if bool(row.get("rollback_executado")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rollback ja executado para esta atualizacao.")
    snap = Path(str(row.get("snapshot_path") or "")).resolve()
    if not snap.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot de rollback nao encontrado.")
    try:
        _atualizar_historico(int(payload.atualizacao_id), "rollback", "Executando rollback solicitado pelo usuario...")
        _rollback_snapshot(snap)
        _reiniciar_servico_agendado(1)
        _atualizar_historico(
            int(payload.atualizacao_id),
            "rollback_concluido",
            "Rollback concluido com sucesso. Reinicio agendado.",
            rollback_executado=True,
            finalizar=True,
        )
    except Exception as exc:
        _atualizar_historico(
            int(payload.atualizacao_id),
            "rollback_erro",
            f"Falha no rollback: {exc}",
            rollback_executado=False,
            finalizar=True,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Falha no rollback: {exc}") from exc
    return {
        "ok": True,
        "mensagem": "Rollback executado. O sistema sera reiniciado em instantes.",
        "atualizacao_id": int(payload.atualizacao_id),
    }


@router.post("/excluir-historicos-liquidados")
def exclusao_historicos_liquidados(payload: ConfirmarExclusaoHistorico, db: Session = Depends(get_db)) -> dict:
    """Remove todas as contas pagas/recebidas e faturas de cartao pagas, com movimentacoes vinculadas."""
    if not payload.confirmar:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Envie {"confirmar": true} para confirmar a exclusao definitiva.',
        )
    try:
        resultado = excluir_historicos_liquidados(db)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao excluir historicos: {exc}",
        ) from exc
    return {"status": "ok", **resultado}


@router.get("/nfe/homologacao/status", response_model=NfeHomologacaoStatusOut)
def nfe_homologacao_status() -> NfeHomologacaoStatusOut:
    """Diagnostico rapido da configuracao de NF-e em homologacao."""
    cfg = _load_nfe_config()
    ambiente = str(cfg.get("ambiente", "homologacao")).lower()
    uf = str(cfg.get("uf", "PR")).upper()
    cnpj = _somente_digitos(str(cfg.get("cnpj_emitente", "")))
    ie = str(cfg.get("ie_emitente", "")).strip()
    crt = str(cfg.get("crt", "simples")).strip().lower()
    serie = int(cfg.get("serie", 1) or 1)
    cfop = str(cfg.get("cfop_padrao", "")).strip()
    csosn = str(cfg.get("csosn_padrao", "")).strip()
    id_csrt = _somente_digitos(str(cfg.get("id_csrt", "")).strip())
    csrt = str(cfg.get("csrt", "")).strip()
    cnpj_resp_tec = _somente_digitos(str(cfg.get("cnpj_responsavel_tecnico", "")).strip())

    cert_path_old = settings.NFE_CERT_PATH
    cert_pass_old = settings.NFE_CERT_PASSWORD
    settings.NFE_CERT_PATH = str(cfg.get("cert_path", "")).strip()
    settings.NFE_CERT_PASSWORD = str(cfg.get("cert_password", "")).strip()
    cert = _inspecionar_certificado_a1()
    settings.NFE_CERT_PATH = cert_path_old
    settings.NFE_CERT_PASSWORD = cert_pass_old

    faltando: list[str] = []
    if not bool(cfg.get("enabled", False)):
        faltando.append("Ativar NFE_ENABLED=true")
    if ambiente not in {"homologacao", "producao"}:
        faltando.append("NFE_AMBIENTE deve ser homologacao ou producao")
    if uf != "PR":
        faltando.append("Para seu cenario atual, configure NFE_UF=PR")
    if len(cnpj) != 14:
        faltando.append("NFE_CNPJ_EMITENTE invalido (14 digitos)")
    if not ie:
        faltando.append("NFE_IE_EMITENTE nao configurado")
    if not cert.get("ok"):
        faltando.append(str(cert.get("erro", "Certificado A1 invalido")))
    if crt not in {"simples", "presumido", "real"}:
        faltando.append("CRT invalido (simples/presumido/real)")
    if serie < 1:
        faltando.append("Serie invalida (>=1)")
    if not cfop:
        faltando.append("CFOP padrao nao configurado")
    if not csosn:
        faltando.append("CSOSN padrao nao configurado")
    if bool(cfg.get("enabled", False)) and uf == "PR":
        if not cnpj_resp_tec:
            faltando.append("CNPJ do responsavel tecnico nao configurado")
        if not id_csrt:
            faltando.append("ID CSRT nao configurado")
        if not csrt:
            faltando.append("CSRT nao configurado")

    pronto = len(faltando) == 0
    return NfeHomologacaoStatusOut(
        pronto=pronto,
        ambiente=ambiente or "homologacao",
        uf=uf or "PR",
        cnpj_emitente=cnpj,
        ie_emitente=ie,
        certificado=cert,
        faltando=faltando,
        autorizacao_implantada=True,
    )


@router.get("/nfe/status", response_model=NfeHomologacaoStatusOut)
def nfe_status() -> NfeHomologacaoStatusOut:
    """Diagnostico da configuracao NF-e para o ambiente selecionado."""
    return nfe_homologacao_status()


@router.get("/nfe/config", response_model=NfeConfigOut)
def nfe_config_get() -> NfeConfigOut:
    cfg = _load_nfe_config()
    return NfeConfigOut(**cfg)


@router.put("/nfe/config", response_model=NfeConfigOut)
def nfe_config_put(payload: NfeConfigIn) -> NfeConfigOut:
    cfg = {
        "enabled": bool(payload.enabled),
        "ambiente": (payload.ambiente or "homologacao").strip().lower(),
        "uf": (payload.uf or "PR").strip().upper(),
        "cert_path": (payload.cert_path or "").strip(),
        "cert_password": (payload.cert_password or "").strip(),
        "cnpj_emitente": _somente_digitos(payload.cnpj_emitente),
        "ie_emitente": (payload.ie_emitente or "").strip(),
        "cnae_principal": (payload.cnae_principal or "").strip(),
        "cnaes_secundarios": (payload.cnaes_secundarios or "").strip(),
        "crt": (payload.crt or "simples").strip().lower(),
        "serie": int(payload.serie or 1),
        "cfop_padrao": (payload.cfop_padrao or "").strip(),
        "csosn_padrao": (payload.csosn_padrao or "").strip(),
        "id_csrt": _somente_digitos(payload.id_csrt),
        "csrt": (payload.csrt or "").strip(),
        "cnpj_responsavel_tecnico": _somente_digitos(payload.cnpj_responsavel_tecnico),
    }
    _save_nfe_config(cfg)
    return NfeConfigOut(**cfg)


@router.post("/nfe/certificado", response_model=NfeUploadCertOut)
def nfe_upload_certificado(arquivo: UploadFile = File(...)) -> NfeUploadCertOut:
    """Recebe certificado A1 (.pfx/.p12), salva no servidor e atualiza config NF-e."""
    nome = (arquivo.filename or "").lower()
    if not nome.endswith(".pfx") and not nome.endswith(".p12"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Envie um arquivo .pfx ou .p12.")
    conteudo = arquivo.file.read()
    if not conteudo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo de certificado vazio.")

    destino = _nfe_cert_dir() / "nfe_a1_certificado.pfx"
    destino.write_bytes(conteudo)

    cfg = _load_nfe_config()
    cfg["cert_path"] = str(destino)
    _save_nfe_config(cfg)
    return NfeUploadCertOut(ok=True, cert_path=str(destino))
