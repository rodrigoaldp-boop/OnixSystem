"""Diagnosticos somente-leitura para a tela Saude do sistema.

Coleta isolada por item, com timeout, cache curto e sem acoes destrutivas.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from sga_financeiro.config import settings
from sga_financeiro.local_config import load_local_config

logger = logging.getLogger(__name__)


def _get_engine():
    from sga_financeiro.database import engine

    return engine


STATUS_OK = "ok"
STATUS_AVISO = "aviso"
STATUS_RISCO = "risco"
STATUS_ERRO = "erro"
STATUS_INFO = "info"

GRUPO_VISAO = "visao"
GRUPO_RECURSOS = "recursos"
GRUPO_APLICACAO = "aplicacao"
GRUPO_REDE = "rede"
GRUPO_ARMAZENAMENTO = "armazenamento"
GRUPO_SEGURANCA = "seguranca"

CACHE_LEVE_TTL_S = 45
CACHE_PESADO_TTL_S = 600
WG_HANDSHAKE_ATIVO_S = 180
TIMEOUT_LEVE_S = 4.0
TIMEOUT_MEDIO_S = 8.0
TIMEOUT_PESADO_S = 15.0

_cache_lock = threading.Lock()
_cache_leve: dict[str, Any] = {"at": 0.0, "payload": None}
_cache_pesado: dict[str, Any] = {}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sanitizar_erro(exc: BaseException | str, limite: int = 200) -> str:
    texto = str(exc or "").strip()
    if not texto:
        return "Indisponivel"
    texto = re.sub(r"(?i)(password|senha|token|secret|api[_-]?key)\s*[:=]\s*\S+", r"\1=***", texto)
    texto = re.sub(r"(?i)://([^:/@]+):([^@/]+)@", r"://\1:***@", texto)
    return texto[:limite]


def _item(
    item_id: str,
    nome: str,
    status: str,
    resumo: str,
    detalhe: str = "",
    *,
    grupo: str = GRUPO_APLICACAO,
    metricas: Optional[dict[str, Any]] = None,
    erro: str = "",
) -> dict[str, Any]:
    st = status if status in {STATUS_OK, STATUS_AVISO, STATUS_RISCO, STATUS_ERRO, STATUS_INFO} else STATUS_INFO
    out: dict[str, Any] = {
        "id": item_id,
        "nome": nome,
        "status": st,
        "resumo": str(resumo or ""),
        "detalhe": str(detalhe or ""),
        "grupo": grupo,
        "metricas": metricas or {},
        "coletado_em": _now_iso(),
        "erro": _sanitizar_erro(erro) if erro else "",
    }
    return out


def _formatar_data_hora_br(iso_text: str) -> str:
    raw = str(iso_text or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return raw


def _format_bytes(n: float | int) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "Indisponivel"
    if v < 0:
        return "Indisponivel"
    unidades = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while v >= 1024 and i < len(unidades) - 1:
        v /= 1024.0
        i += 1
    if i == 0:
        return f"{int(v)} {unidades[i]}"
    return f"{v:.1f} {unidades[i]}"


def _run_cmd(args: list[str], timeout: float = TIMEOUT_MEDIO_S) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return int(proc.returncode), (proc.stdout or ""), (proc.stderr or "")
    except FileNotFoundError:
        return 127, "", "comando nao encontrado"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:  # noqa: BLE001
        return 1, "", _sanitizar_erro(exc)


def _which(nome: str) -> Optional[str]:
    path = shutil.which(nome)
    return path


def _status_disco_pct(pct: float) -> str:
    if pct >= 90:
        return STATUS_ERRO
    if pct >= 85:
        return STATUS_RISCO
    if pct >= 70:
        return STATUS_AVISO
    return STATUS_OK


def _status_ram_pct(pct: float) -> str:
    if pct >= 90:
        return STATUS_ERRO
    if pct >= 75:
        return STATUS_AVISO
    return STATUS_OK


def _cn_de_subject(subject: str) -> str:
    raw = str(subject or "").strip()
    if not raw:
        return ""
    m = re.search(r"(?i)(?:^|,)\s*CN=([^,]+)", raw)
    if m:
        return m.group(1).strip()[:80]
    return raw[:60]


# ---------------------------------------------------------------------------
# Checks existentes (enriquecidos)
# ---------------------------------------------------------------------------


def checar_postgres(db: Optional[Session] = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    cfg = load_local_config()
    host = str(cfg.get("db_host") or "localhost").strip()
    porta = int(cfg.get("db_port") or 5432)
    banco = str(cfg.get("db_name") or "").strip() or "?"
    try:
        with _get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            ms = int((time.perf_counter() - t0) * 1000)
            max_conn = None
            em_uso = None
            tamanho = None
            versao = ""
            try:
                max_conn = int(conn.execute(text("SHOW max_connections")).scalar() or 0)
            except Exception:
                max_conn = None
            try:
                em_uso = int(
                    conn.execute(text("SELECT COUNT(*) FROM pg_stat_activity WHERE pid IS NOT NULL")).scalar() or 0
                )
            except Exception:
                em_uso = None
            try:
                tamanho = int(conn.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
            except Exception:
                tamanho = None
            try:
                versao_raw = str(conn.execute(text("SELECT version()")).scalar() or "")
                versao = versao_raw.split(",")[0].strip()[:80]
            except Exception:
                versao = ""

        linhas = [f"{host}:{porta}/{banco}"]
        metricas: dict[str, Any] = {"latencia_ms": ms, "host": host, "porta": porta, "banco": banco}
        if em_uso is not None and max_conn:
            pct = round((em_uso / max_conn) * 100.0, 1) if max_conn else 0.0
            linhas.append(f"Conexoes: {em_uso} de {max_conn} ({pct}%)")
            metricas.update(
                {
                    "conexoes_em_uso": em_uso,
                    "conexoes_max": max_conn,
                    "conexoes_pct": pct,
                    "barra_pct": pct,
                    "barra_label": "Conexoes",
                }
            )
        if tamanho is not None:
            linhas.append(f"Tamanho do banco: {_format_bytes(tamanho)}")
            metricas["tamanho_bytes"] = tamanho
        if versao:
            linhas.append(f"Versao: {versao}")
            metricas["versao"] = versao

        st = STATUS_OK
        if em_uso is not None and max_conn and max_conn > 0:
            pct_c = (em_uso / max_conn) * 100.0
            if pct_c >= 90:
                st = STATUS_ERRO
            elif pct_c >= 75:
                st = STATUS_AVISO

        return _item(
            "postgres",
            "PostgreSQL",
            st,
            f"conectado em {ms} ms",
            "\n".join(linhas),
            grupo=GRUPO_APLICACAO,
            metricas=metricas,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            "postgres",
            "PostgreSQL",
            STATUS_ERRO,
            "Sem conexao com o banco",
            f"{host}:{porta}/{banco}",
            grupo=GRUPO_APLICACAO,
            erro=_sanitizar_erro(exc),
        )


def _carregar_botbot_cfg_fallback() -> tuple[dict[str, Any], bool]:
    """Le config BotBot de arquivos conhecidos quando o modulo Python nao esta no path.

    Nao desativa nem altera a integracao — so leitura para o diagnostico.
    """
    candidatos = [
        Path(__file__).resolve().parents[1] / "botbot_whatsapp_config.json",
        Path(__file__).resolve().parents[2] / "botbot_whatsapp_config.json",
        Path(__file__).resolve().parents[1] / "whatsapp_botbot_config.json",
    ]
    try:
        from sga_financeiro.local_config import local_config_path

        candidatos.append(local_config_path().parent / "botbot_whatsapp_config.json")
    except Exception:
        pass

    for path in candidatos:
        try:
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            # nunca expor segredos no retorno do fallback
            cfg = {
                "enabled": bool(raw.get("enabled")),
                "provider": str(raw.get("provider") or "botbee").strip().lower() or "botbee",
                "api_url": "***" if raw.get("api_url") or raw.get("url") else "",
                "has_token": bool(str(raw.get("token") or raw.get("api_token") or "").strip()),
            }
            configurado = bool(
                str(raw.get("api_url") or raw.get("url") or "").strip()
                and str(raw.get("token") or raw.get("api_token") or "").strip()
            ) or bool(raw.get("configured"))
            return cfg, configurado
        except Exception:
            continue

    local = load_local_config()
    if any(k in local for k in ("botbot_url", "botbot_token", "whatsapp_botbot_url")):
        configurado = bool(
            str(local.get("botbot_url") or local.get("whatsapp_botbot_url") or "").strip()
            and str(local.get("botbot_token") or local.get("whatsapp_botbot_token") or "").strip()
        )
        return {
            "enabled": bool(local.get("botbot_enabled", configurado)),
            "provider": str(local.get("botbot_provider") or "botbee").strip().lower(),
            "has_token": configurado,
        }, configurado
    return {}, False


def checar_whatsapp(db: Optional[Session] = None) -> dict[str, Any]:
    """Mesma logica do diagnostico original (prod): config + worker + falhas 24h.

    Nao envia mensagem, nao altera config e nao desliga BotBot.
    """
    load_botbot_whatsapp_config = None
    botbot_whatsapp_configurado = None
    try:
        from sga_financeiro.botbot_whatsapp_config import (  # type: ignore
            botbot_whatsapp_configurado as _cfg_ok,
            load_botbot_whatsapp_config as _load_cfg,
        )

        load_botbot_whatsapp_config = _load_cfg
        botbot_whatsapp_configurado = _cfg_ok
    except Exception:
        load_botbot_whatsapp_config = None
        botbot_whatsapp_configurado = None

    worker = {"habilitado": False, "worker_ativo": False, "intervalo_segundos": None}
    try:
        from sga_financeiro.services.lembrete_automatico_service import (  # type: ignore
            status_worker_lembrete_automatico,
        )

        worker = status_worker_lembrete_automatico() or worker
    except Exception:
        pass

    if load_botbot_whatsapp_config and botbot_whatsapp_configurado:
        cfg = load_botbot_whatsapp_config() or {}
        configurado = bool(botbot_whatsapp_configurado())
    else:
        cfg, configurado = _carregar_botbot_cfg_fallback()

    habilitado = bool(cfg.get("enabled"))
    provider = str(cfg.get("provider") or "botbee").strip().lower() or "botbee"
    falhas_24h = 0
    pendentes = None

    # Contagens via engine (nao depende de Session cross-thread)
    try:
        with _get_engine().connect() as conn:
            try:
                row = conn.execute(
                    text(
                        """
                        SELECT COUNT(*) AS n
                        FROM lembrete_whatsapp_historico
                        WHERE sucesso = FALSE
                          AND enviado_em >= (NOW() AT TIME ZONE 'utc') - INTERVAL '24 hours'
                        """
                    )
                ).mappings().first()
                if row:
                    falhas_24h = int(row.get("n") or 0)
            except Exception:
                falhas_24h = 0
            try:
                row_p = conn.execute(
                    text(
                        """
                        SELECT COUNT(*) AS n
                        FROM lembrete_whatsapp_fila
                        WHERE processado = FALSE OR processado IS NULL
                        """
                    )
                ).mappings().first()
                if row_p:
                    pendentes = int(row_p.get("n") or 0)
            except Exception:
                # tabela de fila pode nao existir — ok
                pendentes = None
    except Exception:
        # banco indisponivel: ainda reporta config/worker sem derrubar o card
        pass

    if not configurado:
        return _item(
            "whatsapp",
            "WhatsApp (BotBot)",
            STATUS_INFO,
            "Integracao nao configurada",
            "Cadastre URL/token em Configuracoes > WhatsApp (Botbot).",
            grupo=GRUPO_APLICACAO,
        )

    detalhe_parts = [f"Provedor: {provider}"]
    detalhe_parts.append("Envio habilitado." if habilitado else "Envio desabilitado na configuracao.")
    if worker.get("habilitado"):
        detalhe_parts.append(
            "Worker: "
            + ("ativo" if worker.get("worker_ativo") else "parado")
            + (f" (ciclo ~{worker.get('intervalo_segundos')}s)" if worker.get("intervalo_segundos") else "")
        )
    else:
        detalhe_parts.append("Worker de lembretes desabilitado nesta instancia.")
    if falhas_24h:
        detalhe_parts.append(f"Falhas nas ultimas 24h: {falhas_24h}.")
    if pendentes is not None:
        detalhe_parts.append(f"Itens pendentes na fila (aprox.): {pendentes}.")

    metricas = {
        "provider": provider,
        "envio_habilitado": habilitado,
        "worker_ativo": bool(worker.get("worker_ativo")),
        "falhas_24h": falhas_24h,
    }
    if pendentes is not None:
        metricas["fila_pendente"] = pendentes

    detalhe = "\n".join(detalhe_parts)
    # Nunca incluir token/url no detalhe
    if falhas_24h >= 5:
        return _item("whatsapp", "WhatsApp (BotBot)", STATUS_ERRO, f"{falhas_24h} falhas nas ultimas 24h", detalhe, grupo=GRUPO_APLICACAO, metricas=metricas)
    if not habilitado:
        return _item("whatsapp", "WhatsApp (BotBot)", STATUS_INFO, "Configurado, envio desligado", detalhe, grupo=GRUPO_APLICACAO, metricas=metricas)
    if worker.get("habilitado") and not worker.get("worker_ativo"):
        return _item("whatsapp", "WhatsApp (BotBot)", STATUS_ERRO, "Fila automatica sem worker ativo", detalhe, grupo=GRUPO_APLICACAO, metricas=metricas)
    if falhas_24h > 0:
        return _item("whatsapp", "WhatsApp (BotBot)", STATUS_AVISO, f"{falhas_24h} falha(s) nas ultimas 24h", detalhe, grupo=GRUPO_APLICACAO, metricas=metricas)
    return _item("whatsapp", "WhatsApp (BotBot)", STATUS_OK, "Integracao pronta", detalhe, grupo=GRUPO_APLICACAO, metricas=metricas)


def _load_backup_auto_config_safe() -> dict[str, Any]:
    # Prefer config usada pela rota sistema quando existir; senao arquivo local.
    candidatos = [
        Path(__file__).resolve().parents[1] / "backup_auto_config.json",
        Path(__file__).resolve().parents[2] / "backup_auto_config.json",
        Path("/mnt/hd_A/onix/backups-prod"),
    ]
    cfg: dict[str, Any] = {}
    for path in candidatos[:2]:
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    cfg = raw
                    break
            except Exception:
                continue
    local = load_local_config()
    if not cfg.get("pasta_destino"):
        pasta = str(local.get("backup_pasta") or local.get("pasta_backup") or "").strip()
        if pasta:
            cfg["pasta_destino"] = pasta
    if not cfg.get("pasta_destino"):
        # fallbacks conhecidos do servidor AlmaLinux
        for p in (
            "/mnt/hd_A/onix/backups-prod",
            "/mnt/hd_A/onix/backups",
            str(Path(__file__).resolve().parents[2] / "restore-points"),
        ):
            if Path(p).exists():
                cfg.setdefault("pasta_destino", p)
                break
    cfg.setdefault("enabled", bool(cfg.get("enabled", False) or cfg.get("pasta_destino")))
    cfg.setdefault("intervalo_minutos", int(cfg.get("intervalo_minutos") or 180))
    return cfg


def _scan_backups_pasta(pasta: Path) -> tuple[int, int, Optional[Path], Optional[float]]:
    """Retorna qtd, bytes totais, arquivo mais recente, mtime."""
    if not pasta.exists() or not pasta.is_dir():
        return 0, 0, None, None
    qtd = 0
    total = 0
    mais_recente: Optional[Path] = None
    mtime_max: Optional[float] = None
    padroes = ("*.dump", "*.dump.gz", "*.dump.xz", "*.sql.gz", "*.db", "*.tar.gz")
    vistos: set[Path] = set()
    try:
        for padrao in padroes:
            for arq in pasta.glob(padrao):
                if not arq.is_file() or arq in vistos:
                    continue
                # nao seguir symlink para fora
                try:
                    if arq.is_symlink():
                        resolved = arq.resolve()
                        if pasta.resolve() not in resolved.parents and resolved.parent != pasta.resolve():
                            continue
                except Exception:
                    continue
                vistos.add(arq)
                try:
                    st = arq.stat()
                except OSError:
                    continue
                qtd += 1
                total += int(st.st_size)
                if mtime_max is None or st.st_mtime > mtime_max:
                    mtime_max = float(st.st_mtime)
                    mais_recente = arq
    except OSError:
        return qtd, total, mais_recente, mtime_max
    return qtd, total, mais_recente, mtime_max


def checar_backup(_db: Optional[Session] = None) -> dict[str, Any]:
    cfg = _load_backup_auto_config_safe()
    enabled = bool(cfg.get("enabled"))
    last_at = str(cfg.get("last_backup_at") or "").strip()
    last_err = str(cfg.get("last_error") or "").strip()
    last_path = str(cfg.get("last_backup_path") or "").strip()
    pasta = str(cfg.get("pasta_destino") or "").strip()
    intervalo = int(cfg.get("intervalo_minutos") or 1440)
    next_at = str(cfg.get("next_backup_at") or "").strip()

    if last_err and not last_at:
        return _item(
            "backup",
            "Backup automatico",
            STATUS_ERRO,
            "Ultimo backup com erro",
            _sanitizar_erro(last_err, 400),
            grupo=GRUPO_ARMAZENAMENTO,
            erro=_sanitizar_erro(last_err),
        )

    if not pasta:
        return _item(
            "backup",
            "Backup automatico",
            STATUS_INFO if not enabled else STATUS_AVISO,
            "Agendamento sem pasta" if enabled else "Backup nao configurado",
            "Informe a pasta padrao de backup.",
            grupo=GRUPO_ARMAZENAMENTO,
        )

    pasta_p = Path(pasta).expanduser()
    qtd, total_bytes, mais_recente, mtime = _scan_backups_pasta(pasta_p)
    tamanho_ultimo = None
    if last_path:
        try:
            lp = Path(last_path)
            if lp.is_file():
                tamanho_ultimo = lp.stat().st_size
                if not last_at:
                    last_at = datetime.fromtimestamp(lp.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            pass
    if tamanho_ultimo is None and mais_recente is not None:
        try:
            tamanho_ultimo = mais_recente.stat().st_size
            if not last_at and mtime:
                last_at = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
        except OSError:
            pass

    if not last_at and qtd == 0:
        return _item(
            "backup",
            "Backup automatico",
            STATUS_ERRO if enabled else STATUS_AVISO,
            "Nenhum backup valido encontrado",
            f"Diretorio: {pasta}",
            grupo=GRUPO_ARMAZENAMENTO,
            metricas={"diretorio": pasta, "qtd": 0},
        )

    idade_h = 0.0
    if last_at:
        try:
            dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            idade_h = (datetime.now() - dt).total_seconds() / 3600.0
        except ValueError:
            idade_h = 0.0
    elif mtime:
        idade_h = (time.time() - mtime) / 3600.0
        last_at = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")

    limite_aviso_h = max(2.0, (intervalo / 60.0) * 1.5)
    limite_erro_h = max(4.0, (intervalo / 60.0) * 3.0)

    linhas = [
        f"Ultimo: {_formatar_data_hora_br(last_at) or last_at}",
        f"Idade: {idade_h:.1f} h",
        f"Diretorio: {pasta}",
    ]
    if tamanho_ultimo is not None:
        linhas.append(f"Tamanho do ultimo: {_format_bytes(tamanho_ultimo)}")
    linhas.append(f"Backups mantidos: {qtd} ({_format_bytes(total_bytes)})")
    if next_at:
        linhas.append(f"Proximo: {_formatar_data_hora_br(next_at)}")
    elif enabled and intervalo:
        try:
            dt0 = datetime.fromisoformat(last_at.replace("Z", "+00:00")).replace(tzinfo=None)
            prox = dt0 + timedelta(minutes=intervalo)
            linhas.append(f"Proximo estimado: {prox.strftime('%d/%m/%Y %H:%M')}")
        except Exception:
            pass

    metricas = {
        "diretorio": pasta,
        "qtd_backups": qtd,
        "espaco_bytes": total_bytes,
        "idade_horas": round(idade_h, 2),
    }
    if tamanho_ultimo is not None:
        metricas["ultimo_tamanho_bytes"] = tamanho_ultimo

    if idade_h > limite_erro_h:
        st, resumo = STATUS_ERRO, f"Backup atrasado ({idade_h:.1f} h)"
    elif idade_h > limite_aviso_h:
        st, resumo = STATUS_AVISO, f"Ultimo OK (atrasado): {_formatar_data_hora_br(last_at)}"
    else:
        st, resumo = STATUS_OK, f"Ultimo OK: {_formatar_data_hora_br(last_at)}"

    if not enabled and st == STATUS_OK:
        st = STATUS_INFO
        resumo = "Backups encontrados (agendamento nao confirmado)"

    return _item("backup", "Backup automatico", st, resumo, "\n".join(linhas), grupo=GRUPO_ARMAZENAMENTO, metricas=metricas)


def _inspecionar_cert_local() -> dict[str, Any]:
    try:
        from sga_financeiro.routes.sistema import _inspecionar_certificado_a1, _load_nfe_config

        cfg = _load_nfe_config()
        cert_path_old = settings.NFE_CERT_PATH
        cert_pass_old = settings.NFE_CERT_PASSWORD
        settings.NFE_CERT_PATH = str(cfg.get("cert_path", "")).strip()
        settings.NFE_CERT_PASSWORD = str(cfg.get("cert_password", "")).strip()
        try:
            return _inspecionar_certificado_a1()
        finally:
            settings.NFE_CERT_PATH = cert_path_old
            settings.NFE_CERT_PASSWORD = cert_pass_old
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": _sanitizar_erro(exc)}


def checar_certificado(_db: Optional[Session] = None) -> dict[str, Any]:
    cert = _inspecionar_cert_local()
    if not cert.get("ok"):
        return _item(
            "certificado",
            "Certificado A1 (NF-e)",
            STATUS_ERRO,
            "Certificado invalido ou ausente",
            _sanitizar_erro(str(cert.get("erro") or "Configure em NF-e (certificado A1)."), 400),
            grupo=GRUPO_SEGURANCA,
            erro=_sanitizar_erro(str(cert.get("erro") or "")),
        )
    fim_raw = str(cert.get("validade_fim") or "").strip()
    try:
        fim = datetime.fromisoformat(fim_raw.replace("Z", "+00:00"))
        if fim.tzinfo is not None:
            fim = fim.replace(tzinfo=None)
        dias = (fim.date() - date.today()).days
    except ValueError:
        dias = 999
    cn = _cn_de_subject(str(cert.get("subject") or ""))
    validade_txt = _formatar_data_hora_br(fim_raw) or fim_raw
    linhas = [f"Valido ate {validade_txt}."]
    if cn:
        linhas.append(f"Identificacao: {cn}")
    metricas = {"dias_restantes": dias, "validade_fim": fim_raw}
    if cn:
        metricas["cn"] = cn
    if dias < 0:
        return _item("certificado", "Certificado A1 (NF-e)", STATUS_ERRO, "Certificado vencido", "\n".join(linhas), grupo=GRUPO_SEGURANCA, metricas=metricas)
    if dias <= 30:
        return _item("certificado", "Certificado A1 (NF-e)", STATUS_ERRO if dias <= 7 else STATUS_AVISO, f"Vence em {dias} dia(s)", "\n".join(linhas), grupo=GRUPO_SEGURANCA, metricas=metricas)
    if dias <= 60:
        return _item("certificado", "Certificado A1 (NF-e)", STATUS_AVISO, f"Vence em {dias} dia(s)", "\n".join(linhas), grupo=GRUPO_SEGURANCA, metricas=metricas)
    return _item("certificado", "Certificado A1 (NF-e)", STATUS_OK, f"Valido ({dias} dias restantes)", "\n".join(linhas), grupo=GRUPO_SEGURANCA, metricas=metricas)


def checar_smtp(_db: Optional[Session] = None) -> dict[str, Any]:
    smtp: dict[str, Any] = {}
    try:
        from sga_financeiro.email_documentos_config import (  # type: ignore
            effective_smtp_documentos,
            smtp_documentos_configurado,
        )

        if not smtp_documentos_configurado():
            return _item(
                "smtp",
                "E-mail (SMTP)",
                STATUS_INFO,
                "SMTP nao configurado",
                "Configure em E-mail de documentos.",
                grupo=GRUPO_APLICACAO,
            )
        smtp = effective_smtp_documentos()
    except Exception:
        # fallback config.local / settings genericos
        local = load_local_config()
        host = str(local.get("smtp_host") or "").strip()
        if not host:
            return _item(
                "smtp",
                "E-mail (SMTP)",
                STATUS_INFO,
                "SMTP nao configurado",
                "Modulo de e-mail de documentos nao encontrado / sem host.",
                grupo=GRUPO_APLICACAO,
            )
        smtp = {
            "smtp_host": host,
            "smtp_port": local.get("smtp_port") or 587,
            "smtp_user": local.get("smtp_user") or "",
            "smtp_from": local.get("smtp_from") or local.get("smtp_remetente") or "",
        }

    host = str(smtp.get("smtp_host") or "").strip()
    try:
        porta = int(smtp.get("smtp_port") or 0)
    except (TypeError, ValueError):
        porta = 0
    usuario = str(smtp.get("smtp_user") or "").strip()
    remetente = str(smtp.get("smtp_from") or smtp.get("from_email") or smtp.get("remetente") or "").strip()
    if not remetente and usuario and "@" in usuario:
        remetente = usuario

    linhas = [f"Host: {host or '?'}"]
    if porta:
        linhas[0] += f":{porta}"
    if remetente:
        linhas.append(f"Remetente: {remetente}")
    if usuario:
        linhas.append(f"Usuario: {usuario}")

    metricas: dict[str, Any] = {"host": host, "porta": porta, "remetente": remetente}
    conectividade = "Indisponivel"
    ms = None
    st = STATUS_OK
    if host and porta:
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, porta), timeout=3.0):
                ms = int((time.perf_counter() - t0) * 1000)
                conectividade = f"TCP OK ({ms} ms)"
                metricas["latencia_ms"] = ms
        except Exception as exc:  # noqa: BLE001
            conectividade = f"TCP falhou: {_sanitizar_erro(exc, 80)}"
            st = STATUS_AVISO
    linhas.append(f"Conectividade: {conectividade}")
    resumo = "SMTP configurado" if st == STATUS_OK else "SMTP com falha de conectividade"
    if ms is not None:
        resumo = f"SMTP OK ({ms} ms)"
    return _item("smtp", "E-mail (SMTP)", st, resumo, "\n".join(linhas), grupo=GRUPO_APLICACAO, metricas=metricas)


def _disk_usage_safe(path: Path) -> Optional[Any]:
    try:
        return shutil.disk_usage(path)
    except OSError:
        return None


def _candidatos_disco(pasta_bkp: str) -> list[tuple[str, Path]]:
    candidatos: list[tuple[str, Path]] = [
        ("/", Path("/")),
        ("/mnt/hd_A", Path("/mnt/hd_A")),
        ("/mnt/hd_B", Path("/mnt/hd_B")),
        ("/opt/onixsystem-prod", Path("/opt/onixsystem-prod")),
    ]
    if pasta_bkp:
        candidatos.append(("backups", Path(pasta_bkp).expanduser()))
    for logs_c in (Path("/var/log"), Path(__file__).resolve().parents[2] / "logs"):
        if logs_c.exists():
            candidatos.append(("logs", logs_c))
            break
    return candidatos


def checar_disco(_db: Optional[Session] = None) -> dict[str, Any]:
    cfg_bkp = _load_backup_auto_config_safe()
    pasta_bkp = str(cfg_bkp.get("pasta_destino") or "").strip()
    candidatos = _candidatos_disco(pasta_bkp)

    por_dev: dict[int, dict[str, Any]] = {}
    ordem: list[int] = []
    for rotulo, caminho in candidatos:
        if not caminho.exists():
            continue
        try:
            st_dev = caminho.stat().st_dev
        except OSError:
            continue
        uso = _disk_usage_safe(caminho)
        if uso is None:
            continue
        if st_dev not in por_dev:
            por_dev[st_dev] = {
                "device": st_dev,
                "paths": [str(caminho)],
                "rotulos": [rotulo],
                "total": uso.total,
                "used": uso.used,
                "free": uso.free,
            }
            ordem.append(st_dev)
        else:
            por_dev[st_dev]["paths"].append(str(caminho))
            por_dev[st_dev]["rotulos"].append(rotulo)

    if not por_dev:
        return _item(
            "disco",
            "Espaco em disco",
            STATUS_INFO,
            "Indisponivel",
            "Nao foi possivel ler uso de disco.",
            grupo=GRUPO_ARMAZENAMENTO,
        )

    linhas: list[str] = []
    pior_st = STATUS_OK
    pior_pct = 0.0
    particoes = []
    rank = {STATUS_OK: 0, STATUS_INFO: 0, STATUS_AVISO: 1, STATUS_RISCO: 2, STATUS_ERRO: 3}
    for dev in ordem:
        info = por_dev[dev]
        total = float(info["total"] or 0)
        used = float(info["used"] or 0)
        free = float(info["free"] or 0)
        pct = round((used / total) * 100.0, 1) if total else 0.0
        st = _status_disco_pct(pct)
        if rank[st] > rank[pior_st]:
            pior_st = st
        pior_pct = max(pior_pct, pct)
        rotulos = ", ".join(dict.fromkeys(info["rotulos"]))
        note = ""
        if len(info["paths"]) > 1:
            note = " (mesma particao — sem contagem dupla)"
        linhas.append(
            f"{rotulos}: {pct}% usado — total {_format_bytes(total)}, "
            f"usado {_format_bytes(used)}, livre {_format_bytes(free)}{note}"
        )
        particoes.append(
            {
                "rotulos": info["rotulos"],
                "paths": info["paths"],
                "pct": pct,
                "total": total,
                "used": used,
                "free": free,
                "status": st,
            }
        )

    metricas = {"particoes": particoes, "pior_pct": pior_pct, "barra_pct": pior_pct, "barra_label": "Disco"}
    if pior_st == STATUS_ERRO:
        resumo = f"Disco critico ({pior_pct}%)"
    elif pior_st == STATUS_RISCO:
        resumo = f"Disco em risco ({pior_pct}%)"
    elif pior_st == STATUS_AVISO:
        resumo = f"Uso elevado ({pior_pct}%)"
    else:
        resumo = f"Espaco OK ({pior_pct}% usado)"
    return _item("disco", "Espaco em disco", pior_st, resumo, "\n".join(linhas), grupo=GRUPO_ARMAZENAMENTO, metricas=metricas)


# ---------------------------------------------------------------------------
# Novos cartoes
# ---------------------------------------------------------------------------


def checar_cpu(_db: Optional[Session] = None) -> dict[str, Any]:
    try:
        cores = os.cpu_count() or 1
        load1, load5, load15 = os.getloadavg()
        # amostragem curta de /proc/stat
        def _cpu_times() -> tuple[float, float]:
            with open("/proc/stat", "r", encoding="utf-8") as fh:
                parts = fh.readline().split()
            nums = [float(x) for x in parts[1:8]]
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0.0)
            total = sum(nums)
            return idle, total

        idle1, total1 = _cpu_times()
        time.sleep(0.15)
        idle2, total2 = _cpu_times()
        d_total = max(total2 - total1, 1.0)
        d_idle = idle2 - idle1
        pct = max(0.0, min(100.0, round((1.0 - (d_idle / d_total)) * 100.0, 1)))

        uptime_s = None
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as fh:
                uptime_s = float(fh.read().split()[0])
        except Exception:
            uptime_s = None

        uptime_txt = "Indisponivel"
        if uptime_s is not None:
            dias = int(uptime_s // 86400)
            horas = int((uptime_s % 86400) // 3600)
            mins = int((uptime_s % 3600) // 60)
            uptime_txt = f"{dias}d {horas}h {mins}m"

        st = STATUS_OK
        if load1 > cores * 2.0 or pct >= 95:
            st = STATUS_AVISO
        if load1 > cores * 4.0:
            st = STATUS_RISCO

        detalhe = (
            f"Uso atual: {pct}%\n"
            f"Nucleos: {cores}\n"
            f"Load average: {load1:.2f} / {load5:.2f} / {load15:.2f}\n"
            f"Uptime: {uptime_txt}"
        )
        return _item(
            "cpu",
            "CPU",
            st,
            f"Uso {pct}% · load {load1:.2f}",
            detalhe,
            grupo=GRUPO_RECURSOS,
            metricas={
                "pct": pct,
                "cores": cores,
                "load_1": load1,
                "load_5": load5,
                "load_15": load15,
                "uptime_segundos": uptime_s,
                "barra_pct": pct,
                "barra_label": "CPU",
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _item("cpu", "CPU", STATUS_INFO, "Indisponivel", "", grupo=GRUPO_RECURSOS, erro=_sanitizar_erro(exc))


def _parse_meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 2:
                continue
            key = parts[0].rstrip(":")
            try:
                out[key] = int(parts[1]) * 1024  # kB -> bytes
            except ValueError:
                continue
    return out


def checar_memoria(_db: Optional[Session] = None) -> dict[str, Any]:
    try:
        info = _parse_meminfo()
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", 0)
        cached = info.get("Cached", 0) + info.get("Buffers", 0)
        used = max(0, total - available)
        pct = round((used / total) * 100.0, 1) if total else 0.0
        swap_total = info.get("SwapTotal", 0)
        swap_free = info.get("SwapFree", 0)
        swap_used = max(0, swap_total - swap_free)
        swap_pct = round((swap_used / swap_total) * 100.0, 1) if swap_total else 0.0
        st = _status_ram_pct(pct)
        detalhe = (
            f"Total: {_format_bytes(total)}\n"
            f"Utilizada: {_format_bytes(used)}\n"
            f"Disponivel: {_format_bytes(available)}\n"
            f"Cache/buffers: {_format_bytes(cached)}\n"
            f"Swap: {_format_bytes(swap_used)} / {_format_bytes(swap_total)} ({swap_pct}%)"
        )
        return _item(
            "memoria",
            "Memoria RAM",
            st,
            f"{pct}% em uso · disponivel {_format_bytes(available)}",
            detalhe,
            grupo=GRUPO_RECURSOS,
            metricas={
                "total": total,
                "usada": used,
                "disponivel": available,
                "cache": cached,
                "pct": pct,
                "swap_total": swap_total,
                "swap_usada": swap_used,
                "swap_pct": swap_pct,
                "barra_pct": pct,
                "barra_label": "RAM",
                "barra_pct_swap": swap_pct,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _item("memoria", "Memoria RAM", STATUS_INFO, "Indisponivel", "", grupo=GRUPO_RECURSOS, erro=_sanitizar_erro(exc))


def checar_nginx(_db: Optional[Session] = None) -> dict[str, Any]:
    bin_nginx = _which("nginx")
    if not bin_nginx:
        return _item(
            "nginx",
            "Nginx",
            STATUS_INFO,
            "Nginx nao instalado",
            "Binario nginx nao encontrado neste servidor.",
            grupo=GRUPO_REDE,
        )
    rc, out, err = _run_cmd(["systemctl", "is-active", "nginx"], timeout=TIMEOUT_LEVE_S)
    ativo = (out.strip() == "active")
    status_svc = out.strip() or err.strip() or "Indisponivel"
    pid = ""
    active_enter = ""
    rc2, out2, _ = _run_cmd(
        ["systemctl", "show", "nginx", "--property=MainPID", "--property=ActiveEnterTimestamp", "--no-page"],
        timeout=TIMEOUT_LEVE_S,
    )
    if rc2 == 0:
        for line in out2.splitlines():
            if line.startswith("MainPID="):
                pid = line.split("=", 1)[1].strip()
            elif line.startswith("ActiveEnterTimestamp="):
                active_enter = line.split("=", 1)[1].strip()

    conf_ok = "Indisponivel"
    rc3, out3, err3 = _run_cmd([bin_nginx, "-t"], timeout=TIMEOUT_MEDIO_S)
    if rc3 == 0:
        conf_ok = "valida"
    elif rc3 == 124:
        conf_ok = "teste expirou"
    else:
        # stderr do nginx -t costuma ter o resultado
        msg = (err3 or out3).strip().splitlines()
        conf_ok = "invalida" if rc3 != 0 else "valida"
        if msg:
            conf_ok = f"{conf_ok} ({_sanitizar_erro(msg[-1], 80)})"

    portas: list[str] = []
    rc4, out4, _ = _run_cmd(["ss", "-lntp"], timeout=TIMEOUT_LEVE_S)
    if rc4 == 0:
        for line in out4.splitlines():
            if "nginx" in line.lower() or ":80 " in line or ":443 " in line:
                m = re.search(r":(\d+)\b", line)
                if m:
                    portas.append(m.group(1))
        portas = sorted(set(portas))

    st = STATUS_OK if ativo else STATUS_AVISO
    if conf_ok.startswith("invalida"):
        st = STATUS_ERRO
    linhas = [
        f"Instalado: sim ({bin_nginx})",
        f"Servico: {status_svc}",
        f"PID: {pid or 'Indisponivel'}",
        f"Ativo desde: {active_enter or 'Indisponivel'}",
        f"Configuracao: {conf_ok}",
        f"Portas: {', '.join(portas) if portas else 'Indisponivel'}",
    ]
    return _item(
        "nginx",
        "Nginx",
        st,
        "Ativo" if ativo else "Inativo / indisponivel",
        "\n".join(linhas),
        grupo=GRUPO_REDE,
        metricas={"ativo": ativo, "pid": pid, "portas": portas, "config": conf_ok},
    )


def checar_wireguard(_db: Optional[Session] = None) -> dict[str, Any]:
    if not _which("wg") and not _which("ip"):
        return _item(
            "wireguard",
            "WireGuard",
            STATUS_INFO,
            "WireGuard nao utilizado neste servidor",
            "Ferramentas wg/ip nao encontradas.",
            grupo=GRUPO_REDE,
        )
    ifaces: list[str] = []
    rc, out, _ = _run_cmd(["ip", "-o", "link", "show", "type", "wireguard"], timeout=TIMEOUT_LEVE_S)
    if rc == 0 and out.strip():
        for line in out.splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 2:
                name = parts[1].strip().split("@", 1)[0].strip()
                if name:
                    ifaces.append(name)
    if not ifaces and Path("/sys/class/net").exists():
        for p in Path("/sys/class/net").iterdir():
            if (p / "type").is_file():
                # heuristica: nomes comuns
                if p.name.startswith("wg") or p.name in {"onix-rede", "onixrede"}:
                    ifaces.append(p.name)
    ifaces = sorted(set(ifaces))
    if not ifaces:
        return _item(
            "wireguard",
            "WireGuard",
            STATUS_INFO,
            "Nenhuma interface WireGuard",
            "Nenhuma interface WG detectada.",
            grupo=GRUPO_REDE,
        )

    blocos: list[str] = []
    peers_cfg = 0
    peers_ativos = 0
    rx_total = 0
    tx_total = 0
    ultimo_hs = None
    for iface in ifaces:
        addr = "Indisponivel"
        rc_a, out_a, _ = _run_cmd(["ip", "-4", "-o", "addr", "show", "dev", iface], timeout=TIMEOUT_LEVE_S)
        if rc_a == 0 and out_a.strip():
            m = re.search(r"inet\s+(\S+)", out_a)
            if m:
                addr = m.group(1)
        rc_w, out_w, err_w = _run_cmd(["wg", "show", iface, "dump"], timeout=TIMEOUT_MEDIO_S)
        iface_peers = 0
        iface_ativos = 0
        if rc_w != 0:
            blocos.append(f"{iface}: {addr} · detalhes Indisponivel ({_sanitizar_erro(err_w or 'sem permissao', 60)})")
            continue
        lines = [ln for ln in out_w.splitlines() if ln.strip()]
        # dump: primeira linha = interface; demais = peers
        for ln in lines[1:]:
            cols = ln.split("\t")
            if len(cols) < 7:
                continue
            iface_peers += 1
            peers_cfg += 1
            try:
                hs = int(cols[4] or 0)
            except ValueError:
                hs = 0
            try:
                rx_total += int(cols[5] or 0)
                tx_total += int(cols[6] or 0)
            except ValueError:
                pass
            if hs > 0:
                age = time.time() - hs
                if ultimo_hs is None or hs > ultimo_hs:
                    ultimo_hs = hs
                if age <= WG_HANDSHAKE_ATIVO_S:
                    iface_ativos += 1
                    peers_ativos += 1
        blocos.append(
            f"{iface}: {addr} · peers {iface_peers} (ativos {iface_ativos})"
        )

    hs_txt = "Indisponivel"
    if ultimo_hs:
        hs_txt = datetime.fromtimestamp(ultimo_hs).strftime("%d/%m/%Y %H:%M:%S")
    detalhe = (
        "\n".join(blocos)
        + f"\nPeers configurados: {peers_cfg}"
        + f"\nPeers ativos (<= {WG_HANDSHAKE_ATIVO_S}s): {peers_ativos}"
        + f"\nUltimo handshake: {hs_txt}"
        + f"\nTrafego: RX {_format_bytes(rx_total)} / TX {_format_bytes(tx_total)}"
    )
    st = STATUS_OK if peers_ativos > 0 or peers_cfg == 0 else STATUS_AVISO
    return _item(
        "wireguard",
        "WireGuard",
        st,
        f"{len(ifaces)} interface(s) · {peers_ativos}/{peers_cfg} peers ativos",
        detalhe,
        grupo=GRUPO_REDE,
        metricas={
            "interfaces": ifaces,
            "peers": peers_cfg,
            "peers_ativos": peers_ativos,
            "rx": rx_total,
            "tx": tx_total,
        },
    )


def _runtime_bin() -> tuple[Optional[str], str]:
    if _which("podman"):
        return _which("podman"), "podman"
    if _which("docker"):
        return _which("docker"), "docker"
    return None, ""


def checar_containers(_db: Optional[Session] = None) -> dict[str, Any]:
    cache_key = "containers"
    with _cache_lock:
        hit = _cache_pesado.get(cache_key)
        if hit and (time.time() - float(hit.get("at") or 0)) < CACHE_PESADO_TTL_S:
            return dict(hit["item"])

    bin_path, runtime = _runtime_bin()
    if not bin_path:
        item = _item(
            "containers",
            "Containers",
            STATUS_INFO,
            "Docker/Podman nao utilizado neste servidor",
            "Nenhum runtime de containers detectado.",
            grupo=GRUPO_REDE,
        )
        with _cache_lock:
            _cache_pesado[cache_key] = {"at": time.time(), "item": item}
        return item

    # status do servico (melhor esforco)
    unit = "podman" if runtime == "podman" else "docker"
    rc_s, out_s, _ = _run_cmd(["systemctl", "is-active", unit], timeout=TIMEOUT_LEVE_S)
    svc = out_s.strip() or "Indisponivel"

    ativos = parados = imagens = volumes = dangling_img = dangling_vol = 0
    rc_ps, out_ps, _ = _run_cmd([bin_path, "ps", "-aq", "--filter", "status=running"], timeout=TIMEOUT_MEDIO_S)
    if rc_ps == 0:
        ativos = len([x for x in out_ps.splitlines() if x.strip()])
    rc_ex, out_ex, _ = _run_cmd([bin_path, "ps", "-aq", "--filter", "status=exited"], timeout=TIMEOUT_MEDIO_S)
    if rc_ex == 0:
        parados = len([x for x in out_ex.splitlines() if x.strip()])
    rc_img, out_img, _ = _run_cmd([bin_path, "images", "-q"], timeout=TIMEOUT_MEDIO_S)
    if rc_img == 0:
        imagens = len([x for x in out_img.splitlines() if x.strip()])
    rc_d, out_d, _ = _run_cmd([bin_path, "images", "-f", "dangling=true", "-q"], timeout=TIMEOUT_MEDIO_S)
    if rc_d == 0:
        dangling_img = len([x for x in out_d.splitlines() if x.strip()])
    rc_v, out_v, _ = _run_cmd([bin_path, "volume", "ls", "-q"], timeout=TIMEOUT_MEDIO_S)
    if rc_v == 0:
        volumes = len([x for x in out_v.splitlines() if x.strip()])
    # volumes dangling: docker volume ls -f dangling=true; podman similar
    rc_vd, out_vd, _ = _run_cmd([bin_path, "volume", "ls", "-f", "dangling=true", "-q"], timeout=TIMEOUT_MEDIO_S)
    if rc_vd == 0:
        dangling_vol = len([x for x in out_vd.splitlines() if x.strip()])

    espaco_txt = "Indisponivel"
    rc_df, out_df, _ = _run_cmd([bin_path, "system", "df"], timeout=TIMEOUT_PESADO_S)
    if rc_df == 0 and out_df.strip():
        espaco_txt = "\n".join(out_df.strip().splitlines()[:8])

    detalhe = (
        f"Runtime: {runtime}\n"
        f"Servico ({unit}): {svc}\n"
        f"Containers ativos: {ativos}\n"
        f"Containers parados: {parados}\n"
        f"Imagens: {imagens} (dangling {dangling_img})\n"
        f"Volumes: {volumes} (dangling {dangling_vol})\n"
        f"Uso aproximado:\n{espaco_txt}"
    )
    item = _item(
        "containers",
        "Containers",
        STATUS_OK if ativos >= 0 else STATUS_INFO,
        f"{runtime}: {ativos} ativos · {imagens} imagens",
        detalhe,
        grupo=GRUPO_REDE,
        metricas={
            "runtime": runtime,
            "ativos": ativos,
            "parados": parados,
            "imagens": imagens,
            "volumes": volumes,
            "imagens_dangling": dangling_img,
            "volumes_dangling": dangling_vol,
        },
    )
    with _cache_lock:
        _cache_pesado[cache_key] = {"at": time.time(), "item": item}
    return item


def _parse_systemctl_show(out: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for line in (out or "").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        props[k.strip()] = v.strip()
    return props


def _unit_show(name: str) -> Optional[dict[str, str]]:
    rc, out, _ = _run_cmd(
        [
            "systemctl",
            "show",
            name,
            "--property=LoadState,ActiveState,UnitFileState,FragmentPath,Id",
            "--no-pager",
        ],
        timeout=TIMEOUT_LEVE_S,
    )
    if rc != 0 and not out.strip():
        return None
    props = _parse_systemctl_show(out)
    if not props:
        return None
    if props.get("LoadState") in {"not-found", ""}:
        return None
    return props


def _normalizar_unit(nome: str) -> str:
    n = str(nome or "").strip()
    if not n:
        return ""
    if not n.endswith(".service") and "@" not in n and not n.endswith(".socket"):
        n = n + ".service"
    return n


def _unit_eh_opcional(unit: str) -> bool:
    u = unit.lower()
    if u.startswith("wg-quick@"):
        return True
    if u in {"podman.service", "docker.service", "onix-homolog.service"}:
        return True
    return False


def _unit_deve_listar(unit: str, props: dict[str, str]) -> bool:
    """Evita falso positivo de templates systemd (ex.: wg-quick@qualquer) e services disabled/idle."""
    active = (props.get("ActiveState") or "").lower()
    file_state = (props.get("UnitFileState") or "").lower()
    if active in {"active", "activating", "reloading", "failed"}:
        return True
    if file_state in {"enabled", "enabled-runtime", "linked", "linked-runtime"}:
        return True
    # Essenciais concretos (nao-template): listar mesmo se disabled, para avisar se pararam.
    if not _unit_eh_opcional(unit) and "@" not in unit:
        load = (props.get("LoadState") or "").lower()
        return load in {"loaded", "masked"}
    return False


def _wg_interfaces() -> list[str]:
    rc, out, _ = _run_cmd(["wg", "show", "interfaces"], timeout=TIMEOUT_LEVE_S)
    if rc != 0 or not out.strip():
        return []
    return [x.strip() for x in out.split() if x.strip()]


def checar_servicos(_db: Optional[Session] = None) -> dict[str, Any]:
    candidatos: list[str] = []
    for nome in (
        getattr(settings, "SYSTEMD_SERVICE_NAME", None) or "",
        "onix-prod.service",
        "onix-homolog.service",
        "onixsystem.service",
        "postgresql-17.service",
        "postgresql.service",
        "nginx.service",
        "podman.service",
        "docker.service",
    ):
        n = _normalizar_unit(nome)
        if n and n not in candidatos:
            candidatos.append(n)

    # WireGuard: so instancias reais (iface UP ou unit habilitada), nunca inventar onix-rede.
    for iface in _wg_interfaces():
        n = _normalizar_unit(f"wg-quick@{iface}")
        if n and n not in candidatos:
            candidatos.append(n)

    encontrados: list[dict[str, str]] = []
    for unit in candidatos:
        props = _unit_show(unit)
        if not props or not _unit_deve_listar(unit, props):
            continue
        estado = (props.get("ActiveState") or "unknown").strip() or "unknown"
        if estado == "failed" or (props.get("UnitFileState") or "").lower() == "bad":
            estado = "failed"
        # is-failed e mais confiavel para residual failed
        _rc_f, out_f, _ = _run_cmd(["systemctl", "is-failed", unit], timeout=TIMEOUT_LEVE_S)
        if (out_f or "").strip() == "failed":
            estado = "failed"
        encontrados.append(
            {
                "nome": unit,
                "estado": estado,
                "opcional": "1" if _unit_eh_opcional(unit) else "0",
            }
        )

    if not encontrados:
        return _item(
            "servicos",
            "Servicos essenciais",
            STATUS_INFO,
            "Nenhum servico conhecido detectado",
            "Allowlist nao encontrou units systemd relevantes.",
            grupo=GRUPO_VISAO,
        )

    ativos = sum(1 for x in encontrados if x["estado"] == "active")
    falha = sum(1 for x in encontrados if x["estado"] == "failed")
    # Inativos so contam alerta se nao forem opcionais (podman/wg idle e esperado).
    inativos_alerta = [
        x for x in encontrados if x["estado"] not in {"active", "failed"} and x.get("opcional") != "1"
    ]
    inativos = len([x for x in encontrados if x["estado"] not in {"active", "failed"}])
    st = STATUS_OK
    if falha:
        st = STATUS_ERRO
    elif inativos_alerta:
        st = STATUS_AVISO
    linhas = [f"{x['nome']}: {x['estado']}" for x in encontrados]
    return _item(
        "servicos",
        "Servicos essenciais",
        st,
        f"{ativos} ativos · {inativos} inativos · {falha} com falha · total {len(encontrados)}",
        "\n".join(linhas),
        grupo=GRUPO_VISAO,
        metricas={
            "ativos": ativos,
            "inativos": inativos,
            "falha": falha,
            "total": len(encontrados),
            "lista": encontrados,
        },
    )


def _du_path(path: Path, timeout: float = TIMEOUT_PESADO_S) -> Optional[int]:
    if not path.exists():
        return None
    # nao seguir symlinks (-P)
    rc, out, _ = _run_cmd(["du", "-sbP", str(path)], timeout=timeout)
    if rc != 0 or not out.strip():
        # fallback Python limitado (apenas 1 nivel de arquivos)
        try:
            total = 0
            if path.is_file():
                return path.stat().st_size
            for root, dirs, files in os.walk(path, followlinks=False):
                # limitar profundidade
                rel = Path(root).relative_to(path)
                if len(rel.parts) > 3:
                    dirs[:] = []
                    continue
                for f in files:
                    fp = Path(root) / f
                    try:
                        if fp.is_symlink():
                            continue
                        total += fp.stat().st_size
                    except OSError:
                        continue
            return total
        except Exception:
            return None
    try:
        return int(out.split()[0])
    except (ValueError, IndexError):
        return None


def checar_armazenamento(_db: Optional[Session] = None) -> dict[str, Any]:
    cache_key = "armazenamento"
    with _cache_lock:
        hit = _cache_pesado.get(cache_key)
        if hit and (time.time() - float(hit.get("at") or 0)) < CACHE_PESADO_TTL_S:
            return dict(hit["item"])

    root_proj = Path(__file__).resolve().parents[2]
    cfg = _load_backup_auto_config_safe()
    pasta_bkp = Path(str(cfg.get("pasta_destino") or "").strip() or "/mnt/hd_A/onix/backups-prod")
    allow = [
        ("Projeto (raiz)", root_proj),
        ("sga_financeiro", root_proj / "sga_financeiro"),
        ("Backups", pasta_bkp),
        ("Logs /var/log", Path("/var/log")),
        ("Temp projeto", root_proj / "tmp"),
        ("restore-points", root_proj / "restore-points"),
        ("/opt/onixsystem-prod", Path("/opt/onixsystem-prod")),
        ("/opt/onix-rede", Path("/opt/onix-rede")),
    ]
    # containers storage se existir
    for p in (Path("/var/lib/containers"), Path("/var/lib/docker")):
        if p.exists():
            allow.append((f"Containers ({p})", p))

    linhas: list[str] = []
    metricas_dirs: list[dict[str, Any]] = []
    for rotulo, path in allow:
        if not path.exists():
            continue
        # impedir seguir symlink para fora: se path e symlink, resolve e ignora se sair demais
        try:
            if path.is_symlink():
                resolved = path.resolve()
                # permitido
                _ = resolved
        except Exception:
            continue
        size = _du_path(path)
        if size is None:
            linhas.append(f"{rotulo}: Indisponivel")
            continue
        linhas.append(f"{rotulo}: {_format_bytes(size)}")
        metricas_dirs.append({"nome": rotulo, "path": str(path), "bytes": size})

    if not linhas:
        item = _item(
            "armazenamento",
            "Uso de armazenamento",
            STATUS_INFO,
            "Indisponivel",
            "Nenhum diretorio permitido acessivel.",
            grupo=GRUPO_ARMAZENAMENTO,
        )
    else:
        item = _item(
            "armazenamento",
            "Uso de armazenamento",
            STATUS_OK,
            f"{len(metricas_dirs)} diretorios analisados",
            "\n".join(linhas),
            grupo=GRUPO_ARMAZENAMENTO,
            metricas={"diretorios": metricas_dirs},
        )
    with _cache_lock:
        _cache_pesado[cache_key] = {"at": time.time(), "item": item}
    return item


def checar_saude_geral(itens: list[dict[str, Any]]) -> dict[str, Any]:
    normais = sum(1 for i in itens if i.get("status") == STATUS_OK)
    alertas = sum(1 for i in itens if i.get("status") in {STATUS_AVISO, STATUS_RISCO})
    erros = sum(1 for i in itens if i.get("status") == STATUS_ERRO)
    indisponiveis = sum(1 for i in itens if i.get("status") == STATUS_INFO)
    if erros:
        st, resumo = STATUS_ERRO, "Itens criticos encontrados"
    elif alertas:
        st, resumo = STATUS_AVISO, "Atencao necessaria"
    else:
        st, resumo = STATUS_OK, "Todos normais"
    detalhe = (
        f"Normais: {normais}\n"
        f"Alertas: {alertas}\n"
        f"Erros: {erros}\n"
        f"Indisponiveis / nao utilizados: {indisponiveis}\n"
        f"Atualizado em: {_formatar_data_hora_br(_now_iso())}"
    )
    return _item(
        "saude_geral",
        "Saude geral",
        st,
        resumo,
        detalhe,
        grupo=GRUPO_VISAO,
        metricas={
            "normais": normais,
            "alertas": alertas,
            "erros": erros,
            "indisponiveis": indisponiveis,
        },
    )


CHECK_SPECS: list[tuple[str, str, float, bool]] = [
    ("postgres", "checar_postgres", TIMEOUT_MEDIO_S, False),
    ("whatsapp", "checar_whatsapp", TIMEOUT_MEDIO_S, False),
    ("backup", "checar_backup", TIMEOUT_PESADO_S, False),
    ("certificado", "checar_certificado", TIMEOUT_MEDIO_S, False),
    ("smtp", "checar_smtp", TIMEOUT_MEDIO_S, False),
    ("disco", "checar_disco", TIMEOUT_LEVE_S, False),
    ("cpu", "checar_cpu", TIMEOUT_MEDIO_S, False),
    ("memoria", "checar_memoria", TIMEOUT_LEVE_S, False),
    ("nginx", "checar_nginx", TIMEOUT_MEDIO_S, False),
    ("wireguard", "checar_wireguard", TIMEOUT_MEDIO_S, False),
    ("containers", "checar_containers", TIMEOUT_PESADO_S, True),
    ("servicos", "checar_servicos", TIMEOUT_PESADO_S, False),
    ("armazenamento", "checar_armazenamento", TIMEOUT_PESADO_S, True),
]


def _resolver_check_fn(fn_name: str) -> Callable[[Optional[Session]], dict[str, Any]]:
    fn = globals().get(fn_name)
    if not callable(fn):
        raise RuntimeError(f"check ausente: {fn_name}")
    return fn  # type: ignore[return-value]


def _executar_check(
    nome: str,
    fn: Callable[[Optional[Session]], dict[str, Any]],
    db: Optional[Session],
    timeout: float,
) -> dict[str, Any]:
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(fn, db)
            return fut.result(timeout=timeout)
    except FuturesTimeoutError:
        return _item(nome, nome, STATUS_INFO, "Indisponivel (timeout)", f"Diagnostico '{nome}' excedeu {timeout:.0f}s.", grupo=GRUPO_VISAO, erro="timeout")
    except Exception as exc:  # noqa: BLE001
        return _item(nome, nome, STATUS_INFO, "Indisponivel", "", grupo=GRUPO_VISAO, erro=_sanitizar_erro(exc))


def coletar_health_dashboard(db: Optional[Session] = None, *, refresh: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    if not refresh:
        with _cache_lock:
            payload = _cache_leve.get("payload")
            at = float(_cache_leve.get("at") or 0)
            if payload and (time.time() - at) < CACHE_LEVE_TTL_S:
                return dict(payload)

    resultados: dict[str, dict[str, Any]] = {}

    def _job(spec: tuple[str, str, float, bool]) -> tuple[str, dict[str, Any]]:
        nome, fn_name, timeout, _pesado = spec
        fn = _resolver_check_fn(fn_name)
        return nome, _executar_check(nome, fn, db, timeout)

    for spec in CHECK_SPECS:
        nome = spec[0]
        if nome == "whatsapp":
            fn = _resolver_check_fn(spec[1])
            resultados[nome] = _executar_check(nome, fn, db, spec[2])

    outros = [s for s in CHECK_SPECS if s[0] != "whatsapp"]
    with ThreadPoolExecutor(max_workers=min(6, len(outros) or 1)) as pool:
        futs = {pool.submit(_job, s): s[0] for s in outros}
        for fut in futs:
            nome = futs[fut]
            try:
                n, item = fut.result(timeout=TIMEOUT_PESADO_S + 2)
                resultados[n] = item
            except Exception as exc:  # noqa: BLE001
                resultados[nome] = _item(nome, nome, STATUS_INFO, "Indisponivel", "", erro=_sanitizar_erro(exc))

    ordem = [s[0] for s in CHECK_SPECS]
    itens_base = [resultados[k] for k in ordem if k in resultados]
    geral = checar_saude_geral(itens_base)
    itens = [geral] + itens_base

    # Contagem do banner/badge: so itens reais (exclui o card agregado saude_geral).
    erros = sum(1 for i in itens_base if i.get("status") == STATUS_ERRO)
    avisos = sum(1 for i in itens_base if i.get("status") in {STATUS_AVISO, STATUS_RISCO})
    normais = sum(1 for i in itens_base if i.get("status") == STATUS_OK)
    indisponiveis = sum(1 for i in itens_base if i.get("status") == STATUS_INFO)
    alertas = avisos + erros
    ok = erros == 0 and avisos == 0

    payload = {
        "ok": ok,
        "checked_at": _now_iso(),
        "alertas": alertas,
        "resumo_geral": {
            "normais": normais,
            "alertas": avisos,
            "erros": erros,
            "indisponiveis": indisponiveis,
            "mensagem": geral.get("resumo") or "",
        },
        "itens": itens,
        "manutencao": {
            "habilitada": False,
            "mensagem": "Recursos de manutencao estarao disponiveis apos configuracao e validacao individual.",
        },
    }
    elapsed = time.perf_counter() - t0
    logger.info("health_dashboard coletado em %.2fs (refresh=%s alertas=%s)", elapsed, refresh, alertas)

    with _cache_lock:
        _cache_leve["at"] = time.time()
        _cache_leve["payload"] = payload
    return payload


def limpar_cache_health() -> None:
    with _cache_lock:
        _cache_leve["at"] = 0.0
        _cache_leve["payload"] = None
        _cache_pesado.clear()
