"""Aplicacao principal FastAPI do sistema financeiro."""

import logging
import sys
import hashlib
import json
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

# Garante imports `sga_financeiro.*` quando o processo sobe com cwd em `sga_financeiro/`
# (ex.: `uvicorn main:app` sem PYTHONPATH). Raiz do repositorio = pai da pasta do pacote.
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import inspect, text

from sga_financeiro.config import settings
from sga_financeiro.database import Base, SessionLocal, engine
from sga_financeiro.models import (  # noqa: F401 - importa para registrar tabelas
    CartaoCredito,
    CadastroGeral,
    Categoria,
    CentroCustos,
    Cliente,
    ContaCorrente,
    ContaPagar,
    ContaReceber,
    FaturaCartao,
    Fornecedor,
    GrupoConta,
    GrupoDespesa,
    Movimentacao,
    PlanoConta,
    CategoriaProduto,
    CondicaoPagamento,
    Produto,
    SubgrupoConta,
    Venda,
    VendaItem,
)
from sga_financeiro.routes import (
    assistente,
    cadastros,
    cartoes_credito,
    categorias,
    categorias_produto,
    condicoes_pagamento,
    centros_custos,
    clientes,
    contas_correntes,
    contas_pagar,
    contas_receber,
    dashboard,
    fornecedores,
    grupos_contas,
    grupos_despesas,
    planos_contas,
    produtos,
    subgrupos_contas,
    sistema,
    vendas,
)


def _install_log_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _relatar_falha_inicial(exc: Exception, mensagem: str) -> None:
    import traceback

    tb = traceback.format_exc()
    texto = f"{mensagem}\n\n{tb}"
    print(texto, file=sys.stderr)
    log_path = _install_log_dir() / "onixsystem-startup-error.log"
    try:
        log_path.write_text(texto, encoding="utf-8")
        print(f"\nLog salvo em: {log_path}", file=sys.stderr)
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        input("Pressione Enter para fechar...")
        raise SystemExit(1) from exc
    raise


# Em ambiente inicial, criamos as tabelas automaticamente.
try:
    Base.metadata.create_all(bind=engine)
except Exception as exc:
    _relatar_falha_inicial(
        exc,
        "Falha ao conectar ao PostgreSQL ou criar tabelas.\n"
        "- Servidor PostgreSQL rodando?\n"
        "- Arquivo config.local.json ao lado do OnixSystem.exe com host, porta, banco, usuario e senha?\n"
        "- Firewall liberado para a porta do PostgreSQL?",
    )


def _ajustar_schema_cadastros() -> None:
    """Adiciona colunas novas em bases ja existentes sem migracao formal."""
    inspector = inspect(engine)
    if "cadastros_gerais" not in inspector.get_table_names():
        return
    colunas = {col["name"] for col in inspector.get_columns("cadastros_gerais")}
    if "cidade_uf" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cadastros_gerais ADD COLUMN cidade_uf VARCHAR(80)"))
    if "nome_fantasia" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cadastros_gerais ADD COLUMN nome_fantasia VARCHAR(180)"))
    if "contexto" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cadastros_gerais ADD COLUMN contexto VARCHAR(20) DEFAULT 'pessoas'"))
            conn.execute(text("UPDATE cadastros_gerais SET contexto = 'pessoas' WHERE contexto IS NULL"))
    if "is_cliente" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cadastros_gerais ADD COLUMN is_cliente BOOLEAN DEFAULT 0"))
            conn.execute(text("UPDATE cadastros_gerais SET is_cliente = 0 WHERE is_cliente IS NULL"))
    if "is_funcionario" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cadastros_gerais ADD COLUMN is_funcionario BOOLEAN DEFAULT 0"))
            conn.execute(text("UPDATE cadastros_gerais SET is_funcionario = 0 WHERE is_funcionario IS NULL"))
    if "is_fornecedor" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cadastros_gerais ADD COLUMN is_fornecedor BOOLEAN DEFAULT 0"))
            conn.execute(text("UPDATE cadastros_gerais SET is_fornecedor = 0 WHERE is_fornecedor IS NULL"))
    if "is_vendedor" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cadastros_gerais ADD COLUMN is_vendedor BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE cadastros_gerais SET is_vendedor = FALSE WHERE is_vendedor IS NULL"))
    if "chave_pix" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cadastros_gerais ADD COLUMN chave_pix VARCHAR(180)"))
    if "vendedor_comissionado" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cadastros_gerais ADD COLUMN vendedor_comissionado BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE cadastros_gerais SET vendedor_comissionado = FALSE WHERE vendedor_comissionado IS NULL"))


def _ajustar_schema_contas_correntes() -> None:
    """Adiciona colunas novas de conta corrente sem migracao formal."""
    inspector = inspect(engine)
    if "contas_correntes" not in inspector.get_table_names():
        return
    colunas = {col["name"] for col in inspector.get_columns("contas_correntes")}
    if "nome_conta" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE contas_correntes ADD COLUMN nome_conta VARCHAR(120) DEFAULT ''"))
            conn.execute(text("UPDATE contas_correntes SET nome_conta = '' WHERE nome_conta IS NULL"))


def _ajustar_schema_movimentacoes() -> None:
    """Adiciona colunas de conciliacao em movimentacoes sem migracao formal."""
    inspector = inspect(engine)
    if "movimentacoes" not in inspector.get_table_names():
        return
    colunas = {col["name"] for col in inspector.get_columns("movimentacoes")}
    if "conciliado" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE movimentacoes ADD COLUMN conciliado BOOLEAN DEFAULT 1"))
            conn.execute(text("UPDATE movimentacoes SET conciliado = 1 WHERE conciliado IS NULL"))
    if "data_conciliacao" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE movimentacoes ADD COLUMN data_conciliacao DATETIME"))
            conn.execute(text("UPDATE movimentacoes SET data_conciliacao = data_movimento WHERE conciliado = 1 AND data_conciliacao IS NULL"))


def _ajustar_schema_cartoes_e_contas_pagar() -> None:
    """Colunas de cartao (nome, dia vencimento) e vinculo conta -> fatura."""
    inspector = inspect(engine)
    if "cartoes_credito" in inspector.get_table_names():
        colunas = {col["name"] for col in inspector.get_columns("cartoes_credito")}
        if "nome_conta" not in colunas:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE cartoes_credito ADD COLUMN nome_conta VARCHAR(120) DEFAULT ''"))
                conn.execute(text("UPDATE cartoes_credito SET nome_conta = '' WHERE nome_conta IS NULL"))
        if "data_vencimento" not in colunas:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE cartoes_credito ADD COLUMN data_vencimento INTEGER DEFAULT 10"))
                conn.execute(text("UPDATE cartoes_credito SET data_vencimento = 10 WHERE data_vencimento IS NULL"))
    if "contas_pagar" in inspector.get_table_names():
        colunas_cp = {col["name"] for col in inspector.get_columns("contas_pagar")}
        if "fatura_id" not in colunas_cp:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE contas_pagar ADD COLUMN fatura_id INTEGER"))


def _ajustar_schema_contas_receber_comissao_venda() -> None:
    """Adiciona colunas de vinculo com venda e controle de comissao."""
    inspector = inspect(engine)
    if "contas_receber" not in inspector.get_table_names():
        return
    colunas = {col["name"] for col in inspector.get_columns("contas_receber")}
    with engine.begin() as conn:
        if "venda_id" not in colunas:
            conn.execute(text("ALTER TABLE contas_receber ADD COLUMN venda_id INTEGER"))
        if "comissao_gerada" not in colunas:
            conn.execute(text("ALTER TABLE contas_receber ADD COLUMN comissao_gerada BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE contas_receber SET comissao_gerada = FALSE WHERE comissao_gerada IS NULL"))


_ajustar_schema_cadastros()
_ajustar_schema_contas_correntes()
_ajustar_schema_movimentacoes()
_ajustar_schema_cartoes_e_contas_pagar()
_ajustar_schema_contas_receber_comissao_venda()


def _ajustar_schema_categorias_produto() -> None:
    """Tabela categorias_produto (create_all) + coluna FK em produtos em bases antigas."""
    from sga_financeiro.routes.categorias_produto import garantir_categorias_produto_padrao

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "categorias_produto" not in tables or "produtos" not in tables:
        return
    colunas = {c["name"] for c in inspector.get_columns("produtos")}
    if "categoria_produto_id" not in colunas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE produtos ADD COLUMN categoria_produto_id INTEGER"))
    db = SessionLocal()
    try:
        garantir_categorias_produto_padrao(db)
        db.execute(
            text(
                "UPDATE produtos SET categoria_produto_id = (SELECT id FROM categorias_produto WHERE codigo = 'PRODUTOS' LIMIT 1) "
                "WHERE categoria_produto_id IS NULL"
            )
        )
        db.commit()
    finally:
        db.close()
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE produtos ALTER COLUMN categoria_produto_id SET NOT NULL"))
        except Exception:
            pass
    insp2 = inspect(engine)
    fks = insp2.get_foreign_keys("produtos")
    tem_fk = any((fk.get("referred_table") or "") == "categorias_produto" for fk in fks)
    if not tem_fk:
        with engine.begin() as conn:
            try:
                conn.execute(
                    text(
                        "ALTER TABLE produtos ADD CONSTRAINT produtos_categoria_produto_id_fkey "
                        "FOREIGN KEY (categoria_produto_id) REFERENCES categorias_produto (id)"
                    )
                )
            except Exception:
                pass


def _remover_categoria_comissionados_obsoleta() -> None:
    """Remove COMISSIONADOS (seed antigo); produtos passam para PRODUTOS."""
    inspector = inspect(engine)
    if "categorias_produto" not in inspector.get_table_names():
        return
    if "produtos" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id FROM categorias_produto WHERE codigo = 'COMISSIONADOS' LIMIT 1")
        ).fetchone()
        if not row:
            return
        com_id = row[0]
        conn.execute(
            text(
                "UPDATE produtos SET categoria_produto_id = (SELECT id FROM categorias_produto WHERE codigo = 'PRODUTOS' LIMIT 1) "
                "WHERE categoria_produto_id = :com_id"
            ),
            {"com_id": com_id},
        )
        conn.execute(text("DELETE FROM categorias_produto WHERE id = :com_id"), {"com_id": com_id})


_ajustar_schema_categorias_produto()
_remover_categoria_comissionados_obsoleta()


def _ajustar_schema_vendas_prazo_condicao_catalogo() -> None:
    """Ajustes de vendas para frete/prazo/condicao e status de automacoes."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "condicoes_pagamento" in tables:
        db_seed = SessionLocal()
        try:
            from sga_financeiro.models.condicao_pagamento import CondicaoPagamento

            for _nome in ("PIX", "Boleto"):
                if not db_seed.query(CondicaoPagamento).filter(CondicaoPagamento.nome == _nome).first():
                    db_seed.add(CondicaoPagamento(nome=_nome))
            db_seed.commit()
        finally:
            db_seed.close()

    if "vendas" not in tables:
        return

    def colunas_vendas() -> set[str]:
        return {c["name"] for c in inspect(engine).get_columns("vendas")}

    with engine.begin() as conn:
        colunas = colunas_vendas()
        if "valor_frete" not in colunas:
            conn.execute(text("ALTER TABLE vendas ADD COLUMN valor_frete NUMERIC(14,2) DEFAULT 0"))
            conn.execute(text("UPDATE vendas SET valor_frete = 0 WHERE valor_frete IS NULL"))
            try:
                conn.execute(text("ALTER TABLE vendas ALTER COLUMN valor_frete SET NOT NULL"))
            except Exception:
                pass
        colunas = colunas_vendas()
        if "prazo_pagamento" not in colunas:
            if "condicao_pagamento" in colunas:
                conn.execute(text("ALTER TABLE vendas RENAME COLUMN condicao_pagamento TO prazo_pagamento"))
            else:
                conn.execute(text("ALTER TABLE vendas ADD COLUMN prazo_pagamento VARCHAR(200)"))
        colunas = colunas_vendas()
        if "condicao_pagamento_id" not in colunas:
            if "condicoes_pagamento" in tables:
                conn.execute(
                    text(
                        "ALTER TABLE vendas ADD COLUMN condicao_pagamento_id INTEGER "
                        "REFERENCES condicoes_pagamento (id)"
                    )
                )
            else:
                conn.execute(text("ALTER TABLE vendas ADD COLUMN condicao_pagamento_id INTEGER"))
        else:
            if "condicoes_pagamento" in tables:
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE vendas ADD CONSTRAINT vendas_condicao_pagamento_id_fkey "
                            "FOREIGN KEY (condicao_pagamento_id) REFERENCES condicoes_pagamento (id)"
                        )
                    )
                except Exception:
                    pass
        colunas = colunas_vendas()
        if "financeiro_gerado" not in colunas:
            conn.execute(text("ALTER TABLE vendas ADD COLUMN financeiro_gerado BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE vendas SET financeiro_gerado = FALSE WHERE financeiro_gerado IS NULL"))
        colunas = colunas_vendas()
        if "nfse_gerada" not in colunas:
            conn.execute(text("ALTER TABLE vendas ADD COLUMN nfse_gerada BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE vendas SET nfse_gerada = FALSE WHERE nfse_gerada IS NULL"))
        colunas = colunas_vendas()
        if "nfe_gerada" not in colunas:
            conn.execute(text("ALTER TABLE vendas ADD COLUMN nfe_gerada BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE vendas SET nfe_gerada = FALSE WHERE nfe_gerada IS NULL"))


try:
    _ajustar_schema_vendas_prazo_condicao_catalogo()
except Exception as exc:
    logging.getLogger(__name__).warning(
        "Ajuste schema vendas/condicoes_pagamento ignorado (app seguira sem migracao completa): %s",
        exc,
    )


def _ajustar_schema_home_evento_lembrete() -> None:
    """Cria tabela simples para evento/lembrete da tela inicial."""
    inspector = inspect(engine)
    if "home_evento_lembrete" not in inspector.get_table_names():
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE home_evento_lembrete (
                        id INTEGER PRIMARY KEY,
                        nome_evento VARCHAR(180) DEFAULT '',
                        tipo_evento VARCHAR(80) DEFAULT '',
                        mensagem TEXT DEFAULT '',
                        data_inicio DATE,
                        data_fim DATE,
                        tarefa_executada BOOLEAN DEFAULT FALSE,
                        parte_id INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO home_evento_lembrete
                    (id, nome_evento, tipo_evento, mensagem, data_inicio, data_fim, tarefa_executada, parte_id)
                    VALUES (1, '', '', '', NULL, NULL, FALSE, NULL)
                    """
                )
            )
        return
    colunas = {col["name"] for col in inspector.get_columns("home_evento_lembrete")}
    with engine.begin() as conn:
        if "nome_evento" not in colunas:
            conn.execute(text("ALTER TABLE home_evento_lembrete ADD COLUMN nome_evento VARCHAR(180) DEFAULT ''"))
        if "tipo_evento" not in colunas:
            conn.execute(text("ALTER TABLE home_evento_lembrete ADD COLUMN tipo_evento VARCHAR(80) DEFAULT ''"))
        if "mensagem" not in colunas:
            conn.execute(text("ALTER TABLE home_evento_lembrete ADD COLUMN mensagem TEXT DEFAULT ''"))
        if "data_inicio" not in colunas:
            conn.execute(text("ALTER TABLE home_evento_lembrete ADD COLUMN data_inicio DATE"))
        if "data_fim" not in colunas:
            conn.execute(text("ALTER TABLE home_evento_lembrete ADD COLUMN data_fim DATE"))
        if "tarefa_executada" not in colunas:
            conn.execute(text("ALTER TABLE home_evento_lembrete ADD COLUMN tarefa_executada BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE home_evento_lembrete SET tarefa_executada = FALSE WHERE tarefa_executada IS NULL"))
        if "parte_id" not in colunas:
            conn.execute(text("ALTER TABLE home_evento_lembrete ADD COLUMN parte_id INTEGER"))
        qtd = conn.execute(text("SELECT COUNT(1) FROM home_evento_lembrete")).scalar() or 0
        if int(qtd) == 0:
            conn.execute(
                text(
                    """
                    INSERT INTO home_evento_lembrete
                    (id, nome_evento, tipo_evento, mensagem, data_inicio, data_fim, tarefa_executada, parte_id)
                    VALUES (1, '', '', '', NULL, NULL, FALSE, NULL)
                    """
                )
            )


try:
    _ajustar_schema_home_evento_lembrete()
except Exception as exc:
    logging.getLogger(__name__).warning(
        "Ajuste schema home_evento_lembrete ignorado: %s",
        exc,
    )


def _hash_senha_usuario(senha: str) -> str:
    return hashlib.sha256((senha or "").encode("utf-8")).hexdigest()


def _mapear_usuario_sistema(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "nome": row.get("nome") or "",
        "login": row.get("login") or "",
        "perfil": row.get("perfil") or "gerencial",
        "ativo": bool(row.get("ativo") if row.get("ativo") is not None else True),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
    }


def _mapear_compra_estoque(row: dict) -> dict:
    itens_raw = row.get("itens_json")
    itens = []
    if itens_raw:
        try:
            parsed = json.loads(itens_raw)
            if isinstance(parsed, list):
                itens = parsed
        except Exception:
            itens = []
    return {
        "id": row.get("id"),
        "tipo_lancamento": row.get("tipo_lancamento") or "manual",
        "entrada_nota": bool(row.get("entrada_nota") or False),
        "compra_simples": bool(row.get("compra_simples") or False),
        "fornecedor_id": row.get("fornecedor_id"),
        "data_emissao": row.get("data_emissao").isoformat() if row.get("data_emissao") else None,
        "numero_nota": row.get("numero_nota") or "",
        "chave_nfe": row.get("chave_nfe") or "",
        "observacao": row.get("observacao") or "",
        "total": float(row.get("total") or 0),
        "itens": itens,
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
    }


def _ajustar_schema_estoque_compras() -> None:
    inspector = inspect(engine)
    if "estoque_compras" not in inspector.get_table_names():
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE estoque_compras (
                        id INTEGER PRIMARY KEY,
                        tipo_lancamento VARCHAR(20) DEFAULT 'manual',
                        entrada_nota BOOLEAN DEFAULT FALSE,
                        compra_simples BOOLEAN DEFAULT FALSE,
                        fornecedor_id INTEGER,
                        data_emissao DATE,
                        numero_nota VARCHAR(40) DEFAULT '',
                        chave_nfe VARCHAR(64) DEFAULT '',
                        observacao TEXT DEFAULT '',
                        itens_json TEXT DEFAULT '[]',
                        total NUMERIC(14,2) DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        return
    colunas = {col["name"] for col in inspector.get_columns("estoque_compras")}
    with engine.begin() as conn:
        if "tipo_lancamento" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN tipo_lancamento VARCHAR(20) DEFAULT 'manual'"))
        if "entrada_nota" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN entrada_nota BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE estoque_compras SET entrada_nota = FALSE WHERE entrada_nota IS NULL"))
        if "compra_simples" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN compra_simples BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE estoque_compras SET compra_simples = FALSE WHERE compra_simples IS NULL"))
        if "fornecedor_id" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN fornecedor_id INTEGER"))
        if "data_emissao" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN data_emissao DATE"))
        if "numero_nota" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN numero_nota VARCHAR(40) DEFAULT ''"))
        if "chave_nfe" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN chave_nfe VARCHAR(64) DEFAULT ''"))
        if "observacao" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN observacao TEXT DEFAULT ''"))
        if "itens_json" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN itens_json TEXT DEFAULT '[]'"))
        if "total" not in colunas:
            conn.execute(text("ALTER TABLE estoque_compras ADD COLUMN total NUMERIC(14,2) DEFAULT 0"))


def _ajustar_schema_estoque_ajustes() -> None:
    inspector = inspect(engine)
    if "estoque_ajustes" not in inspector.get_table_names():
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE estoque_ajustes (
                        id INTEGER PRIMARY KEY,
                        produto_id INTEGER NOT NULL,
                        novo_estoque NUMERIC(14,4) DEFAULT 0,
                        motivo TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        return
    colunas = {col["name"] for col in inspector.get_columns("estoque_ajustes")}
    with engine.begin() as conn:
        if "produto_id" not in colunas:
            conn.execute(text("ALTER TABLE estoque_ajustes ADD COLUMN produto_id INTEGER"))
        if "novo_estoque" not in colunas:
            conn.execute(text("ALTER TABLE estoque_ajustes ADD COLUMN novo_estoque NUMERIC(14,4) DEFAULT 0"))
        if "motivo" not in colunas:
            conn.execute(text("ALTER TABLE estoque_ajustes ADD COLUMN motivo TEXT DEFAULT ''"))


def _ajustar_schema_usuarios_sistema() -> None:
    inspector = inspect(engine)
    if "usuarios_sistema" not in inspector.get_table_names():
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE usuarios_sistema (
                        id INTEGER PRIMARY KEY,
                        nome VARCHAR(180) NOT NULL DEFAULT '',
                        login VARCHAR(80) NOT NULL UNIQUE,
                        senha_hash VARCHAR(128) NOT NULL,
                        perfil VARCHAR(20) NOT NULL DEFAULT 'gerencial',
                        ativo BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO usuarios_sistema (id, nome, login, senha_hash, perfil, ativo)
                    VALUES (1, 'Administrador', 'admin', :senha_hash, 'admin', TRUE)
                    """
                ),
                {"senha_hash": _hash_senha_usuario("admin123")},
            )
        return

    colunas = {col["name"] for col in inspector.get_columns("usuarios_sistema")}
    with engine.begin() as conn:
        if "nome" not in colunas:
            conn.execute(text("ALTER TABLE usuarios_sistema ADD COLUMN nome VARCHAR(180) DEFAULT ''"))
        if "perfil" not in colunas:
            conn.execute(text("ALTER TABLE usuarios_sistema ADD COLUMN perfil VARCHAR(20) DEFAULT 'gerencial'"))
            conn.execute(text("UPDATE usuarios_sistema SET perfil = 'gerencial' WHERE perfil IS NULL OR perfil = ''"))
        if "ativo" not in colunas:
            conn.execute(text("ALTER TABLE usuarios_sistema ADD COLUMN ativo BOOLEAN DEFAULT TRUE"))
            conn.execute(text("UPDATE usuarios_sistema SET ativo = TRUE WHERE ativo IS NULL"))
        qtd = conn.execute(text("SELECT COUNT(1) FROM usuarios_sistema")).scalar() or 0
        if int(qtd) == 0:
            conn.execute(
                text(
                    """
                    INSERT INTO usuarios_sistema (id, nome, login, senha_hash, perfil, ativo)
                    VALUES (1, 'Administrador', 'admin', :senha_hash, 'admin', TRUE)
                    """
                ),
                {"senha_hash": _hash_senha_usuario("admin123")},
            )


try:
    _ajustar_schema_usuarios_sistema()
except Exception as exc:
    logging.getLogger(__name__).warning(
        "Ajuste schema usuarios_sistema ignorado: %s",
        exc,
    )

try:
    _ajustar_schema_estoque_compras()
except Exception as exc:
    logging.getLogger(__name__).warning(
        "Ajuste schema estoque_compras ignorado: %s",
        exc,
    )

try:
    _ajustar_schema_estoque_ajustes()
except Exception as exc:
    logging.getLogger(__name__).warning(
        "Ajuste schema estoque_ajustes ignorado: %s",
        exc,
    )

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categorias.router, prefix=settings.API_PREFIX)
app.include_router(categorias_produto.router, prefix=settings.API_PREFIX)
app.include_router(cadastros.router, prefix=settings.API_PREFIX)
app.include_router(grupos_contas.router, prefix=settings.API_PREFIX)
app.include_router(subgrupos_contas.router, prefix=settings.API_PREFIX)
app.include_router(grupos_despesas.router, prefix=settings.API_PREFIX)
app.include_router(planos_contas.router, prefix=settings.API_PREFIX)
app.include_router(centros_custos.router, prefix=settings.API_PREFIX)
app.include_router(fornecedores.router, prefix=settings.API_PREFIX)
app.include_router(clientes.router, prefix=settings.API_PREFIX)
app.include_router(contas_correntes.router, prefix=settings.API_PREFIX)
app.include_router(cartoes_credito.router, prefix=settings.API_PREFIX)
app.include_router(contas_pagar.router, prefix=settings.API_PREFIX)
app.include_router(contas_receber.router, prefix=settings.API_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_PREFIX)
app.include_router(sistema.router, prefix=settings.API_PREFIX)
app.include_router(assistente.router, prefix=settings.API_PREFIX)
app.include_router(produtos.router, prefix=settings.API_PREFIX)
app.include_router(condicoes_pagamento.router, prefix=settings.API_PREFIX)
app.include_router(vendas.router, prefix=settings.API_PREFIX)


@app.get("/health")
def healthcheck() -> dict:
    """Endpoint simples para verificar se a API esta ativa."""
    return {"status": "ok", "app": settings.APP_NAME}


def _mapear_evento_home(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "nome_evento": row.get("nome_evento") or "",
        "tipo_evento": row.get("tipo_evento") or "",
        "mensagem": row.get("mensagem") or "",
        "data_inicio": row.get("data_inicio").isoformat() if row.get("data_inicio") else None,
        "data_fim": row.get("data_fim").isoformat() if row.get("data_fim") else None,
        "tarefa_executada": bool(row.get("tarefa_executada") or False),
        "parte_id": row.get("parte_id"),
    }


@app.get("/api/home-eventos")
def listar_home_eventos() -> list[dict]:
    """Lista eventos configurados para exibicao na home."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, nome_evento, tipo_evento, mensagem, data_inicio, data_fim, tarefa_executada, parte_id
                FROM home_evento_lembrete
                ORDER BY id DESC
                """
            )
        ).mappings().all()
    return [_mapear_evento_home(r) for r in rows]


@app.post("/api/home-eventos")
def criar_home_evento(payload: dict) -> dict:
    """Cria um novo evento para home."""
    nome_evento = str(payload.get("nome_evento") or "").strip()
    tipo_evento = str(payload.get("tipo_evento") or "").strip()
    mensagem = str(payload.get("mensagem") or "").strip()
    data_inicio = payload.get("data_inicio")
    data_fim = payload.get("data_fim")
    tarefa_executada = bool(payload.get("tarefa_executada") or False)
    parte_id = payload.get("parte_id")
    try:
        parte_id = int(parte_id) if parte_id is not None and str(parte_id).strip() else None
    except Exception:
        parte_id = None
    with engine.begin() as conn:
        next_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM home_evento_lembrete")).scalar()
        row = conn.execute(
            text(
                """
                INSERT INTO home_evento_lembrete
                (id, nome_evento, tipo_evento, mensagem, data_inicio, data_fim, tarefa_executada, parte_id)
                VALUES (:id, :nome_evento, :tipo_evento, :mensagem, :data_inicio, :data_fim, :tarefa_executada, :parte_id)
                RETURNING id
                """
            ),
            {
                "id": int(next_id or 1),
                "nome_evento": nome_evento,
                "tipo_evento": tipo_evento,
                "mensagem": mensagem,
                "data_inicio": data_inicio or None,
                "data_fim": data_fim or None,
                "tarefa_executada": tarefa_executada,
                "parte_id": parte_id,
            },
        ).mappings().first()
    return {"ok": True, "id": row.get("id") if row else None}


@app.put("/api/home-eventos/{evento_id}")
def atualizar_home_evento(evento_id: int, payload: dict) -> dict:
    """Atualiza evento existente da home."""
    nome_evento = str(payload.get("nome_evento") or "").strip()
    tipo_evento = str(payload.get("tipo_evento") or "").strip()
    mensagem = str(payload.get("mensagem") or "").strip()
    data_inicio = payload.get("data_inicio")
    data_fim = payload.get("data_fim")
    tarefa_executada = bool(payload.get("tarefa_executada") or False)
    parte_id = payload.get("parte_id")
    try:
        parte_id = int(parte_id) if parte_id is not None and str(parte_id).strip() else None
    except Exception:
        parte_id = None
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE home_evento_lembrete
                SET nome_evento = :nome_evento,
                    tipo_evento = :tipo_evento,
                    mensagem = :mensagem,
                    data_inicio = :data_inicio,
                    data_fim = :data_fim,
                    tarefa_executada = :tarefa_executada,
                    parte_id = :parte_id
                WHERE id = :evento_id
                """
            ),
            {
                "evento_id": int(evento_id),
                "nome_evento": nome_evento,
                "tipo_evento": tipo_evento,
                "mensagem": mensagem,
                "data_inicio": data_inicio or None,
                "data_fim": data_fim or None,
                "tarefa_executada": tarefa_executada,
                "parte_id": parte_id,
            },
        )
    return {"ok": True}


@app.post("/api/home-eventos/{evento_id}/executar")
def marcar_home_evento_executado(evento_id: int) -> dict:
    """Marca um evento da home como executado."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE home_evento_lembrete
                SET tarefa_executada = TRUE
                WHERE id = :evento_id
                """
            ),
            {"evento_id": int(evento_id)},
        )
    return {"ok": True}


@app.get("/api/usuarios")
def listar_usuarios_sistema() -> list[dict]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, nome, login, perfil, ativo, created_at
                FROM usuarios_sistema
                ORDER BY id ASC
                """
            )
        ).mappings().all()
    return [_mapear_usuario_sistema(r) for r in rows]


@app.post("/api/usuarios")
def criar_usuario_sistema(payload: dict) -> dict:
    nome = str(payload.get("nome") or "").strip()
    login = str(payload.get("login") or "").strip().lower()
    senha = str(payload.get("senha") or "").strip()
    perfil = str(payload.get("perfil") or "gerencial").strip().lower()
    ativo = bool(payload.get("ativo") if payload.get("ativo") is not None else True)
    if perfil not in {"admin", "gerencial"}:
        raise HTTPException(status_code=400, detail="Perfil invalido. Use admin ou gerencial.")
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do usuario e obrigatorio.")
    if not login:
        raise HTTPException(status_code=400, detail="Login do usuario e obrigatorio.")
    if len(senha) < 4:
        raise HTTPException(status_code=400, detail="Senha deve ter ao menos 4 caracteres.")
    with engine.begin() as conn:
        existente = conn.execute(
            text("SELECT id FROM usuarios_sistema WHERE lower(login) = :login LIMIT 1"),
            {"login": login},
        ).scalar()
        if existente:
            raise HTTPException(status_code=400, detail="Ja existe usuario com este login.")
        next_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM usuarios_sistema")).scalar() or 1
        conn.execute(
            text(
                """
                INSERT INTO usuarios_sistema (id, nome, login, senha_hash, perfil, ativo)
                VALUES (:id, :nome, :login, :senha_hash, :perfil, :ativo)
                """
            ),
            {
                "id": int(next_id),
                "nome": nome,
                "login": login,
                "senha_hash": _hash_senha_usuario(senha),
                "perfil": perfil,
                "ativo": ativo,
            },
        )
    return {"ok": True, "id": int(next_id)}


@app.put("/api/usuarios/{usuario_id}")
def atualizar_usuario_sistema(usuario_id: int, payload: dict) -> dict:
    nome = str(payload.get("nome") or "").strip()
    login = str(payload.get("login") or "").strip().lower()
    senha = str(payload.get("senha") or "").strip()
    perfil = str(payload.get("perfil") or "gerencial").strip().lower()
    ativo = bool(payload.get("ativo") if payload.get("ativo") is not None else True)
    if perfil not in {"admin", "gerencial"}:
        raise HTTPException(status_code=400, detail="Perfil invalido. Use admin ou gerencial.")
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do usuario e obrigatorio.")
    if not login:
        raise HTTPException(status_code=400, detail="Login do usuario e obrigatorio.")
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, perfil FROM usuarios_sistema WHERE id = :id LIMIT 1"),
            {"id": int(usuario_id)},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado.")
        existente = conn.execute(
            text("SELECT id FROM usuarios_sistema WHERE lower(login) = :login AND id <> :id LIMIT 1"),
            {"login": login, "id": int(usuario_id)},
        ).scalar()
        if existente:
            raise HTTPException(status_code=400, detail="Ja existe usuario com este login.")
        if row.get("perfil") == "admin" and perfil != "admin":
            total_admin_ativos = conn.execute(
                text("SELECT COUNT(1) FROM usuarios_sistema WHERE perfil = 'admin' AND ativo = TRUE")
            ).scalar() or 0
            if int(total_admin_ativos) <= 1:
                raise HTTPException(status_code=400, detail="Nao e permitido remover o ultimo admin ativo.")
        conn.execute(
            text(
                """
                UPDATE usuarios_sistema
                SET nome = :nome, login = :login, perfil = :perfil, ativo = :ativo
                WHERE id = :id
                """
            ),
            {"id": int(usuario_id), "nome": nome, "login": login, "perfil": perfil, "ativo": ativo},
        )
        if senha:
            if len(senha) < 4:
                raise HTTPException(status_code=400, detail="Senha deve ter ao menos 4 caracteres.")
            conn.execute(
                text("UPDATE usuarios_sistema SET senha_hash = :senha_hash WHERE id = :id"),
                {"id": int(usuario_id), "senha_hash": _hash_senha_usuario(senha)},
            )
    return {"ok": True}


@app.delete("/api/usuarios/{usuario_id}")
def excluir_usuario_sistema(usuario_id: int) -> dict:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, perfil FROM usuarios_sistema WHERE id = :id LIMIT 1"),
            {"id": int(usuario_id)},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado.")
        if row.get("perfil") == "admin":
            total_admin = conn.execute(
                text("SELECT COUNT(1) FROM usuarios_sistema WHERE perfil = 'admin'")
            ).scalar() or 0
            if int(total_admin) <= 1:
                raise HTTPException(status_code=400, detail="Nao e permitido excluir o ultimo usuario admin.")
        conn.execute(text("DELETE FROM usuarios_sistema WHERE id = :id"), {"id": int(usuario_id)})
    return {"ok": True}


@app.post("/api/usuarios/validar-admin")
def validar_senha_admin(payload: dict) -> dict:
    usuario_id = payload.get("usuario_id")
    senha = str(payload.get("senha") or "").strip()
    if usuario_id is None or not senha:
        return {"ok": False}
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, senha_hash
                FROM usuarios_sistema
                WHERE id = :id AND perfil = 'admin' AND ativo = TRUE
                LIMIT 1
                """
            ),
            {"id": int(usuario_id)},
        ).mappings().first()
    if not row:
        return {"ok": False}
    return {"ok": _hash_senha_usuario(senha) == str(row.get("senha_hash") or "")}


def _xml_local_name(tag: str) -> str:
    if "}" in str(tag):
        return str(tag).split("}", 1)[1]
    return str(tag)


def _xml_primeiro(root: ET.Element, nome: str):
    alvo = (nome or "").strip()
    if not alvo:
        return None
    for el in root.iter():
        if _xml_local_name(el.tag) == alvo:
            return el
    return None


def _xml_texto(root: ET.Element, nome: str) -> str:
    el = _xml_primeiro(root, nome)
    return (el.text or "").strip() if el is not None else ""


@app.post("/api/estoque/importar-xml")
def importar_xml_compra_estoque(arquivo: UploadFile = File(...)) -> dict:
    nome = str(arquivo.filename or "").lower()
    if not nome.endswith(".xml"):
        raise HTTPException(status_code=400, detail="Envie um arquivo XML.")
    conteudo = arquivo.file.read()
    if not conteudo:
        raise HTTPException(status_code=400, detail="Arquivo XML vazio.")
    try:
        root = ET.fromstring(conteudo)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Falha ao ler XML: {exc}") from exc

    emit = _xml_primeiro(root, "emit")
    fornecedor_nome = _xml_texto(emit, "xNome") if emit is not None else ""
    fornecedor_doc = _xml_texto(emit, "CNPJ") if emit is not None else ""
    if not fornecedor_doc and emit is not None:
        fornecedor_doc = _xml_texto(emit, "CPF")

    ide = _xml_primeiro(root, "ide")
    numero_nota = _xml_texto(ide, "nNF") if ide is not None else ""
    data_emissao = _xml_texto(ide, "dhEmi") if ide is not None else ""
    if data_emissao:
        data_emissao = data_emissao[:10]

    inf_nfe = _xml_primeiro(root, "infNFe")
    chave = ""
    if inf_nfe is not None:
        inf_id = str(inf_nfe.attrib.get("Id") or "").strip()
        chave = inf_id[3:] if inf_id.startswith("NFe") else inf_id

    itens: list[dict] = []
    total = 0.0
    for det in root.iter():
        if _xml_local_name(det.tag) != "det":
            continue
        prod = None
        for child in list(det):
            if _xml_local_name(child.tag) == "prod":
                prod = child
                break
        if prod is None:
            continue
        descricao = _xml_texto(prod, "xProd")
        quantidade = float(_xml_texto(prod, "qCom") or 0)
        valor_unitario = float(_xml_texto(prod, "vUnCom") or 0)
        valor_total = float(_xml_texto(prod, "vProd") or (quantidade * valor_unitario))
        total += valor_total
        itens.append(
            {
                "produto_id": None,
                "descricao": descricao,
                "quantidade": quantidade,
                "valor_unitario": valor_unitario,
                "total": valor_total,
            }
        )

    return {
        "fornecedor_nome": fornecedor_nome,
        "fornecedor_doc": fornecedor_doc,
        "numero_nota": numero_nota,
        "data_emissao": data_emissao,
        "chave_nfe": chave,
        "itens": itens,
        "total": total,
    }


@app.get("/api/estoque/compras")
def listar_compras_estoque() -> list[dict]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, tipo_lancamento, entrada_nota, compra_simples, fornecedor_id, data_emissao, numero_nota, chave_nfe,
                       observacao, itens_json, total, created_at
                FROM estoque_compras
                ORDER BY id DESC
                """
            )
        ).mappings().all()
    return [_mapear_compra_estoque(r) for r in rows]


@app.get("/api/estoque/posicao-atual")
def listar_posicao_atual_estoque() -> list[dict]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, itens_json
                FROM estoque_compras
                ORDER BY id ASC
                """
            )
        ).mappings().all()
        produtos = conn.execute(
            text(
                """
                SELECT id, nome, unidade
                FROM produtos
                ORDER BY id ASC
                """
            )
        ).mappings().all()
        ajustes = conn.execute(
            text(
                """
                SELECT id, produto_id, novo_estoque, motivo, created_at
                FROM estoque_ajustes
                ORDER BY created_at ASC, id ASC
                """
            )
        ).mappings().all()
    prod_map = {int(p.get("id")): p for p in produtos if p.get("id") is not None}
    saldo_map: dict[int, dict] = {}
    avulsos: dict[str, dict] = {}
    for row in rows:
        try:
            itens = json.loads(row.get("itens_json") or "[]")
        except Exception:
            itens = []
        if not isinstance(itens, list):
            continue
        for item in itens:
            if not isinstance(item, dict):
                continue
            qtd = float(item.get("quantidade") or 0)
            if qtd <= 0:
                continue
            pid = item.get("produto_id")
            if pid is not None and str(pid).strip() != "":
                try:
                    pid_int = int(pid)
                except Exception:
                    pid_int = None
                if pid_int is not None:
                    atual = saldo_map.get(pid_int) or {"produto_id": pid_int, "nome": "", "unidade": "UN", "quantidade": 0.0}
                    atual["quantidade"] = float(atual["quantidade"]) + qtd
                    p = prod_map.get(pid_int)
                    if p:
                        atual["nome"] = p.get("nome") or atual["nome"]
                        atual["unidade"] = p.get("unidade") or atual["unidade"]
                    elif not atual["nome"]:
                        atual["nome"] = str(item.get("descricao") or f"Produto {pid_int}")
                    saldo_map[pid_int] = atual
                    continue
            desc = str(item.get("descricao") or "").strip() or "Item sem descricao"
            av = avulsos.get(desc) or {"produto_id": None, "nome": desc, "unidade": "UN", "quantidade": 0.0}
            av["quantidade"] = float(av["quantidade"]) + qtd
            avulsos[desc] = av

    lista = list(saldo_map.values()) + list(avulsos.values())
    for aj in ajustes:
        pid = aj.get("produto_id")
        if pid is None:
            continue
        try:
            pid_int = int(pid)
        except Exception:
            continue
        p = prod_map.get(pid_int)
        base = saldo_map.get(pid_int) or {
            "produto_id": pid_int,
            "nome": (p.get("nome") if p else f"Produto {pid_int}"),
            "unidade": (p.get("unidade") if p else "UN"),
            "quantidade": 0.0,
        }
        base["quantidade"] = float(aj.get("novo_estoque") or 0)
        if p:
            base["nome"] = p.get("nome") or base["nome"]
            base["unidade"] = p.get("unidade") or base["unidade"]
        saldo_map[pid_int] = base
    lista = list(saldo_map.values()) + list(avulsos.values())
    lista.sort(key=lambda x: (str(x.get("nome") or "").lower(), int(x.get("produto_id") or 0)))
    return lista


@app.get("/api/estoque/ajustes")
def listar_ajustes_estoque() -> list[dict]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT a.id, a.produto_id, a.novo_estoque, a.motivo, a.created_at, p.nome AS produto_nome, p.unidade AS produto_unidade
                FROM estoque_ajustes a
                LEFT JOIN produtos p ON p.id = a.produto_id
                ORDER BY a.id DESC
                """
            )
        ).mappings().all()
    retorno = []
    for r in rows:
        retorno.append(
            {
                "id": r.get("id"),
                "produto_id": r.get("produto_id"),
                "produto_nome": r.get("produto_nome") or f"Produto {r.get('produto_id')}",
                "unidade": r.get("produto_unidade") or "UN",
                "novo_estoque": float(r.get("novo_estoque") or 0),
                "motivo": r.get("motivo") or "",
                "created_at": r.get("created_at").isoformat() if r.get("created_at") else None,
            }
        )
    return retorno


@app.post("/api/estoque/ajustes")
def criar_ajuste_estoque(payload: dict) -> dict:
    produto_id = payload.get("produto_id")
    novo_estoque = payload.get("novo_estoque")
    motivo = str(payload.get("motivo") or "").strip()
    try:
        produto_id = int(produto_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Produto invalido para ajuste.")
    try:
        novo_estoque = float(novo_estoque)
    except Exception:
        raise HTTPException(status_code=400, detail="Novo estoque invalido.")
    if novo_estoque < 0:
        raise HTTPException(status_code=400, detail="Novo estoque nao pode ser negativo.")
    if not motivo:
        raise HTTPException(status_code=400, detail="Informe o motivo do ajuste.")
    with engine.begin() as conn:
        produto_existe = conn.execute(text("SELECT id FROM produtos WHERE id = :id"), {"id": produto_id}).scalar()
        if not produto_existe:
            raise HTTPException(status_code=404, detail="Produto nao encontrado.")
        next_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM estoque_ajustes")).scalar() or 1
        conn.execute(
            text(
                """
                INSERT INTO estoque_ajustes (id, produto_id, novo_estoque, motivo, created_at)
                VALUES (:id, :produto_id, :novo_estoque, :motivo, :created_at)
                """
            ),
            {
                "id": int(next_id),
                "produto_id": produto_id,
                "novo_estoque": novo_estoque,
                "motivo": motivo,
                "created_at": datetime.now(),
            },
        )
    return {"ok": True, "id": int(next_id)}


@app.post("/api/estoque/compras")
def criar_compra_estoque(payload: dict) -> dict:
    entrada_nota = bool(payload.get("entrada_nota") or False)
    compra_simples = bool(payload.get("compra_simples") or False)
    if not entrada_nota and not compra_simples:
        raise HTTPException(status_code=400, detail="Marque Entrada de Nota ou Compra Simples.")
    tipo_lancamento = str(payload.get("tipo_lancamento") or "manual").strip().lower()
    if tipo_lancamento not in {"manual", "xml"}:
        tipo_lancamento = "manual"
    numero_nota = str(payload.get("numero_nota") or "").strip()
    data_emissao = str(payload.get("data_emissao") or "").strip()[:10] or None
    chave_nfe = str(payload.get("chave_nfe") or "").strip()
    observacao = str(payload.get("observacao") or "").strip()
    fornecedor_id = payload.get("fornecedor_id")
    try:
        fornecedor_id = int(fornecedor_id) if fornecedor_id is not None and str(fornecedor_id).strip() else None
    except Exception:
        fornecedor_id = None
    itens = payload.get("itens") if isinstance(payload.get("itens"), list) else []
    itens_norm = []
    total = 0.0
    for item in itens:
        if not isinstance(item, dict):
            continue
        qtd = float(item.get("quantidade") or 0)
        vu = float(item.get("valor_unitario") or 0)
        vt = float(item.get("total") or (qtd * vu))
        if qtd <= 0 and vt <= 0:
            continue
        itens_norm.append(
            {
                "produto_id": int(item.get("produto_id")) if item.get("produto_id") not in (None, "") else None,
                "descricao": str(item.get("descricao") or "").strip(),
                "quantidade": qtd,
                "valor_unitario": vu,
                "total": vt,
            }
        )
        total += vt
    if not itens_norm:
        raise HTTPException(status_code=400, detail="Adicione ao menos um item na compra.")

    with engine.begin() as conn:
        next_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM estoque_compras")).scalar() or 1
        conn.execute(
            text(
                """
                INSERT INTO estoque_compras
                (id, tipo_lancamento, entrada_nota, compra_simples, fornecedor_id, data_emissao, numero_nota, chave_nfe, observacao, itens_json, total, created_at)
                VALUES
                (:id, :tipo_lancamento, :entrada_nota, :compra_simples, :fornecedor_id, :data_emissao, :numero_nota, :chave_nfe, :observacao, :itens_json, :total, :created_at)
                """
            ),
            {
                "id": int(next_id),
                "tipo_lancamento": tipo_lancamento,
                "entrada_nota": entrada_nota,
                "compra_simples": compra_simples,
                "fornecedor_id": fornecedor_id,
                "data_emissao": data_emissao,
                "numero_nota": numero_nota,
                "chave_nfe": chave_nfe,
                "observacao": observacao,
                "itens_json": json.dumps(itens_norm, ensure_ascii=False),
                "total": total,
                "created_at": datetime.now(),
            },
        )
    return {"ok": True, "id": int(next_id)}


@app.put("/api/estoque/ajustes/{ajuste_id}")
def atualizar_ajuste_estoque(ajuste_id: int, payload: dict) -> dict:
    produto_id = payload.get("produto_id")
    novo_estoque = payload.get("novo_estoque")
    motivo = str(payload.get("motivo") or "").strip()
    try:
        produto_id = int(produto_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Produto invalido para ajuste.")
    try:
        novo_estoque = float(novo_estoque)
    except Exception:
        raise HTTPException(status_code=400, detail="Novo estoque invalido.")
    if novo_estoque < 0:
        raise HTTPException(status_code=400, detail="Novo estoque nao pode ser negativo.")
    if not motivo:
        raise HTTPException(status_code=400, detail="Informe o motivo do ajuste.")
    with engine.begin() as conn:
        existe = conn.execute(text("SELECT id FROM estoque_ajustes WHERE id = :id"), {"id": int(ajuste_id)}).scalar()
        if not existe:
            raise HTTPException(status_code=404, detail="Ajuste nao encontrado.")
        produto_existe = conn.execute(text("SELECT id FROM produtos WHERE id = :id"), {"id": produto_id}).scalar()
        if not produto_existe:
            raise HTTPException(status_code=404, detail="Produto nao encontrado.")
        conn.execute(
            text(
                """
                UPDATE estoque_ajustes
                SET produto_id = :produto_id, novo_estoque = :novo_estoque, motivo = :motivo
                WHERE id = :id
                """
            ),
            {
                "id": int(ajuste_id),
                "produto_id": produto_id,
                "novo_estoque": novo_estoque,
                "motivo": motivo,
            },
        )
    return {"ok": True}


@app.delete("/api/estoque/ajustes/{ajuste_id}")
def excluir_ajuste_estoque(ajuste_id: int) -> dict:
    with engine.begin() as conn:
        existe = conn.execute(text("SELECT id FROM estoque_ajustes WHERE id = :id"), {"id": int(ajuste_id)}).scalar()
        if not existe:
            raise HTTPException(status_code=404, detail="Ajuste nao encontrado.")
        conn.execute(text("DELETE FROM estoque_ajustes WHERE id = :id"), {"id": int(ajuste_id)})
    return {"ok": True}


@app.get("/")
def home_redirect() -> RedirectResponse:
    """Redireciona a raiz para o painel web principal."""
    return RedirectResponse(url="/app", status_code=307)


@app.get("/app")
def app_demo():
    """Interface web para visualizacao e testes do sistema."""
    payload = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Onix System — Painel</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Arial, sans-serif; background: #ebedf0; color: #1f2937; }
    .topbar {
      background: linear-gradient(180deg, #2f3238, #25272c);
      color: #fff;
      border-bottom: 1px solid #1f2125;
      box-shadow: 0 2px 6px rgba(0,0,0,.25);
    }
    .topbar-inner {
      max-width: 1400px;
      margin: 0 auto;
      display: flex;
      align-items: stretch;
      gap: 2px;
      overflow-x: auto;
      padding: 8px 10px;
    }
    .topbar-menu { display: flex; gap: 2px; align-items: stretch; }
    .topbar-actions {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: max-content;
      padding-left: 8px;
    }
    .theme-select {
      min-width: 150px;
      margin: 0;
      padding: 8px 10px;
      border-radius: 10px;
      font-weight: 600;
    }
    .menu-item {
      min-width: 130px;
      background: #2d3036;
      border: 1px solid #3c4048;
      border-radius: 6px;
      color: #fff;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 8px;
      cursor: pointer;
    }
    .menu-item.active { background: #1f7a53; border-color: #35b57b; }
    .menu-icon { font-size: 28px; line-height: 1; margin-bottom: 4px; }
    .menu-label { font-size: 14px; text-align: center; }
    .menu-item.menu-item-home {
      min-width: 150px;
      background: linear-gradient(180deg, #1f7a53, #155f3f);
      border-color: #2d9b69;
    }

    .container { max-width: 1400px; margin: 16px auto; padding: 0 12px 20px; }
    .tab-header {
      background: #f6f7f9;
      border: 1px solid #bfc5cf;
      border-bottom: none;
      display: inline-block;
      padding: 8px 12px;
      font-weight: bold;
      border-top-left-radius: 4px;
      border-top-right-radius: 4px;
    }
    .tab-strip {
      display: flex;
      gap: 4px;
      margin-bottom: -1px;
      flex-wrap: wrap;
    }
    .tab-btn {
      background: #f6f7f9;
      border: 1px solid #bfc5cf;
      border-bottom: none;
      padding: 8px 12px;
      font-weight: bold;
      border-top-left-radius: 4px;
      border-top-right-radius: 4px;
      cursor: pointer;
    }
    .tab-btn.active {
      background: #ffffff;
      color: #1f7a53;
      border-color: #9fb0c8;
    }
    .vertical-tab-strip {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      margin-bottom: 12px;
      justify-items: start;
      align-content: start;
    }
    .vertical-tab-strip.overlay-selector {
      position: fixed;
      top: 80px;
      left: 16px;
      z-index: 30;
      padding: 10px;
      border-radius: 12px;
      border: 1px solid #bfdbfe;
      background: rgba(255, 255, 255, 0.95);
      box-shadow: 0 16px 28px rgba(15, 23, 42, 0.22);
      max-height: 72vh;
      overflow: auto;
      backdrop-filter: blur(4px);
    }
    .vertical-tab-strip .tab-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 230px;
      min-height: 42px;
      border-bottom: 1px solid #bfc5cf;
      border-radius: 10px;
      background: var(--card-bg, #f8fafc);
      color: var(--card-fg, #1f2937);
      border-color: var(--card-border, #bfc5cf);
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
      transition: transform .18s ease, box-shadow .18s ease, background-color .18s ease, border-color .18s ease;
    }
    .vertical-tab-strip .tab-btn:hover {
      transform: translateX(4px);
      background: #ffffff;
      border-color: #8fb4ff;
      box-shadow: 0 8px 20px rgba(37, 99, 235, 0.18);
    }
    .vertical-tab-strip .tab-btn.active {
      background: linear-gradient(90deg, #e8f1ff, #ffffff);
      color: #1f4fd3;
      border-color: #5e8dff;
      box-shadow: 0 8px 20px rgba(37, 99, 235, 0.2);
    }
    .open-cards-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 10px;
      min-height: 38px;
      align-items: center;
    }
    .global-open-cards {
      position: sticky;
      top: 6px;
      z-index: 25;
      padding: 8px;
      border-radius: 12px;
      background: rgba(255,255,255,.88);
      border: 1px solid #dbeafe;
      box-shadow: 0 10px 18px rgba(30, 64, 175, 0.12);
      backdrop-filter: blur(4px);
    }
    #cadastroOpenCards,
    #faturasOpenCards,
    #financeiroOpenCards { display: none !important; }
    .open-card-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 6px 10px;
      border: 1px solid #93c5fd;
      background: #eff6ff;
      color: #1e3a8a;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 4px 10px rgba(30, 64, 175, 0.15);
      transition: transform .18s ease, box-shadow .18s ease, background-color .18s ease;
    }
    .open-card-pill:hover {
      transform: translateY(-1px);
      box-shadow: 0 8px 14px rgba(30, 64, 175, 0.22);
    }
    .open-card-pill.active {
      background: linear-gradient(90deg, #2563eb, #1d4ed8);
      color: #fff;
      border-color: #1d4ed8;
      box-shadow: 0 10px 18px rgba(37, 99, 235, 0.35);
    }
    .open-card-pill .close-open-card {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      border: 1px solid rgba(255,255,255,.45);
      background: rgba(255,255,255,.18);
      color: inherit;
      font-size: 12px;
      line-height: 1;
      cursor: pointer;
      padding: 0;
    }
    .open-card-pill:not(.active) .close-open-card {
      border-color: rgba(30, 58, 138, .28);
      background: rgba(30, 58, 138, .08);
    }
    .tab-btn.card-geral,
    .tab-btn.card-pessoas,
    .tab-btn.card-produtos,
    .tab-btn.card-catprod,
    .tab-btn.card-condpag,
    .tab-btn.card-grupo,
    .tab-btn.card-plano,
    .tab-btn.card-grupocontas,
    .tab-btn.card-contas {
      --card-bg:#ffffff;
      --card-border:#60a5fa;
      --card-fg:#1e3a8a;
    }
    .board {
      border: 1px solid #bfc5cf;
      background: #dfe3e8;
      padding: 12px;
    }
    .section-card {
      background: #f4f6f9;
      border: 1px solid #c8cdd6;
      margin-bottom: 12px;
      border-radius: 6px;
      overflow: hidden;
    }
    .section-title {
      background: #d7dce3;
      padding: 8px 10px;
      border-bottom: 1px solid #c2c8d1;
      font-weight: bold;
      font-size: 14px;
    }
    .section-body { padding: 10px; }
    .grid-kpi { display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 10px; }
    .kpi-box {
      background: #fff;
      border: 1px solid #c8cdd6;
      border-radius: 6px;
      padding: 10px;
    }
    .kpi-label { font-size: 12px; color: #4b5563; text-transform: uppercase; }
    .kpi-value { font-size: 26px; color: #1d4ed8; font-weight: bold; margin-top: 4px; }
    .home-layout {
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
      align-items: start;
    }
    .home-toolbar {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      margin-bottom: 10px;
      position: relative;
    }
    .home-gear-btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      border-radius: 10px;
      font-weight: 700;
      border: 1px solid #60a5fa;
      background: #ffffff;
      color: #1e3a8a;
      cursor: pointer;
      box-shadow: 0 4px 10px rgba(30, 64, 175, 0.12);
    }
    .home-gear-btn:hover {
      box-shadow: 0 10px 20px rgba(30, 64, 175, 0.2);
      transform: translateY(-1px);
    }
    .home-evento-aviso-overlay {
      position: fixed;
      inset: 0;
      z-index: 80;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(15, 23, 42, 0.45);
      padding: 14px;
    }
    .home-evento-aviso-card {
      width: min(860px, 96vw);
      background: #ffffff;
      border: 2px solid #60a5fa;
      border-radius: 14px;
      box-shadow: 0 24px 44px rgba(15, 23, 42, 0.32);
      padding: 16px;
    }
    .home-evento-aviso-topo {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
    }
    .home-evento-close {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      border: 1px solid #bfdbfe;
      background: #eff6ff;
      color: #1e3a8a;
      cursor: pointer;
      font-weight: 700;
    }
    .home-evento-item {
      border: 1px solid #93c5fd;
      border-radius: 10px;
      background: #f8fbff;
      padding: 10px;
      margin-bottom: 10px;
    }
    .home-config-btn {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 8px;
      padding: 10px 12px;
      border-radius: 8px;
      transition: transform .18s ease, box-shadow .18s ease;
    }
    .home-config-btn:hover {
      transform: translateY(-1px);
      box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
    }
    .home-forecast-card .kpi-value { color: #0f766e; }
    .layout-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 22px; align-items: start; }
    .estoque-top-row { display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: end; }
    .estoque-top-row .btn-row { margin-bottom: 8px; }
    .estoque-flags-row {
      display: flex;
      align-items: center;
      gap: 18px;
      flex-wrap: wrap;
      margin: 2px 0 10px;
      padding: 8px 10px;
      border: 1px solid #dbe4ff;
      border-radius: 8px;
      background: #f8fbff;
    }
    .estoque-flags-row .fin-check-inline { margin: 0; }
    .forms-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(320px,1fr)); gap: 10px; }
    .inner-card {
      background: #fff;
      border: 1px solid #d2d7df;
      border-radius: 6px;
      padding: 10px;
    }
    .inner-title {
      font-weight: bold;
      font-size: 14px;
      margin-bottom: 8px;
      color: #1f2937;
    }
    table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d2d7df; }
    th, td { border-bottom: 1px solid #e5e7eb; padding: 7px; font-size: 13px; text-align: left; }
    th { background: #f4f5f7; }
    input {
      width: 100%;
      border: 1px solid #cdd3dc;
      border-radius: 4px;
      padding: 7px;
      margin-top: 2px;
      margin-bottom: 8px;
      background: #fff;
    }
    select {
      width: 100%;
      border: 1px solid #cdd3dc;
      border-radius: 4px;
      padding: 7px;
      margin-top: 2px;
      margin-bottom: 8px;
      background: #fff;
    }
    .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .btn-row { display: flex; gap: 8px; flex-wrap: wrap; }
    .btn-kebab { min-width: 34px; padding: 6px 10px; }
    .section-card.section-card-vendas { overflow: visible; }
    td.venda-acoes-cell { position: relative; overflow: visible; white-space: nowrap; }
    .venda-menu-popover {
      position: fixed;
      min-width: 190px;
      border: 1px solid #d1d5db;
      background: #fff;
      border-radius: 6px;
      box-shadow: 0 8px 18px rgba(0,0,0,.18);
      z-index: 2147483647;
      padding: 6px;
      display: grid;
      gap: 6px;
    }
    .venda-status-tags { display: flex; gap: 8px; align-items: center; white-space: nowrap; }
    .venda-status-item { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 700; color: #374151; }
    .venda-status-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      display: inline-block;
      border: 1px solid rgba(17,24,39,.22);
      background: #ef4444;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.2);
    }
    .venda-status-dot.ok { background: #16a34a; }
    .venda-status-dot.pend { background: #ef4444; }
    .venda-menu-popover button {
      width: 100%;
      text-align: left;
      padding: 7px 10px;
    }
    button {
      border: 1px solid #1f63d1;
      background: #2563eb;
      color: #fff;
      border-radius: 4px;
      padding: 8px 12px;
      cursor: pointer;
      font-weight: bold;
    }
    button.alt { background: #374151; border-color: #374151; }
    .status-line { min-height: 18px; font-size: 12px; }
    .ok { color: #047857; }
    .err { color: #b91c1c; }
    .muted { color: #6b7280; font-size: 12px; }
    .tag {
      display: inline-block;
      background: #e5e7eb;
      border-radius: 999px;
      font-size: 11px;
      padding: 2px 8px;
    }
    .hidden { display: none; }
    .check-row { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin: 6px 0 10px; }
    .check-item { display: flex; gap: 6px; align-items: center; font-size: 13px; }
    .check-item input { width: auto; margin: 0; }
    .input-with-action { display: grid; grid-template-columns: 1fr auto; gap: 6px; align-items: end; }
    .btn-icon { min-width: 38px; padding: 8px 10px; }
    .search-row { display: grid; grid-template-columns: 1fr auto auto; gap: 6px; align-items: end; margin-bottom: 8px; }
    .result-box {
      margin-top: 6px;
      border: 1px solid #d1d5db;
      background: #fff;
      border-radius: 4px;
      max-height: 170px;
      overflow: auto;
    }
    .result-item {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      padding: 6px 8px;
      border-bottom: 1px solid #eef2f7;
      font-size: 13px;
    }
    .result-item:last-child { border-bottom: none; }
    .chat-box {
      background: #ffffff;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      min-height: 280px;
      max-height: 440px;
      overflow: auto;
      padding: 10px;
      margin-bottom: 10px;
    }
    .chat-msg {
      margin-bottom: 8px;
      padding: 8px 10px;
      border-radius: 8px;
      font-size: 13px;
      white-space: pre-wrap;
      line-height: 1.35;
    }
    .chat-msg.user {
      background: #dbeafe;
      border: 1px solid #bfdbfe;
    }
    .chat-msg.ai {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
    }
    textarea {
      width: 100%;
      border: 1px solid #cdd3dc;
      border-radius: 4px;
      padding: 8px;
      background: #fff;
      resize: vertical;
    }
    .modal-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,.45);
      z-index: 9999;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .modal-overlay.hidden { display: none; }
    .modal-box {
      width: min(820px, 94vw);
      background: #fff;
      border-radius: 8px;
      border: 1px solid #cdd3dc;
      box-shadow: 0 12px 32px rgba(0,0,0,.3);
      max-height: 92vh;
      display: flex;
      flex-direction: column;
    }
    .modal-box.modal-box--finance {
      width: min(940px, 96vw);
    }
    .modal-box.modal-box--pedido-venda {
      width: min(1090px, 98vw);
      max-height: calc(92vh - 10px);
    }
    table.ven-itens-pedido {
      width: 100%;
      table-layout: fixed;
      border-collapse: collapse;
    }
    table.ven-itens-pedido th,
    table.ven-itens-pedido td {
      padding: 6px 8px;
      vertical-align: middle;
    }
    table.ven-itens-pedido th:nth-child(1),
    table.ven-itens-pedido td:nth-child(1) { width: 32%; }
    table.ven-itens-pedido th:nth-child(2),
    table.ven-itens-pedido td:nth-child(2) { width: 10%; }
    table.ven-itens-pedido th:nth-child(3),
    table.ven-itens-pedido td:nth-child(3) { width: 15%; }
    table.ven-itens-pedido th:nth-child(4),
    table.ven-itens-pedido td:nth-child(4) { width: 14%; }
    table.ven-itens-pedido th:nth-child(5),
    table.ven-itens-pedido td:nth-child(5) { width: 15%; }
    table.ven-itens-pedido th:nth-child(6),
    table.ven-itens-pedido td:nth-child(6) {
      width: 14%;
      min-width: 96px;
      text-align: center;
      white-space: nowrap;
    }
    table.ven-itens-pedido td:nth-child(6) button {
      padding: 6px 10px;
      font-size: 12px;
    }
    .ven-inp-frete {
      max-width: 130px;
      width: 100%;
      box-sizing: border-box;
      text-align: right;
    }
    table.ven-itens-pedido .ven-inp-compact {
      width: 100%;
      max-width: 100%;
      box-sizing: border-box;
      text-align: right;
    }
    table.ven-itens-pedido select.ven-sel-produto {
      width: 100%;
      max-width: 100%;
      box-sizing: border-box;
    }
    #modalFinanceiro .fin-modal-parte {
      display: block;
      margin-bottom: 4px;
      padding-bottom: 14px;
      border-bottom: 1px solid #e2e8f0;
    }
    #modalFinanceiro .fin-parte-titulo {
      display: block;
      margin-bottom: 8px;
    }
    #modalFinanceiro .fin-parte-linha {
      display: grid;
      grid-template-columns: minmax(140px, 220px) 1fr;
      gap: 4px 12px;
      align-items: end;
    }
    #modalFinanceiro .fin-parte-linha.fin-parte-linha--sem-codigo {
      grid-template-columns: 1fr;
    }
    #modalFinanceiro .fin-parte-codigo .input-with-action,
    #modalFinanceiro .fin-parte-nome .input-with-action {
      max-width: none;
    }
    #modalFinanceiro .fin-parte-codigo label,
    #modalFinanceiro .fin-parte-nome label {
      font-size: 11px;
      margin-bottom: 4px;
    }
    @media (max-width: 640px) {
      #modalFinanceiro .fin-parte-linha:not(.fin-parte-linha--sem-codigo) {
        grid-template-columns: 1fr;
      }
    }
    #modalFinanceiro .fin-modal-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px 12px;
      align-items: start;
    }
    #modalFinanceiro .fin-modal-col {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }
    #modalFinanceiro .fin-modal-col > label {
      margin: 0;
    }
    #modalFinanceiro .fin-modal-col input,
    #modalFinanceiro .fin-modal-col select {
      margin-top: 0;
      margin-bottom: 0;
      width: 100%;
    }
    #modalFinanceiro .fin-modal-col .input-with-action {
      margin-bottom: 0;
    }
    #modalFinanceiro .fin-top-bar {
      padding: 12px 14px;
      margin-bottom: 14px;
    }
    #modalFinanceiro .fin-pay-flags {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 18px 28px;
      margin-bottom: 2px;
    }
    #modalFinanceiro .fin-check-inline {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 600;
      color: var(--text, #0f172a);
      text-transform: none;
      letter-spacing: 0;
      cursor: pointer;
      margin: 0;
    }
    #modalFinanceiro .fin-check-inline input {
      width: auto;
      margin: 0;
      cursor: pointer;
    }
    #modalFinanceiro .fin-cartao-linha {
      margin-top: 10px;
      max-width: 420px;
    }
    #modalFinanceiro .fin-cartao-linha label {
      margin-bottom: 4px;
    }
    #modalFinanceiro .fin-liquidacao-linha {
      margin-top: 10px;
      max-width: 420px;
    }
    #modalFinanceiro .fin-liquidacao-linha label {
      margin-bottom: 4px;
    }
    #modalFinanceiro input.fin-input-calculado:disabled {
      opacity: 0.52;
      cursor: not-allowed;
    }
    #modalFinanceiro #tbParcelasFinanceiro input.fin-parcela-data-cartao:disabled {
      opacity: 0.52;
      cursor: not-allowed;
    }
    .modal-box > div:last-child { overflow: auto; }
    tr.row-vencida td { background: #fee2e2; color: #991b1b; }
    tr.row-selected td { background: #dbeafe; }

    /* Tema visual moderno */
    :root {
      --bg-0: #f4f7ff;
      --bg-1: #eef2ff;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --line: #dbe3f0;
      --text: #0f172a;
      --muted: #64748b;
      --primary: #2563eb;
      --primary-600: #1d4ed8;
      --danger-bg: #fef2f2;
      --danger-text: #b91c1c;
      --shadow-soft: 0 10px 24px rgba(15, 23, 42, 0.06);
      --row-hover: #f8fbff;
      --focus-ring: 0 0 0 3px rgba(96, 165, 250, .2);
      --radius-xl: 16px;
      --radius-lg: 12px;
      --radius-md: 10px;
      --radius-sm: 8px;
      --panel-accent: #2563eb;
      --panel-accent-soft: rgba(37, 99, 235, .18);
    }

    body {
      background: radial-gradient(circle at top right, var(--bg-1), var(--bg-0) 55%);
      color: var(--text);
      font-family: "Inter", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      letter-spacing: 0.01em;
      line-height: 1.45;
    }
    .topbar {
      background: linear-gradient(110deg, #0b1220 0%, #16233b 45%, #0a1120 100%);
      border-bottom: 1px solid #111827;
      box-shadow: 0 10px 30px rgba(8, 15, 32, 0.38);
    }
    .topbar-inner { padding: 10px 12px; gap: 6px; }
    .topbar-menu { gap: 6px; }
    .menu-item {
      min-width: 136px;
      background: linear-gradient(180deg, rgba(255,255,255,0.09), rgba(255,255,255,0.04));
      border: 1px solid rgba(148, 163, 184, 0.28);
      border-radius: var(--radius-md);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 4px 14px rgba(2, 6, 23, .22);
      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease;
    }
    .menu-item:hover {
      transform: translateY(-2px);
      background: linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.08));
      border-color: rgba(147, 197, 253, 0.55);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.12), 0 10px 22px rgba(2, 6, 23, .28);
    }
    .menu-item.active {
      background: linear-gradient(135deg, #2563eb, #1d4ed8 55%, #1e40af);
      border-color: #60a5fa;
      box-shadow: 0 12px 24px rgba(37, 99, 235, .45), inset 0 1px 0 rgba(255,255,255,.2);
    }
    .menu-icon { font-size: 24px; margin-bottom: 5px; filter: drop-shadow(0 2px 6px rgba(0,0,0,.25)); }
    .menu-label { font-size: 13px; font-weight: 700; letter-spacing: .02em; }
    .container {
      margin-top: 20px;
      max-width: min(96vw, 1720px);
    }
    .container::before {
      content: "";
      position: fixed;
      inset: auto auto -140px -140px;
      width: 360px;
      height: 360px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(37,99,235,.22), rgba(37,99,235,0));
      pointer-events: none;
      z-index: 0;
    }
    .tab-btn {
      border-radius: var(--radius-md) var(--radius-md) 0 0;
      border: 1px solid var(--line);
      background: var(--surface-soft);
      font-weight: 700;
    }
    .tab-btn.active {
      background: var(--surface);
      color: var(--primary-600);
      border-color: #bfdbfe;
      box-shadow: 0 -2px 0 #60a5fa inset, 0 6px 18px rgba(59, 130, 246, .16);
    }
    .board {
      border: 1px solid var(--line);
      border-radius: var(--radius-xl);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.76), rgba(255, 255, 255, 0.62));
      backdrop-filter: blur(7px);
      box-shadow: 0 14px 34px rgba(15, 23, 42, .08);
      padding: 14px;
      position: relative;
      overflow: hidden;
    }
    .board::after {
      content: "";
      position: absolute;
      top: -120px;
      right: -120px;
      width: 260px;
      height: 260px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(148, 197, 255, .25), rgba(148, 197, 255, 0));
      pointer-events: none;
    }
    .section-card {
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
      background: var(--surface);
      transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
    }
    .section-card:hover {
      transform: translateY(-2px);
      border-color: #bfdbfe;
      box-shadow: 0 18px 32px rgba(30, 41, 59, 0.12);
    }
    .section-title {
      background: linear-gradient(180deg, #f8fafc, #eff6ff);
      border-bottom: 1px solid var(--line);
      color: #1e3a8a;
      letter-spacing: .3px;
      font-size: 13px;
      text-transform: uppercase;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .section-title::before {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: linear-gradient(180deg, color-mix(in srgb, var(--panel-accent) 65%, #ffffff), var(--panel-accent));
      box-shadow: 0 0 0 4px var(--panel-accent-soft);
      flex-shrink: 0;
    }
    .section-title-icon {
      width: 20px;
      height: 20px;
      border-radius: 6px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      background: color-mix(in srgb, var(--panel-accent) 16%, #ffffff);
      border: 1px solid color-mix(in srgb, var(--panel-accent) 45%, #ffffff);
      color: color-mix(in srgb, var(--panel-accent) 70%, #0f172a);
      box-shadow: 0 4px 10px color-mix(in srgb, var(--panel-accent) 28%, transparent);
    }
    .inner-card {
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: linear-gradient(180deg, #ffffff, #fbfdff);
      box-shadow: 0 6px 16px rgba(30, 41, 59, .05);
    }
    .inner-title {
      color: #1e293b;
      font-weight: 800;
      letter-spacing: .01em;
    }
    input, select {
      border: 1px solid #cbd5e1;
      border-radius: var(--radius-sm);
      transition: border-color .15s ease, box-shadow .15s ease;
      background: rgba(255, 255, 255, .92);
    }
    input:focus, select:focus {
      outline: none;
      border-color: #60a5fa;
      box-shadow: var(--focus-ring);
    }
    label { font-size: 12px; letter-spacing: .2px; color: var(--muted); font-weight: 700; text-transform: uppercase; }
    .section-body, .inner-card { padding: 14px; }
    .btn-row { gap: 10px; }
    button { font-size: 13px; letter-spacing: .15px; }
    th, td { padding: 9px 10px; }
    button {
      border: 1px solid var(--primary-600);
      border-radius: var(--radius-sm);
      background: linear-gradient(180deg, var(--primary), var(--primary-600));
      box-shadow: 0 4px 10px rgba(37, 99, 235, .25);
      transition: all .15s ease;
    }
    button:hover { transform: translateY(-1px); filter: brightness(1.06); box-shadow: 0 8px 16px rgba(37, 99, 235, .32); }
    button:active { transform: translateY(0); }
    .theme-select { border-radius: var(--radius-sm); border-color: rgba(148, 163, 184, .6); background: rgba(255,255,255,.92); }
    button.alt {
      background: linear-gradient(180deg, #475569, #334155);
      border-color: #334155;
      box-shadow: 0 4px 10px rgba(51, 65, 85, .24);
    }
    table {
      border-radius: var(--radius-md);
      overflow: hidden;
      border: 1px solid var(--line);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.8);
    }
    th {
      background: #f8fafc;
      color: #334155;
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 1;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    td { border-bottom: 1px solid #edf2f7; }
    tr:hover td { background: var(--row-hover); }
    .muted { color: var(--muted); font-weight: 500; }
    .modal-overlay { background: rgba(15, 23, 42, .58); }
    .modal-box {
      border-radius: var(--radius-xl);
      border: 1px solid #d6deec;
      box-shadow: 0 24px 48px rgba(15, 23, 42, .35);
      backdrop-filter: blur(6px);
    }
    .global-open-cards {
      border-radius: var(--radius-lg);
      border-color: #c7ddff;
      background: linear-gradient(180deg, rgba(255,255,255,.9), rgba(241,246,255,.86));
      box-shadow: 0 14px 28px rgba(37, 99, 235, .12);
    }
    .open-card-pill {
      border-radius: 999px;
      padding: 7px 12px;
      background: linear-gradient(90deg, #eff6ff, #e0edff);
      border-color: #93c5fd;
    }
    .open-card-pill.active {
      background: linear-gradient(90deg, #2563eb, #1d4ed8 65%, #1e40af);
      box-shadow: 0 10px 18px rgba(37, 99, 235, 0.4);
    }
    .vertical-tab-strip.overlay-selector {
      border-color: #bfdbfe;
      box-shadow: 0 0 0 1px rgba(96, 165, 250, .28), 0 12px 28px rgba(37, 99, 235, .22);
      background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(244,249,255,.94));
    }
    .vertical-tab-strip .tab-btn {
      font-weight: 700;
      letter-spacing: .01em;
    }
    .vertical-tab-strip .tab-btn:hover {
      transform: translateX(5px) scale(1.01);
    }
    .vertical-tab-strip .tab-btn.active {
      box-shadow: 0 0 0 1px rgba(96,165,250,.4), 0 10px 24px rgba(37,99,235,.24);
    }
    .kpi-box {
      border-radius: var(--radius-md);
      box-shadow: 0 8px 18px rgba(30, 41, 59, .08);
      background: linear-gradient(180deg, #ffffff, #f9fbff);
    }
    .kpi-value { text-shadow: 0 2px 10px rgba(37, 99, 235, .15); }
    #onixHomePanel { --panel-accent: #2563eb; --panel-accent-soft: rgba(37, 99, 235, .18); }
    #cadastroPanel { --panel-accent: #0ea5e9; --panel-accent-soft: rgba(14, 165, 233, .18); }
    #dashboardPanel { --panel-accent: #6366f1; --panel-accent-soft: rgba(99, 102, 241, .18); }
    #faturasPanel { --panel-accent: #8b5cf6; --panel-accent-soft: rgba(139, 92, 246, .18); }
    #vendasPanel { --panel-accent: #0f766e; --panel-accent-soft: rgba(15, 118, 110, .18); }
    #estoquePanel { --panel-accent: #2563eb; --panel-accent-soft: rgba(37, 99, 235, .18); }
    #contadorPanel { --panel-accent: #0891b2; --panel-accent-soft: rgba(8, 145, 178, .18); }
    #relatoriosPanel { --panel-accent: #1d4ed8; --panel-accent-soft: rgba(29, 78, 216, .18); }
    #onixIaPanel { --panel-accent: #7c3aed; --panel-accent-soft: rgba(124, 58, 237, .18); }
    .tag {
      background: linear-gradient(180deg, #eef2ff, #dbeafe);
      color: #1e3a8a;
      font-weight: 700;
      border: 1px solid #bfdbfe;
    }
    .status-line {
      padding-left: 2px;
      font-weight: 600;
      letter-spacing: .01em;
    }
    tr.row-vencida td {
      background: var(--danger-bg);
      color: var(--danger-text);
      border-bottom-color: #fecaca;
    }
    tr.row-selected td { background: #e0ecff; }
    .cc-saldo-negativo {
      color: #dc2626;
      font-weight: 700;
    }
    .cc-total-destaque {
      font-size: 1.5rem;
      line-height: 1;
      font-weight: 800;
      padding: 10px 14px;
    }
    .cc-total-label {
      color: #111111;
    }
    .cc-total-valor-positivo {
      color: var(--primary-600);
    }
    .cc-total-valor-negativo {
      color: #dc2626;
    }

    body[data-theme="dark"] {
      --bg-0: #020617;
      --bg-1: #0f172a;
      --surface: #0f172a;
      --surface-soft: #111827;
      --line: #243244;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --primary: #3b82f6;
      --primary-600: #2563eb;
      --danger-bg: #3f1d1d;
      --danger-text: #fecaca;
      --shadow-soft: 0 14px 28px rgba(0, 0, 0, 0.35);
      --row-hover: #172033;
      --focus-ring: 0 0 0 3px rgba(59, 130, 246, .25);
    }
    body[data-theme="dark"] .topbar {
      background: linear-gradient(110deg, #020617 0%, #0b1220 45%, #111827 100%);
      border-bottom-color: #1e293b;
    }
    body[data-theme="dark"] .menu-item {
      background: rgba(148, 163, 184, 0.08);
      border-color: rgba(148, 163, 184, 0.2);
      color: #e2e8f0;
    }
    body[data-theme="dark"] .menu-item:hover {
      background: rgba(148, 163, 184, 0.16);
    }
    body[data-theme="dark"] .board {
      background: rgba(2, 6, 23, 0.75);
    }
    body[data-theme="dark"] .board::after {
      background: radial-gradient(circle, rgba(59,130,246,.25), rgba(59,130,246,0));
    }
    body[data-theme="dark"] .section-card:hover {
      border-color: #3b82f6;
      box-shadow: 0 20px 34px rgba(2, 6, 23, .48);
    }
    body[data-theme="dark"] .global-open-cards {
      background: linear-gradient(180deg, rgba(15,23,42,.9), rgba(2,6,23,.88));
      border-color: #334155;
    }
    body[data-theme="dark"] .open-card-pill {
      background: linear-gradient(90deg, #1e293b, #1e3a8a);
      border-color: #3b82f6;
      color: #dbeafe;
    }
    body[data-theme="dark"] .open-card-pill.active {
      background: linear-gradient(90deg, #2563eb, #1e40af);
    }
    body[data-theme="dark"] .vertical-tab-strip.overlay-selector {
      background: linear-gradient(180deg, rgba(15,23,42,.96), rgba(2,6,23,.95));
      border-color: #334155;
      box-shadow: 0 0 0 1px rgba(59,130,246,.28), 0 14px 30px rgba(2,6,23,.62);
    }
    body[data-theme="dark"] .section-title {
      background: linear-gradient(180deg, #0f172a, #111827);
      color: #bfdbfe;
    }
    body[data-theme="dark"] .inner-card {
      background: linear-gradient(180deg, #0b1220, #0f172a);
    }
    body[data-theme="dark"] input,
    body[data-theme="dark"] select {
      background: #0b1220;
      color: #e2e8f0;
      border-color: #334155;
    }
    body[data-theme="dark"] table {
      background: #0b1220;
      border-color: #243244;
    }
    body[data-theme="dark"] th {
      background: #111827;
      color: #cbd5e1;
      border-bottom-color: #243244;
    }
    body[data-theme="dark"] td { border-bottom-color: #1e293b; }
    body[data-theme="dark"] .modal-overlay { background: rgba(2, 6, 23, .72); }
    body[data-theme="dark"] .modal-box {
      border-color: #243244;
      background: #0f172a;
    }
    body[data-theme="dark"] #modalFinanceiro .fin-modal-parte {
      border-bottom-color: #334155;
    }
    body[data-theme="dark"] #modalFinanceiro .fin-check-inline {
      color: #e2e8f0;
    }
    .tag-cartao-fatura {
      display: inline-block;
      max-width: 260px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      vertical-align: middle;
      font-weight: 600;
    }
    body[data-theme="dark"] .tag {
      background: linear-gradient(180deg, #1e293b, #172033);
      border-color: #334155;
      color: #bfdbfe;
    }
    body[data-theme="dark"] .theme-select {
      background: rgba(15,23,42,.92);
      color: #e2e8f0;
      border-color: #334155;
    }
    body[data-theme="dark"] .section-title-icon {
      background: color-mix(in srgb, var(--panel-accent) 20%, #0f172a);
      border-color: color-mix(in srgb, var(--panel-accent) 45%, #334155);
      color: #dbeafe;
    }
    body[data-theme="dark"] .cc-total-valor-positivo { color: #93c5fd; }
    body[data-theme="dark"] .cc-total-valor-negativo { color: #fca5a5; }
    body[data-theme="dark"] .cc-saldo-negativo { color: #fca5a5; }
    body[data-theme="dark"] .chat-box { background: #111827; border-color: #334155; }
    body[data-theme="dark"] .chat-msg.user { background: #1e3a8a; border-color: #1d4ed8; color: #dbeafe; }
    body[data-theme="dark"] .chat-msg.ai { background: #1f2937; border-color: #334155; color: #e5e7eb; }
    body[data-theme="dark"] textarea { background: #0f172a; border-color: #334155; color: #e5e7eb; }

    .board,
    .section-card,
    .open-card-pill,
    .menu-item,
    button,
    input,
    select {
      animation: uiFadeUp .22s ease both;
    }
    @keyframes uiFadeUp {
      from {
        opacity: 0;
        transform: translateY(4px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .board,
      .section-card,
      .open-card-pill,
      .menu-item,
      button,
      input,
      select {
        animation: none !important;
        transition: none !important;
      }
    }

    @media (max-width: 980px) {
      .layout-2 { grid-template-columns: 1fr; }
    }
    @media (min-width: 1680px) {
      .topbar-inner { max-width: 1760px; }
      .container { max-width: 1760px; padding: 0 16px 26px; }
      .board { padding: 16px; }
      .section-card { margin-bottom: 14px; }
      .grid-kpi { grid-template-columns: repeat(3, minmax(240px, 1fr)); }
    }
  </style>
</head>
<body>
  <script>
  (function() {
    function showErr(msg) {
      var el = document.getElementById('__sgaJsErrBar');
      if (!el) {
        el = document.createElement('div');
        el.id = '__sgaJsErrBar';
        el.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:2147483647;background:#991b1b;color:#fecaca;padding:10px 14px;font:13px Arial,sans-serif;white-space:pre-wrap;max-height:35vh;overflow:auto;box-shadow:0 -4px 16px rgba(0,0,0,.35);display:flex;gap:12px;align-items:flex-start;justify-content:space-between';
        document.body.appendChild(el);
      }
      while (el.firstChild) el.removeChild(el.firstChild);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = 'Fechar';
      btn.style.cssText = 'flex-shrink:0;padding:6px 12px;cursor:pointer;font-weight:bold;border-radius:4px;border:1px solid #fecaca;background:#7f1d1d;color:#fecaca;font:13px Arial,sans-serif';
      btn.onclick = function() {
        if (el && el.parentNode) el.parentNode.removeChild(el);
      };
      var span = document.createElement('span');
      span.style.flex = '1';
      span.textContent = 'Erro JavaScript (interface pode nao responder): ' + msg;
      el.appendChild(btn);
      el.appendChild(span);
    }
    function navFallback(dest) {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pFat = document.getElementById('faturasPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pIa = document.getElementById('onixIaPanel');
      function hideAll() {
        if (pHome) pHome.classList.add('hidden');
        if (pCad) pCad.classList.add('hidden');
        if (pRel) pRel.classList.add('hidden');
        if (pFat) pFat.classList.add('hidden');
        if (pVendas) pVendas.classList.add('hidden');
        if (pEstoque) pEstoque.classList.add('hidden');
        if (pContador) pContador.classList.add('hidden');
        if (pDash) pDash.classList.add('hidden');
        if (pIa) pIa.classList.add('hidden');
      }
      var mh = document.getElementById('menuOnixHome');
      var mc = document.getElementById('menuCadastro');
      var mf = document.getElementById('menuFinanceiro');
      var mr = document.getElementById('menuRelatorios');
      var mfat = document.getElementById('menuFaturas');
      var mv = document.getElementById('menuVendas');
      var me = document.getElementById('menuEstoque');
      var mcont = document.getElementById('menuContador');
      var mia = document.getElementById('menuOnixIa');
      function clearActive() {
        if (mh) mh.classList.remove('active');
        if (mc) mc.classList.remove('active');
        if (mf) mf.classList.remove('active');
        if (mr) mr.classList.remove('active');
        if (mfat) mfat.classList.remove('active');
        if (mv) mv.classList.remove('active');
        if (me) me.classList.remove('active');
        if (mcont) mcont.classList.remove('active');
        if (mia) mia.classList.remove('active');
      }
      if (dest === 'onixhome') {
        if (!pHome) return;
        hideAll();
        pHome.classList.remove('hidden');
        clearActive();
        if (mh) mh.classList.add('active');
        if (typeof window.carregarIndicadoresOnixHome === 'function') {
          window.carregarIndicadoresOnixHome();
        }
        return;
      }
      if (dest === 'cadastro') {
        if (!pCad || !pDash) return;
        hideAll();
        pCad.classList.remove('hidden');
        clearActive();
        if (mc) mc.classList.add('active');
        var ag = document.getElementById('abaGeral');
        var ap = document.getElementById('abaPessoas');
        var agg = document.getElementById('abaGrupoDespesas');
        var apl = document.getElementById('abaPlanoContas');
        var agc = document.getElementById('abaGrupoContas');
        var acc = document.getElementById('abaContasCorrentes');
        var apr = document.getElementById('abaProdutos');
        var apc = document.getElementById('abaCategoriasProduto');
        var acp = document.getElementById('abaCondPag');
        var b1 = document.getElementById('abaBtnGeral');
        var b2 = document.getElementById('abaBtnPessoas');
        var b7 = document.getElementById('abaBtnProdutos');
        var b8 = document.getElementById('abaBtnCatProd');
        var bcp = document.getElementById('abaBtnCondPag');
        var b3 = document.getElementById('abaBtnGrupo');
        var b4 = document.getElementById('abaBtnPlano');
        var b5 = document.getElementById('abaBtnGrupoContas');
        var b6 = document.getElementById('abaBtnContas');
        if (ag) ag.classList.remove('hidden');
        if (ap) ap.classList.add('hidden');
        if (apr) apr.classList.add('hidden');
        if (apc) apc.classList.add('hidden');
        if (acp) acp.classList.add('hidden');
        if (agg) agg.classList.add('hidden');
        if (apl) apl.classList.add('hidden');
        if (agc) agc.classList.add('hidden');
        if (acc) acc.classList.add('hidden');
        if (b1) b1.classList.add('active');
        if (b2) b2.classList.remove('active');
        if (b7) b7.classList.remove('active');
        if (b8) b8.classList.remove('active');
        if (bcp) bcp.classList.remove('active');
        if (b3) b3.classList.remove('active');
        if (b4) b4.classList.remove('active');
        if (b5) b5.classList.remove('active');
        if (b6) b6.classList.remove('active');
        return;
      }
      if (dest === 'financeiro') {
        if (!pDash) return;
        hideAll();
        pDash.classList.remove('hidden');
        clearActive();
        if (mf) mf.classList.add('active');
        return;
      }
      if (dest === 'relatorios') {
        if (!pRel || !pDash) return;
        hideAll();
        pRel.classList.remove('hidden');
        clearActive();
        if (mr) mr.classList.add('active');
        return;
      }
      if (dest === 'faturas') {
        if (!pFat || !pDash) return;
        hideAll();
        pFat.classList.remove('hidden');
        clearActive();
        if (mfat) mfat.classList.add('active');
        return;
      }
      if (dest === 'vendas') {
        if (!pVendas || !pDash) return;
        hideAll();
        pVendas.classList.remove('hidden');
        clearActive();
        if (mv) mv.classList.add('active');
        return;
      }
      if (dest === 'estoque') {
        if (!pEstoque || !pDash) return;
        hideAll();
        pEstoque.classList.remove('hidden');
        clearActive();
        if (me) me.classList.add('active');
        return;
      }
      if (dest === 'contador') {
        if (!pContador || !pDash) return;
        hideAll();
        pContador.classList.remove('hidden');
        clearActive();
        if (mcont) mcont.classList.add('active');
        return;
      }
      if (dest === 'onixia') {
        if (!pIa || !pDash) return;
        hideAll();
        pIa.classList.remove('hidden');
        clearActive();
        if (mia) mia.classList.add('active');
      }
    }

    window.__sgaIrCadastro = function() {
      try {
        if (typeof window.abrirCadastro === 'function') {
          window.abrirCadastro();
        } else {
          navFallback('cadastro');
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaIrOnixHome = function() {
      try {
        if (typeof window.abrirOnixHome === 'function') {
          window.abrirOnixHome();
        } else {
          navFallback('onixhome');
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaIrFinanceiro = function() {
      try {
        if (typeof window.abrirFinanceiro === 'function') {
          window.abrirFinanceiro();
        } else {
          navFallback('financeiro');
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaIrRelatorios = function() {
      try {
        if (typeof window.abrirRelatorios === 'function') {
          window.abrirRelatorios();
        } else {
          navFallback('relatorios');
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaIrFaturas = function() {
      try {
        if (typeof window.abrirFaturas === 'function') {
          window.abrirFaturas();
        } else {
          navFallback('faturas');
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaIrOnixIa = function() {
      try {
        if (typeof window.abrirOnixIa === 'function') {
          window.abrirOnixIa();
        } else {
          navFallback('onixia');
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaIrEstoque = function() {
      try {
        if (typeof window.abrirEstoque === 'function') {
          window.abrirEstoque();
        } else {
          navFallback('estoque');
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaIrContador = function() {
      try {
        if (typeof window.abrirEspacoContador === 'function') {
          window.abrirEspacoContador();
        } else {
          navFallback('contador');
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaIrVendas = function() {
      try {
        if (typeof window.abrirVendas === 'function') {
          window.abrirVendas();
        } else {
          navFallback('vendas');
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaIrProdutos = function() {
      try {
        if (typeof window.abrirProdutos === 'function') {
          window.abrirProdutos();
        } else {
          navFallback('cadastro');
          if (typeof window.abrirAbaCadastro === 'function') {
            window.abrirAbaCadastro('produtos');
          }
        }
      } catch (e) {
        showErr(e && e.message ? e.message : String(e));
      }
    };
    window.__sgaAplicarTemaUi = function(valor) {
      if (typeof window.aplicarTema === 'function') {
        window.aplicarTema(valor);
      } else {
        document.body.setAttribute('data-theme', valor === 'dark' ? 'dark' : 'light');
      }
    };

    window.addEventListener('error', function(ev) {
      var msg = (ev && ev.message) ? ev.message : 'erro desconhecido';
      if (ev && ev.filename) {
        msg += ' @ ...' + String(ev.filename).slice(-120) + ':' + (ev.lineno != null ? ev.lineno : '?') + ':' + (ev.colno != null ? ev.colno : '?');
      }
      showErr(msg);
    });
    window.addEventListener('unhandledrejection', function(ev) {
      var r = ev && ev.reason;
      var msg = r && r.message ? r.message : String(r || 'Promise rejeitada');
      if (r && r.stack) {
        msg += '\\n' + String(r.stack).slice(0, 1200);
      }
      showErr(msg);
    });
  })();
  </script>
  <div class="topbar">
    <div class="topbar-inner">
      <div class="topbar-menu">
        <div id="menuOnixHome" class="menu-item menu-item-home active" onclick="__sgaIrOnixHome()"><div class="menu-icon">🏠</div><div class="menu-label">Onix Home</div></div>
        <div id="menuCadastro" class="menu-item" onclick="__sgaIrCadastro()"><div class="menu-icon">🧾</div><div class="menu-label">Cadastro</div></div>
        <div id="menuFinanceiro" class="menu-item" onclick="__sgaIrFinanceiro()"><div class="menu-icon">🏦</div><div class="menu-label">Financeiro</div></div>
        <div id="menuRelatorios" class="menu-item" onclick="__sgaIrRelatorios()"><div class="menu-icon">📊</div><div class="menu-label">Relatorios</div></div>
        <div id="menuFaturas" class="menu-item" onclick="__sgaIrFaturas()"><div class="menu-icon">💳</div><div class="menu-label">Faturas</div></div>
        <div id="menuVendas" class="menu-item" onclick="__sgaIrVendas()"><div class="menu-icon">🛒</div><div class="menu-label">Vendas</div></div>
        <div id="menuEstoque" class="menu-item" onclick="__sgaIrEstoque()"><div class="menu-icon">📦</div><div class="menu-label">Estoque</div></div>
        <div id="menuContador" class="menu-item" onclick="__sgaIrContador()"><div class="menu-icon">🧮</div><div class="menu-label">Espaco Contador</div></div>
        <div id="menuOnixIa" class="menu-item" onclick="__sgaIrOnixIa()"><div class="menu-icon">🤖</div><div class="menu-label">Onix_ia</div></div>
      </div>
      <div class="topbar-actions">
        <select id="themeSelect" class="theme-select" onchange="__sgaAplicarTemaUi(this.value)">
          <option value="light">Tema Claro</option>
          <option value="dark">Tema Escuro</option>
        </select>
      </div>
    </div>
  </div>

  <div class="container">
    <div id="globalOpenCards" class="open-cards-strip global-open-cards hidden"></div>
    <div id="homeEventoAviso" class="home-evento-aviso-overlay hidden">
      <div class="home-evento-aviso-card">
        <div class="home-evento-aviso-topo" style="margin-bottom:10px;">
          <div class="inner-title" style="margin:0;">Avisos de Eventos</div>
          <button class="home-evento-close" type="button" title="Fechar todos os avisos nesta sessao" onclick="fecharAvisoEventoHome()">x</button>
        </div>
        <div id="homeEventosAvisoLista"></div>
      </div>
    </div>
    <div id="onixHomePanel">
      <div class="home-toolbar">
        <button id="btnHomeConfiguracoes" class="home-gear-btn" type="button">⚙ Configuracoes</button>
      </div>
      <div class="tab-strip vertical-tab-strip hidden" id="homeConfigSelector">
        <div id="homeCfgEmpresa" data-aba="empresa" class="tab-btn card-pessoas" role="button" tabindex="0">Cadastro de Empresa</div>
        <div id="homeCfgBanco" data-aba="banco" class="tab-btn card-geral" role="button" tabindex="0">Configurar Banco (Instalacao)</div>
        <div id="homeCfgNfe" data-aba="nfe" class="tab-btn card-catprod" role="button" tabindex="0">Configurar NF-e A1</div>
        <div id="homeCfgAtualizacoes" data-aba="atualizacoes" class="tab-btn card-plano" role="button" tabindex="0">Atualizacoes do Sistema</div>
        <div id="homeCfgEvento" data-aba="evento" class="tab-btn card-produtos" role="button" tabindex="0">Configurar Evento</div>
        <div id="homeCfgBackup" data-aba="backup" class="tab-btn card-condpag" role="button" tabindex="0">Fazer Backup</div>
        <div id="homeCfgRestore" data-aba="restore" class="tab-btn card-grupo" role="button" tabindex="0">Restaurar Backup</div>
      </div>
      <input id="restoreFileInputHome" type="file" accept=".db" class="hidden" onchange="restaurarBackup(this)" />
      <div class="board">
        <div class="home-layout">
          <div class="section-card">
            <div class="section-title">Onix Home — Dashboard</div>
            <div class="section-body">
              <div class="grid-kpi">
                <div class="kpi-box">
                  <div class="kpi-label">Contas a pagar da semana</div>
                  <div id="homePagarSemana" class="kpi-value">R$ 0,00</div>
                </div>
                <div class="kpi-box">
                  <div class="kpi-label">Contas a receber da semana</div>
                  <div id="homeReceberSemana" class="kpi-value">R$ 0,00</div>
                </div>
                <div class="kpi-box home-forecast-card">
                  <div class="kpi-label">Previsao de caixa para sexta-feira</div>
                  <div id="homePrevisaoSexta" class="kpi-value">R$ 0,00</div>
                </div>
              </div>
              <div id="statusHomeDashboard" class="status-line muted" style="margin-top:10px;"></div>
              <div id="statusHomeConfig" class="status-line muted" style="margin-top:10px;"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div id="cadastroPanel" class="hidden">
      <div id="cadastroOpenCards" class="open-cards-strip hidden"></div>
      <div class="tab-strip vertical-tab-strip">
        <div id="abaBtnGeral" data-aba="geral" class="tab-btn card-geral active" role="button" tabindex="0">Geral</div>
        <div id="abaBtnPessoas" data-aba="pessoas" class="tab-btn card-pessoas" role="button" tabindex="0">Pessoas</div>
        <div id="abaBtnProdutos" data-aba="produtos" class="tab-btn card-produtos" role="button" tabindex="0">Produtos</div>
        <div id="abaBtnCatProd" data-aba="catProd" class="tab-btn card-catprod" role="button" tabindex="0">Cat. Prod.</div>
        <div id="abaBtnCondPag" data-aba="condPag" class="tab-btn card-condpag" role="button" tabindex="0">Cond. Pag.</div>
        <div id="abaBtnGrupo" data-aba="grupo" class="tab-btn card-grupo" role="button" tabindex="0">Grupo de Despesas</div>
        <div id="abaBtnPlano" data-aba="plano" class="tab-btn card-plano" role="button" tabindex="0">Plano de Contas</div>
        <div id="abaBtnGrupoContas" data-aba="grupoContas" class="tab-btn card-grupocontas" role="button" tabindex="0">Grupo de Contas</div>
        <div id="abaBtnContas" data-aba="contas" class="tab-btn card-contas" role="button" tabindex="0">Contas Correntes</div>
        <div id="abaBtnUsuarios" data-aba="usuarios" class="tab-btn card-geral" role="button" tabindex="0">Usuarios e Permissoes</div>
      </div>
      <div class="board">
        <div id="abaGeral">
          <div class="section-card">
            <div class="section-title">Geral</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Acoes gerais de cadastro</div>
                <div class="btn-row">
                  <button type="button" onclick="void abrirModalNovoCadastro('geral')">＋ Cadastro de Empresas</button>
                  <button type="button" onclick="abrirModalNfeConfig()">⚙ Configurar NF-e (A1)</button>
                  <button type="button" onclick="fazerBackup()">⬇ Fazer Backup</button>
                  <button class="alt" type="button" onclick="document.getElementById('restoreFileInput').click()">⟲ Restaurar Backup</button>
                  <button class="alt" type="button" title="Remove do banco contas pagas, recebidas e faturas pagas" onclick="excluirHistoricosLiquidados()">Limpar pagos/recebidos</button>
                  <input id="restoreFileInput" type="file" accept=".db" class="hidden" onchange="restaurarBackup(this)" />
                </div>
                <div id="statusGeral" class="status-line muted" style="margin-top:8px;"></div>
                <div id="dadosEmpresaPadrao" class="muted" style="margin-top:10px;"></div>
              </div>
            </div>
          </div>
        </div>

        <div id="abaPessoas" class="hidden">
        <div class="section-card section-card-vendas">
          <div class="section-title">Ultimos Cadastros</div>
          <div class="section-body">
            <div class="search-row">
              <input id="cadBusca" placeholder="Pesquisar por razao social ou CNPJ" onkeydown="if(event.key==='Enter'){event.preventDefault();pesquisarCadastros();}" />
              <button class="btn-icon" type="button" onclick="pesquisarCadastros()">🔍</button>
              <button class="alt" type="button" onclick="listarCadastros()">Limpar</button>
            </div>
            <div class="btn-row" style="margin-bottom:8px;">
              <button type="button" onclick="void abrirModalNovoCadastro('pessoas')">＋ Novo Cadastro</button>
              <button type="button" onclick="abrirModalEdicao()">✎ Editar selecionado</button>
              <button class="alt" type="button" onclick="excluirCadastroSelecionado()">🗑 Excluir selecionado</button>
              <button class="alt" onclick="voltarDashboard()">Voltar para Dashboard</button>
            </div>
            <div id="statusCadastro" class="status-line muted"></div>
            <table>
              <thead><tr><th>Sel.</th><th>ID</th><th>Razao Social</th><th>Cidade/UF</th><th>Nome Fantasia</th><th>CNPJ/CPF</th><th>Telefone</th><th>CEP</th></tr></thead>
              <tbody id="tbCadastros"></tbody>
            </table>
          </div>
        </div>
        </div>

        <div id="abaProdutos" class="hidden">
          <div class="section-card">
            <div class="section-title">Produtos e Servicos</div>
            <div class="section-body">
              <div class="btn-row" style="margin-bottom:8px;">
                <button type="button" onclick="void abrirModalProduto()">＋ Novo Produto/Servico</button>
                <button class="alt" type="button" onclick="void listarProdutosPainel()">Atualizar lista</button>
                <button class="alt" type="button" onclick="voltarDashboard()">Voltar para Dashboard</button>
              </div>
              <div id="statusProdutosCadastro" class="status-line muted"></div>
              <table>
                <thead><tr><th>ID</th><th>Nome</th><th>SKU</th><th>Categoria</th><th>Preco venda</th><th>NCM</th><th>CFOP venda</th><th>CSOSN</th><th>Acao</th></tr></thead>
                <tbody id="tbProdutosCadastro"></tbody>
              </table>
            </div>
          </div>
        </div>

        <div id="abaCategoriasProduto" class="hidden">
          <div class="section-card">
            <div class="section-title">Categorias de Produto</div>
            <div class="section-body">
              <div class="muted" style="margin-bottom:8px;">Selecione uma linha (radio), depois Editar ou Excluir. Categorias padrao nao podem ser excluidas. Nome padrao nao pode ser alterado; comissao sim.</div>
              <div class="btn-row" style="margin-bottom:8px;">
                <button type="button" onclick="void abrirModalEdicaoCategoriaProduto()">✎ Editar selecionado</button>
                <button class="alt" type="button" onclick="void excluirCategoriaProdutoSelecionada()">🗑 Excluir selecionado</button>
                <button class="alt" type="button" onclick="void listarCategoriasProdutoPainel()">Atualizar lista</button>
                <button class="alt" type="button" onclick="voltarDashboard()">Voltar para Dashboard</button>
              </div>
              <div id="statusCategoriasProduto" class="status-line muted"></div>
              <table>
                <thead><tr><th>Sel.</th><th>Codigo</th><th>Nome</th><th>Comissao (%)</th></tr></thead>
                <tbody id="tbCategoriasProduto"></tbody>
              </table>
            </div>
          </div>
        </div>

        <div id="abaCondPag" class="hidden">
          <div class="section-card">
            <div class="section-title">Condicoes de Pagamento</div>
            <div class="section-body">
              <div class="muted" style="margin-bottom:8px;">Padrao: PIX e Boleto. Cadastre outras formas e selecione-as no pedido de venda.</div>
              <div class="btn-row" style="margin-bottom:8px;">
                <button type="button" onclick="void abrirModalNovaCondicaoPagamento()">＋ Novo</button>
                <button type="button" onclick="void abrirModalEdicaoCondicaoPagamento()">✎ Editar selecionado</button>
                <button class="alt" type="button" onclick="void excluirCondicaoPagamentoSelecionada()">🗑 Excluir selecionado</button>
                <button class="alt" type="button" onclick="void listarCondicoesPagamentoPainel()">Atualizar lista</button>
                <button class="alt" type="button" onclick="voltarDashboard()">Voltar para Dashboard</button>
              </div>
              <div id="statusCondicoesPagamento" class="status-line muted"></div>
              <table>
                <thead><tr><th>Sel.</th><th>ID</th><th>Nome</th></tr></thead>
                <tbody id="tbCondicoesPagamento"></tbody>
              </table>
            </div>
          </div>
        </div>

        <div id="abaGrupoDespesas" class="hidden">
          <div class="section-card">
            <div class="section-title">Grupo de Despesas</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Ultimos grupos cadastrados</div>
                <div class="btn-row" style="margin-bottom:8px;">
                  <button type="button" onclick="abrirModalNovoGrupoDespesa()">＋ Novo Cadastro</button>
                  <button type="button" onclick="abrirModalEdicaoGrupoDespesa()">✎ Editar selecionado</button>
                  <button class="alt" type="button" onclick="excluirGrupoDespesa()">🗑 Excluir selecionado</button>
                </div>
                <div id="statusGrupoDespesa" class="status-line muted"></div>
                <table>
                  <thead><tr><th>Sel.</th><th>ID</th><th>Nome</th></tr></thead>
                  <tbody id="tbGrupoDespesas"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        <div id="abaPlanoContas" class="hidden">
          <div class="section-card">
            <div class="section-title">Plano de Contas</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Ultimos planos cadastrados</div>
                <div class="btn-row" style="margin-bottom:8px;">
                  <button type="button" onclick="abrirModalNovoPlanoConta()">＋ Novo Cadastro</button>
                  <button type="button" onclick="abrirModalEdicaoPlanoConta()">✎ Editar selecionado</button>
                  <button class="alt" type="button" onclick="excluirPlanoConta()">🗑 Excluir selecionado</button>
                </div>
                <div id="statusPlanoConta" class="status-line muted"></div>
                <table>
                  <thead><tr><th>Sel.</th><th>ID</th><th>Nome</th></tr></thead>
                  <tbody id="tbPlanosContas"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        <div id="abaGrupoContas" class="hidden">
          <div class="section-card">
            <div class="section-title">Grupo de Contas</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Cadastro de grupos</div>
                <div class="btn-row" style="margin-bottom:8px;">
                  <button type="button" onclick="abrirModalNovoGrupoConta()">＋ Novo Cadastro</button>
                  <button type="button" onclick="abrirModalEdicaoGrupoConta()">✎ Editar selecionado</button>
                  <button class="alt" type="button" onclick="excluirGrupoConta()">🗑 Excluir selecionado</button>
                </div>
                <div id="statusGrupoConta" class="status-line muted"></div>
                <table>
                  <thead><tr><th>Sel.</th><th>ID</th><th>Nome</th></tr></thead>
                  <tbody id="tbGruposContas"></tbody>
                </table>
              </div>
            </div>
          </div>

          <div class="section-card">
            <div class="section-title">Subgrupo de Contas</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Cadastro de subgrupos</div>
                <div id="grupoContaSelecionadoInfo" class="muted" style="margin-bottom:8px;">Selecione um grupo para listar os subgrupos.</div>
                <div class="btn-row" style="margin-bottom:8px;">
                  <button type="button" onclick="abrirModalNovoSubgrupoConta()">＋ Novo Cadastro</button>
                  <button type="button" onclick="abrirModalEdicaoSubgrupoConta()">✎ Editar selecionado</button>
                  <button class="alt" type="button" onclick="excluirSubgrupoConta()">🗑 Excluir selecionado</button>
                </div>
                <div id="statusSubgrupoConta" class="status-line muted"></div>
                <table>
                  <thead><tr><th>Sel.</th><th>ID</th><th>Grupo</th><th>Subgrupo</th></tr></thead>
                  <tbody id="tbSubgruposContas"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        <div id="abaContasCorrentes" class="hidden">
          <div class="section-card">
            <div class="section-title">Contas Correntes</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title" style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
                  <span>Gestao de contas bancarias</span>
                  <span id="totalContasCorrentes" class="tag cc-total-destaque"><span class="cc-total-label">Total: R$ </span><span class="cc-total-valor-positivo">0,00</span></span>
                </div>
                <div class="btn-row" style="margin-bottom:8px;">
                  <button type="button" onclick="abrirModalNovaContaCorrente()">＋ Novo Cadastro</button>
                  <button type="button" onclick="abrirModalEdicaoContaCorrente()">✎ Editar selecionado</button>
                  <button class="alt" type="button" onclick="excluirContaCorrenteSelecionada()">🗑 Excluir selecionado</button>
                  <button class="alt" type="button" onclick="abrirModalTransferenciaContas()">⇄ Transferencia entre contas</button>
                </div>
                <div id="statusContasCorrentes" class="status-line muted"></div>
                <table>
                  <thead><tr><th>Sel.</th><th>ID</th><th>Banco</th><th>Agencia</th><th>Conta Corrente</th><th>Nome da Conta</th><th>Saldo</th></tr></thead>
                  <tbody id="tbContasCorrentes"></tbody>
                </table>
              </div>
            </div>
          </div>
          <div class="section-card">
            <div class="section-title">Lancamentos Pendentes</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Pendentes de conciliacao</div>
                <div class="btn-row" style="margin-bottom:8px;">
                  <button type="button" onclick="autorizarConciliacaoSelecionada()">✔ Autorizar conciliacao</button>
                </div>
                <div id="statusPendenciasConciliacao" class="status-line muted"></div>
                <table>
                  <thead><tr><th>Sel.</th><th>Data</th><th>Conta</th><th>Tipo</th><th>Descricao</th><th>Valor</th></tr></thead>
                  <tbody id="tbPendenciasConciliacao"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        <div id="abaUsuarios" class="hidden">
          <div class="section-card">
            <div class="section-title">Usuarios e Permissoes</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Sessao ativa</div>
                <div class="layout-2" style="gap:10px; align-items:end;">
                  <div>
                    <label>Usuario em uso no sistema</label>
                    <select id="sessaoUsuarioAtivo" onchange="trocarUsuarioSessao(this.value)"></select>
                  </div>
                  <div class="muted" id="sessaoPerfilInfo">Perfil atual: -</div>
                </div>
              </div>
              <div class="inner-card" style="margin-top:10px;">
                <div class="inner-title">Cadastro de usuarios</div>
                <div class="layout-2" style="gap:10px;">
                  <div>
                    <label>Nome</label>
                    <input id="usrNome" placeholder="Nome do usuario" />
                  </div>
                  <div>
                    <label>Login</label>
                    <input id="usrLogin" placeholder="login" />
                  </div>
                </div>
                <div class="layout-2" style="gap:10px;">
                  <div>
                    <label>Perfil</label>
                    <select id="usrPerfil">
                      <option value="admin">Admin</option>
                      <option value="gerencial">Gerencial</option>
                    </select>
                  </div>
                  <div>
                    <label>Senha (no editar, deixe vazio para manter)</label>
                    <input id="usrSenha" type="password" autocomplete="new-password" />
                  </div>
                </div>
                <label class="fin-check-inline" style="margin-top:8px;">
                  <input id="usrAtivo" type="checkbox" checked />
                  Usuario ativo
                </label>
                <div class="btn-row" style="margin-top:8px;">
                  <button type="button" onclick="salvarUsuarioSistema()">Salvar usuario</button>
                  <button class="alt" type="button" onclick="limparFormularioUsuarioSistema()">Limpar</button>
                  <button class="alt" type="button" onclick="listarUsuariosSistema()">Atualizar lista</button>
                </div>
                <div id="statusUsuariosSistema" class="status-line muted"></div>
                <table>
                  <thead><tr><th>Sel.</th><th>ID</th><th>Nome</th><th>Login</th><th>Perfil</th><th>Ativo</th><th>Criado em</th></tr></thead>
                  <tbody id="tbUsuariosSistema"></tbody>
                </table>
                <div class="btn-row" style="margin-top:8px;">
                  <button type="button" onclick="editarUsuarioSistemaSelecionado()">✎ Editar selecionado</button>
                  <button class="alt" type="button" onclick="excluirUsuarioSistemaSelecionado()">🗑 Excluir selecionado</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div id="relatoriosPanel" class="hidden">
      <div class="board">
        <div class="section-card">
          <div class="section-title">Relatorios do Sistema</div>
          <div class="section-body">
            <div class="inner-card">
              <div class="inner-title">Filtros e montagem de relatorio</div>
              <div class="layout-2" style="gap:10px;">
                <div>
                  <label>Tipo de Relatorio</label>
                  <select id="relTipo">
                    <option value="geral">Geral Financeiro</option>
                    <option value="pagar_abertas">Contas a Pagar (Abertas)</option>
                    <option value="receber_abertas">Contas a Receber (Abertas)</option>
                    <option value="pagas">Contas Pagas</option>
                    <option value="recebidas">Contas Recebidas</option>
                    <option value="saldos_bancos">Saldos Bancarios</option>
                    <option value="cadastros_pessoas">Cadastros - Pessoas</option>
                    <option value="produtos">Cadastro - Produtos</option>
                    <option value="vendas_pedidos">Vendas - Pedidos</option>
                    <option value="vendas_orcamentos">Vendas - Orcamentos</option>
                    <option value="vendas_nfe">Vendas - Notas NF-e</option>
                    <option value="vendas_nfse">Vendas - Notas NFS-e</option>
                    <option value="faturas_abertas">Faturas - Em Aberto</option>
                    <option value="faturas_pagas">Faturas - Pagas</option>
                    <option value="cartoes_credito">Faturas - Cartoes de Credito</option>
                    <option value="estoque_posicao">Estoque - Posicao Atual</option>
                    <option value="estoque_compras">Estoque - Compras</option>
                    <option value="estoque_ajustes">Estoque - Ajustes</option>
                    <option value="usuarios_sistema">Usuarios do Sistema</option>
                  </select>
                  <label>Data Inicial</label>
                  <input id="relDataInicio" type="date" />
                  <label>Data Final</label>
                  <input id="relDataFim" type="date" />
                  <label>Fornecedor</label>
                  <select id="relFornecedor"><option value="">Todos</option></select>
                </div>
                <div>
                  <label>Cliente</label>
                  <select id="relCliente"><option value="">Todos</option></select>
                  <label>Banco / Conta Corrente</label>
                  <select id="relContaCorrente"><option value="">Todas</option></select>
                  <label>Status</label>
                  <select id="relStatus">
                    <option value="">Todos</option>
                    <option value="pendente">Pendente</option>
                    <option value="vencido">Vencido</option>
                    <option value="pago">Pago</option>
                    <option value="recebido">Recebido</option>
                  </select>
                  <label>Texto (descricao/produto/motivo)</label>
                  <input id="relTextoLivre" placeholder="Digite para filtrar" />
                </div>
              </div>
              <div class="btn-row" style="margin-top:10px;">
                <button type="button" onclick="window.gerarRelatorioFinanceiro(true)">📊 Gerar Relatorio</button>
                <button class="alt" type="button" onclick="limparFiltrosRelatorio()">Limpar Filtros</button>
                <button class="alt" type="button" onclick="exportarRelatorioPDF()">⬇ Exportar PDF</button>
              </div>
              <div id="statusRelatorios" class="status-line muted" style="margin-top:8px;"></div>
            </div>
          </div>
        </div>
        <div class="section-card">
          <div class="section-title">Resultado</div>
          <div class="section-body">
            <table>
              <thead>
                <tr id="relatorioHeadRow">
                  <th>Tipo</th><th>ID</th><th>Parte/Conta</th><th>Descricao</th><th>Vencimento</th><th>Baixa/Receb.</th><th>Status</th><th>Conta Corrente</th><th>Valor</th>
                </tr>
              </thead>
              <tbody id="tbRelatoriosFinanceiro"></tbody>
            </table>
            <div class="muted" id="resumoRelatorioFinanceiro" style="margin-top:8px;">Total: R$ 0,00 | Registros: 0</div>
          </div>
        </div>
      </div>
    </div>

    <div id="faturasPanel" class="hidden">
      <div id="faturasOpenCards" class="open-cards-strip hidden"></div>
      <div class="tab-strip vertical-tab-strip">
        <div id="fatAbaCartoes" data-aba="cartoes" class="tab-btn card-produtos active" role="button" tabindex="0">Cartoes de Credito</div>
        <div id="fatAbaFaturasLista" data-aba="faturas" class="tab-btn card-catprod" role="button" tabindex="0">Faturas em Aberto</div>
        <div id="fatAbaFaturasPagas" data-aba="faturasPagas" class="tab-btn card-condpag" role="button" tabindex="0">Faturas Pagas</div>
      </div>
      <div class="board">
        <div id="fatConteudoCartoes">
          <div class="section-card">
            <div class="section-title">Cartoes de credito</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Cadastro de cartoes</div>
                <div class="btn-row" style="margin-bottom:8px;">
                  <button type="button" onclick="abrirModalCartaoCredito(null)">＋ Novo cartao</button>
                  <button type="button" onclick="abrirModalCartaoCreditoEditar()">✎ Editar selecionado</button>
                  <button class="alt" type="button" onclick="excluirCartaoCreditoSelecionado()">🗑 Excluir selecionado</button>
                  <button class="alt" type="button" onclick="voltarDashboard()">Voltar para Dashboard</button>
                </div>
                <div id="statusCartoesCreditoPainel" class="status-line muted"></div>
                <table>
                  <thead><tr><th>Sel.</th><th>ID</th><th>Banco</th><th>Nome da conta</th><th>Fechamento (dia)</th><th>Vencimento (dia)</th><th>Limite</th><th>Saldo usado</th><th>Ativo</th></tr></thead>
                  <tbody id="tbCartoesCreditoPainel"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
        <div id="fatConteudoFaturas" class="hidden">
          <div class="section-card">
            <div class="section-title">Faturas de cartao</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Em aberto — vencimento previsto e data de registro da fatura</div>
                <div class="btn-row" style="margin-bottom:8px;">
                  <button class="alt" type="button" onclick="listarFaturasCartaoPainel()">Atualizar lista</button>
                  <button class="alt" type="button" onclick="voltarDashboard()">Voltar para Dashboard</button>
                </div>
                <div id="statusFaturasCartaoPainel" class="status-line muted"></div>
                <table>
                  <thead><tr><th>ID</th><th>Cartao</th><th>Mes ref.</th><th>Vencimento</th><th>Registro</th><th>Valor</th><th>Status</th><th>Acao</th></tr></thead>
                  <tbody id="tbFaturasCartaoPainel"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
        <div id="fatConteudoFaturasPagas" class="hidden">
          <div class="section-card">
            <div class="section-title">Faturas pagas</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Historico — consulte detalhes e lancamentos baixados</div>
                <div class="btn-row" style="margin-bottom:8px;">
                  <button class="alt" type="button" onclick="listarFaturasCartaoPainel()">Atualizar lista</button>
                  <button class="alt" type="button" onclick="voltarDashboard()">Voltar para Dashboard</button>
                </div>
                <div id="statusFaturasPagasCartaoPainel" class="status-line muted"></div>
                <table>
                  <thead><tr><th>ID</th><th>Cartao</th><th>Mes ref.</th><th>Vencimento</th><th>Registro</th><th>Pagamento</th><th>Valor</th><th>Status</th><th>Acao</th></tr></thead>
                  <tbody id="tbFaturasPagasCartaoPainel"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div id="vendasPanel" class="hidden">
      <div class="tab-strip vertical-tab-strip">
        <div id="venAbaPedidos" data-aba="pedidos" class="tab-btn card-geral active" role="button" tabindex="0">Pedidos</div>
        <div id="venAbaOrcamentos" data-aba="orcamentos" class="tab-btn card-plano" role="button" tabindex="0">Orcamentos</div>
        <div id="venAbaNfe" data-aba="nfe" class="tab-btn card-grupocontas" role="button" tabindex="0">Notas NF-e</div>
        <div id="venAbaNfse" data-aba="nfse" class="tab-btn card-contas" role="button" tabindex="0">Notas NFS-e</div>
      </div>
      <div class="board">
        <div class="section-card">
          <div class="section-title">Vendas</div>
          <div class="section-body">
            <div class="btn-row" style="margin-bottom:10px;">
              <button type="button" onclick="abrirModalNovoPedido()">＋ Novo Pedido</button>
              <button class="alt" type="button" onclick="listarVendasPainel()">Atualizar lista</button>
            </div>
            <div id="statusVendas" class="status-line muted"></div>
            <div class="inner-card" style="margin-top:12px;">
              <div class="inner-title">Pedidos cadastrados</div>
              <div style="overflow-x:auto; overflow-y:visible; position:relative; z-index:1;">
                <table>
                  <thead><tr><th>Sel.</th><th>ID</th><th>Numero</th><th>Cliente</th><th>Vendedor</th><th>Cond. pag.</th><th>Prazo</th><th>Total</th><th>Data</th><th>Status</th><th>Acao</th></tr></thead>
                  <tbody id="tbVendas"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div id="estoquePanel" class="hidden">
      <div id="estoqueOpenCards" class="open-cards-strip hidden"></div>
      <div class="tab-strip vertical-tab-strip">
        <div id="estAbaCompra" data-aba="compra" class="tab-btn card-produtos active" role="button" tabindex="0">Lancar Compra</div>
        <div id="estAbaPosicao" data-aba="posicao" class="tab-btn card-contas" role="button" tabindex="0">Posicao Atual</div>
        <div id="estAbaAjuste" data-aba="ajuste" class="tab-btn card-grupo" role="button" tabindex="0">Ajuste de Estoque</div>
      </div>
      <div class="board">
        <div id="estConteudoCompra">
          <div class="section-card">
            <div class="section-title">Estoque - Compras</div>
            <div class="section-body">
              <div class="btn-row" style="margin-bottom:10px;">
                <button type="button" onclick="abrirModalCompraEstoque()">＋ Novo Lancamento de Compra</button>
                <button class="alt" type="button" onclick="listarComprasEstoque()">Atualizar lista</button>
              </div>
              <div id="statusEstoqueCompras" class="status-line muted"></div>
              <table>
                <thead><tr><th>ID</th><th>Data</th><th>Fornecedor</th><th>Tipo</th><th>Numero nota</th><th>Total</th><th>Itens</th></tr></thead>
                <tbody id="tbEstoqueCompras"></tbody>
              </table>
            </div>
          </div>
        </div>
        <div id="estConteudoPosicao" class="hidden">
          <div class="section-card">
            <div class="section-title">Estoque - Posicao Atual</div>
            <div class="section-body">
              <div class="btn-row" style="margin-bottom:10px;">
                <button class="alt" type="button" onclick="listarPosicaoAtualEstoque()">Atualizar posicao</button>
              </div>
              <div id="statusEstoquePosicao" class="status-line muted"></div>
              <table>
                <thead><tr><th>Produto ID</th><th>Item</th><th>Unidade</th><th>Quantidade em estoque</th></tr></thead>
                <tbody id="tbEstoquePosicao"></tbody>
              </table>
            </div>
          </div>
        </div>
        <div id="estConteudoAjuste" class="hidden">
          <div class="section-card">
            <div class="section-title">Estoque - Ajuste de Estoque</div>
            <div class="section-body">
              <div class="layout-2" style="gap:10px;">
                <div>
                  <label>Produto</label>
                  <select id="estAjusteProduto"><option value="">Selecione...</option></select>
                </div>
                <div>
                  <label>Codigo do produto</label>
                  <input id="estAjusteCodigo" placeholder="ID do produto" oninput="preencherProdutoAjustePorCodigo()" />
                </div>
              </div>
              <div class="layout-2" style="gap:10px;">
                <div>
                  <label>Novo estoque</label>
                  <input id="estAjusteNovoEstoque" type="number" step="0.0001" min="0" />
                </div>
                <div>
                  <label>Motivo</label>
                  <input id="estAjusteMotivo" />
                </div>
              </div>
              <div class="btn-row" style="margin-top:8px;">
                <button type="button" onclick="salvarAjusteEstoque()">Salvar ajuste</button>
                <button type="button" onclick="editarAjusteEstoqueSelecionado()">Editar selecionado</button>
                <button class="alt" type="button" onclick="excluirAjusteEstoqueSelecionado()">Excluir selecionado</button>
                <button class="alt" type="button" onclick="listarAjustesEstoque()">Atualizar lista</button>
              </div>
              <div id="statusEstoqueAjuste" class="status-line muted"></div>
              <table>
                <thead><tr><th>Sel.</th><th>ID</th><th>Data</th><th>Produto</th><th>Novo estoque</th><th>Motivo</th></tr></thead>
                <tbody id="tbEstoqueAjustes"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div id="contadorPanel" class="hidden">
      <div id="contadorOpenCards" class="open-cards-strip hidden"></div>
      <div class="tab-strip vertical-tab-strip">
        <div id="ctrAbaChecklist" data-aba="checklist" class="tab-btn card-grupo active" role="button" tabindex="0">Checklist Mensal</div>
        <div id="ctrAbaFiscal" data-aba="fiscal" class="tab-btn card-produtos" role="button" tabindex="0">Documentos Fiscais</div>
        <div id="ctrAbaFinanceiro" data-aba="financeiro" class="tab-btn card-contas" role="button" tabindex="0">Financeiro para Contabilidade</div>
        <div id="ctrAbaEnvio" data-aba="envio" class="tab-btn card-pessoas" role="button" tabindex="0">Envio ao Contador</div>
      </div>
      <div class="board">
        <div id="ctrConteudoChecklist">
          <div class="section-card">
            <div class="section-title">Espaco Contador - Checklist Mensal</div>
            <div class="section-body">
              <div class="muted" style="margin-bottom:10px;">Use este card no inicio de cada mes para nao esquecer nenhum envio.</div>
              <div class="check-row">
                <label class="check-item"><input type="checkbox" id="ctrChkNfeXml" /> XML e PDF das NF-e emitidas/canceladas</label>
                <label class="check-item"><input type="checkbox" id="ctrChkFaturamento" /> Relatorio de faturamento mensal</label>
                <label class="check-item"><input type="checkbox" id="ctrChkExtratos" /> Extratos bancarios do periodo</label>
                <label class="check-item"><input type="checkbox" id="ctrChkPagarReceber" /> Relatorio de contas a pagar/receber</label>
              </div>
              <div id="statusContadorChecklist" class="status-line muted" style="margin-top:8px;">Checklist inicial carregado.</div>
            </div>
          </div>
        </div>
        <div id="ctrConteudoFiscal" class="hidden">
          <div class="section-card">
            <div class="section-title">Espaco Contador - Documentos Fiscais</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Arquivos normalmente solicitados</div>
                <ul class="muted" style="margin:0; padding-left:18px;">
                  <li>XML/PDF das NF-e emitidas no mes</li>
                  <li>XML/PDF de notas canceladas e inutilizacoes</li>
                  <li>Relatorio de vendas por periodo</li>
                  <li>Comprovantes de despesas com impacto fiscal</li>
                </ul>
                <div class="btn-row" style="margin-top:10px;">
                  <button type="button" onclick="baixarRelatorioVendasContador()">Baixar relatorio de vendas (CSV)</button>
                  <button class="alt" type="button" onclick="baixarRelatorioEstoqueContador()">Baixar posicao de estoque (CSV)</button>
                </div>
              </div>
              <div id="statusContadorFiscal" class="status-line muted" style="margin-top:8px;"></div>
            </div>
          </div>
        </div>
        <div id="ctrConteudoFinanceiro" class="hidden">
          <div class="section-card">
            <div class="section-title">Espaco Contador - Financeiro para Contabilidade</div>
            <div class="section-body">
              <div class="inner-card">
                <div class="inner-title">Conferencia recomendada antes do envio</div>
                <ul class="muted" style="margin:0; padding-left:18px;">
                  <li>Contas a pagar e receber conciliadas</li>
                  <li>Movimentacoes bancarias do mes fechadas</li>
                  <li>Pagamentos em cartao e PIX conferidos</li>
                  <li>Ajustes de estoque com motivo preenchido</li>
                </ul>
                <div class="btn-row" style="margin-top:10px;">
                  <button type="button" onclick="baixarRelatorioFinanceiroContador()">Baixar relatorio financeiro (CSV)</button>
                  <button class="alt" type="button" onclick="baixarRelatorioPagarContador()">Baixar contas a pagar (CSV)</button>
                  <button class="alt" type="button" onclick="baixarRelatorioReceberContador()">Baixar contas a receber (CSV)</button>
                </div>
              </div>
              <div id="statusContadorFinanceiro" class="status-line muted" style="margin-top:8px;"></div>
            </div>
          </div>
        </div>
        <div id="ctrConteudoEnvio" class="hidden">
          <div class="section-card">
            <div class="section-title">Espaco Contador - Envio ao Contador</div>
            <div class="section-body">
              <div class="layout-2" style="gap:10px;">
                <div>
                  <label>Competencia (mes/ano)</label>
                  <input id="ctrCompetencia" placeholder="Ex.: 04/2026" />
                </div>
                <div>
                  <label>Status</label>
                  <select id="ctrStatusEnvio">
                    <option value="pendente">Pendente</option>
                    <option value="enviado">Enviado</option>
                  </select>
                </div>
              </div>
              <div class="btn-row" style="margin-top:8px;">
                <button type="button" onclick="registrarStatusEnvioContador()">Atualizar status</button>
              </div>
              <div id="statusContadorEnvio" class="status-line muted"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div id="onixIaPanel" class="hidden">
      <div class="board">
        <div class="section-card">
          <div class="section-title">Onix_ia</div>
          <div class="section-body">
            <div class="inner-card">
              <div class="inner-title">Assistente inteligente do Onix System</div>
              <div id="onixIaHistorico" class="chat-box"></div>
              <label for="onixIaMensagem">Mensagem</label>
              <textarea id="onixIaMensagem" rows="4" placeholder="Ex.: liste contas a pagar dos proximos 7 dias"></textarea>
              <div class="check-row">
                <label class="check-item"><input id="onixIaConfirmar" type="checkbox" /> Confirmar execucao (acoes que gravam no banco)</label>
              </div>
              <div class="btn-row">
                <button type="button" onclick="enviarMensagemOnixIa()">Enviar</button>
                <button class="alt" type="button" onclick="limparChatOnixIa()">Limpar conversa</button>
                <button class="alt" type="button" onclick="voltarDashboard()">Voltar para Dashboard</button>
              </div>
              <div id="statusOnixIa" class="status-line muted" style="margin-top:8px;"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div id="dashboardPanel" class="hidden">
    <div id="financeiroOpenCards" class="open-cards-strip hidden"></div>
    <div class="tab-strip vertical-tab-strip">
      <div id="finAbaPagar" data-aba="pagar" class="tab-btn card-grupo active" role="button" tabindex="0">Contas a Pagar</div>
      <div id="finAbaReceber" data-aba="receber" class="tab-btn card-plano" role="button" tabindex="0">Contas a Receber</div>
      <div id="finAbaPagas" data-aba="pagas" class="tab-btn card-grupocontas" role="button" tabindex="0">Contas Pagas</div>
      <div id="finAbaRecebidas" data-aba="recebidas" class="tab-btn card-contas" role="button" tabindex="0">Contas Recebidas</div>
    </div>
    <div class="board">
      <div class="section-card">
        <div class="section-title">Acoes de Lancamento</div>
        <div class="section-body">
          <div class="btn-row">
            <button id="btnNovoLancamentoFinanceiro" type="button" onclick="abrirNovoLancamentoFinanceiro()">＋ Novo Lancamento</button>
            <button type="button" onclick="abrirModalEdicaoContaFinanceira()">✎ Editar selecionado</button>
            <button class="alt" type="button" onclick="excluirContasFinanceirasSelecionadas()">🗑 Excluir selecionados</button>
            <button id="btnBaixaFinanceiro" type="button" onclick="abrirModalBaixaContaFinanceira()">💸 Baixar/Receber selecionados</button>
          </div>
          <div id="statusFinanceiro" class="status-line muted" style="margin-top:8px;"></div>
        </div>
      </div>

      <div class="section-card">
        <div class="section-title">Parte Superior - Fornecedores/Clientes com Contas</div>
        <div class="section-body">
          <div class="search-row">
            <input id="finBuscaParteResumo" placeholder="Buscar fornecedor/cliente por nome ou codigo" oninput="renderResumoPartesFinanceiro()" />
            <button class="alt" type="button" onclick="limparFiltroParteFinanceiro()">Limpar</button>
          </div>
          <table>
            <thead><tr><th>Codigo</th><th>Nome</th><th>Quantidade de Contas</th><th>Total</th></tr></thead>
            <tbody id="tbResumoPartesFinanceiro"></tbody>
          </table>
        </div>
      </div>

      <div class="section-card">
        <div class="section-title">Parte Inferior - Contas Lancadas</div>
        <div class="section-body">
          <table>
            <thead><tr><th>Sel.</th><th>ID</th><th>Parte</th><th>Descricao</th><th>Cartao / fatura</th><th>Vencimento</th><th>Status</th><th>Valor</th></tr></thead>
            <tbody id="tbContasFinanceiro"></tbody>
          </table>
        </div>
      </div>
    </div>
    </div>
  </div>

  <div id="modalNovoPedido" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance modal-box--pedido-venda">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalPedidoVenda">Novo Pedido de Venda</strong>
        <button class="alt" type="button" onclick="fecharModalNovoPedido()">Fechar</button>
      </div>
      <div style="padding:12px; display:flex; flex-direction:column; flex:1; min-height:0;">
        <div class="form-row">
          <div><label>Cliente</label><select id="venCliente"></select></div>
          <div><label>Vendedor</label><select id="venVendedor"></select></div>
        </div>
        <div class="inner-card" style="margin-top:8px; flex:1; min-height:0; display:flex; flex-direction:column;">
          <div class="inner-title">Itens do pedido</div>
          <div style="overflow:auto; flex:1; min-height:100px;">
            <table class="ven-itens-pedido">
              <thead><tr><th>Produto</th><th>Qtd</th><th>Vlr unit. (R$)</th><th>Desc. (R$)</th><th>Total</th><th>Acao</th></tr></thead>
              <tbody id="tbItensVenda"></tbody>
            </table>
          </div>
          <div class="btn-row" style="margin-top:8px;">
            <button type="button" onclick="adicionarLinhaItemVenda()">＋ Adicionar Produto</button>
          </div>
        </div>
        <div class="form-row" style="margin-top:10px; align-items:flex-end; flex-wrap:wrap;">
          <div>
            <label for="venFrete">Frete</label>
            <input id="venFrete" type="text" class="ven-inp-frete" placeholder="R$ 0,00" autocomplete="off" />
          </div>
          <div style="flex:1; min-width:200px;">
            <label for="venCondicaoPagId">Condicao de pagamento</label>
            <select id="venCondicaoPagId"><option value="">Selecione...</option></select>
          </div>
          <div style="flex:1; min-width:220px;">
            <label for="venPrazoPag">Prazo de pagamento</label>
            <input id="venPrazoPag" type="text" placeholder="Ex.: a vista, 30/60 dias" autocomplete="off" />
          </div>
        </div>
        <label for="venObs" style="margin-top:12px;">Observacao</label>
        <textarea id="venObs" rows="3" style="width:100%; box-sizing:border-box; margin-top:4px;" placeholder="Observacoes do pedido (opcional)"></textarea>
        <div id="statusVendaModal" class="status-line muted" style="margin-top:8px;"></div>
        <div class="btn-row" style="margin-top:10px;">
          <button type="button" onclick="salvarVenda()">Salvar Pedido</button>
          <button class="alt" type="button" onclick="fecharModalNovoPedido()">Cancelar</button>
        </div>
      </div>
    </div>
  </div>

  <div id="modalProduto" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalProduto">Cadastro de Produto/Servico</strong>
        <button class="alt" type="button" onclick="fecharModalProduto()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="form-row">
          <div><label>Nome</label><input id="proNome" /></div>
          <div><label>SKU</label><input id="proSku" /></div>
        </div>
        <div class="form-row">
          <div style="flex:1;min-width:220px;"><label>Categoria</label><select id="proCategoria"></select></div>
        </div>
        <div class="form-row">
          <div><label>Preco Custo</label><input id="proPrecoCusto" type="number" step="0.01" /></div>
          <div><label>Preco Venda</label><input id="proPrecoVenda" type="number" step="0.01" /></div>
        </div>
        <div class="form-row">
          <div><label>NCM</label><input id="proNcm" /></div>
          <div><label>CEST</label><input id="proCest" /></div>
        </div>
        <div class="form-row">
          <div><label>CFOP Compra</label><input id="proCfopCompra" /></div>
          <div><label>CFOP Venda</label><input id="proCfopVenda" /></div>
        </div>
        <div class="form-row">
          <div><label>CSOSN</label><input id="proCsosn" /></div>
          <div><label>Aliq ICMS Saida (%)</label><input id="proAliqSaida" type="number" step="0.01" /></div>
        </div>
        <label>Descricao</label>
        <input id="proDescricao" />
        <div id="statusProdutoModal" class="status-line muted" style="margin-top:8px;"></div>
        <div class="btn-row" style="margin-top:10px;">
          <button type="button" onclick="salvarProduto()">Salvar Produto</button>
          <button class="alt" type="button" onclick="fecharModalProduto()">Cancelar</button>
        </div>
      </div>
    </div>
  </div>

  <div id="modalCategoriaProduto" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalCategoriaProduto">Editar Categoria</strong>
        <button class="alt" type="button" onclick="fecharModalCategoriaProduto()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <input type="hidden" id="catModalId" value="" />
        <div class="form-row">
          <div><label>Codigo</label><div id="catModalCodigo" class="muted" style="padding:8px 0;"></div></div>
        </div>
        <div class="form-row">
          <div style="flex:1;"><label>Nome</label><input id="catModalNome" /></div>
        </div>
        <div class="form-row">
          <div><label>Comissao (%)</label><input id="catModalPct" type="text" placeholder="0%" /></div>
        </div>
        <div id="statusModalCategoriaProduto" class="status-line muted" style="margin-top:8px;"></div>
        <div class="btn-row" style="margin-top:10px;">
          <button type="button" onclick="void salvarModalCategoriaProduto()">Salvar</button>
          <button class="alt" type="button" onclick="fecharModalCategoriaProduto()">Cancelar</button>
        </div>
      </div>
    </div>
  </div>

  <div id="modalEdicao" class="modal-overlay hidden">
    <div class="modal-box">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalCadastro">Editar Cadastro</strong>
        <button class="alt" type="button" onclick="fecharModalEdicao()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="form-row">
          <div>
            <label>CNPJ/CPF</label>
            <div class="input-with-action">
              <input id="editCnpj" />
              <button class="btn-icon" type="button" onclick="consultarCnpjModal()">🔎</button>
            </div>
          </div>
          <div><label>Razao Social</label><input id="editRazao" /></div>
        </div>
        <div class="form-row">
          <div><label>Cidade/UF</label><input id="editCidadeUf" placeholder="Ex.: Maringa/PR" /></div>
          <div>
            <label>Nome Fantasia</label>
            <div class="input-with-action">
              <input id="editNomeFantasia" />
              <button class="btn-icon" type="button" onclick="copiarRazaoParaFantasia()" title="Copiar Razao Social">📋</button>
            </div>
          </div>
        </div>
        <div class="form-row">
          <div><label>Telefone</label><input id="editTelefone" /></div>
          <div><label>CEP</label><input id="editCep" /></div>
        </div>
        <div id="flagsPessoaRow" class="form-row">
          <div>
            <label><input id="editIsCliente" type="checkbox" style="width:auto; margin-right:6px;" />Cliente</label>
            <label><input id="editIsFuncionario" type="checkbox" style="width:auto; margin-right:6px; margin-left:12px;" />Funcionario</label>
            <label><input id="editIsFornecedor" type="checkbox" style="width:auto; margin-right:6px; margin-left:12px;" />Fornecedor</label>
            <label><input id="editIsVendedor" type="checkbox" style="width:auto; margin-right:6px; margin-left:12px;" onchange="atualizarVisibilidadeVendedor()" />Vendedor</label>
          </div>
          <div></div>
        </div>
        <div id="vendedorExtraRow" class="form-row hidden">
          <div><label>Chave PIX</label><input id="editChavePix" /></div>
          <div>
            <label><input id="editVendedorComissionado" type="checkbox" style="width:auto; margin-right:6px;" />Comissionado</label>
          </div>
        </div>
        <label>Endereco</label>
        <input id="editEndereco" />
        <div class="btn-row">
          <button type="button" onclick="salvarCadastroModal()">Salvar alteracoes</button>
          <button class="alt" type="button" onclick="fecharModalEdicao()">Cancelar</button>
        </div>
        <div id="statusEdicao" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalCadastroBasico" class="modal-overlay hidden">
    <div class="modal-box">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalCadastroBasico">Novo Cadastro</strong>
        <button class="alt" type="button" onclick="fecharModalCadastroBasico()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <label id="rotuloModalCadastroBasico">Nome</label>
        <input id="inputModalCadastroBasico" />
        <div id="cadastroBasicoGrupoContainer" class="hidden">
          <label>Grupo de Contas</label>
          <select id="inputModalCadastroBasicoGrupoConta"></select>
        </div>
        <div class="btn-row" style="margin-top:10px;">
          <button type="button" onclick="salvarModalCadastroBasico()">Salvar alteracoes</button>
          <button class="alt" type="button" onclick="fecharModalCadastroBasico()">Cancelar</button>
        </div>
        <div id="statusModalCadastroBasico" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalContaCorrente" class="modal-overlay hidden">
    <div class="modal-box">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalContaCorrente">Nova Conta Corrente</strong>
        <button class="alt" type="button" onclick="fecharModalContaCorrente()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="form-row">
          <div><label>Banco</label><input id="ccBanco" /></div>
          <div><label>Agencia</label><input id="ccAgencia" /></div>
        </div>
        <div class="form-row">
          <div><label>Conta Corrente</label><input id="ccNumero" /></div>
          <div><label>Nome da Conta</label><input id="ccNomeConta" /></div>
        </div>
        <div class="form-row">
          <div><label>Saldo da Conta</label><input id="ccSaldo" type="number" step="0.01" value="0" /></div>
          <div></div>
        </div>
        <div class="btn-row">
          <button type="button" onclick="salvarContaCorrenteModal()">Salvar alteracoes</button>
          <button class="alt" type="button" onclick="fecharModalContaCorrente()">Cancelar</button>
        </div>
        <div id="statusModalContaCorrente" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalCartaoCredito" class="modal-overlay hidden">
    <div class="modal-box">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalCartaoCredito">Novo cartao de credito</strong>
        <button class="alt" type="button" onclick="fecharModalCartaoCredito()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="form-row">
          <div><label>Banco</label><input id="ccFatBanco" /></div>
          <div><label>Nome da conta / identificacao</label><input id="ccFatNomeConta" placeholder="Ex.: Visa corporativo" /></div>
        </div>
        <div class="form-row">
          <div><label>Ultimos 4 digitos</label><input id="ccFatUltimos" maxlength="4" placeholder="0000" /></div>
          <div><label>Limite</label><input id="ccFatLimite" type="number" step="0.01" min="0" value="0" /></div>
        </div>
        <div class="form-row">
          <div><label>Dia de fechamento (1-31)</label><input id="ccFatFechamento" type="number" min="1" max="31" value="10" /></div>
          <div><label>Dia de vencimento (1-31)</label><input id="ccFatVencimento" type="number" min="1" max="31" value="10" /></div>
        </div>
        <label style="display:flex; align-items:center; gap:8px; margin-top:8px;">
          <input id="ccFatAtiva" type="checkbox" checked />
          <span>Cartao ativo</span>
        </label>
        <div class="btn-row" style="margin-top:10px;">
          <button type="button" onclick="salvarModalCartaoCredito()">Salvar</button>
          <button class="alt" type="button" onclick="fecharModalCartaoCredito()">Cancelar</button>
        </div>
        <div id="statusModalCartaoCredito" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalPagarFaturaCartao" class="modal-overlay hidden">
    <div class="modal-box">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong>Pagar fatura do cartao</strong>
        <button class="alt" type="button" onclick="fecharModalPagarFaturaCartao()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <input id="pagarFaturaCartaoId" type="hidden" value="" />
        <label>Conta corrente (debito)</label>
        <select id="pagarFaturaContaCorrenteId"></select>
        <label style="margin-top:8px;">Data do pagamento</label>
        <input id="pagarFaturaData" type="date" />
        <div class="btn-row" style="margin-top:10px;">
          <button type="button" onclick="confirmarPagarFaturaCartao()">Confirmar pagamento</button>
          <button class="alt" type="button" onclick="fecharModalPagarFaturaCartao()">Cancelar</button>
        </div>
        <div id="statusModalPagarFaturaCartao" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalDetalheFaturaCartao" class="modal-overlay hidden">
    <div class="modal-box" style="width:min(720px,94vw);">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong>Detalhes da fatura</strong>
        <button class="alt" type="button" onclick="fecharModalDetalheFaturaCartao()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div id="detalheFaturaResumo" class="muted" style="margin-bottom:12px; line-height:1.5;"></div>
        <div class="inner-title" style="margin-bottom:6px;">Lancamentos (contas a pagar)</div>
        <table>
          <thead><tr><th>ID</th><th>Descricao</th><th>Vencimento</th><th>Valor</th><th>Status</th></tr></thead>
          <tbody id="tbDetalheFaturaLancamentos"></tbody>
        </table>
        <div id="statusModalDetalheFaturaCartao" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalTransferenciaContas" class="modal-overlay hidden">
    <div class="modal-box">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong>Transferencia entre contas</strong>
        <button class="alt" type="button" onclick="fecharModalTransferenciaContas()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="form-row">
          <div><label>Conta de Origem</label><select id="transfContaOrigem"></select></div>
          <div><label>Conta de Destino</label><select id="transfContaDestino"></select></div>
        </div>
        <div class="form-row">
          <div><label>Valor</label><input id="transfValor" type="number" step="0.01" min="0.01" /></div>
          <div><label>Motivo</label><input id="transfMotivo" /></div>
        </div>
        <div class="btn-row">
          <button type="button" onclick="confirmarTransferenciaContas()">Confirmar transferencia</button>
          <button class="alt" type="button" onclick="fecharModalTransferenciaContas()">Cancelar</button>
        </div>
        <div id="statusModalTransferenciaContas" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalEdicaoFinanceiro" class="modal-overlay hidden">
    <div class="modal-box">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalEdicaoFinanceiro">Editar Lancamento</strong>
        <button class="alt" type="button" onclick="fecharModalEdicaoContaFinanceira()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="form-row">
          <div><label>Descricao</label><input id="editFinDescricao" /></div>
          <div><label>Valor</label><input id="editFinValor" type="number" step="0.01" /></div>
        </div>
        <div class="form-row">
          <div><label>Data de Lancamento</label><input id="editFinDataVencimento" type="date" /></div>
          <div><label>Documento Original</label><input id="editFinDocumento" /></div>
        </div>
        <div class="btn-row">
          <button type="button" onclick="salvarEdicaoContaFinanceira()">Salvar alteracoes</button>
          <button class="alt" type="button" onclick="fecharModalEdicaoContaFinanceira()">Cancelar</button>
        </div>
        <div id="statusModalEdicaoFinanceiro" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalBaixaFinanceiro" class="modal-overlay hidden">
    <div class="modal-box">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalBaixaFinanceiro">Baixar Lancamento</strong>
        <button class="alt" type="button" onclick="fecharModalBaixaContaFinanceira()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="form-row">
          <div><label>Conta Corrente</label><select id="baixaContaCorrenteId"></select></div>
          <div><label>Data da Baixa</label><input id="baixaData" type="date" /></div>
        </div>
        <label>Comprovante/Observacao</label>
        <input id="baixaComprovante" />
        <div class="btn-row">
          <button id="btnConfirmarBaixaFinanceiro" type="button" onclick="confirmarBaixaContaFinanceira()">Confirmar baixa</button>
          <button class="alt" type="button" onclick="fecharModalBaixaContaFinanceira()">Cancelar</button>
        </div>
        <div id="statusModalBaixaFinanceiro" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalFinanceiro" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalFinanceiro">Novo Lancamento</strong>
        <button class="alt" type="button" onclick="fecharModalFinanceiro()">Fechar</button>
      </div>
      <div style="padding:14px 16px;">
        <div class="fin-modal-parte">
          <label id="finParteLabel" class="fin-parte-titulo">Fornecedor</label>
          <div id="finParteLinha" class="fin-parte-linha">
            <div id="finParteColCodigo" class="fin-parte-codigo">
              <label for="finParteCodigo">Codigo</label>
              <div id="finParteCodigoBox" class="input-with-action">
                <input id="finParteCodigo" placeholder="Codigo" onkeydown="if(event.key==='Enter'){event.preventDefault();buscarPartePorCodigo();}" />
                <button class="btn-icon" type="button" onclick="buscarPartePorCodigo()">↵</button>
              </div>
            </div>
            <div class="fin-parte-nome">
              <label id="finParteSublabelNome" for="finParteNome">Selecionar fornecedor</label>
              <div class="input-with-action">
                <input id="finParteNome" readonly placeholder="Buscar pela lupa" />
                <button class="btn-icon" type="button" onclick="abrirModalBuscaParte()">🔍</button>
              </div>
            </div>
          </div>
          <input id="finParteId" type="hidden" value="" />
          <div id="finParteSelecionado" class="muted" style="margin-top:8px;">Nenhum selecionado</div>
        </div>
        <div id="finTopoBar" class="inner-card fin-top-bar">
          <div class="fin-pay-flags">
            <label id="finLabelPagamentoCartao" class="fin-check-inline">
              <input id="finPagamentoCartao" type="checkbox" onchange="atualizarFormaPagamentoFinanceiro()" />
              <span>Pagamento com cartao</span>
            </label>
            <label class="fin-check-inline">
              <input id="finLiquidacaoImediata" type="checkbox" onchange="atualizarVisibilidadeLiquidacaoImediata()" />
              <span id="finLiquidacaoImediataLabel">Pagamento / recebimento imediato</span>
            </label>
            <label id="finLabelContaAPagar" class="fin-check-inline">
              <input id="finContaAPagarFlag" type="checkbox" />
              <span>Contas a Pagar</span>
            </label>
          </div>
          <div id="finCartaoCreditoLinha" class="fin-cartao-linha hidden">
            <label>Cartao de credito</label>
            <select id="finCartaoCreditoId" disabled onchange="gerarParcelasFinanceiro()"></select>
          </div>
          <div id="finLiquidacaoContaBox" class="fin-liquidacao-linha hidden">
            <label>Conta corrente (conciliacao pendente)</label>
            <select id="finLiquidacaoContaCorrenteId"></select>
          </div>
        </div>
        <div id="finCamposPagar">
          <div class="layout-2 fin-modal-grid">
            <div class="fin-modal-col">
              <label>Grupo de Despesas</label>
              <select id="finGrupoDespesaId"></select>
              <label>Descricao</label>
              <input id="finDescricao" />
              <label>Data de Emissao</label>
              <input id="finDataEmissao" type="date" onchange="gerarParcelasFinanceiro()" />
              <label>Data de Vencimento</label>
              <input id="finDataVencimento" type="date" onchange="gerarParcelasFinanceiro()" />
              <label>Plano de Contas</label>
              <select id="finPlanoContaId"></select>
            </div>
            <div class="fin-modal-col">
              <label>Grupo de Contas</label>
              <select id="finGrupoContaId" onchange="carregarSubgruposFinanceiro()"></select>
              <label>Subgrupo de Contas</label>
              <select id="finSubgrupoContaId"></select>
              <label>Valor</label>
              <input id="finValor" type="number" step="0.01" oninput="gerarParcelasFinanceiro()" />
              <label>Quantidade de Parcelas</label>
              <input id="finParcelas" type="number" min="1" value="1" oninput="gerarParcelasFinanceiro()" />
              <label>Documento Original</label>
              <input id="finDocumentoOriginal" placeholder="Numero do documento, nota, pedido..." />
            </div>
          </div>
          <div class="inner-card" style="margin-top:8px;">
            <div class="inner-title" id="finTituloParcelas">Parcelas</div>
            <table>
              <thead><tr><th>Parcela</th><th>Vencimento</th><th>Valor</th></tr></thead>
              <tbody id="tbParcelasFinanceiro"></tbody>
            </table>
          </div>
        </div>
        <div id="finCamposReceber" class="hidden">
          <div class="layout-2 fin-modal-grid">
            <div class="fin-modal-col">
              <label>Descricao</label>
              <input id="finDescricaoReceber" />
              <label>Data de Emissao</label>
              <input id="finDataEmissaoReceber" type="date" />
              <label>Data de Lancamento</label>
              <input id="finDataVencimentoReceber" type="date" />
              <label>Documento Original</label>
              <input id="finDocumentoOriginalReceber" placeholder="Numero do documento, nota, pedido..." />
            </div>
            <div class="fin-modal-col">
              <label>Valor</label>
              <input id="finValorReceber" type="number" step="0.01" />
            </div>
          </div>
        </div>
        <div class="btn-row">
          <button type="button" onclick="salvarLancamentoFinanceiro()">Salvar Lancamento</button>
          <button class="alt" type="button" onclick="fecharModalFinanceiro()">Cancelar</button>
        </div>
        <div id="statusModalFinanceiro" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalBuscaParte" class="modal-overlay hidden">
    <div class="modal-box">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong id="tituloModalBuscaParte">Buscar Fornecedor</strong>
        <button class="alt" type="button" onclick="fecharModalBuscaParte()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="search-row">
          <input
            id="buscaParteInput"
            placeholder="Digite para buscar..."
            oninput="filtrarBuscaParte()"
            onkeydown="if(event.key==='Enter'){event.preventDefault();confirmarBuscaPartePorEnter();}"
          />
          <button class="btn-icon" type="button" onclick="filtrarBuscaParte()">🔍</button>
        </div>
        <div id="buscaParteLista" class="result-box" style="max-height:300px; overflow:auto;"></div>
      </div>
    </div>
  </div>

  <div id="modalNfeConfig" class="modal-overlay hidden">
    <div class="modal-box" style="width:min(760px,94vw);">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong>Configuracao NF-e (A1) - Homologacao</strong>
        <button class="alt" type="button" onclick="fecharModalNfeConfig()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="form-row">
          <div><label>Habilitar NF-e</label><select id="nfeCfgEnabled"><option value="false">Nao</option><option value="true">Sim</option></select></div>
          <div><label>Ambiente</label><select id="nfeCfgAmbiente"><option value="homologacao">Homologacao</option><option value="producao">Producao</option></select></div>
        </div>
        <div class="form-row">
          <div><label>UF</label><input id="nfeCfgUf" maxlength="2" placeholder="PR" /></div>
          <div><label>CNPJ Emitente</label><input id="nfeCfgCnpj" placeholder="Somente numeros" /></div>
        </div>
        <div class="form-row">
          <div><label>Inscricao Estadual</label><input id="nfeCfgIe" /></div>
          <div><label>Senha do Certificado A1</label><input id="nfeCfgSenha" type="password" autocomplete="new-password" /></div>
        </div>
        <div class="form-row">
          <div><label>CRT</label><select id="nfeCfgCrt"><option value="simples">Simples</option><option value="presumido">Presumido</option><option value="real">Real</option></select></div>
          <div><label>Serie NF-e</label><input id="nfeCfgSerie" type="number" min="1" value="1" /></div>
        </div>
        <div class="form-row">
          <div><label>CFOP padrao</label><input id="nfeCfgCfop" placeholder="5102" /></div>
          <div><label>CSOSN padrao</label><input id="nfeCfgCsosn" placeholder="0102" /></div>
        </div>
        <div class="form-row">
          <div><label>ID CSRT</label><input id="nfeCfgIdCsrt" placeholder="Ex.: 01" /></div>
          <div><label>CSRT</label><input id="nfeCfgCsrt" type="password" autocomplete="new-password" placeholder="Token CSRT da SEFAZ" /></div>
        </div>
        <div class="form-row">
          <div><label>CNPJ Responsavel Tecnico</label><input id="nfeCfgCnpjRespTec" placeholder="Somente numeros" /></div>
          <div></div>
        </div>
        <label>CNAE principal</label>
        <input id="nfeCfgCnaePrincipal" placeholder="6204-0/00 - Consultoria em tecnologia da informação" />
        <label>CNAEs secundarios (separar por ;)</label>
        <input id="nfeCfgCnaesSecundarios" placeholder="3312-1/02 - ... ; 3314-7/10 - ... ; 4752-1/00 - ... ; 4751-2/01 - ..." />
        <label>Caminho do Certificado .pfx</label>
        <input id="nfeCfgCertPath" placeholder="/caminho/arquivo.pfx" />
        <div class="btn-row" style="margin-top:4px;">
          <button class="alt" type="button" onclick="document.getElementById('nfeCfgUploadFile').click()">Upload .pfx/.p12</button>
          <input id="nfeCfgUploadFile" type="file" accept=".pfx,.p12" class="hidden" onchange="uploadNfeCertificado(this)" />
        </div>
        <div class="btn-row" style="margin-top:8px;">
          <button type="button" onclick="salvarNfeConfig()">Salvar configuracao</button>
          <button class="alt" type="button" onclick="testarStatusNfeConfig()">Testar prontidao do ambiente</button>
          <button class="alt" type="button" onclick="fecharModalNfeConfig()">Cancelar</button>
        </div>
        <div style="margin-top:10px; border:1px solid #dbe4ff; border-radius:6px; padding:10px; background:#f8fbff;">
          <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
            <strong>Status do Certificado</strong>
            <span id="nfeStatusBadge" class="tag">-</span>
          </div>
          <div id="nfeStatusArquivo" class="muted">Arquivo: -</div>
          <div id="nfeStatusValidade" class="muted">Validade: -</div>
        </div>
        <div id="statusModalNfeConfig" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <div id="modalHomeEvento" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance" style="width:min(880px,96vw);">
      <div style="font-weight:bold; margin-bottom:8px;">Configurar Evento da Tela Inicial</div>
      <div id="homeEventoPainelLista">
        <div class="inner-card" style="margin-bottom:10px;">
          <div class="inner-title">Eventos existentes</div>
          <div id="homeEventosListaConfig"></div>
        </div>
        <div class="btn-row" style="margin-top:10px;">
          <button type="button" onclick="novoEventoHomeFormulario()">Novo Evento</button>
          <button type="button" onclick="editarEventoHomeSelecionado()">Editar Evento</button>
          <button class="alt" type="button" onclick="fecharModalEventoHome()">Fechar</button>
        </div>
      </div>
      <div id="homeEventoPainelEditor" class="hidden">
      <div class="layout-2">
        <div>
          <label>Nome do evento</label>
          <input id="homeEventoNomeInput" />
        </div>
        <div>
          <label>Tipo do evento</label>
          <select id="homeEventoTipoInput" onchange="atualizarOpcoesParteEventoHome()">
            <option value="">Selecione...</option>
            <option value="contas_pagar">Contas a Pagar</option>
            <option value="contas_receber">Contas a Receber</option>
          </select>
        </div>
      </div>
      <label id="homeEventoParteLabel">Fornecedor</label>
      <select id="homeEventoParteIdInput">
        <option value="">Selecione...</option>
      </select>
      <label>Mensagem</label>
      <textarea id="homeEventoMensagemInput" rows="6" style="width:100%;"></textarea>
      <div class="layout-2">
        <div>
          <label>Mostrar de (data inicial)</label>
          <input id="homeEventoDataInicioInput" type="date" />
        </div>
        <div>
          <label>Mostrar ate (data final)</label>
          <input id="homeEventoDataFimInput" type="date" />
        </div>
      </div>
      <label class="fin-check-inline" style="margin-top:6px;">
        <input id="homeEventoExecutadaInput" type="checkbox" />
        Tarefa Executada
      </label>
      <div class="btn-row" style="margin-top:10px;">
        <button type="button" onclick="salvarConfiguracaoEventoHome()">Salvar Evento</button>
        <button type="button" onclick="executarEventoSelecionadoHomeAgora()">Executar agora</button>
        <button class="alt" type="button" onclick="voltarListaEventosHome()">Voltar</button>
      </div>
      </div>
      <div id="statusModalHomeEvento" class="status-line muted" style="margin-top:8px;"></div>
    </div>
  </div>

  <div id="modalAtualizacaoSistema" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance" style="width:min(760px,94vw);">
      <div style="font-weight:bold; margin-bottom:8px;">Atualizacoes do Sistema</div>
      <div class="inner-card" style="margin-bottom:10px;">
        <div class="inner-title">Status da versao instalada</div>
        <div id="atualizacaoVersaoAtual" class="muted">Versao atual: -</div>
        <div id="atualizacaoVersaoDisponivel" class="muted">Versao disponivel: -</div>
        <div id="atualizacaoPacoteUrl" class="muted">Pacote: -</div>
      </div>
      <label>Changelog da versao disponivel</label>
      <textarea id="atualizacaoChangelog" rows="8" readonly style="width:100%;"></textarea>
      <div class="btn-row" style="margin-top:10px;">
        <button type="button" onclick="verificarAtualizacaoSistema()">Verificar atualizacoes</button>
        <button type="button" onclick="aplicarAtualizacaoSistema()">Atualizar agora</button>
        <button class="alt" type="button" onclick="listarHistoricoAtualizacoesSistema()">Atualizar historico</button>
        <button class="alt" type="button" onclick="rollbackAtualizacaoSistemaSelecionada()">Rollback selecionado</button>
        <button class="alt" type="button" onclick="fecharModalAtualizacaoSistema()">Fechar</button>
      </div>
      <div class="inner-card" style="margin-top:10px;">
        <div class="inner-title">Historico de atualizacoes</div>
        <table>
          <thead>
            <tr><th>Sel.</th><th>ID</th><th>Inicio</th><th>Origem</th><th>Alvo</th><th>Status</th><th>Mensagem</th><th>Rollback</th></tr>
          </thead>
          <tbody id="tbAtualizacaoHistorico"></tbody>
        </table>
      </div>
      <div id="statusModalAtualizacaoSistema" class="status-line muted" style="margin-top:8px;"></div>
    </div>
  </div>

  <div id="modalConfigBanco" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance" style="width:min(760px,94vw);">
      <div style="font-weight:bold; margin-bottom:8px;">Configurar Banco de Dados (Instalacao)</div>
      <div class="layout-2" style="gap:10px;">
        <div>
          <label>Host / IP do banco</label>
          <input id="cfgBancoHost" placeholder="Ex.: 192.168.1.20" />
        </div>
        <div>
          <label>Porta</label>
          <input id="cfgBancoPorta" type="number" min="1" max="65535" value="5432" />
        </div>
      </div>
      <div class="layout-2" style="gap:10px;">
        <div>
          <label>Nome do banco</label>
          <input id="cfgBancoNome" placeholder="onix_system" />
        </div>
        <div>
          <label>Usuario</label>
          <input id="cfgBancoUsuario" placeholder="postgres" />
        </div>
      </div>
      <label>Senha</label>
      <input id="cfgBancoSenha" type="password" />
      <div class="btn-row" style="margin-top:10px;">
        <button type="button" onclick="testarConfigBancoSistema()">Testar conexao</button>
        <button type="button" onclick="salvarConfigBancoSistema()">Salvar configuracao</button>
        <button class="alt" type="button" onclick="fecharModalConfigBancoSistema()">Fechar</button>
      </div>
      <div id="statusModalConfigBanco" class="status-line muted" style="margin-top:8px;"></div>
    </div>
  </div>

  <div id="modalCompraEstoque" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance" style="width:min(980px,96vw);">
      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
        <div style="font-weight:bold;">Lancamento de Compra (Estoque)</div>
        <button class="alt" type="button" onclick="fecharModalCompraEstoque()">Fechar</button>
      </div>
      <div class="estoque-top-row">
        <div>
          <label>Tipo de lancamento</label>
          <select id="estCompraTipoLancamento">
            <option value="manual">Lancamento manual</option>
            <option value="xml">Importar XML</option>
          </select>
        </div>
        <div id="estCompraXmlBox" class="btn-row">
          <button class="alt" type="button" onclick="document.getElementById('estCompraXmlFile').click()">Importar XML</button>
          <input id="estCompraXmlFile" type="file" accept=".xml" class="hidden" onchange="importarXmlCompraEstoque(this)" />
        </div>
      </div>
      <div class="estoque-flags-row">
        <label class="fin-check-inline">
          <input id="estFlagEntradaNota" type="checkbox" />
          Entrada de Nota
        </label>
        <label class="fin-check-inline">
          <input id="estFlagCompraSimples" type="checkbox" />
          Compra Simples
        </label>
      </div>
      <div class="layout-2">
        <div>
          <label>Fornecedor</label>
          <select id="estCompraFornecedor"><option value="">Selecione...</option></select>
        </div>
        <div>
          <label>Data da compra</label>
          <input id="estCompraData" type="date" />
        </div>
      </div>
      <div class="layout-2">
        <div>
          <label>Numero da nota</label>
          <input id="estCompraNumeroNota" />
        </div>
        <div>
          <label>Chave NF-e (opcional)</label>
          <input id="estCompraChaveNfe" />
        </div>
      </div>
      <label>Observacao</label>
      <textarea id="estCompraObs" rows="2"></textarea>
      <div class="inner-card" style="margin-top:8px;">
        <div class="inner-title">Itens da compra</div>
        <div class="btn-row" style="margin-bottom:8px;">
          <button type="button" onclick="adicionarLinhaItemCompraEstoque()">＋ Adicionar item</button>
        </div>
        <table>
          <thead><tr><th>Produto</th><th>Descricao</th><th>Qtd</th><th>Valor Unit.</th><th>Total</th><th>Acao</th></tr></thead>
          <tbody id="tbItensCompraEstoque"></tbody>
        </table>
      </div>
      <div class="btn-row" style="margin-top:10px;">
        <button type="button" onclick="salvarCompraEstoque()">Salvar compra</button>
        <button class="alt" type="button" onclick="fecharModalCompraEstoque()">Cancelar</button>
      </div>
      <div id="statusModalCompraEstoque" class="status-line muted" style="margin-top:8px;"></div>
    </div>
  </div>

  <div id="modalAuthExclusaoAdmin" class="modal-overlay hidden">
    <div class="modal-box" style="width:min(520px,94vw);">
      <div style="padding:10px 12px; border-bottom:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center;">
        <strong>Autorizacao de exclusao</strong>
        <button class="alt" type="button" onclick="fecharModalAuthExclusao()">Fechar</button>
      </div>
      <div style="padding:12px;">
        <div class="muted" style="margin-bottom:8px;">Perfil gerencial exige senha de um usuario admin para excluir registros.</div>
        <label>Usuario admin</label>
        <select id="authExclusaoAdminUsuario"></select>
        <label>Senha do admin</label>
        <input id="authExclusaoAdminSenha" type="password" autocomplete="new-password" />
        <div class="btn-row" style="margin-top:10px;">
          <button type="button" onclick="confirmarAuthExclusaoAdmin()">Autorizar</button>
          <button class="alt" type="button" onclick="fecharModalAuthExclusao()">Cancelar</button>
        </div>
        <div id="statusAuthExclusaoAdmin" class="status-line muted" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <script>
    const api = (path, options = {}) => fetch(`/api${path}`, options).then(async r => {
      if (!r.ok) {
        let msg = `Erro ${r.status}`;
        try {
          const body = await r.json();
          if (Array.isArray(body.detail) && body.detail.length) {
            msg = body.detail.map(x => x.msg || JSON.stringify(x)).join(" | ");
          } else if (body.detail) {
            msg = body.detail;
          }
        } catch (e) {}
        throw new Error(msg);
      }
      if (r.status === 204) return null;
      return r.json();
    });

    const apiComTimeout = (path, timeoutMs = 15000, options = {}) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      const opts = Object.assign({}, options, { signal: controller.signal });
      return api(path, opts).finally(() => clearTimeout(timer)).catch(err => {
        if (err && err.name === 'AbortError') {
          throw new Error('Tempo limite excedido ao tentar conectar no banco.');
        }
        throw err;
      });
    };

    function moeda(valor) {
      return Number(valor || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    }

    function parseDecimalBr(s) {
      if (s == null || s === '') return 0;
      let t = String(s).trim().replace(/\s/g, '');
      if (!t) return 0;
      t = t.replace(/\./g, '').replace(',', '.');
      const n = Number(t);
      return Number.isFinite(n) ? n : 0;
    }

    function parseMoedaBr(s) {
      if (s == null || s === '') return 0;
      let t = String(s).trim().replace(/\s/g, '');
      t = t.replace(/R\$\s?/gi, '');
      t = t.replace(/\./g, '').replace(',', '.');
      const n = Number(t);
      return Number.isFinite(n) ? n : 0;
    }

    function formatMoedaBrCampo(n) {
      return Number(n || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    }

    function formatQtdBr(n) {
      const v = Number(n || 0);
      if (!Number.isFinite(v)) return '';
      return v.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 4 });
    }

    function calcTotalLinhaVendaItem(item) {
      const q = Number(item.quantidade || 0);
      const vu = Number(item.valor_unitario || 0);
      const d = Number(item.desconto || 0);
      return q * vu - d;
    }

    function formatDescBr(n) {
      const v = Number(n || 0);
      if (!Number.isFinite(v)) return '0,00';
      return v.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function formatDataBr(iso) {
      if (!iso) return '-';
      const s = String(iso);
      const d = s.includes('T') ? s.slice(0, 10) : s.slice(0, 10);
      if (d.length < 10) return '-';
      const [y, m, day] = d.split('-');
      if (!y || !m || !day) return '-';
      return `${day}/${m}/${y}`;
    }

    function escapeHtml(s) {
      var t = s !== null && s !== undefined ? s : '';
      return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function moedaTotalContaCorrente(valor) {
      const numero = Number(valor || 0);
      const base = Math.abs(numero).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      return `R$ ${numero < 0 ? '-' : ''}${base}`;
    }

    function setMsg(id, text, ok = true) {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = text;
      el.className = `status-line ${ok ? 'ok' : 'err'}`;
    }

    function usuarioSessaoAtual() {
      if (!usuariosSistemaCache.length) return null;
      return usuariosSistemaCache.find(item => item.id === usuarioSessaoAtivaId) || null;
    }

    function atualizarInfoSessaoUsuario() {
      const info = document.getElementById('sessaoPerfilInfo');
      if (!info) return;
      const atual = usuarioSessaoAtual();
      if (!atual) {
        info.textContent = 'Perfil atual: -';
        usuarioSessaoAtivaPerfil = 'admin';
        return;
      }
      usuarioSessaoAtivaPerfil = String(atual.perfil || 'gerencial').toLowerCase();
      info.textContent = `Perfil atual: ${usuarioSessaoAtivaPerfil === 'admin' ? 'Admin' : 'Gerencial'} (${atual.nome || atual.login || ('ID ' + atual.id)})`;
    }

    function sincronizarSessaoUsuarioSelect() {
      const sel = document.getElementById('sessaoUsuarioAtivo');
      if (!sel) return;
      const ativos = usuariosSistemaCache.filter(item => !!item.ativo);
      sel.innerHTML = '';
      ativos.forEach(item => {
        const op = document.createElement('option');
        op.value = String(item.id);
        op.textContent = `${item.nome || item.login} (${item.perfil})`;
        sel.appendChild(op);
      });
      if (!ativos.length) {
        usuarioSessaoAtivaId = null;
      } else {
        const existe = ativos.some(item => item.id === usuarioSessaoAtivaId);
        if (!existe) {
          const admin = ativos.find(item => String(item.perfil || '').toLowerCase() === 'admin');
          usuarioSessaoAtivaId = admin ? admin.id : ativos[0].id;
        }
        sel.value = String(usuarioSessaoAtivaId);
      }
      try {
        if (usuarioSessaoAtivaId) localStorage.setItem('sga-usuario-sessao-id', String(usuarioSessaoAtivaId));
      } catch (e) {}
      atualizarInfoSessaoUsuario();
    }

    function trocarUsuarioSessao(id) {
      const numero = Number(id || 0);
      if (!numero) return;
      usuarioSessaoAtivaId = numero;
      try {
        localStorage.setItem('sga-usuario-sessao-id', String(usuarioSessaoAtivaId));
      } catch (e) {}
      sincronizarSessaoUsuarioSelect();
      setMsg('statusUsuariosSistema', 'Sessao ativa atualizada.');
    }

    function preencherSelectAdminsAutorizacao() {
      const sel = document.getElementById('authExclusaoAdminUsuario');
      if (!sel) return;
      sel.innerHTML = '';
      usuariosSistemaCache
        .filter(item => !!item.ativo && String(item.perfil || '').toLowerCase() === 'admin')
        .forEach(item => {
          const op = document.createElement('option');
          op.value = String(item.id);
          op.textContent = `${item.nome || item.login} (${item.login})`;
          sel.appendChild(op);
        });
    }

    function limparFormularioUsuarioSistema() {
      usuarioSistemaSelecionadoId = null;
      const nome = document.getElementById('usrNome');
      const login = document.getElementById('usrLogin');
      const perfil = document.getElementById('usrPerfil');
      const senha = document.getElementById('usrSenha');
      const ativo = document.getElementById('usrAtivo');
      if (nome) nome.value = '';
      if (login) login.value = '';
      if (perfil) perfil.value = 'admin';
      if (senha) senha.value = '';
      if (ativo) ativo.checked = true;
      setMsg('statusUsuariosSistema', '');
    }

    function selecionarUsuarioSistema(id) {
      usuarioSistemaSelecionadoId = Number(id || 0) || null;
      const item = usuariosSistemaCache.find(row => row.id === usuarioSistemaSelecionadoId);
      setMsg('statusUsuariosSistema', item ? `Selecionado: ${item.nome || item.login}` : 'Usuario selecionado.');
    }

    async function listarUsuariosSistema() {
      try {
        const itens = await api('/usuarios');
        usuariosSistemaCache = Array.isArray(itens) ? itens : [];
        const tbody = document.getElementById('tbUsuariosSistema');
        if (!tbody) return;
        tbody.innerHTML = '';
        usuariosSistemaCache.forEach(item => {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><input type="radio" name="usrSistemaSel" onchange="selecionarUsuarioSistema(${item.id})" /></td><td>${item.id}</td><td>${escapeHtml(item.nome || '')}</td><td>${escapeHtml(item.login || '')}</td><td>${escapeHtml(item.perfil || '')}</td><td>${item.ativo ? 'Sim' : 'Nao'}</td><td>${formatDataBr(item.created_at)}</td>`;
          tbody.appendChild(tr);
        });
        try {
          const salvo = Number(localStorage.getItem('sga-usuario-sessao-id') || 0);
          if (salvo) usuarioSessaoAtivaId = salvo;
        } catch (e) {}
        sincronizarSessaoUsuarioSelect();
        preencherSelectAdminsAutorizacao();
        setMsg('statusUsuariosSistema', `${usuariosSistemaCache.length} usuario(s) carregado(s).`);
      } catch (err) {
        setMsg('statusUsuariosSistema', `Falha ao listar usuarios: ${err.message}`, false);
      }
    }

    function editarUsuarioSistemaSelecionado() {
      if (!usuarioSistemaSelecionadoId) {
        setMsg('statusUsuariosSistema', 'Selecione um usuario para editar.', false);
        return;
      }
      const item = usuariosSistemaCache.find(row => row.id === usuarioSistemaSelecionadoId);
      if (!item) {
        setMsg('statusUsuariosSistema', 'Usuario selecionado nao encontrado.', false);
        return;
      }
      document.getElementById('usrNome').value = item.nome || '';
      document.getElementById('usrLogin').value = item.login || '';
      document.getElementById('usrPerfil').value = (item.perfil || 'gerencial').toLowerCase();
      document.getElementById('usrSenha').value = '';
      document.getElementById('usrAtivo').checked = !!item.ativo;
      setMsg('statusUsuariosSistema', `Editando usuario ${item.nome || item.login}.`);
    }

    async function salvarUsuarioSistema() {
      const payload = {
        nome: document.getElementById('usrNome').value.trim(),
        login: document.getElementById('usrLogin').value.trim(),
        perfil: (document.getElementById('usrPerfil').value || 'gerencial').trim().toLowerCase(),
        senha: document.getElementById('usrSenha').value || '',
        ativo: !!document.getElementById('usrAtivo').checked,
      };
      try {
        if (!payload.nome || !payload.login) {
          setMsg('statusUsuariosSistema', 'Nome e login sao obrigatorios.', false);
          return;
        }
        if (!usuarioSistemaSelecionadoId && (!payload.senha || payload.senha.length < 4)) {
          setMsg('statusUsuariosSistema', 'Senha inicial deve ter ao menos 4 caracteres.', false);
          return;
        }
        if (usuarioSistemaSelecionadoId) {
          await api(`/usuarios/${usuarioSistemaSelecionadoId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          setMsg('statusUsuariosSistema', 'Usuario atualizado com sucesso.');
        } else {
          await api('/usuarios', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          setMsg('statusUsuariosSistema', 'Usuario cadastrado com sucesso.');
        }
        limparFormularioUsuarioSistema();
        await listarUsuariosSistema();
      } catch (err) {
        setMsg('statusUsuariosSistema', err.message, false);
      }
    }

    async function excluirUsuarioSistemaSelecionado() {
      if (!usuarioSistemaSelecionadoId) {
        setMsg('statusUsuariosSistema', 'Selecione um usuario para excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const item = usuariosSistemaCache.find(row => row.id === usuarioSistemaSelecionadoId);
      if (!window.confirm(`Confirma exclusao do usuario ${item ? (item.nome || item.login) : usuarioSistemaSelecionadoId}?`)) return;
      try {
        await api(`/usuarios/${usuarioSistemaSelecionadoId}`, { method: 'DELETE' });
        usuarioSistemaSelecionadoId = null;
        limparFormularioUsuarioSistema();
        await listarUsuariosSistema();
        setMsg('statusUsuariosSistema', 'Usuario excluido com sucesso.');
      } catch (err) {
        setMsg('statusUsuariosSistema', err.message, false);
      }
    }

    function abrirModalAuthExclusao() {
      preencherSelectAdminsAutorizacao();
      const modal = document.getElementById('modalAuthExclusaoAdmin');
      if (!modal) return;
      document.getElementById('authExclusaoAdminSenha').value = '';
      setMsg('statusAuthExclusaoAdmin', '');
      modal.classList.remove('hidden');
    }

    function fecharModalAuthExclusao() {
      const modal = document.getElementById('modalAuthExclusaoAdmin');
      if (modal) modal.classList.add('hidden');
      if (resolverAuthExclusaoAdmin) {
        resolverAuthExclusaoAdmin(false);
        resolverAuthExclusaoAdmin = null;
      }
    }

    async function confirmarAuthExclusaoAdmin() {
      const sel = document.getElementById('authExclusaoAdminUsuario');
      const senha = document.getElementById('authExclusaoAdminSenha').value || '';
      const usuarioId = Number(sel && sel.value ? sel.value : 0);
      if (!usuarioId || !senha) {
        setMsg('statusAuthExclusaoAdmin', 'Selecione um admin e informe a senha.', false);
        return;
      }
      try {
        const resp = await api('/usuarios/validar-admin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ usuario_id: usuarioId, senha: senha }),
        });
        if (!resp || !resp.ok) {
          setMsg('statusAuthExclusaoAdmin', 'Senha admin invalida.', false);
          return;
        }
        const modal = document.getElementById('modalAuthExclusaoAdmin');
        if (modal) modal.classList.add('hidden');
        if (resolverAuthExclusaoAdmin) {
          resolverAuthExclusaoAdmin(true);
          resolverAuthExclusaoAdmin = null;
        }
      } catch (err) {
        setMsg('statusAuthExclusaoAdmin', err.message, false);
      }
    }

    async function validarPermissaoExclusao() {
      const atual = usuarioSessaoAtual();
      if (!atual) return true;
      const perfil = String(atual.perfil || 'gerencial').toLowerCase();
      if (perfil === 'admin') return true;
      return new Promise(resolve => {
        resolverAuthExclusaoAdmin = resolve;
        abrirModalAuthExclusao();
      });
    }

    let cadastroEditId = null;
    let cadastroSelecionadoId = null;
    let tipoLancamentoFinanceiro = null;
    let origemCadastroModal = 'pessoas';
    const cadastrosCache = new Map();
    let grupoDespesaSelecionadoId = null;
    let planoContaSelecionadoId = null;
    let grupoContaSelecionadoId = null;
    let subgrupoContaSelecionadoId = null;
    let contaCorrenteSelecionadaId = null;
    let cadastroBasicoTipo = null;
    let cadastroBasicoEditId = null;
    const gruposDespesasCache = new Map();
    const planosContasCache = new Map();
    const gruposContasCache = new Map();
    const subgruposContasCache = new Map();
    const contasCorrentesCache = new Map();
    let abaFinanceiroAtiva = 'pagar';
    let gruposDespesaFinanceiro = [];
    let planosContaFinanceiro = [];
    let gruposContaFinanceiro = [];
    let subgruposContaFinanceiro = [];
    let contasCorrentesFinanceiro = [];
    let cartoesCreditoFinanceiro = [];
    let cartaoCreditoPainelSelecionadoId = null;
    let cartaoCreditoModalEditId = null;
    let cartoesCreditoPainelCache = [];
    let faturasCartaoPainelCache = [];
    let contaFinanceiraSelecionadaId = null;
    let contasFinanceiroBaixaIds = [];
    const contasFinanceiroSelecionadas = new Set();
    const pendenciasConciliacaoSelecionadas = new Set();
    let parteFinanceiroSelecionadaId = null;
    let resumoPartesFinanceiroCache = [];
    const partesMapFinanceiroCache = new Map();
    let contasFinanceiroCache = [];
    let partesFinanceiroCache = [];
    let partesBuscaFiltradas = [];
    let relatorioRowsCache = [];
    let cardsCadastroAbertos = [];
    let cardCadastroAtivo = null;
    let seletorCadastroVisivel = false;
    let timerFecharSeletorCadastro = null;
    let cardsFaturasAbertos = [];
    let cardFaturasAtivo = null;
    let seletorFaturasVisivel = false;
    let timerFecharSeletorFaturas = null;
    let cardsFinanceiroAbertos = [];
    let cardFinanceiroAtivo = null;
    let seletorFinanceiroVisivel = false;
    let timerFecharSeletorFinanceiro = null;
    let cardsVendasAbertos = [];
    let cardVendasAtivo = null;
    let seletorVendasVisivel = false;
    let timerFecharSeletorVendas = null;
    let abaVendasAtiva = 'pedidos';
    let cardsEstoqueAbertos = [];
    let cardEstoqueAtivo = null;
    let seletorEstoqueVisivel = false;
    let timerFecharSeletorEstoque = null;
    let cardsContadorAbertos = [];
    let cardContadorAtivo = null;
    let seletorContadorVisivel = false;
    let timerFecharSeletorContador = null;
    let comprasEstoqueCache = [];
    let fornecedoresEstoqueCache = [];
    let itensCompraEstoqueTemp = [];
    let ajusteEstoqueSelecionadoId = null;
    let atualizacaoHistoricoSelecionadoId = null;
    let seletorHomeConfigVisivel = false;
    let timerFecharSeletorHomeConfig = null;
    let homeEventosCache = [];
    let homeEventoFechadosSessaoIds = new Set();
    let homeEventosAvisosFechadosSessao = false;
    let homeEventoSelecionadoIdGestao = null;
    let vendasCache = [];
    const vendasSelecionadas = new Set();
    let vendaMenuPopoverEl = null;
    let vendaMenuAnchorId = null;
    let venEditVendaId = null;
    let condicoesPagamentoCache = new Map();
    let condicaoPagSelecionadaId = null;
    let produtosCache = [];
    let categoriasProdutoCache = [];
    let categoriaProdutoSelecionadaId = null;
    const codigosCategoriaProdutoImutaveis = ['PRODUTOS', 'SERVICOS'];
    let produtoEdicaoId = null;
    let usuariosSistemaCache = [];
    let usuarioSistemaSelecionadoId = null;
    let usuarioSessaoAtivaId = null;
    let usuarioSessaoAtivaPerfil = 'admin';
    let resolverAuthExclusaoAdmin = null;
    let itensVendaTemp = [];
    let relatorioMetaCache = {
      titulo: 'Relatorio Financeiro',
      empresaNome: 'Empresa nao informada',
      empresaCnpj: '-',
      empresaTelefone: '-',
      empresaEndereco: '-',
      geradoEm: '',
      resumo: '',
    };
    let relatorioColunasAtivas = [
      { key: 'tipo', label: 'Tipo' },
      { key: 'id', label: 'ID' },
      { key: 'parte', label: 'Parte/Conta' },
      { key: 'descricao', label: 'Descricao' },
      { key: 'data_vencimento', label: 'Vencimento' },
      { key: 'data_baixa', label: 'Baixa/Receb.' },
      { key: 'status', label: 'Status', tag: true },
      { key: 'conta_corrente', label: 'Conta Corrente' },
      { key: 'valor', label: 'Valor', money: true },
    ];
    let onixIaMensagens = [];

    function aplicarTema(tema) {
      const temaFinal = tema === 'dark' ? 'dark' : 'light';
      document.body.setAttribute('data-theme', temaFinal);
      try {
        localStorage.setItem('sga-theme', temaFinal);
      } catch (e) {}
      const seletor = document.getElementById('themeSelect');
      if (seletor && seletor.value !== temaFinal) {
        seletor.value = temaFinal;
      }
    }

    function inicializarTema() {
      let tema = 'light';
      try {
        tema = localStorage.getItem('sga-theme') || 'light';
      } catch (e) {}
      aplicarTema(tema);
    }

    function limparFormularioModal() {
      cadastroEditId = null;
      document.getElementById('editCnpj').value = '';
      document.getElementById('editRazao').value = '';
      document.getElementById('editCidadeUf').value = '';
      document.getElementById('editNomeFantasia').value = '';
      document.getElementById('editEndereco').value = '';
      document.getElementById('editTelefone').value = '';
      document.getElementById('editCep').value = '';
      document.getElementById('editIsCliente').checked = false;
      document.getElementById('editIsFuncionario').checked = false;
      document.getElementById('editIsFornecedor').checked = false;
      document.getElementById('editIsVendedor').checked = false;
      document.getElementById('editChavePix').value = '';
      document.getElementById('editVendedorComissionado').checked = false;
      atualizarVisibilidadeVendedor();
      document.getElementById('statusEdicao').textContent = '';
    }

    function atualizarVisibilidadeFlagsCadastro() {
      const row = document.getElementById('flagsPessoaRow');
      if (!row) return;
      if (origemCadastroModal === 'pessoas') {
        row.classList.remove('hidden');
      } else {
        row.classList.add('hidden');
        document.getElementById('editIsCliente').checked = false;
        document.getElementById('editIsFuncionario').checked = false;
        document.getElementById('editIsFornecedor').checked = false;
        document.getElementById('editIsVendedor').checked = false;
        document.getElementById('editChavePix').value = '';
        document.getElementById('editVendedorComissionado').checked = false;
      }
      atualizarVisibilidadeVendedor();
    }

    function atualizarVisibilidadeVendedor() {
      const row = document.getElementById('vendedorExtraRow');
      const isVend = document.getElementById('editIsVendedor');
      if (!row || !isVend) return;
      if (origemCadastroModal === 'pessoas' && isVend.checked) {
        row.classList.remove('hidden');
      } else {
        row.classList.add('hidden');
      }
    }

    function selecionarCadastro(id) {
      cadastroSelecionadoId = id;
      setMsg('statusCadastro', `Cadastro ID ${id} selecionado.`);
    }

    function ativarMenuPrincipal(menu) {
      var mh = document.getElementById('menuOnixHome');
      var mc = document.getElementById('menuCadastro');
      var mf = document.getElementById('menuFinanceiro');
      var mr = document.getElementById('menuRelatorios');
      var mfat = document.getElementById('menuFaturas');
      var mv = document.getElementById('menuVendas');
      var mest = document.getElementById('menuEstoque');
      var mcont = document.getElementById('menuContador');
      var mia = document.getElementById('menuOnixIa');
      if (mh) mh.classList.toggle('active', menu === 'onixhome');
      if (mc) mc.classList.toggle('active', menu === 'cadastro');
      if (mf) mf.classList.toggle('active', menu === 'financeiro');
      if (mr) mr.classList.toggle('active', menu === 'relatorios');
      if (mfat) mfat.classList.toggle('active', menu === 'faturas');
      if (mv) mv.classList.toggle('active', menu === 'vendas');
      if (mest) mest.classList.toggle('active', menu === 'estoque');
      if (mcont) mcont.classList.toggle('active', menu === 'contador');
      if (mia) mia.classList.toggle('active', menu === 'onixia');
    }

    function dataIsoHoje() {
      return new Date().toISOString().slice(0, 10);
    }

    function parseDataIsoSemFuso(valor) {
      var s = String(valor || '').slice(0, 10);
      if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(s)) return null;
      var p = s.split('-');
      return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    }

    function isoFromDateLocal(dt) {
      var y = dt.getFullYear();
      var m = String(dt.getMonth() + 1).padStart(2, '0');
      var d = String(dt.getDate()).padStart(2, '0');
      return y + '-' + m + '-' + d;
    }

    function calcularIntervaloSemanaAtual() {
      var hoje = new Date();
      var inicio = new Date(hoje);
      inicio.setHours(0, 0, 0, 0);
      var dia = inicio.getDay();
      var desloc = dia === 0 ? 6 : dia - 1;
      inicio.setDate(inicio.getDate() - desloc);
      var fim = new Date(inicio);
      fim.setDate(fim.getDate() + 6);
      return { inicio: isoFromDateLocal(inicio), fim: isoFromDateLocal(fim) };
    }

    function calcularProximaSexta() {
      var hoje = new Date();
      hoje.setHours(0, 0, 0, 0);
      var sexta = new Date(hoje);
      var dif = (5 - hoje.getDay() + 7) % 7;
      sexta.setDate(hoje.getDate() + dif);
      return isoFromDateLocal(sexta);
    }

    function eventoHomeEstaNoPrazo(cfg) {
      if (!cfg) return false;
      if (cfg.tarefa_executada) return false;
      if (!String(cfg.nome_evento || '').trim()) return false;
      if (!String(cfg.tipo_evento || '').trim()) return false;
      if (!String(cfg.mensagem || '').trim()) return false;
      var hojeIso = dataIsoHoje();
      var inicio = String(cfg.data_inicio || '').slice(0, 10);
      var fim = String(cfg.data_fim || '').slice(0, 10);
      if (!inicio || !fim) return false;
      if (fim < inicio) return false;
      return hojeIso >= inicio && hojeIso <= fim;
    }

    function obterEventoHomePorId(eventoId) {
      return homeEventosCache.find(function(item) { return Number(item.id) === Number(eventoId); }) || null;
    }

    function tipoEventoLabel(tipoEvento) {
      return String(tipoEvento || '') === 'contas_receber' ? 'Contas a Receber' : 'Contas a Pagar';
    }

    function renderEventoHomeCard() {
      var aviso = document.getElementById('homeEventoAviso');
      var lista = document.getElementById('homeEventosAvisoLista');
      if (!aviso || !lista) return;
      lista.innerHTML = '';
      if (homeEventosAvisosFechadosSessao) {
        aviso.classList.add('hidden');
        return;
      }
      var ativos = homeEventosCache.filter(function(cfg) {
        return eventoHomeEstaNoPrazo(cfg) && !homeEventoFechadosSessaoIds.has(Number(cfg.id));
      });
      if (!ativos.length) {
        aviso.classList.add('hidden');
        return;
      }
      ativos.forEach(function(cfg) {
        var destinoLabel = cfg.tipo_evento === 'contas_receber'
          ? 'Destino: Financeiro > Contas a Receber'
          : 'Destino: Financeiro > Contas a Pagar';
        var item = document.createElement('div');
        item.className = 'home-evento-item';
        item.innerHTML = `
          <div class="home-evento-aviso-topo">
            <div>
              <div class="inner-title" style="margin-bottom:4px;">${escapeHtml(cfg.nome_evento || 'Aviso')}</div>
              <div class="muted">Tipo: ${escapeHtml(tipoEventoLabel(cfg.tipo_evento))}</div>
            </div>
            <button class="home-evento-close" type="button" title="Fechar aviso" onclick="fecharAvisoEventoHome(${Number(cfg.id)})">x</button>
          </div>
          <div style="white-space:pre-wrap; margin:10px 0;">${escapeHtml(cfg.mensagem || '')}</div>
          <div class="muted" style="margin-bottom:8px;">${escapeHtml(destinoLabel)}</div>
          <div class="muted" style="margin-bottom:10px;">Periodo: ${escapeHtml(formatDataBr(cfg.data_inicio))} ate ${escapeHtml(formatDataBr(cfg.data_fim))}</div>
          <div class="btn-row">
            <button type="button" onclick="executarEventoHomeAgora(${Number(cfg.id)})">Executar agora</button>
            <button class="alt" type="button" onclick="fecharAvisoEventoHome(${Number(cfg.id)})">Fechar</button>
            <button type="button" onclick="marcarEventoHomeExecutado(${Number(cfg.id)})">Tarefa Executada</button>
          </div>
        `;
        lista.appendChild(item);
      });
      aviso.classList.remove('hidden');
    }

    function fecharAvisoEventoHome(eventoId) {
      if (eventoId) {
        homeEventoFechadosSessaoIds.add(Number(eventoId));
      } else {
        homeEventosAvisosFechadosSessao = true;
      }
      renderEventoHomeCard();
    }

    async function carregarEventoHome() {
      try {
        var eventos = await api('/home-eventos');
        homeEventosCache = Array.isArray(eventos) ? eventos.filter(function(e) {
          return String(e.nome_evento || '').trim() || String(e.mensagem || '').trim();
        }) : [];
        renderEventoHomeCard();
      } catch (err) {
        setMsg('statusHomeConfig', `Falha ao carregar evento: ${err.message}`, false);
      }
    }

    function preencherListaEventosModalHome() {
      var box = document.getElementById('homeEventosListaConfig');
      if (!box) return;
      box.innerHTML = '';
      var lista = homeEventosCache.filter(function(ev) {
        return String(ev.nome_evento || '').trim() && !ev.tarefa_executada;
      });
      if (!lista.length) {
        box.innerHTML = '<div class="muted">Nenhum evento cadastrado.</div>';
        return;
      }
      lista.forEach(function(ev) {
        var item = document.createElement('div');
        item.className = 'home-evento-item';
        if (Number(homeEventoSelecionadoIdGestao) === Number(ev.id)) {
          item.style.borderColor = '#2563eb';
          item.style.boxShadow = '0 0 0 1px #2563eb inset';
        }
        var tipoLabel = tipoEventoLabel(ev.tipo_evento);
        item.innerHTML = `
          <div style="font-weight:700;">${escapeHtml(ev.nome_evento || '')}</div>
          <div class="muted">Tipo: ${escapeHtml(tipoLabel)} | Periodo: ${escapeHtml(formatDataBr(ev.data_inicio))} ate ${escapeHtml(formatDataBr(ev.data_fim))}</div>
        `;
        item.onclick = function() { selecionarEventoListaHome(ev.id); };
        box.appendChild(item);
      });
    }

    function selecionarEventoListaHome(eventoId) {
      homeEventoSelecionadoIdGestao = Number(eventoId) || null;
      preencherListaEventosModalHome();
    }

    function mostrarPainelEditorEventoHome(mostrar) {
      var pLista = document.getElementById('homeEventoPainelLista');
      var pEditor = document.getElementById('homeEventoPainelEditor');
      if (pLista) pLista.classList.toggle('hidden', !!mostrar);
      if (pEditor) pEditor.classList.toggle('hidden', !mostrar);
    }

    function novoEventoHomeFormulario() {
      homeEventoSelecionadoIdGestao = null;
      document.getElementById('homeEventoNomeInput').value = '';
      document.getElementById('homeEventoTipoInput').value = '';
      document.getElementById('homeEventoMensagemInput').value = '';
      document.getElementById('homeEventoDataInicioInput').value = '';
      document.getElementById('homeEventoDataFimInput').value = '';
      document.getElementById('homeEventoExecutadaInput').checked = false;
      document.getElementById('homeEventoParteIdInput').innerHTML = '<option value="">Selecione...</option>';
      var label = document.getElementById('homeEventoParteLabel');
      if (label) label.textContent = 'Fornecedor/Cliente';
      mostrarPainelEditorEventoHome(true);
    }

    async function carregarEventoSelecionadoHome() {
      var eventoId = Number(homeEventoSelecionadoIdGestao || 0);
      if (!eventoId) {
        novoEventoHomeFormulario();
        return;
      }
      var cfg = obterEventoHomePorId(eventoId);
      if (!cfg || cfg.tarefa_executada) {
        voltarListaEventosHome();
        return;
      }
      document.getElementById('homeEventoNomeInput').value = cfg.nome_evento || '';
      document.getElementById('homeEventoTipoInput').value = cfg.tipo_evento || '';
      await atualizarOpcoesParteEventoHome();
      document.getElementById('homeEventoParteIdInput').value = cfg.parte_id != null ? String(cfg.parte_id) : '';
      document.getElementById('homeEventoMensagemInput').value = cfg.mensagem || '';
      document.getElementById('homeEventoDataInicioInput').value = cfg.data_inicio || '';
      document.getElementById('homeEventoDataFimInput').value = cfg.data_fim || '';
      document.getElementById('homeEventoExecutadaInput').checked = !!cfg.tarefa_executada;
      mostrarPainelEditorEventoHome(true);
    }

    async function editarEventoHomeSelecionado() {
      if (!homeEventoSelecionadoIdGestao) {
        setMsg('statusModalHomeEvento', 'Selecione um evento na lista para editar.', false);
        return;
      }
      await carregarEventoSelecionadoHome();
    }

    function voltarListaEventosHome() {
      mostrarPainelEditorEventoHome(false);
      preencherListaEventosModalHome();
    }

    async function abrirModalEventoHome() {
      try {
        await carregarEventoHome();
        preencherListaEventosModalHome();
        homeEventoSelecionadoIdGestao = null;
        mostrarPainelEditorEventoHome(false);
        setMsg('statusModalHomeEvento', '');
        document.getElementById('modalHomeEvento').classList.remove('hidden');
      } catch (err) {
        setMsg('statusHomeConfig', `Falha ao abrir evento: ${err.message}`, false);
      }
    }

    function fecharModalEventoHome() {
      document.getElementById('modalHomeEvento').classList.add('hidden');
    }

    async function salvarConfiguracaoEventoHome() {
      var eventoId = Number(homeEventoSelecionadoIdGestao) || null;
      var nome = String(document.getElementById('homeEventoNomeInput').value || '').trim();
      var tipo = String(document.getElementById('homeEventoTipoInput').value || '').trim();
      var parteId = Number(document.getElementById('homeEventoParteIdInput').value) || null;
      var msg = String(document.getElementById('homeEventoMensagemInput').value || '').trim();
      var ini = String(document.getElementById('homeEventoDataInicioInput').value || '').slice(0, 10);
      var fim = String(document.getElementById('homeEventoDataFimInput').value || '').slice(0, 10);
      var executada = !!document.getElementById('homeEventoExecutadaInput').checked;
      if (!nome) {
        setMsg('statusModalHomeEvento', 'Informe o nome do evento.', false);
        return;
      }
      if (!tipo) {
        setMsg('statusModalHomeEvento', 'Informe o tipo do evento.', false);
        return;
      }
      if (tipo !== 'contas_pagar' && tipo !== 'contas_receber') {
        setMsg('statusModalHomeEvento', 'Tipo do evento invalido.', false);
        return;
      }
      if (!parteId) {
        setMsg('statusModalHomeEvento', tipo === 'contas_pagar' ? 'Selecione o fornecedor.' : 'Selecione o cliente.', false);
        return;
      }
      if (!msg) {
        setMsg('statusModalHomeEvento', 'Informe a mensagem do evento.', false);
        return;
      }
      if (!ini || !fim) {
        setMsg('statusModalHomeEvento', 'Informe o periodo (de/ate).', false);
        return;
      }
      if (fim < ini) {
        setMsg('statusModalHomeEvento', 'Data final nao pode ser menor que a inicial.', false);
        return;
      }
      try {
        var payload = {
          nome_evento: nome,
          tipo_evento: tipo,
          parte_id: parteId,
          mensagem: msg,
          data_inicio: ini,
          data_fim: fim,
          tarefa_executada: executada,
        };
        if (eventoId) {
          await api(`/home-eventos/${eventoId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
        } else {
          await api('/home-eventos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
        }
        homeEventosAvisosFechadosSessao = false;
        homeEventoFechadosSessaoIds.clear();
        setMsg('statusModalHomeEvento', 'Evento salvo com sucesso.');
        setMsg('statusHomeConfig', 'Eventos da tela inicial atualizados.');
        await carregarEventoHome();
        if (eventoId) homeEventoSelecionadoIdGestao = eventoId;
        preencherListaEventosModalHome();
        mostrarPainelEditorEventoHome(false);
      } catch (err) {
        setMsg('statusModalHomeEvento', err.message, false);
      }
    }

    async function atualizarOpcoesParteEventoHome() {
      var tipo = String((document.getElementById('homeEventoTipoInput') || {}).value || '');
      var sel = document.getElementById('homeEventoParteIdInput');
      var label = document.getElementById('homeEventoParteLabel');
      if (!sel) return;
      sel.innerHTML = '<option value="">Selecione...</option>';
      if (tipo === 'contas_pagar') {
        if (label) label.textContent = 'Fornecedor';
        try {
          var cad = await api('/cadastros-gerais?contexto=pessoas');
          cad.filter(function(x) { return !!x.is_fornecedor; }).forEach(function(x) {
            var o = document.createElement('option');
            o.value = String(x.id);
            o.textContent = `${x.id} - ${x.razao_social || ''}`;
            sel.appendChild(o);
          });
        } catch (err) {
          setMsg('statusModalHomeEvento', `Falha ao listar fornecedores: ${err.message}`, false);
        }
        return;
      }
      if (tipo === 'contas_receber') {
        if (label) label.textContent = 'Cliente';
        try {
          var cli = await api('/clientes');
          cli.forEach(function(x) {
            var o = document.createElement('option');
            o.value = String(x.id);
            o.textContent = `${x.id} - ${x.nome || ''}`;
            sel.appendChild(o);
          });
        } catch (err2) {
          setMsg('statusModalHomeEvento', `Falha ao listar clientes: ${err2.message}`, false);
        }
        return;
      }
      if (label) label.textContent = 'Fornecedor/Cliente';
    }

    async function selecionarParteFinanceiraPorId(tipo, parteId) {
      if (!parteId) return;
      if (tipo === 'pagar') {
        var cadastros = await api('/cadastros-gerais?contexto=pessoas');
        var fornecedor = cadastros.find(function(item) { return Number(item.id) === Number(parteId) && !!item.is_fornecedor; });
        if (!fornecedor) throw new Error('Fornecedor do evento nao encontrado.');
        selecionarParteFinanceira(fornecedor.id, fornecedor.razao_social || 'Sem nome', fornecedor.cnpj || '');
        return;
      }
      var clientes = await api('/clientes');
      var cliente = clientes.find(function(item) { return Number(item.id) === Number(parteId); });
      if (!cliente) throw new Error('Cliente do evento nao encontrado.');
      selecionarParteFinanceira(cliente.id, cliente.nome || 'Sem nome', cliente.cnpj_cpf || '');
    }

    async function executarEventoHomeAgora(eventoId = null) {
      try {
        var cfg = eventoId ? obterEventoHomePorId(eventoId) : null;
        if (!cfg) {
          cfg = await api('/home-eventos');
          if (Array.isArray(cfg)) {
            cfg = eventoId
              ? cfg.find(function(item) { return Number(item.id) === Number(eventoId); })
              : cfg.find(function(item) { return !item.tarefa_executada; });
          }
        }
        if (!cfg || !cfg.tipo_evento) {
          setMsg('statusModalHomeEvento', 'Salve o evento antes de executar.', false);
          return;
        }
        var tipoFin = cfg.tipo_evento === 'contas_receber' ? 'receber' : 'pagar';
        abrirFinanceiro(true);
        selecionarAbaFinanceiro(tipoFin === 'pagar' ? 'pagar' : 'receber');
        await abrirModalFinanceiro(tipoFin);
        if (cfg.parte_id) {
          await selecionarParteFinanceiraPorId(tipoFin, cfg.parte_id);
        }
        var nomeEvento = String(cfg.nome_evento || '').trim();
        var msgEvento = String(cfg.mensagem || '').trim();
        var descricaoMontada = [nomeEvento, msgEvento].filter(function(x) { return !!x; }).join(' - ');
        if (tipoFin === 'pagar') {
          var finDesc = document.getElementById('finDescricao');
          var finDoc = document.getElementById('finDocumentoOriginal');
          if (finDesc) finDesc.value = descricaoMontada || nomeEvento || msgEvento;
          if (finDoc && msgEvento) finDoc.value = msgEvento;
        } else {
          var finDescRec = document.getElementById('finDescricaoReceber');
          var finDocRec = document.getElementById('finDocumentoOriginalReceber');
          if (finDescRec) finDescRec.value = descricaoMontada || nomeEvento || msgEvento;
          if (finDocRec && msgEvento) finDocRec.value = msgEvento;
        }
        if (cfg.id) fecharAvisoEventoHome(cfg.id);
        setMsg('statusModalHomeEvento', 'Lancamento aberto com descricao preenchida para finalizar.');
      } catch (err) {
        setMsg('statusModalHomeEvento', `Falha ao executar evento: ${err.message}`, false);
      }
    }

    function executarEventoSelecionadoHomeAgora() {
      var eventoId = Number(homeEventoSelecionadoIdGestao) || null;
      void executarEventoHomeAgora(eventoId);
    }

    async function marcarEventoHomeExecutado(eventoId = null) {
      try {
        var alvoId = Number(eventoId) || Number(homeEventoSelecionadoIdGestao) || 0;
        if (!alvoId) {
          setMsg('statusModalHomeEvento', 'Selecione um evento para marcar como executado.', false);
          return;
        }
        await api(`/home-eventos/${alvoId}/executar`, { method: 'POST' });
        homeEventoFechadosSessaoIds.add(alvoId);
        if (Number(homeEventoSelecionadoIdGestao) === Number(alvoId)) {
          homeEventoSelecionadoIdGestao = null;
        }
        setMsg('statusHomeConfig', 'Evento marcado como tarefa executada.');
        await carregarEventoHome();
        preencherListaEventosModalHome();
        mostrarPainelEditorEventoHome(false);
      } catch (err) {
        setMsg('statusHomeConfig', err.message, false);
      }
    }

    async function carregarIndicadoresOnixHome() {
      try {
        var semana = calcularIntervaloSemanaAtual();
        var sextaIso = calcularProximaSexta();
        var hojeIso = dataIsoHoje();
        var [contasPagar, contasReceber, contasCorrentes] = await Promise.all([
          api('/contas-pagar'),
          api('/contas-receber'),
          api('/contas-correntes'),
        ]);

        var pagarSemana = contasPagar
          .filter(c => String(c.status || '').toLowerCase() !== 'pago')
          .filter(c => {
            var d = String(c.data_vencimento || '').slice(0, 10);
            return d >= semana.inicio && d <= semana.fim;
          })
          .reduce((acc, c) => acc + Number(c.valor || 0), 0);

        var receberSemana = contasReceber
          .filter(c => String(c.status || '').toLowerCase() !== 'recebido')
          .filter(c => {
            var d = String(c.data_vencimento || '').slice(0, 10);
            return d >= semana.inicio && d <= semana.fim;
          })
          .reduce((acc, c) => acc + Number(c.valor || 0), 0);

        var saldoAtual = contasCorrentes.reduce((acc, c) => acc + Number(c.saldo_atual || 0), 0);
        var entradasAteSexta = contasReceber
          .filter(c => String(c.status || '').toLowerCase() !== 'recebido')
          .filter(c => {
            var d = String(c.data_vencimento || '').slice(0, 10);
            return d >= hojeIso && d <= sextaIso;
          })
          .reduce((acc, c) => acc + Number(c.valor || 0), 0);
        var saidasAteSexta = contasPagar
          .filter(c => String(c.status || '').toLowerCase() !== 'pago')
          .filter(c => {
            var d = String(c.data_vencimento || '').slice(0, 10);
            return d >= hojeIso && d <= sextaIso;
          })
          .reduce((acc, c) => acc + Number(c.valor || 0), 0);
        var previsaoSexta = saldoAtual + entradasAteSexta - saidasAteSexta;

        var elPagar = document.getElementById('homePagarSemana');
        var elReceber = document.getElementById('homeReceberSemana');
        var elPrev = document.getElementById('homePrevisaoSexta');
        if (elPagar) elPagar.textContent = moeda(pagarSemana);
        if (elReceber) elReceber.textContent = moeda(receberSemana);
        if (elPrev) elPrev.textContent = moeda(previsaoSexta);

        var st = document.getElementById('statusHomeDashboard');
        if (st) st.textContent = `Semana: ${formatDataBr(semana.inicio)} ate ${formatDataBr(semana.fim)} | Previsao para sexta: ${formatDataBr(sextaIso)}`;
      } catch (err) {
        var stErr = document.getElementById('statusHomeDashboard');
        if (stErr) {
          stErr.className = 'status-line err';
          stErr.textContent = 'Falha ao carregar indicadores do Onix Home: ' + err.message;
        }
      }
    }

    function atualizarVisibilidadeBotoesHomeConfig() {
      var strip = document.getElementById('homeConfigSelector');
      if (!strip) return;
      strip.classList.toggle('hidden', !seletorHomeConfigVisivel);
      strip.classList.toggle('overlay-selector', seletorHomeConfigVisivel);
    }

    function posicionarSeletorHomeConfig() {
      var strip = document.getElementById('homeConfigSelector');
      var btn = document.getElementById('btnHomeConfiguracoes');
      if (!strip || !btn || strip.classList.contains('hidden')) return;
      var rect = btn.getBoundingClientRect();
      strip.style.top = (rect.bottom + 8) + 'px';
      strip.style.left = Math.max(8, rect.left) + 'px';
      requestAnimationFrame(function() {
        if (!strip || strip.classList.contains('hidden')) return;
        var margem = 8;
        var largura = strip.offsetWidth || 320;
        var maxLeft = window.innerWidth - largura - margem;
        var leftAtual = parseFloat(strip.style.left || '0');
        if (!Number.isFinite(leftAtual)) leftAtual = margem;
        strip.style.left = Math.max(margem, Math.min(leftAtual, maxLeft)) + 'px';
      });
    }

    function mostrarSeletorHomeConfig() {
      seletorHomeConfigVisivel = true;
      atualizarVisibilidadeBotoesHomeConfig();
      posicionarSeletorHomeConfig();
      instalarAutoFecharSeletorHomeConfig();
    }

    function ocultarSeletorHomeConfig() {
      seletorHomeConfigVisivel = false;
      if (timerFecharSeletorHomeConfig) {
        clearTimeout(timerFecharSeletorHomeConfig);
        timerFecharSeletorHomeConfig = null;
      }
      atualizarVisibilidadeBotoesHomeConfig();
    }

    function instalarAutoFecharSeletorHomeConfig() {
      var strip = document.getElementById('homeConfigSelector');
      if (!strip) return;
      strip.onmouseenter = function() {
        if (timerFecharSeletorHomeConfig) {
          clearTimeout(timerFecharSeletorHomeConfig);
          timerFecharSeletorHomeConfig = null;
        }
      };
      strip.onmouseleave = function() {
        if (timerFecharSeletorHomeConfig) clearTimeout(timerFecharSeletorHomeConfig);
        timerFecharSeletorHomeConfig = setTimeout(function() {
          if (seletorHomeConfigVisivel) ocultarSeletorHomeConfig();
        }, 120);
      };
    }

    function executarAcaoHomeConfig(acao) {
      ocultarSeletorHomeConfig();
      if (acao === 'empresa') {
        void abrirModalNovoCadastro('geral');
        return;
      }
      if (acao === 'banco') {
        void abrirModalConfigBancoSistema();
        return;
      }
      if (acao === 'nfe') {
        abrirModalNfeConfig();
        return;
      }
      if (acao === 'atualizacoes') {
        void abrirModalAtualizacaoSistema();
        return;
      }
      if (acao === 'evento') {
        void abrirModalEventoHome();
        return;
      }
      if (acao === 'backup') {
        fazerBackup();
        return;
      }
      if (acao === 'restore') {
        var fileEl = document.getElementById('restoreFileInputHome');
        if (fileEl) fileEl.click();
      }
    }

    async function abrirModalConfigBancoSistema() {
      const modal = document.getElementById('modalConfigBanco');
      if (!modal) return;
      modal.classList.remove('hidden');
      setMsg('statusModalConfigBanco', 'Carregando configuracao atual...');
      try {
        const cfg = await api('/sistema/config-banco');
        document.getElementById('cfgBancoHost').value = cfg.db_host || '';
        document.getElementById('cfgBancoPorta').value = String(cfg.db_port || 5432);
        document.getElementById('cfgBancoNome').value = cfg.db_name || '';
        document.getElementById('cfgBancoUsuario').value = cfg.db_user || '';
        document.getElementById('cfgBancoSenha').value = '';
        setMsg('statusModalConfigBanco', `Configuracao carregada. Arquivo: ${cfg.config_path || '-'}`);
      } catch (err) {
        setMsg('statusModalConfigBanco', `Falha ao carregar configuracao: ${err.message}`, false);
      }
    }

    function fecharModalConfigBancoSistema() {
      const modal = document.getElementById('modalConfigBanco');
      if (modal) modal.classList.add('hidden');
      setMsg('statusModalConfigBanco', '');
    }

    function obterPayloadConfigBancoSistema() {
      return {
        db_host: String(document.getElementById('cfgBancoHost').value || '').trim(),
        db_port: Number(document.getElementById('cfgBancoPorta').value || 5432),
        db_name: String(document.getElementById('cfgBancoNome').value || '').trim(),
        db_user: String(document.getElementById('cfgBancoUsuario').value || '').trim(),
        db_password: String(document.getElementById('cfgBancoSenha').value || '').trim(),
      };
    }

    async function testarConfigBancoSistema() {
      const payload = obterPayloadConfigBancoSistema();
      if (!payload.db_host || !payload.db_name || !payload.db_user) {
        setMsg('statusModalConfigBanco', 'Preencha host, banco e usuario.', false);
        return;
      }
      try {
        setMsg('statusModalConfigBanco', 'Testando conexao com o banco...');
        const resp = await apiComTimeout('/sistema/config-banco/testar', 15000, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        setMsg('statusModalConfigBanco', resp.mensagem || 'Conexao validada com sucesso.');
      } catch (err) {
        setMsg('statusModalConfigBanco', `Falha no teste: ${err.message}`, false);
      }
    }

    async function salvarConfigBancoSistema() {
      const payload = obterPayloadConfigBancoSistema();
      if (!payload.db_host || !payload.db_name || !payload.db_user) {
        setMsg('statusModalConfigBanco', 'Preencha host, banco e usuario.', false);
        return;
      }
      const confirmou = window.confirm('Salvar configuracao de banco desta instalacao?');
      if (!confirmou) return;
      try {
        setMsg('statusModalConfigBanco', 'Salvando configuracao...');
        const resp = await apiComTimeout('/sistema/config-banco/salvar', 20000, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        setMsg('statusModalConfigBanco', (resp.mensagem || 'Configuracao salva.') + ' Reinicie o sistema.');
      } catch (err) {
        setMsg('statusModalConfigBanco', `Falha ao salvar: ${err.message}`, false);
      }
    }

    async function abrirModalAtualizacaoSistema() {
      const modal = document.getElementById('modalAtualizacaoSistema');
      if (!modal) return;
      modal.classList.remove('hidden');
      setMsg('statusModalAtualizacaoSistema', 'Consultando versao atual...');
      await verificarAtualizacaoSistema();
      await listarHistoricoAtualizacoesSistema();
    }

    function fecharModalAtualizacaoSistema() {
      const modal = document.getElementById('modalAtualizacaoSistema');
      if (modal) modal.classList.add('hidden');
      atualizacaoHistoricoSelecionadoId = null;
      setMsg('statusModalAtualizacaoSistema', '');
    }

    function selecionarAtualizacaoHistorico(id) {
      atualizacaoHistoricoSelecionadoId = Number(id || 0) || null;
      if (atualizacaoHistoricoSelecionadoId) {
        setMsg('statusModalAtualizacaoSistema', `Atualizacao #${atualizacaoHistoricoSelecionadoId} selecionada.`);
      }
    }

    async function listarHistoricoAtualizacoesSistema() {
      try {
        const lista = await api('/sistema/atualizacao/historico');
        const tb = document.getElementById('tbAtualizacaoHistorico');
        if (!tb) return;
        tb.innerHTML = '';
        (Array.isArray(lista) ? lista : []).forEach(item => {
          const tr = document.createElement('tr');
          const marcado = Number(atualizacaoHistoricoSelecionadoId || 0) === Number(item.id) ? 'checked' : '';
          const msg = String(item.mensagem || '');
          tr.innerHTML = `<td><input type="radio" name="selAtualizacaoHistorico" ${marcado} onclick="selecionarAtualizacaoHistorico(${Number(item.id)})"></td><td>${item.id}</td><td>${formatDataBr(item.iniciado_em)}</td><td>${item.versao_origem || '-'}</td><td>${item.versao_alvo || '-'}</td><td>${escapeHtml(item.status || '-')}</td><td>${escapeHtml(msg)}</td><td>${item.rollback_executado ? 'Ja executado' : (item.rollback_disponivel ? 'Disponivel' : '-')}</td>`;
          tb.appendChild(tr);
        });
      } catch (err) {
        setMsg('statusModalAtualizacaoSistema', `Falha ao carregar historico: ${err.message}`, false);
      }
    }

    async function verificarAtualizacaoSistema() {
      try {
        const versao = await api('/sistema/versao');
        const check = await api('/sistema/atualizacao/check');
        const atualEl = document.getElementById('atualizacaoVersaoAtual');
        const dispEl = document.getElementById('atualizacaoVersaoDisponivel');
        const pacoteEl = document.getElementById('atualizacaoPacoteUrl');
        const changelogEl = document.getElementById('atualizacaoChangelog');
        if (atualEl) atualEl.textContent = `Versao atual: ${versao.versao || check.versao_atual || '-'}`;
        if (dispEl) dispEl.textContent = `Versao disponivel: ${check.versao_disponivel || '-'}`;
        if (pacoteEl) pacoteEl.textContent = `Pacote: ${check.pacote_url || 'nao informado no manifesto'}`;
        if (changelogEl) changelogEl.value = String(check.changelog || 'Sem changelog informado.');
        if (check.tem_atualizacao) {
          setMsg('statusModalAtualizacaoSistema', `Atualizacao disponivel para ${check.versao_disponivel}.`);
        } else {
          setMsg('statusModalAtualizacaoSistema', 'Seu sistema ja esta na versao mais recente.');
        }
      } catch (err) {
        setMsg('statusModalAtualizacaoSistema', `Falha ao verificar atualizacao: ${err.message}`, false);
      }
    }

    async function aplicarAtualizacaoSistema() {
      try {
        const check = await api('/sistema/atualizacao/check');
        if (!check.tem_atualizacao) {
          setMsg('statusModalAtualizacaoSistema', 'Nao ha atualizacao pendente para aplicar.');
          return;
        }
        if (!check.pacote_url) {
          setMsg('statusModalAtualizacaoSistema', 'Manifesto sem pacote de atualizacao (package_url).', false);
          return;
        }
        const confirmou = window.confirm(`Confirmar atualizacao para a versao ${check.versao_disponivel}?`);
        if (!confirmou) return;
        setMsg('statusModalAtualizacaoSistema', `Aplicando atualizacao ${check.versao_disponivel}... aguarde.`);
        const resp = await api('/sistema/atualizacao/aplicar', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ versao_alvo: check.versao_disponivel }),
        });
        setMsg('statusModalAtualizacaoSistema', resp.mensagem || 'Atualizacao aplicada.');
        await verificarAtualizacaoSistema();
        await listarHistoricoAtualizacoesSistema();
      } catch (err) {
        setMsg('statusModalAtualizacaoSistema', `Falha ao iniciar atualizacao: ${err.message}`, false);
      }
    }

    async function rollbackAtualizacaoSistemaSelecionada() {
      if (!atualizacaoHistoricoSelecionadoId) {
        setMsg('statusModalAtualizacaoSistema', 'Selecione uma atualizacao no historico para rollback.', false);
        return;
      }
      const confirmou = window.confirm(`Confirmar rollback da atualizacao #${atualizacaoHistoricoSelecionadoId}?`);
      if (!confirmou) return;
      try {
        const resp = await api('/sistema/atualizacao/rollback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ atualizacao_id: Number(atualizacaoHistoricoSelecionadoId) }),
        });
        setMsg('statusModalAtualizacaoSistema', resp.mensagem || 'Rollback solicitado.');
        await listarHistoricoAtualizacoesSistema();
      } catch (err) {
        setMsg('statusModalAtualizacaoSistema', `Falha no rollback: ${err.message}`, false);
      }
    }

    function abrirOnixHome() {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pFat = document.getElementById('faturasPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pIa = document.getElementById('onixIaPanel');
      if (!pHome) return;
      pHome.classList.remove('hidden');
      if (pCad) pCad.classList.add('hidden');
      if (pRel) pRel.classList.add('hidden');
      if (pFat) pFat.classList.add('hidden');
      if (pVendas) pVendas.classList.add('hidden');
      if (pEstoque) pEstoque.classList.add('hidden');
      if (pContador) pContador.classList.add('hidden');
      if (pDash) pDash.classList.add('hidden');
      if (pIa) pIa.classList.add('hidden');
      if (seletorHomeConfigVisivel) ocultarSeletorHomeConfig();
      if (seletorEstoqueVisivel) ocultarSeletorEstoque();
      if (seletorContadorVisivel) ocultarSeletorContador();
      ativarMenuPrincipal('onixhome');
      void carregarIndicadoresOnixHome();
      void carregarEventoHome();
    }

    function abrirFinanceiro(forcar = false) {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pFat = document.getElementById('faturasPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pIa = document.getElementById('onixIaPanel');
      if (!pDash) return;
      if (!pDash.classList.contains('hidden') && !forcar) {
        if (seletorFinanceiroVisivel) {
          ocultarSeletorFinanceiro();
        } else {
          mostrarSeletorFinanceiro();
        }
        return;
      }
      if (pHome) pHome.classList.add('hidden');
      ocultarSeletorHomeConfig();
      if (pCad) pCad.classList.add('hidden');
      if (pRel) pRel.classList.add('hidden');
      if (pFat) pFat.classList.add('hidden');
      if (pVendas) pVendas.classList.add('hidden');
      if (pEstoque) pEstoque.classList.add('hidden');
      if (pContador) pContador.classList.add('hidden');
      if (pIa) pIa.classList.add('hidden');
      pDash.classList.remove('hidden');
      ativarMenuPrincipal('financeiro');
      if (!cardFinanceiroAtivo) {
        mostrarConteudoPadraoFinanceiro();
      }
      mostrarSeletorFinanceiro();
    }

    function abrirCadastro(forcar = false) {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pFat = document.getElementById('faturasPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pIa = document.getElementById('onixIaPanel');
      if (!pCad || !pDash) return;
      if (!pCad.classList.contains('hidden') && !forcar) {
        if (seletorCadastroVisivel) {
          ocultarSeletorCardsCadastro();
        } else {
          mostrarSeletorCardsCadastro();
        }
        return;
      }
      if (pHome) pHome.classList.add('hidden');
      ocultarSeletorHomeConfig();
      pCad.classList.remove('hidden');
      if (pRel) pRel.classList.add('hidden');
      if (pFat) pFat.classList.add('hidden');
      if (pVendas) pVendas.classList.add('hidden');
      if (pEstoque) pEstoque.classList.add('hidden');
      if (pContador) pContador.classList.add('hidden');
      if (pIa) pIa.classList.add('hidden');
      pDash.classList.add('hidden');
      ativarMenuPrincipal('cadastro');
      if (!cardCadastroAtivo) {
        mostrarConteudoCadastroPadrao();
      }
      mostrarSeletorCardsCadastro();
      setMsg('statusCadastro', '');
      listarCadastros();
      carregarEmpresaPadrao();
    }

    function labelCardFaturas(aba) {
      var mapa = { cartoes: 'Cartoes de Credito', faturas: 'Faturas em Aberto', faturasPagas: 'Faturas Pagas' };
      return mapa[aba] || aba;
    }

    function labelCardFinanceiro(aba) {
      var mapa = { pagar: 'Contas a Pagar', receber: 'Contas a Receber', pagas: 'Contas Pagas', recebidas: 'Contas Recebidas' };
      return mapa[aba] || aba;
    }

    function labelCardVendas(aba) {
      var mapa = { pedidos: 'Pedidos', orcamentos: 'Orcamentos', nfe: 'Notas NF-e', nfse: 'Notas NFS-e' };
      return mapa[aba] || aba;
    }

    function labelCardEstoque(aba) {
      var mapa = { compra: 'Lancar Compra', posicao: 'Posicao Atual', ajuste: 'Ajuste de Estoque' };
      return mapa[aba] || aba;
    }

    function labelCardCadastro(aba) {
      var mapa = {
        geral: 'Geral',
        pessoas: 'Pessoas',
        produtos: 'Produtos',
        catProd: 'Cat. Prod.',
        condPag: 'Cond. Pag.',
        grupo: 'Grupo de Despesas',
        plano: 'Plano de Contas',
        grupoContas: 'Grupo de Contas',
        contas: 'Contas Correntes',
        usuarios: 'Usuarios e Permissoes',
      };
      return mapa[aba] || aba;
    }

    function labelCardContador(aba) {
      var mapa = {
        checklist: 'Checklist Mensal',
        fiscal: 'Documentos Fiscais',
        financeiro: 'Financeiro para Contabilidade',
        envio: 'Envio ao Contador',
      };
      return mapa[aba] || aba;
    }

    function totalCardsAbertosTopo() {
      return cardsCadastroAbertos.length + cardsFaturasAbertos.length + cardsFinanceiroAbertos.length + cardsVendasAbertos.length + cardsEstoqueAbertos.length + cardsContadorAbertos.length;
    }

    function voltarParaHomeSeSemCardsAbertos() {
      if (totalCardsAbertosTopo() > 0) return false;
      abrirOnixHome();
      return true;
    }

    function atualizarVisibilidadeBotoesCadastro() {
      var strip = document.querySelector('#cadastroPanel .vertical-tab-strip');
      if (!strip) return;
      var mostrarStrip = seletorCadastroVisivel;
      strip.classList.toggle('hidden', !mostrarStrip);
      strip.classList.toggle('overlay-selector', seletorCadastroVisivel);
      var botoes = strip.querySelectorAll('.tab-btn');
      botoes.forEach(function(btn) {
        var alvo = btn.getAttribute('data-aba') || '';
        btn.classList.toggle('hidden', cardsCadastroAbertos.indexOf(alvo) >= 0);
      });
    }

    function mostrarSeletorCardsCadastro() {
      seletorCadastroVisivel = true;
      atualizarVisibilidadeBotoesCadastro();
      posicionarSeletorCardsCadastro();
      instalarAutoFecharSeletorCadastro();
    }

    function ocultarSeletorCardsCadastro() {
      seletorCadastroVisivel = false;
      if (timerFecharSeletorCadastro) {
        clearTimeout(timerFecharSeletorCadastro);
        timerFecharSeletorCadastro = null;
      }
      atualizarVisibilidadeBotoesCadastro();
    }

    function instalarAutoFecharSeletorCadastro() {
      var strip = document.querySelector('#cadastroPanel .vertical-tab-strip');
      if (!strip) return;
      strip.onmouseenter = function() {
        if (timerFecharSeletorCadastro) {
          clearTimeout(timerFecharSeletorCadastro);
          timerFecharSeletorCadastro = null;
        }
      };
      strip.onmouseleave = function() {
        if (timerFecharSeletorCadastro) clearTimeout(timerFecharSeletorCadastro);
        timerFecharSeletorCadastro = setTimeout(function() {
          if (seletorCadastroVisivel) ocultarSeletorCardsCadastro();
        }, 120);
      };
    }

    function posicionarSeletorCardsCadastro() {
      var strip = document.querySelector('#cadastroPanel .vertical-tab-strip');
      var aba = document.getElementById('menuCadastro');
      if (!strip || !aba || strip.classList.contains('hidden')) return;
      var rect = aba.getBoundingClientRect();
      strip.style.top = (rect.bottom + 8) + 'px';
      strip.style.left = Math.max(8, rect.left) + 'px';
      requestAnimationFrame(function() {
        if (!strip || strip.classList.contains('hidden')) return;
        var margem = 8;
        var largura = strip.offsetWidth || 320;
        var maxLeft = window.innerWidth - largura - margem;
        var leftAtual = parseFloat(strip.style.left || '0');
        if (!Number.isFinite(leftAtual)) leftAtual = margem;
        strip.style.left = Math.max(margem, Math.min(leftAtual, maxLeft)) + 'px';
      });
    }

    function renderCardsAbertosCadastro() {
      var box = document.getElementById('cadastroOpenCards');
      if (!box) return;
      box.innerHTML = '';
      if (!cardsCadastroAbertos.length) {
        box.classList.add('hidden');
        atualizarVisibilidadeBotoesCadastro();
        return;
      }
      box.classList.remove('hidden');
      cardsCadastroAbertos.forEach(function(aba) {
        var pill = document.createElement('div');
        pill.className = 'open-card-pill' + (aba === cardCadastroAtivo ? ' active' : '');
        pill.setAttribute('role', 'button');
        pill.tabIndex = 0;
        pill.onclick = function() { abrirAbaCadastro(aba); };
        var titulo = document.createElement('span');
        titulo.textContent = labelCardCadastro(aba);
        var fechar = document.createElement('button');
        fechar.type = 'button';
        fechar.className = 'close-open-card';
        fechar.title = 'Fechar card';
        fechar.textContent = 'x';
        fechar.onclick = function(ev) {
          if (ev.stopPropagation) ev.stopPropagation();
          fecharCardCadastro(aba);
        };
        pill.appendChild(titulo);
        pill.appendChild(fechar);
        box.appendChild(pill);
      });
      atualizarVisibilidadeBotoesCadastro();
      renderCardsGlobaisAbertos();
    }

    function fecharCardCadastro(aba) {
      var idx = cardsCadastroAbertos.indexOf(aba);
      if (idx < 0) return;
      cardsCadastroAbertos.splice(idx, 1);
      if (!cardsCadastroAbertos.length) {
        cardCadastroAtivo = null;
        mostrarConteudoCadastroPadrao();
        mostrarSeletorCardsCadastro();
        renderCardsAbertosCadastro();
        renderCardsGlobaisAbertos();
        voltarParaHomeSeSemCardsAbertos();
        return;
      }
      if (cardCadastroAtivo === aba) {
        var proximo = cardsCadastroAbertos[Math.max(0, idx - 1)] || cardsCadastroAbertos[0];
        abrirAbaCadastro(proximo);
        return;
      }
      renderCardsAbertosCadastro();
      renderCardsGlobaisAbertos();
    }

    function mostrarConteudoCadastroPadrao() {
      document.getElementById('abaGeral').classList.remove('hidden');
      document.getElementById('abaPessoas').classList.add('hidden');
      document.getElementById('abaProdutos').classList.add('hidden');
      document.getElementById('abaCategoriasProduto').classList.add('hidden');
      var pCondPag = document.getElementById('abaCondPag');
      if (pCondPag) pCondPag.classList.add('hidden');
      document.getElementById('abaGrupoDespesas').classList.add('hidden');
      document.getElementById('abaPlanoContas').classList.add('hidden');
      document.getElementById('abaGrupoContas').classList.add('hidden');
      document.getElementById('abaContasCorrentes').classList.add('hidden');
      var pUsuarios = document.getElementById('abaUsuarios');
      if (pUsuarios) pUsuarios.classList.add('hidden');

      document.getElementById('abaBtnGeral').classList.add('active');
      document.getElementById('abaBtnPessoas').classList.remove('active');
      document.getElementById('abaBtnProdutos').classList.remove('active');
      document.getElementById('abaBtnCatProd').classList.remove('active');
      var bCondPag = document.getElementById('abaBtnCondPag');
      if (bCondPag) bCondPag.classList.remove('active');
      document.getElementById('abaBtnGrupo').classList.remove('active');
      document.getElementById('abaBtnPlano').classList.remove('active');
      document.getElementById('abaBtnGrupoContas').classList.remove('active');
      document.getElementById('abaBtnContas').classList.remove('active');
      var bUsuarios = document.getElementById('abaBtnUsuarios');
      if (bUsuarios) bUsuarios.classList.remove('active');
    }

    function atualizarVisibilidadeBotoesFaturas() {
      var strip = document.querySelector('#faturasPanel .vertical-tab-strip');
      if (!strip) return;
      strip.classList.toggle('hidden', !seletorFaturasVisivel);
      strip.classList.toggle('overlay-selector', seletorFaturasVisivel);
      var botoes = strip.querySelectorAll('.tab-btn');
      botoes.forEach(function(btn) {
        var alvo = btn.getAttribute('data-aba') || '';
        btn.classList.toggle('hidden', cardsFaturasAbertos.indexOf(alvo) >= 0);
      });
    }

    function posicionarSeletorFaturas() {
      var strip = document.querySelector('#faturasPanel .vertical-tab-strip');
      var aba = document.getElementById('menuFaturas');
      if (!strip || !aba || strip.classList.contains('hidden')) return;
      var rect = aba.getBoundingClientRect();
      strip.style.top = (rect.bottom + 8) + 'px';
      strip.style.left = Math.max(8, rect.left) + 'px';
    }

    function mostrarSeletorFaturas() {
      seletorFaturasVisivel = true;
      atualizarVisibilidadeBotoesFaturas();
      posicionarSeletorFaturas();
      instalarAutoFecharSeletorFaturas();
    }

    function ocultarSeletorFaturas() {
      seletorFaturasVisivel = false;
      if (timerFecharSeletorFaturas) {
        clearTimeout(timerFecharSeletorFaturas);
        timerFecharSeletorFaturas = null;
      }
      atualizarVisibilidadeBotoesFaturas();
    }

    function instalarAutoFecharSeletorFaturas() {
      var strip = document.querySelector('#faturasPanel .vertical-tab-strip');
      if (!strip) return;
      strip.onmouseenter = function() {
        if (timerFecharSeletorFaturas) {
          clearTimeout(timerFecharSeletorFaturas);
          timerFecharSeletorFaturas = null;
        }
      };
      strip.onmouseleave = function() {
        if (timerFecharSeletorFaturas) clearTimeout(timerFecharSeletorFaturas);
        timerFecharSeletorFaturas = setTimeout(function() {
          if (seletorFaturasVisivel) ocultarSeletorFaturas();
        }, 120);
      };
    }

    function renderCardsAbertosFaturas() {
      var box = document.getElementById('faturasOpenCards');
      if (!box) return;
      box.innerHTML = '';
      if (!cardsFaturasAbertos.length) {
        box.classList.add('hidden');
        atualizarVisibilidadeBotoesFaturas();
        return;
      }
      box.classList.remove('hidden');
      cardsFaturasAbertos.forEach(function(aba) {
        var pill = document.createElement('div');
        pill.className = 'open-card-pill' + (aba === cardFaturasAtivo ? ' active' : '');
        pill.setAttribute('role', 'button');
        pill.tabIndex = 0;
        pill.onclick = function() { abrirAbaFaturas(aba); };
        var titulo = document.createElement('span');
        titulo.textContent = labelCardFaturas(aba);
        var fechar = document.createElement('button');
        fechar.type = 'button';
        fechar.className = 'close-open-card';
        fechar.title = 'Fechar card';
        fechar.textContent = 'x';
        fechar.onclick = function(ev) {
          if (ev.stopPropagation) ev.stopPropagation();
          fecharCardFaturas(aba);
        };
        pill.appendChild(titulo);
        pill.appendChild(fechar);
        box.appendChild(pill);
      });
      atualizarVisibilidadeBotoesFaturas();
      renderCardsGlobaisAbertos();
    }

    function fecharCardFaturas(aba) {
      var idx = cardsFaturasAbertos.indexOf(aba);
      if (idx >= 0) cardsFaturasAbertos.splice(idx, 1);
      if (!cardsFaturasAbertos.length) {
        cardFaturasAtivo = null;
        mostrarSeletorFaturas();
        mostrarConteudoPadraoFaturas();
        renderCardsAbertosFaturas();
        renderCardsGlobaisAbertos();
        voltarParaHomeSeSemCardsAbertos();
        return;
      }
      if (cardFaturasAtivo === aba) {
        var prox = cardsFaturasAbertos[Math.max(0, idx - 1)] || cardsFaturasAbertos[0];
        abrirAbaFaturas(prox);
        return;
      }
      renderCardsAbertosFaturas();
    }

    function mostrarConteudoPadraoFaturas() {
      var cartoes = document.getElementById('fatConteudoCartoes');
      var faturas = document.getElementById('fatConteudoFaturas');
      var faturasPagas = document.getElementById('fatConteudoFaturasPagas');
      var btnC = document.getElementById('fatAbaCartoes');
      var btnF = document.getElementById('fatAbaFaturasLista');
      var btnFP = document.getElementById('fatAbaFaturasPagas');
      if (cartoes) cartoes.classList.remove('hidden');
      if (faturas) faturas.classList.add('hidden');
      if (faturasPagas) faturasPagas.classList.add('hidden');
      if (btnC) btnC.classList.add('active');
      if (btnF) btnF.classList.remove('active');
      if (btnFP) btnFP.classList.remove('active');
    }

    function atualizarVisibilidadeBotoesFinanceiro() {
      var strip = document.querySelector('#dashboardPanel .vertical-tab-strip');
      if (!strip) return;
      strip.classList.toggle('hidden', !seletorFinanceiroVisivel);
      strip.classList.toggle('overlay-selector', seletorFinanceiroVisivel);
      var botoes = strip.querySelectorAll('.tab-btn');
      botoes.forEach(function(btn) {
        var alvo = btn.getAttribute('data-aba') || '';
        btn.classList.toggle('hidden', cardsFinanceiroAbertos.indexOf(alvo) >= 0);
      });
    }

    function posicionarSeletorFinanceiro() {
      var strip = document.querySelector('#dashboardPanel .vertical-tab-strip');
      var aba = document.getElementById('menuFinanceiro');
      if (!strip || !aba || strip.classList.contains('hidden')) return;
      var rect = aba.getBoundingClientRect();
      strip.style.top = (rect.bottom + 8) + 'px';
      strip.style.left = Math.max(8, rect.left) + 'px';
    }

    function mostrarSeletorFinanceiro() {
      seletorFinanceiroVisivel = true;
      atualizarVisibilidadeBotoesFinanceiro();
      posicionarSeletorFinanceiro();
      instalarAutoFecharSeletorFinanceiro();
    }

    function ocultarSeletorFinanceiro() {
      seletorFinanceiroVisivel = false;
      if (timerFecharSeletorFinanceiro) {
        clearTimeout(timerFecharSeletorFinanceiro);
        timerFecharSeletorFinanceiro = null;
      }
      atualizarVisibilidadeBotoesFinanceiro();
    }

    function instalarAutoFecharSeletorFinanceiro() {
      var strip = document.querySelector('#dashboardPanel .vertical-tab-strip');
      if (!strip) return;
      strip.onmouseenter = function() {
        if (timerFecharSeletorFinanceiro) {
          clearTimeout(timerFecharSeletorFinanceiro);
          timerFecharSeletorFinanceiro = null;
        }
      };
      strip.onmouseleave = function() {
        if (timerFecharSeletorFinanceiro) clearTimeout(timerFecharSeletorFinanceiro);
        timerFecharSeletorFinanceiro = setTimeout(function() {
          if (seletorFinanceiroVisivel) ocultarSeletorFinanceiro();
        }, 120);
      };
    }

    function renderCardsAbertosFinanceiro() {
      var box = document.getElementById('financeiroOpenCards');
      if (!box) return;
      box.innerHTML = '';
      if (!cardsFinanceiroAbertos.length) {
        box.classList.add('hidden');
        atualizarVisibilidadeBotoesFinanceiro();
        return;
      }
      box.classList.remove('hidden');
      cardsFinanceiroAbertos.forEach(function(aba) {
        var pill = document.createElement('div');
        pill.className = 'open-card-pill' + (aba === cardFinanceiroAtivo ? ' active' : '');
        pill.setAttribute('role', 'button');
        pill.tabIndex = 0;
        pill.onclick = function() { selecionarAbaFinanceiro(aba); };
        var titulo = document.createElement('span');
        titulo.textContent = labelCardFinanceiro(aba);
        var fechar = document.createElement('button');
        fechar.type = 'button';
        fechar.className = 'close-open-card';
        fechar.title = 'Fechar card';
        fechar.textContent = 'x';
        fechar.onclick = function(ev) {
          if (ev.stopPropagation) ev.stopPropagation();
          fecharCardFinanceiro(aba);
        };
        pill.appendChild(titulo);
        pill.appendChild(fechar);
        box.appendChild(pill);
      });
      atualizarVisibilidadeBotoesFinanceiro();
      renderCardsGlobaisAbertos();
    }

    function fecharCardFinanceiro(aba) {
      var idx = cardsFinanceiroAbertos.indexOf(aba);
      if (idx >= 0) cardsFinanceiroAbertos.splice(idx, 1);
      if (!cardsFinanceiroAbertos.length) {
        cardFinanceiroAtivo = null;
        mostrarSeletorFinanceiro();
        mostrarConteudoPadraoFinanceiro();
        renderCardsAbertosFinanceiro();
        renderCardsGlobaisAbertos();
        voltarParaHomeSeSemCardsAbertos();
        return;
      }
      if (cardFinanceiroAtivo === aba) {
        var prox = cardsFinanceiroAbertos[Math.max(0, idx - 1)] || cardsFinanceiroAbertos[0];
        selecionarAbaFinanceiro(prox);
        return;
      }
      renderCardsAbertosFinanceiro();
    }

    function atualizarVisibilidadeBotoesVendas() {
      var strip = document.querySelector('#vendasPanel .vertical-tab-strip');
      if (!strip) return;
      strip.classList.toggle('hidden', !seletorVendasVisivel);
      strip.classList.toggle('overlay-selector', seletorVendasVisivel);
      var botoes = strip.querySelectorAll('.tab-btn');
      botoes.forEach(function(btn) {
        var alvo = btn.getAttribute('data-aba') || '';
        btn.classList.toggle('hidden', cardsVendasAbertos.indexOf(alvo) >= 0);
      });
    }

    function posicionarSeletorVendas() {
      var strip = document.querySelector('#vendasPanel .vertical-tab-strip');
      var aba = document.getElementById('menuVendas');
      if (!strip || !aba || strip.classList.contains('hidden')) return;
      var rect = aba.getBoundingClientRect();
      strip.style.top = (rect.bottom + 8) + 'px';
      strip.style.left = Math.max(8, rect.left) + 'px';
    }

    function mostrarSeletorVendas() {
      seletorVendasVisivel = true;
      atualizarVisibilidadeBotoesVendas();
      posicionarSeletorVendas();
      instalarAutoFecharSeletorVendas();
    }

    function ocultarSeletorVendas() {
      seletorVendasVisivel = false;
      if (timerFecharSeletorVendas) {
        clearTimeout(timerFecharSeletorVendas);
        timerFecharSeletorVendas = null;
      }
      atualizarVisibilidadeBotoesVendas();
    }

    function instalarAutoFecharSeletorVendas() {
      var strip = document.querySelector('#vendasPanel .vertical-tab-strip');
      if (!strip) return;
      strip.onmouseenter = function() {
        if (timerFecharSeletorVendas) {
          clearTimeout(timerFecharSeletorVendas);
          timerFecharSeletorVendas = null;
        }
      };
      strip.onmouseleave = function() {
        if (timerFecharSeletorVendas) clearTimeout(timerFecharSeletorVendas);
        timerFecharSeletorVendas = setTimeout(function() {
          if (seletorVendasVisivel) ocultarSeletorVendas();
        }, 120);
      };
    }

    function selecionarAbaVendas(aba) {
      abaVendasAtiva = aba;
      var botoes = document.querySelectorAll('#vendasPanel .vertical-tab-strip .tab-btn');
      botoes.forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-aba') === aba);
      });
      if (cardsVendasAbertos.indexOf(aba) < 0) cardsVendasAbertos.push(aba);
      cardVendasAtivo = aba;
      ocultarSeletorVendas();
      renderCardsGlobaisAbertos();
      void listarVendasPainel();
    }

    function fecharCardVendas(aba) {
      var idx = cardsVendasAbertos.indexOf(aba);
      if (idx >= 0) cardsVendasAbertos.splice(idx, 1);
      if (!cardsVendasAbertos.length) {
        cardVendasAtivo = null;
        abaVendasAtiva = 'pedidos';
        mostrarSeletorVendas();
        renderCardsGlobaisAbertos();
        if (voltarParaHomeSeSemCardsAbertos()) return;
        void listarVendasPainel();
        return;
      }
      if (cardVendasAtivo === aba) {
        var prox = cardsVendasAbertos[Math.max(0, idx - 1)] || cardsVendasAbertos[0];
        selecionarAbaVendas(prox);
        return;
      }
      renderCardsGlobaisAbertos();
    }

    function atualizarVisibilidadeBotoesEstoque() {
      var strip = document.querySelector('#estoquePanel .vertical-tab-strip');
      if (!strip) return;
      strip.classList.toggle('hidden', !seletorEstoqueVisivel);
      strip.classList.toggle('overlay-selector', seletorEstoqueVisivel);
      var botoes = strip.querySelectorAll('.tab-btn');
      botoes.forEach(function(btn) {
        var alvo = btn.getAttribute('data-aba') || '';
        btn.classList.toggle('hidden', cardsEstoqueAbertos.indexOf(alvo) >= 0);
      });
    }

    function posicionarSeletorEstoque() {
      var strip = document.querySelector('#estoquePanel .vertical-tab-strip');
      var aba = document.getElementById('menuEstoque');
      if (!strip || !aba || strip.classList.contains('hidden')) return;
      var rect = aba.getBoundingClientRect();
      strip.style.top = (rect.bottom + 8) + 'px';
      strip.style.left = Math.max(8, rect.left) + 'px';
    }

    function mostrarSeletorEstoque() {
      seletorEstoqueVisivel = true;
      atualizarVisibilidadeBotoesEstoque();
      posicionarSeletorEstoque();
      instalarAutoFecharSeletorEstoque();
    }

    function ocultarSeletorEstoque() {
      seletorEstoqueVisivel = false;
      if (timerFecharSeletorEstoque) {
        clearTimeout(timerFecharSeletorEstoque);
        timerFecharSeletorEstoque = null;
      }
      atualizarVisibilidadeBotoesEstoque();
    }

    function instalarAutoFecharSeletorEstoque() {
      var strip = document.querySelector('#estoquePanel .vertical-tab-strip');
      if (!strip) return;
      strip.onmouseenter = function() {
        if (timerFecharSeletorEstoque) {
          clearTimeout(timerFecharSeletorEstoque);
          timerFecharSeletorEstoque = null;
        }
      };
      strip.onmouseleave = function() {
        if (timerFecharSeletorEstoque) clearTimeout(timerFecharSeletorEstoque);
        timerFecharSeletorEstoque = setTimeout(function() {
          if (seletorEstoqueVisivel) ocultarSeletorEstoque();
        }, 120);
      };
    }

    function renderCardsAbertosEstoque() {
      var box = document.getElementById('estoqueOpenCards');
      if (!box) return;
      box.innerHTML = '';
      if (!cardsEstoqueAbertos.length) {
        box.classList.add('hidden');
        atualizarVisibilidadeBotoesEstoque();
        renderCardsGlobaisAbertos();
        return;
      }
      box.classList.remove('hidden');
      cardsEstoqueAbertos.forEach(function(aba) {
        var pill = document.createElement('div');
        pill.className = 'open-card-pill' + (aba === cardEstoqueAtivo ? ' active' : '');
        pill.setAttribute('role', 'button');
        pill.tabIndex = 0;
        pill.onclick = function() { selecionarAbaEstoque(aba); };
        var titulo = document.createElement('span');
        titulo.textContent = labelCardEstoque(aba);
        var fechar = document.createElement('button');
        fechar.type = 'button';
        fechar.className = 'close-open-card';
        fechar.title = 'Fechar card';
        fechar.textContent = 'x';
        fechar.onclick = function(ev) {
          if (ev.stopPropagation) ev.stopPropagation();
          fecharCardEstoque(aba);
        };
        pill.appendChild(titulo);
        pill.appendChild(fechar);
        box.appendChild(pill);
      });
      atualizarVisibilidadeBotoesEstoque();
      renderCardsGlobaisAbertos();
    }

    function selecionarAbaEstoque(aba) {
      var botoes = document.querySelectorAll('#estoquePanel .vertical-tab-strip .tab-btn');
      botoes.forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-aba') === aba);
      });
      var cCompra = document.getElementById('estConteudoCompra');
      var cPos = document.getElementById('estConteudoPosicao');
      var cAjuste = document.getElementById('estConteudoAjuste');
      if (cCompra) cCompra.classList.toggle('hidden', aba !== 'compra');
      if (cPos) cPos.classList.toggle('hidden', aba !== 'posicao');
      if (cAjuste) cAjuste.classList.toggle('hidden', aba !== 'ajuste');
      if (cardsEstoqueAbertos.indexOf(aba) < 0) cardsEstoqueAbertos.push(aba);
      cardEstoqueAtivo = aba;
      ocultarSeletorEstoque();
      renderCardsAbertosEstoque();
      if (aba === 'compra') {
        void listarComprasEstoque();
      } else if (aba === 'posicao') {
        void listarPosicaoAtualEstoque();
      } else if (aba === 'ajuste') {
        void listarAjustesEstoque();
      }
    }

    function fecharCardEstoque(aba) {
      var idx = cardsEstoqueAbertos.indexOf(aba);
      if (idx >= 0) cardsEstoqueAbertos.splice(idx, 1);
      if (!cardsEstoqueAbertos.length) {
        cardEstoqueAtivo = null;
        ocultarSeletorEstoque();
        renderCardsAbertosEstoque();
        if (voltarParaHomeSeSemCardsAbertos()) return;
        mostrarSeletorEstoque();
        return;
      }
      if (cardEstoqueAtivo === aba) {
        var prox = cardsEstoqueAbertos[Math.max(0, idx - 1)] || cardsEstoqueAbertos[0];
        selecionarAbaEstoque(prox);
        return;
      }
      renderCardsAbertosEstoque();
    }

    function atualizarVisibilidadeBotoesContador() {
      var strip = document.querySelector('#contadorPanel .vertical-tab-strip');
      if (!strip) return;
      strip.classList.toggle('hidden', !seletorContadorVisivel);
      strip.classList.toggle('overlay-selector', seletorContadorVisivel);
      var botoes = strip.querySelectorAll('.tab-btn');
      botoes.forEach(function(btn) {
        var alvo = btn.getAttribute('data-aba') || '';
        btn.classList.toggle('hidden', cardsContadorAbertos.indexOf(alvo) >= 0);
      });
    }

    function posicionarSeletorContador() {
      var strip = document.querySelector('#contadorPanel .vertical-tab-strip');
      var aba = document.getElementById('menuContador');
      if (!strip || !aba) return;
      var rect = aba.getBoundingClientRect();
      var top = rect.bottom + 6;
      var left = rect.left;
      var largura = strip.offsetWidth || 220;
      var maxLeft = window.innerWidth - largura - 12;
      if (left > maxLeft) left = maxLeft;
      if (left < 8) left = 8;
      strip.style.position = 'fixed';
      strip.style.top = top + 'px';
      strip.style.left = left + 'px';
      strip.style.zIndex = '55';
    }

    function mostrarSeletorContador() {
      seletorContadorVisivel = true;
      atualizarVisibilidadeBotoesContador();
      posicionarSeletorContador();
      instalarAutoFecharSeletorContador();
    }

    function ocultarSeletorContador() {
      seletorContadorVisivel = false;
      atualizarVisibilidadeBotoesContador();
    }

    function instalarAutoFecharSeletorContador() {
      var strip = document.querySelector('#contadorPanel .vertical-tab-strip');
      if (!strip) return;
      strip.onmouseenter = function() {
        if (timerFecharSeletorContador) {
          clearTimeout(timerFecharSeletorContador);
          timerFecharSeletorContador = null;
        }
      };
      strip.onmouseleave = function() {
        if (timerFecharSeletorContador) clearTimeout(timerFecharSeletorContador);
        timerFecharSeletorContador = setTimeout(function() {
          if (seletorContadorVisivel) ocultarSeletorContador();
        }, 120);
      };
    }

    function renderCardsAbertosContador() {
      var box = document.getElementById('contadorOpenCards');
      if (!box) return;
      box.innerHTML = '';
      box.classList.add('hidden');
      atualizarVisibilidadeBotoesContador();
      renderCardsGlobaisAbertos();
    }

    function selecionarAbaContador(aba) {
      var botoes = document.querySelectorAll('#contadorPanel .vertical-tab-strip .tab-btn');
      botoes.forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-aba') === aba);
      });
      var cChecklist = document.getElementById('ctrConteudoChecklist');
      var cFiscal = document.getElementById('ctrConteudoFiscal');
      var cFinanceiro = document.getElementById('ctrConteudoFinanceiro');
      var cEnvio = document.getElementById('ctrConteudoEnvio');
      if (cChecklist) cChecklist.classList.toggle('hidden', aba !== 'checklist');
      if (cFiscal) cFiscal.classList.toggle('hidden', aba !== 'fiscal');
      if (cFinanceiro) cFinanceiro.classList.toggle('hidden', aba !== 'financeiro');
      if (cEnvio) cEnvio.classList.toggle('hidden', aba !== 'envio');
      if (cardsContadorAbertos.indexOf(aba) < 0) cardsContadorAbertos.push(aba);
      cardContadorAtivo = aba;
      ocultarSeletorContador();
      renderCardsAbertosContador();
    }

    function fecharCardContador(aba) {
      var idx = cardsContadorAbertos.indexOf(aba);
      if (idx >= 0) cardsContadorAbertos.splice(idx, 1);
      if (!cardsContadorAbertos.length) {
        cardContadorAtivo = null;
        ocultarSeletorContador();
        renderCardsAbertosContador();
        if (voltarParaHomeSeSemCardsAbertos()) return;
        mostrarSeletorContador();
        return;
      }
      if (cardContadorAtivo === aba) {
        var prox = cardsContadorAbertos[Math.max(0, idx - 1)] || cardsContadorAbertos[0];
        selecionarAbaContador(prox);
        return;
      }
      renderCardsAbertosContador();
    }

    function registrarStatusEnvioContador() {
      var competencia = document.getElementById('ctrCompetencia');
      var status = document.getElementById('ctrStatusEnvio');
      var textoCompetencia = competencia ? String(competencia.value || '').trim() : '';
      var textoStatus = status ? String(status.value || 'pendente') : 'pendente';
      if (!textoCompetencia) {
        setMsg('statusContadorEnvio', 'Informe a competencia para registrar o envio.', false);
        return;
      }
      if (textoStatus === 'enviado') {
        setMsg('statusContadorEnvio', `Competencia ${textoCompetencia} marcada como enviada ao contador.`);
      } else {
        setMsg('statusContadorEnvio', `Competencia ${textoCompetencia} marcada como pendente.`);
      }
    }

    function escaparCsvContador(valor) {
      var texto = String(valor == null ? '' : valor);
      if (texto.includes('"') || texto.includes(';') || texto.includes('\\n')) {
        return '"' + texto.replace(/"/g, '""') + '"';
      }
      return texto;
    }

    function baixarCsvContador(nomeBase, cabecalhos, linhas) {
      var partes = [];
      partes.push(cabecalhos.map(escaparCsvContador).join(';'));
      (Array.isArray(linhas) ? linhas : []).forEach(function(linha) {
        partes.push((Array.isArray(linha) ? linha : []).map(escaparCsvContador).join(';'));
      });
      var conteudo = '\ufeff' + partes.join('\\n');
      var blob = new Blob([conteudo], { type: 'text/csv;charset=utf-8;' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = nomeBase + '_' + new Date().toISOString().slice(0, 10) + '.csv';
      a.target = '_blank';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function() { URL.revokeObjectURL(url); }, 5000);
    }

    async function baixarRelatorioPagarContador() {
      try {
        var contas = await api('/contas-pagar');
        var cadastros = await api('/cadastros-gerais?contexto=pessoas');
        var fornecedoresMap = new Map();
        (Array.isArray(cadastros) ? cadastros : []).forEach(function(item) {
          if (item && item.is_fornecedor) fornecedoresMap.set(Number(item.id), item.razao_social || ('Fornecedor ' + item.id));
        });
        var linhas = (Array.isArray(contas) ? contas : []).map(function(item) {
          var fid = Number(item.fornecedor_id || 0);
          return [
            item.id || '',
            fornecedoresMap.get(fid) || (fid ? ('Fornecedor ' + fid) : '-'),
            item.descricao || '',
            normalizarDataRelatorio(item.data_vencimento) || '',
            normalizarDataRelatorio(item.data_pagamento) || '',
            String(item.status || '').toLowerCase(),
            Number(item.valor || 0).toFixed(2),
          ];
        });
        baixarCsvContador('contas_a_pagar', ['ID', 'Fornecedor', 'Descricao', 'Vencimento', 'Pagamento', 'Status', 'Valor'], linhas);
        setMsg('statusContadorFinanceiro', 'Download de contas a pagar concluido.');
      } catch (err) {
        setMsg('statusContadorFinanceiro', 'Falha no download de contas a pagar: ' + err.message, false);
      }
    }

    async function baixarRelatorioReceberContador() {
      try {
        var contas = await api('/contas-receber');
        var clientes = await api('/clientes');
        var clientesMap = new Map();
        (Array.isArray(clientes) ? clientes : []).forEach(function(item) {
          clientesMap.set(Number(item.id), item.nome || ('Cliente ' + item.id));
        });
        var linhas = (Array.isArray(contas) ? contas : []).map(function(item) {
          var cid = Number(item.cliente_id || 0);
          return [
            item.id || '',
            clientesMap.get(cid) || (cid ? ('Cliente ' + cid) : '-'),
            item.descricao || '',
            normalizarDataRelatorio(item.data_vencimento) || '',
            normalizarDataRelatorio(item.data_recebimento) || '',
            String(item.status || '').toLowerCase(),
            Number(item.valor || 0).toFixed(2),
          ];
        });
        baixarCsvContador('contas_a_receber', ['ID', 'Cliente', 'Descricao', 'Vencimento', 'Recebimento', 'Status', 'Valor'], linhas);
        setMsg('statusContadorFinanceiro', 'Download de contas a receber concluido.');
      } catch (err) {
        setMsg('statusContadorFinanceiro', 'Falha no download de contas a receber: ' + err.message, false);
      }
    }

    async function baixarRelatorioFinanceiroContador() {
      try {
        var contasPagar = await api('/contas-pagar');
        var contasReceber = await api('/contas-receber');
        var linhas = [];
        (Array.isArray(contasPagar) ? contasPagar : []).forEach(function(item) {
          linhas.push([
            'PAGAR',
            item.id || '',
            item.descricao || '',
            normalizarDataRelatorio(item.data_vencimento) || '',
            String(item.status || '').toLowerCase(),
            Number(item.valor || 0).toFixed(2),
          ]);
        });
        (Array.isArray(contasReceber) ? contasReceber : []).forEach(function(item) {
          linhas.push([
            'RECEBER',
            item.id || '',
            item.descricao || '',
            normalizarDataRelatorio(item.data_vencimento) || '',
            String(item.status || '').toLowerCase(),
            Number(item.valor || 0).toFixed(2),
          ]);
        });
        baixarCsvContador('relatorio_financeiro', ['Tipo', 'ID', 'Descricao', 'Vencimento', 'Status', 'Valor'], linhas);
        setMsg('statusContadorFinanceiro', 'Download do relatorio financeiro concluido.');
      } catch (err) {
        setMsg('statusContadorFinanceiro', 'Falha no download do relatorio financeiro: ' + err.message, false);
      }
    }

    async function baixarRelatorioVendasContador() {
      try {
        var vendas = await api('/vendas');
        var linhas = (Array.isArray(vendas) ? vendas : []).map(function(item) {
          return [
            item.id || '',
            item.numero || '',
            normalizarDataRelatorio(item.data_emissao) || '',
            item.cliente_nome || '',
            String(item.status || '').toLowerCase(),
            Number(item.valor_total || 0).toFixed(2),
          ];
        });
        baixarCsvContador('relatorio_vendas', ['ID', 'Numero', 'Data emissao', 'Cliente', 'Status', 'Valor total'], linhas);
        setMsg('statusContadorFiscal', 'Download do relatorio de vendas concluido.');
      } catch (err) {
        setMsg('statusContadorFiscal', 'Falha no download de vendas: ' + err.message, false);
      }
    }

    async function baixarRelatorioEstoqueContador() {
      try {
        var itens = await api('/estoque/posicao-atual');
        var linhas = (Array.isArray(itens) ? itens : []).map(function(item) {
          return [
            item.produto_id || '',
            item.nome || '',
            item.unidade || 'UN',
            Number(item.quantidade || 0).toFixed(4),
          ];
        });
        baixarCsvContador('posicao_estoque', ['Produto ID', 'Item', 'Unidade', 'Quantidade'], linhas);
        setMsg('statusContadorFiscal', 'Download da posicao de estoque concluido.');
      } catch (err) {
        setMsg('statusContadorFiscal', 'Falha no download de estoque: ' + err.message, false);
      }
    }

    function renderCardsGlobaisAbertos() {
      var box = document.getElementById('globalOpenCards');
      if (!box) return;
      box.innerHTML = '';
      var itens = [];
      cardsCadastroAbertos.forEach(function(aba) {
        itens.push({ escopo: 'cadastro', aba: aba, titulo: 'Cadastro • ' + labelCardCadastro(aba), ativo: aba === cardCadastroAtivo });
      });
      cardsFaturasAbertos.forEach(function(aba) {
        itens.push({ escopo: 'faturas', aba: aba, titulo: 'Faturas • ' + labelCardFaturas(aba), ativo: aba === cardFaturasAtivo });
      });
      cardsFinanceiroAbertos.forEach(function(aba) {
        itens.push({ escopo: 'financeiro', aba: aba, titulo: 'Financeiro • ' + labelCardFinanceiro(aba), ativo: aba === cardFinanceiroAtivo });
      });
      cardsVendasAbertos.forEach(function(aba) {
        itens.push({ escopo: 'vendas', aba: aba, titulo: 'Vendas • ' + labelCardVendas(aba), ativo: aba === cardVendasAtivo });
      });
      cardsEstoqueAbertos.forEach(function(aba) {
        itens.push({ escopo: 'estoque', aba: aba, titulo: 'Estoque • ' + labelCardEstoque(aba), ativo: aba === cardEstoqueAtivo });
      });
      cardsContadorAbertos.forEach(function(aba) {
        itens.push({ escopo: 'contador', aba: aba, titulo: 'Espaco Contador • ' + labelCardContador(aba), ativo: aba === cardContadorAtivo });
      });
      if (!itens.length) {
        box.classList.add('hidden');
        return;
      }
      box.classList.remove('hidden');
      itens.forEach(function(item) {
        var pill = document.createElement('div');
        pill.className = 'open-card-pill' + (item.ativo ? ' active' : '');
        pill.setAttribute('role', 'button');
        pill.tabIndex = 0;
        pill.onclick = function() {
          if (item.escopo === 'cadastro') {
            abrirCadastro(true);
            abrirAbaCadastro(item.aba);
            return;
          }
          if (item.escopo === 'faturas') {
            void abrirFaturas(true).then(function() { abrirAbaFaturas(item.aba); });
            return;
          }
          if (item.escopo === 'vendas') {
            void abrirVendas(true).then(function() { selecionarAbaVendas(item.aba); });
            return;
          }
          if (item.escopo === 'estoque') {
            void abrirEstoque(true).then(function() { selecionarAbaEstoque(item.aba); });
            return;
          }
          if (item.escopo === 'contador') {
            void abrirEspacoContador(true).then(function() { selecionarAbaContador(item.aba); });
            return;
          }
          abrirFinanceiro(true);
          selecionarAbaFinanceiro(item.aba);
        };
        var titulo = document.createElement('span');
        titulo.textContent = item.titulo;
        var fechar = document.createElement('button');
        fechar.type = 'button';
        fechar.className = 'close-open-card';
        fechar.title = 'Fechar card';
        fechar.textContent = 'x';
        fechar.onclick = function(ev) {
          if (ev.stopPropagation) ev.stopPropagation();
          if (item.escopo === 'cadastro') return fecharCardCadastro(item.aba);
          if (item.escopo === 'faturas') return fecharCardFaturas(item.aba);
          if (item.escopo === 'vendas') return fecharCardVendas(item.aba);
          if (item.escopo === 'estoque') return fecharCardEstoque(item.aba);
          if (item.escopo === 'contador') return fecharCardContador(item.aba);
          fecharCardFinanceiro(item.aba);
        };
        pill.appendChild(titulo);
        pill.appendChild(fechar);
        box.appendChild(pill);
      });
    }

    function mostrarConteudoPadraoFinanceiro() {
      abaFinanceiroAtiva = 'pagar';
      var a1 = document.getElementById('finAbaPagar');
      var a2 = document.getElementById('finAbaReceber');
      var a3 = document.getElementById('finAbaPagas');
      var a4 = document.getElementById('finAbaRecebidas');
      if (a1) a1.classList.add('active');
      if (a2) a2.classList.remove('active');
      if (a3) a3.classList.remove('active');
      if (a4) a4.classList.remove('active');
      void carregarTudo();
    }

    function voltarDashboard() {
      abrirOnixHome();
    }

    async function abrirFaturas(forcar = false) {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pFat = document.getElementById('faturasPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pIa = document.getElementById('onixIaPanel');
      if (!pFat || !pDash) return;
      if (!pFat.classList.contains('hidden') && !forcar) {
        if (seletorFaturasVisivel) {
          ocultarSeletorFaturas();
        } else {
          mostrarSeletorFaturas();
        }
        return;
      }
      if (pHome) pHome.classList.add('hidden');
      ocultarSeletorHomeConfig();
      if (pCad) pCad.classList.add('hidden');
      if (pRel) pRel.classList.add('hidden');
      if (pVendas) pVendas.classList.add('hidden');
      if (pEstoque) pEstoque.classList.add('hidden');
      if (pContador) pContador.classList.add('hidden');
      if (pIa) pIa.classList.add('hidden');
      pDash.classList.add('hidden');
      pFat.classList.remove('hidden');
      ativarMenuPrincipal('faturas');
      if (!cardFaturasAtivo) {
        mostrarConteudoPadraoFaturas();
      }
      mostrarSeletorFaturas();
    }

    function abrirAbaFaturas(aba) {
      const cartoes = document.getElementById('fatConteudoCartoes');
      const faturas = document.getElementById('fatConteudoFaturas');
      const faturasPagas = document.getElementById('fatConteudoFaturasPagas');
      const btnC = document.getElementById('fatAbaCartoes');
      const btnF = document.getElementById('fatAbaFaturasLista');
      const btnFP = document.getElementById('fatAbaFaturasPagas');
      if (!cartoes || !faturas || !btnC || !btnF) return;
      const isCartoes = aba === 'cartoes';
      const isFaturas = aba === 'faturas';
      const isPagas = aba === 'faturasPagas';
      if (cardsFaturasAbertos.indexOf(aba) < 0) cardsFaturasAbertos.push(aba);
      cardFaturasAtivo = aba;
      ocultarSeletorFaturas();
      cartoes.classList.toggle('hidden', !isCartoes);
      faturas.classList.toggle('hidden', isCartoes || isPagas);
      if (faturasPagas) {
        faturasPagas.classList.toggle('hidden', isCartoes || isFaturas);
      }
      btnC.classList.toggle('active', isCartoes);
      btnF.classList.toggle('active', isFaturas);
      if (btnFP) btnFP.classList.toggle('active', isPagas);
      renderCardsAbertosFaturas();
      if (isCartoes) {
        void listarCartoesCreditoPainel();
      } else {
        void listarFaturasCartaoPainel();
      }
    }

    function nomeCartaoFaturaPainel(f, mapCartao) {
      const c = mapCartao.get(f.cartao_id);
      return c ? `${c.banco}${(c.nome_conta || '').trim() ? ' - ' + c.nome_conta : ''}` : `ID ${f.cartao_id}`;
    }

    function renderTabelaFaturasAbertasPainel(mapCartao, lista) {
      const tb = document.getElementById('tbFaturasCartaoPainel');
      if (!tb) return;
      tb.innerHTML = '';
      lista.forEach(f => {
        const tr = document.createElement('tr');
        const nomeCartao = nomeCartaoFaturaPainel(f, mapCartao);
        const st = String(f.status || '').toLowerCase();
        const podePagar = st !== 'paga' && Number(f.valor_total) > 0;
        const btn = podePagar
          ? `<button type="button" onclick="abrirModalPagarFaturaCartao(${f.id})">Pagar</button>`
          : '-';
        const ven = formatDataBr(f.data_vencimento_prevista);
        const reg = formatDataBr(f.created_at);
        tr.innerHTML = `<td>${f.id}</td><td>${nomeCartao}</td><td>${f.mes_referencia}</td><td>${ven}</td><td>${reg}</td><td>${moeda(f.valor_total)}</td><td>${f.status}</td><td>${btn}</td>`;
        tb.appendChild(tr);
      });
    }

    function renderTabelaFaturasPagasPainel(mapCartao, lista) {
      const tb = document.getElementById('tbFaturasPagasCartaoPainel');
      if (!tb) return;
      tb.innerHTML = '';
      lista.forEach(f => {
        const tr = document.createElement('tr');
        const nomeCartao = nomeCartaoFaturaPainel(f, mapCartao);
        const ven = formatDataBr(f.data_vencimento_prevista);
        const reg = formatDataBr(f.created_at);
        const pg = formatDataBr(f.data_pagamento);
        const btn = `<button type="button" class="alt" onclick="abrirModalDetalheFaturaCartao(${f.id})">Detalhes</button> <button type="button" class="alt" title="Remove so o registro desta fatura da lista" onclick="void window.excluirFaturaPagaPainel(${f.id})">Excluir</button>`;
        tr.innerHTML = `<td>${f.id}</td><td>${nomeCartao}</td><td>${f.mes_referencia}</td><td>${ven}</td><td>${reg}</td><td>${pg}</td><td>${moeda(f.valor_total)}</td><td>${f.status}</td><td>${btn}</td>`;
        tb.appendChild(tr);
      });
    }

    async function excluirFaturaPagaPainel(faturaId) {
      if (!(await validarPermissaoExclusao())) return;
      if (!window.confirm('Remover apenas o registro desta fatura da lista? Lancamentos pagos e movimentacoes no banco NAO serao alterados.')) return;
      try {
        await api(`/cartoes-credito/faturas/${faturaId}`, { method: 'DELETE' });
        setMsg('statusFaturasPagasCartaoPainel', 'Registro da fatura removido.');
        await listarFaturasCartaoPainel();
      } catch (err) {
        setMsg('statusFaturasPagasCartaoPainel', err.message, false);
      }
    }

    function renderCartoesCreditoPainelTabela() {
      const tb = document.getElementById('tbCartoesCreditoPainel');
      if (!tb) return;
      tb.innerHTML = '';
      cartoesCreditoPainelCache.forEach(c => {
        const tr = document.createElement('tr');
        tr.style.cursor = 'pointer';
        tr.onclick = () => selecionarCartaoCreditoPainel(c.id);
        const checked = cartaoCreditoPainelSelecionadoId === c.id ? 'checked' : '';
        const nome = (c.nome_conta || '').trim() || '-';
        const ativo = c.ativa !== false ? 'Sim' : 'Nao';
        tr.innerHTML = `<td><input type="radio" name="selCartaoPainel" ${checked} onclick="event.stopPropagation();selecionarCartaoCreditoPainel(${c.id})" /></td><td>${c.id}</td><td>${c.banco || '-'}</td><td>${nome}</td><td>${c.data_fechamento}</td><td>${c.data_vencimento != null ? c.data_vencimento : 10}</td><td>${moeda(c.limite)}</td><td>${moeda(c.saldo_usado)}</td><td>${ativo}</td>`;
        tb.appendChild(tr);
      });
    }

    async function listarCartoesCreditoPainel() {
      try {
        cartoesCreditoPainelCache = await api('/cartoes-credito');
        renderCartoesCreditoPainelTabela();
        setMsg('statusCartoesCreditoPainel', `${cartoesCreditoPainelCache.length} cartao(oes).`);
      } catch (err) {
        setMsg('statusCartoesCreditoPainel', err.message, false);
      }
    }

    function selecionarCartaoCreditoPainel(id) {
      cartaoCreditoPainelSelecionadoId = id;
      renderCartoesCreditoPainelTabela();
    }

    async function listarFaturasCartaoPainel() {
      try {
        faturasCartaoPainelCache = await api('/cartoes-credito/faturas');
        const mapCartao = new Map(cartoesCreditoPainelCache.map(c => [c.id, c]));
        if (!cartoesCreditoPainelCache.length) {
          cartoesCreditoPainelCache = await api('/cartoes-credito');
          cartoesCreditoPainelCache.forEach(c => mapCartao.set(c.id, c));
        }
        const abertas = faturasCartaoPainelCache.filter(f => String(f.status || '').toLowerCase() !== 'paga');
        const pagas = faturasCartaoPainelCache.filter(f => String(f.status || '').toLowerCase() === 'paga');
        renderTabelaFaturasAbertasPainel(mapCartao, abertas);
        renderTabelaFaturasPagasPainel(mapCartao, pagas);
        setMsg('statusFaturasCartaoPainel', `${abertas.length} fatura(s) em aberto.`);
        const sp = document.getElementById('statusFaturasPagasCartaoPainel');
        if (sp) {
          sp.textContent = `${pagas.length} fatura(s) paga(s).`;
          sp.className = 'status-line muted';
        }
      } catch (err) {
        setMsg('statusFaturasCartaoPainel', err.message, false);
        const sp = document.getElementById('statusFaturasPagasCartaoPainel');
        if (sp) {
          sp.textContent = err.message;
          sp.className = 'status-line err';
        }
      }
    }

    function fecharModalDetalheFaturaCartao() {
      document.getElementById('modalDetalheFaturaCartao').classList.add('hidden');
    }

    async function abrirModalDetalheFaturaCartao(faturaId) {
      const resumo = document.getElementById('detalheFaturaResumo');
      const tb = document.getElementById('tbDetalheFaturaLancamentos');
      const st = document.getElementById('statusModalDetalheFaturaCartao');
      if (resumo) resumo.innerHTML = '';
      if (tb) tb.innerHTML = '';
      if (st) st.textContent = '';
      document.getElementById('modalDetalheFaturaCartao').classList.remove('hidden');
      try {
        const d = await api(`/cartoes-credito/faturas/${faturaId}/detalhes`);
        const fat = d.fatura;
        if (resumo) {
          resumo.innerHTML = [
            `<div><strong>Cartao:</strong> ${escapeHtml(d.nome_cartao)}</div>`,
            `<div><strong>Mes referencia:</strong> ${escapeHtml(fat.mes_referencia)} &nbsp; <strong>Valor:</strong> ${moeda(fat.valor_total)}</div>`,
            `<div><strong>Vencimento previsto:</strong> ${formatDataBr(fat.data_vencimento_prevista)} &nbsp; <strong>Registro:</strong> ${formatDataBr(fat.created_at)}</div>`,
            `<div><strong>Status:</strong> ${escapeHtml(String(fat.status))}${fat.data_pagamento ? ` &nbsp; <strong>Pagamento:</strong> ${formatDataBr(fat.data_pagamento)}` : ''}</div>`,
          ].join('');
        }
        if (tb) {
          (d.lancamentos || []).forEach(l => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${l.id}</td><td>${escapeHtml(l.descricao)}</td><td>${formatDataBr(l.data_vencimento)}</td><td>${moeda(l.valor)}</td><td>${escapeHtml(l.status)}</td>`;
            tb.appendChild(tr);
          });
        }
      } catch (err) {
        if (st) {
          st.textContent = err.message;
          st.className = 'status-line err';
        }
      }
    }

    function abrirModalCartaoCreditoEditar() {
      if (!cartaoCreditoPainelSelecionadoId) {
        setMsg('statusCartoesCreditoPainel', 'Selecione um cartao na lista.', false);
        return;
      }
      abrirModalCartaoCredito(cartaoCreditoPainelSelecionadoId);
    }

    function abrirModalCartaoCredito(editId) {
      const idNum = Number(editId);
      cartaoCreditoModalEditId = Number.isFinite(idNum) && idNum > 0 ? idNum : null;
      document.getElementById('statusModalCartaoCredito').textContent = '';
      if (cartaoCreditoModalEditId) {
        const c = cartoesCreditoPainelCache.find(x => x.id === cartaoCreditoModalEditId);
        if (!c) {
          setMsg('statusCartoesCreditoPainel', 'Selecione um cartao na lista para editar.', false);
          return;
        }
        document.getElementById('tituloModalCartaoCredito').textContent = 'Editar cartao de credito';
        document.getElementById('ccFatBanco').value = c.banco || '';
        document.getElementById('ccFatNomeConta').value = c.nome_conta || '';
        document.getElementById('ccFatUltimos').value = c.ultimos_digitos || '0000';
        document.getElementById('ccFatLimite').value = c.limite != null ? String(c.limite) : '0';
        document.getElementById('ccFatFechamento').value = String(c.data_fechamento != null ? c.data_fechamento : 10);
        document.getElementById('ccFatVencimento').value = String(c.data_vencimento != null ? c.data_vencimento : 10);
        document.getElementById('ccFatAtiva').checked = c.ativa !== false;
      } else {
        document.getElementById('tituloModalCartaoCredito').textContent = 'Novo cartao de credito';
        document.getElementById('ccFatBanco').value = '';
        document.getElementById('ccFatNomeConta').value = '';
        document.getElementById('ccFatUltimos').value = '0000';
        document.getElementById('ccFatLimite').value = '0';
        document.getElementById('ccFatFechamento').value = '10';
        document.getElementById('ccFatVencimento').value = '10';
        document.getElementById('ccFatAtiva').checked = true;
      }
      document.getElementById('modalCartaoCredito').classList.remove('hidden');
    }

    function fecharModalCartaoCredito() {
      document.getElementById('modalCartaoCredito').classList.add('hidden');
    }

    async function salvarModalCartaoCredito() {
      const banco = document.getElementById('ccFatBanco').value.trim();
      const nome_conta = document.getElementById('ccFatNomeConta').value.trim();
      let ultimos = (document.getElementById('ccFatUltimos').value || '').trim().replace(/\D/g, '');
      if (ultimos.length < 4) ultimos = (ultimos + '0000').slice(-4);
      const limite = Number(document.getElementById('ccFatLimite').value) || 0;
      const data_fechamento = Math.min(31, Math.max(1, parseInt(document.getElementById('ccFatFechamento').value, 10) || 10));
      const data_vencimento = Math.min(31, Math.max(1, parseInt(document.getElementById('ccFatVencimento').value, 10) || 10));
      const ativa = document.getElementById('ccFatAtiva').checked;
      if (!banco) {
        setMsg('statusModalCartaoCredito', 'Informe o banco.', false);
        return;
      }
      try {
        if (cartaoCreditoModalEditId) {
          const atual = cartoesCreditoPainelCache.find(x => x.id === cartaoCreditoModalEditId);
          const bodyPut = { banco, nome_conta, ultimos_digitos: ultimos, limite, data_fechamento, data_vencimento, ativa };
          if (atual) bodyPut.saldo_usado = atual.saldo_usado;
          await api(`/cartoes-credito/${cartaoCreditoModalEditId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bodyPut),
          });
        } else {
          const bodyPost = { banco, nome_conta, ultimos_digitos: ultimos, limite, data_fechamento, data_vencimento, ativa, saldo_usado: 0 };
          await api('/cartoes-credito', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bodyPost),
          });
        }
        fecharModalCartaoCredito();
        await listarCartoesCreditoPainel();
        setMsg('statusCartoesCreditoPainel', 'Cartao salvo com sucesso.');
      } catch (err) {
        setMsg('statusModalCartaoCredito', err.message, false);
      }
    }

    async function excluirCartaoCreditoSelecionado() {
      if (!cartaoCreditoPainelSelecionadoId) {
        setMsg('statusCartoesCreditoPainel', 'Selecione um cartao.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      if (!confirm('Excluir o cartao selecionado? So e permitido se nao houver lancamentos vinculados.')) return;
      try {
        await api(`/cartoes-credito/${cartaoCreditoPainelSelecionadoId}`, { method: 'DELETE' });
        cartaoCreditoPainelSelecionadoId = null;
        await listarCartoesCreditoPainel();
        setMsg('statusCartoesCreditoPainel', 'Cartao excluido.');
      } catch (err) {
        setMsg('statusCartoesCreditoPainel', err.message, false);
      }
    }

    async function abrirModalPagarFaturaCartao(faturaId) {
      document.getElementById('pagarFaturaCartaoId').value = String(faturaId);
      const hoje = new Date().toISOString().slice(0, 10);
      document.getElementById('pagarFaturaData').value = hoje;
      document.getElementById('statusModalPagarFaturaCartao').textContent = '';
      const contas = await api('/contas-correntes');
      const sel = document.getElementById('pagarFaturaContaCorrenteId');
      sel.innerHTML = '';
      contas.forEach(item => {
        const opt = document.createElement('option');
        opt.value = String(item.id);
        const nomeConta = (item.nome_conta || '').trim();
        opt.textContent = nomeConta ? `${item.id} - ${nomeConta}` : `${item.id} - ${item.banco} / ${item.numero}`;
        sel.appendChild(opt);
      });
      document.getElementById('modalPagarFaturaCartao').classList.remove('hidden');
    }

    function fecharModalPagarFaturaCartao() {
      document.getElementById('modalPagarFaturaCartao').classList.add('hidden');
    }

    async function confirmarPagarFaturaCartao() {
      const faturaId = Number(document.getElementById('pagarFaturaCartaoId').value) || 0;
      const contaId = Number(document.getElementById('pagarFaturaContaCorrenteId').value) || 0;
      const dataPag = document.getElementById('pagarFaturaData').value;
      if (!faturaId || !contaId || !dataPag) {
        setMsg('statusModalPagarFaturaCartao', 'Preencha conta e data.', false);
        return;
      }
      try {
        await api(`/cartoes-credito/faturas/${faturaId}/pagar?conta_id=${contaId}&data_pagamento=${encodeURIComponent(dataPag)}`, {
          method: 'PUT',
        });
        fecharModalPagarFaturaCartao();
        await listarFaturasCartaoPainel();
        await listarCartoesCreditoPainel();
        setMsg('statusFaturasCartaoPainel', 'Fatura paga; lancamentos vinculados foram baixados.');
        await carregarTudo();
      } catch (err) {
        setMsg('statusModalPagarFaturaCartao', err.message, false);
      }
    }

    async function abrirRelatorios() {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pFat = document.getElementById('faturasPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pIa = document.getElementById('onixIaPanel');
      if (!pRel || !pDash) return;
      if (pHome) pHome.classList.add('hidden');
      if (pCad) pCad.classList.add('hidden');
      if (pFat) pFat.classList.add('hidden');
      if (pVendas) pVendas.classList.add('hidden');
      if (pEstoque) pEstoque.classList.add('hidden');
      if (pContador) pContador.classList.add('hidden');
      if (pIa) pIa.classList.add('hidden');
      pDash.classList.add('hidden');
      pRel.classList.remove('hidden');
      ativarMenuPrincipal('relatorios');
      await preencherFiltrosRelatorio();
      await window.gerarRelatorioFinanceiro();
    }

    function renderHistoricoOnixIa() {
      var box = document.getElementById('onixIaHistorico');
      if (!box) return;
      box.innerHTML = '';
      if (!onixIaMensagens.length) {
        box.innerHTML = '<div class="muted">Conversa vazia. Envie uma mensagem para a Onix_ia.</div>';
        return;
      }
      onixIaMensagens.forEach(function(item) {
        var div = document.createElement('div');
        div.className = 'chat-msg ' + (item.origem === 'user' ? 'user' : 'ai');
        div.textContent = item.texto;
        box.appendChild(div);
      });
      box.scrollTop = box.scrollHeight;
    }

    function limparChatOnixIa() {
      onixIaMensagens = [];
      renderHistoricoOnixIa();
      setMsg('statusOnixIa', 'Conversa limpa.');
    }

    async function enviarMensagemOnixIa() {
      var input = document.getElementById('onixIaMensagem');
      var chk = document.getElementById('onixIaConfirmar');
      var texto = input ? String(input.value || '').trim() : '';
      if (!texto) {
        setMsg('statusOnixIa', 'Digite uma mensagem antes de enviar.', false);
        return;
      }
      onixIaMensagens.push({ origem: 'user', texto: texto });
      renderHistoricoOnixIa();
      if (input) input.value = '';

      var textoLower = texto.toLowerCase();
      var pediuPdf = textoLower.indexOf('pdf') >= 0 && textoLower.indexOf('contas a pagar') >= 0;
      if (pediuPdf) {
        var diasMatch = textoLower.match(/(\d+)\s*dias?/);
        var dias = diasMatch ? Number(diasMatch[1]) : 5;
        if (!Number.isFinite(dias) || dias < 1) dias = 5;
        if (dias > 60) dias = 60;
        var hoje = new Date();
        var fim = new Date(hoje);
        fim.setDate(fim.getDate() + dias);
        var hojeIso = hoje.toISOString().slice(0, 10);
        var fimIso = fim.toISOString().slice(0, 10);
        try {
          if (typeof window.abrirRelatorios === 'function') {
            await window.abrirRelatorios();
          }
          var tipoEl = document.getElementById('relTipo');
          var iniEl = document.getElementById('relDataInicio');
          var fimEl = document.getElementById('relDataFim');
          if (tipoEl) tipoEl.value = 'pagar_abertas';
          if (iniEl) iniEl.value = hojeIso;
          if (fimEl) fimEl.value = fimIso;
          if (typeof window.gerarRelatorioFinanceiro === 'function') {
            await window.gerarRelatorioFinanceiro();
          }
          if (typeof window.exportarRelatorioPDF === 'function') {
            window.exportarRelatorioPDF();
          }
          onixIaMensagens.push({
            origem: 'ai',
            texto: `Relatorio em PDF de contas a pagar (proximos ${dias} dias) foi solicitado. Verifique a janela/aba de exportacao aberta no navegador.`,
          });
          renderHistoricoOnixIa();
          setMsg('statusOnixIa', 'PDF solicitado com sucesso.');
          return;
        } catch (errPdf) {
          onixIaMensagens.push({ origem: 'ai', texto: 'Erro ao gerar PDF localmente: ' + errPdf.message });
          renderHistoricoOnixIa();
          setMsg('statusOnixIa', errPdf.message, false);
          return;
        }
      }

      setMsg('statusOnixIa', 'Processando...');
      try {
        var payload = {
          mensagem: texto,
          confirmar_execucao: !!(chk && chk.checked),
        };
        var resp = await api('/assistente/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        var resposta = resp && resp.resposta ? resp.resposta : 'Sem resposta da IA.';
        onixIaMensagens.push({ origem: 'ai', texto: resposta });
        renderHistoricoOnixIa();
        setMsg('statusOnixIa', 'Mensagem processada com sucesso.');
      } catch (err) {
        onixIaMensagens.push({ origem: 'ai', texto: 'Erro: ' + err.message });
        renderHistoricoOnixIa();
        setMsg('statusOnixIa', err.message, false);
      }
    }

    function abrirOnixIa() {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pFat = document.getElementById('faturasPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pIa = document.getElementById('onixIaPanel');
      if (!pIa || !pDash) return;
      if (pHome) pHome.classList.add('hidden');
      ocultarSeletorHomeConfig();
      if (pCad) pCad.classList.add('hidden');
      if (pFat) pFat.classList.add('hidden');
      if (pVendas) pVendas.classList.add('hidden');
      if (pEstoque) pEstoque.classList.add('hidden');
      if (pContador) pContador.classList.add('hidden');
      if (pRel) pRel.classList.add('hidden');
      pDash.classList.add('hidden');
      pIa.classList.remove('hidden');
      ativarMenuPrincipal('onixia');
      renderHistoricoOnixIa();
      setMsg('statusOnixIa', 'Onix_ia pronta.');
    }

    async function abrirVendas(forcar = false) {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pFat = document.getElementById('faturasPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pIa = document.getElementById('onixIaPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      if (!pVendas || !pDash) return;
      if (pHome) pHome.classList.add('hidden');
      ocultarSeletorHomeConfig();
      if (pCad) pCad.classList.add('hidden');
      if (pFat) pFat.classList.add('hidden');
      if (pRel) pRel.classList.add('hidden');
      if (pEstoque) pEstoque.classList.add('hidden');
      if (pContador) pContador.classList.add('hidden');
      if (pIa) pIa.classList.add('hidden');
      pDash.classList.add('hidden');
      if (!pVendas.classList.contains('hidden') && !forcar) {
        if (cardVendasAtivo) {
          if (seletorVendasVisivel) ocultarSeletorVendas();
          else mostrarSeletorVendas();
        } else {
          if (seletorVendasVisivel) ocultarSeletorVendas();
          else mostrarSeletorVendas();
        }
        return;
      }
      pVendas.classList.remove('hidden');
      ativarMenuPrincipal('vendas');
      if (!cardVendasAtivo) {
        abaVendasAtiva = 'pedidos';
        mostrarSeletorVendas();
      }
      await listarVendasPainel();
    }

    async function abrirEstoque(forcar = false) {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pFat = document.getElementById('faturasPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pIa = document.getElementById('onixIaPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      if (!pEstoque || !pDash) return;
      if (pHome) pHome.classList.add('hidden');
      ocultarSeletorHomeConfig();
      if (pCad) pCad.classList.add('hidden');
      if (pFat) pFat.classList.add('hidden');
      if (pRel) pRel.classList.add('hidden');
      if (pIa) pIa.classList.add('hidden');
      if (pVendas) pVendas.classList.add('hidden');
      if (pContador) pContador.classList.add('hidden');
      pDash.classList.add('hidden');
      if (!pEstoque.classList.contains('hidden') && !forcar) {
        if (seletorEstoqueVisivel) ocultarSeletorEstoque();
        else mostrarSeletorEstoque();
        return;
      }
      pEstoque.classList.remove('hidden');
      ativarMenuPrincipal('estoque');
      if (!cardEstoqueAtivo) {
        mostrarSeletorEstoque();
      }
      await listarComprasEstoque();
    }

    async function abrirEspacoContador(forcar = false) {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pFat = document.getElementById('faturasPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pIa = document.getElementById('onixIaPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      if (!pContador || !pDash) return;
      if (pHome) pHome.classList.add('hidden');
      ocultarSeletorHomeConfig();
      if (pCad) pCad.classList.add('hidden');
      if (pFat) pFat.classList.add('hidden');
      if (pRel) pRel.classList.add('hidden');
      if (pIa) pIa.classList.add('hidden');
      if (pVendas) pVendas.classList.add('hidden');
      if (pEstoque) pEstoque.classList.add('hidden');
      pDash.classList.add('hidden');
      if (!pContador.classList.contains('hidden') && !forcar) {
        if (seletorContadorVisivel) ocultarSeletorContador();
        else mostrarSeletorContador();
        return;
      }
      pContador.classList.remove('hidden');
      ativarMenuPrincipal('contador');
      if (!cardContadorAtivo) {
        mostrarSeletorContador();
      }
    }

    function recalcularLinhaItemCompraEstoque(idx) {
      const item = itensCompraEstoqueTemp[idx];
      if (!item) return;
      const qtd = Number(item.quantidade || 0);
      const vu = Number(item.valor_unitario || 0);
      item.total = Number((qtd * vu).toFixed(2));
    }

    function renderItensCompraEstoque() {
      const tb = document.getElementById('tbItensCompraEstoque');
      if (!tb) return;
      tb.innerHTML = '';
      itensCompraEstoqueTemp.forEach((item, idx) => {
        const tr = document.createElement('tr');
        const sel = document.createElement('select');
        sel.innerHTML = '<option value="">Selecione...</option>';
        produtosCache.forEach(p => {
          const op = document.createElement('option');
          op.value = String(p.id);
          op.textContent = `${p.id} - ${p.nome}`;
          if (Number(item.produto_id) === Number(p.id)) op.selected = true;
          sel.appendChild(op);
        });
        sel.onchange = function() {
          const pid = Number(sel.value || 0);
          item.produto_id = pid || null;
          const prod = produtosCache.find(p => Number(p.id) === pid);
          if (prod && !item.descricao) item.descricao = prod.nome || '';
          renderItensCompraEstoque();
        };
        const desc = document.createElement('input');
        desc.value = item.descricao || '';
        desc.oninput = function() { item.descricao = desc.value || ''; };
        const qtd = document.createElement('input');
        qtd.type = 'number';
        qtd.step = '0.0001';
        qtd.min = '0';
        qtd.value = String(item.quantidade || 0);
        qtd.oninput = function() {
          item.quantidade = Number(qtd.value || 0);
          recalcularLinhaItemCompraEstoque(idx);
          renderItensCompraEstoque();
        };
        const vu = document.createElement('input');
        vu.type = 'number';
        vu.step = '0.01';
        vu.min = '0';
        vu.value = String(item.valor_unitario || 0);
        vu.oninput = function() {
          item.valor_unitario = Number(vu.value || 0);
          recalcularLinhaItemCompraEstoque(idx);
          renderItensCompraEstoque();
        };
        const total = document.createElement('span');
        total.textContent = moeda(item.total || 0);
        const acao = document.createElement('button');
        acao.type = 'button';
        acao.className = 'alt';
        acao.textContent = 'x';
        acao.onclick = function() {
          itensCompraEstoqueTemp.splice(idx, 1);
          renderItensCompraEstoque();
        };
        const td1 = document.createElement('td'); td1.appendChild(sel);
        const td2 = document.createElement('td'); td2.appendChild(desc);
        const td3 = document.createElement('td'); td3.appendChild(qtd);
        const td4 = document.createElement('td'); td4.appendChild(vu);
        const td5 = document.createElement('td'); td5.appendChild(total);
        const td6 = document.createElement('td'); td6.appendChild(acao);
        tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(td4); tr.appendChild(td5); tr.appendChild(td6);
        tb.appendChild(tr);
      });
    }

    function adicionarLinhaItemCompraEstoque(base = null) {
      const item = {
        produto_id: base && base.produto_id ? Number(base.produto_id) : null,
        descricao: (base && base.descricao) ? String(base.descricao) : '',
        quantidade: Number(base && base.quantidade ? base.quantidade : 1),
        valor_unitario: Number(base && base.valor_unitario ? base.valor_unitario : 0),
        total: Number(base && base.total ? base.total : 0),
      };
      if (!item.total) item.total = Number((item.quantidade * item.valor_unitario).toFixed(2));
      itensCompraEstoqueTemp.push(item);
      renderItensCompraEstoque();
    }

    async function carregarFornecedoresEstoque() {
      const cad = await api('/cadastros-gerais?contexto=pessoas');
      fornecedoresEstoqueCache = (Array.isArray(cad) ? cad : []).filter(item => !!item.is_fornecedor);
      const sel = document.getElementById('estCompraFornecedor');
      if (!sel) return;
      sel.innerHTML = '<option value="">Selecione...</option>';
      fornecedoresEstoqueCache.forEach(item => {
        const op = document.createElement('option');
        op.value = String(item.id);
        op.textContent = `${item.id} - ${item.razao_social || 'Sem nome'}`;
        sel.appendChild(op);
      });
    }

    async function abrirModalCompraEstoque() {
      try {
        const [produtos] = await Promise.all([api('/produtos'), carregarFornecedoresEstoque()]);
        produtosCache = Array.isArray(produtos) ? produtos : [];
      } catch (err) {
        setMsg('statusEstoqueCompras', `Falha ao carregar cadastro de compra: ${err.message}`, false);
      }
      document.getElementById('estCompraTipoLancamento').value = 'manual';
      document.getElementById('estFlagEntradaNota').checked = false;
      document.getElementById('estFlagCompraSimples').checked = false;
      document.getElementById('estCompraData').value = dataIsoHoje();
      document.getElementById('estCompraNumeroNota').value = '';
      document.getElementById('estCompraChaveNfe').value = '';
      document.getElementById('estCompraObs').value = '';
      setMsg('statusModalCompraEstoque', '');
      itensCompraEstoqueTemp = [];
      adicionarLinhaItemCompraEstoque();
      document.getElementById('modalCompraEstoque').classList.remove('hidden');
    }

    function fecharModalCompraEstoque() {
      document.getElementById('modalCompraEstoque').classList.add('hidden');
    }

    async function importarXmlCompraEstoque(input) {
      const file = input && input.files && input.files[0];
      if (!file) return;
      try {
        setMsg('statusModalCompraEstoque', 'Importando XML...');
        const formData = new FormData();
        formData.append('arquivo', file);
        const res = await fetch('/api/estoque/importar-xml', { method: 'POST', body: formData });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || 'Falha ao importar XML.');
        document.getElementById('estCompraTipoLancamento').value = 'xml';
        document.getElementById('estCompraNumeroNota').value = body.numero_nota || '';
        document.getElementById('estCompraData').value = body.data_emissao || dataIsoHoje();
        document.getElementById('estCompraChaveNfe').value = body.chave_nfe || '';
        itensCompraEstoqueTemp = [];
        (Array.isArray(body.itens) ? body.itens : []).forEach(item => adicionarLinhaItemCompraEstoque(item));
        if (!itensCompraEstoqueTemp.length) adicionarLinhaItemCompraEstoque();
        if (body.fornecedor_doc) {
          const forn = fornecedoresEstoqueCache.find(f => String(f.cnpj || '').replace(/\D+/g, '') === String(body.fornecedor_doc || '').replace(/\D+/g, ''));
          if (forn) document.getElementById('estCompraFornecedor').value = String(forn.id);
        }
        setMsg('statusModalCompraEstoque', 'XML importado com sucesso.');
      } catch (err) {
        setMsg('statusModalCompraEstoque', err.message, false);
      } finally {
        input.value = '';
      }
    }

    async function salvarCompraEstoque() {
      const entradaNota = !!document.getElementById('estFlagEntradaNota').checked;
      const compraSimples = !!document.getElementById('estFlagCompraSimples').checked;
      if (!entradaNota && !compraSimples) {
        setMsg('statusModalCompraEstoque', 'Marque Entrada de Nota ou Compra Simples.', false);
        return;
      }
      const itens = itensCompraEstoqueTemp
        .map(item => ({
          produto_id: item.produto_id || null,
          descricao: String(item.descricao || '').trim(),
          quantidade: Number(item.quantidade || 0),
          valor_unitario: Number(item.valor_unitario || 0),
          total: Number(item.total || 0),
        }))
        .filter(item => item.quantidade > 0 || item.total > 0);
      if (!itens.length) {
        setMsg('statusModalCompraEstoque', 'Adicione ao menos um item na compra.', false);
        return;
      }
      const payload = {
        tipo_lancamento: (document.getElementById('estCompraTipoLancamento').value || 'manual').toLowerCase(),
        entrada_nota: entradaNota,
        compra_simples: compraSimples,
        fornecedor_id: Number(document.getElementById('estCompraFornecedor').value) || null,
        data_emissao: document.getElementById('estCompraData').value || null,
        numero_nota: document.getElementById('estCompraNumeroNota').value.trim(),
        chave_nfe: document.getElementById('estCompraChaveNfe').value.trim(),
        observacao: document.getElementById('estCompraObs').value.trim(),
        itens: itens,
      };
      try {
        await api('/estoque/compras', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        setMsg('statusModalCompraEstoque', 'Compra lancada com sucesso.');
        fecharModalCompraEstoque();
        await listarComprasEstoque();
      } catch (err) {
        setMsg('statusModalCompraEstoque', err.message, false);
      }
    }

    async function listarComprasEstoque() {
      try {
        const [compras, cad] = await Promise.all([api('/estoque/compras'), api('/cadastros-gerais?contexto=pessoas')]);
        comprasEstoqueCache = Array.isArray(compras) ? compras : [];
        const fornMap = new Map();
        (Array.isArray(cad) ? cad : []).forEach(item => {
          if (item && item.id) fornMap.set(Number(item.id), item.razao_social || `Fornecedor ${item.id}`);
        });
        const tb = document.getElementById('tbEstoqueCompras');
        if (!tb) return;
        tb.innerHTML = '';
        comprasEstoqueCache.forEach(c => {
          const tr = document.createElement('tr');
          const tipo = c.entrada_nota ? 'Entrada de Nota' : (c.compra_simples ? 'Compra Simples' : '-');
          const fornecedorNome = c.fornecedor_id ? (fornMap.get(Number(c.fornecedor_id)) || `Fornecedor ${c.fornecedor_id}`) : '-';
          tr.innerHTML = `<td>${c.id}</td><td>${formatDataBr(c.data_emissao || c.created_at)}</td><td>${escapeHtml(fornecedorNome)}</td><td>${tipo}</td><td>${escapeHtml(c.numero_nota || '-')}</td><td>${moeda(c.total || 0)}</td><td>${Array.isArray(c.itens) ? c.itens.length : 0}</td>`;
          tb.appendChild(tr);
        });
        setMsg('statusEstoqueCompras', `${comprasEstoqueCache.length} compra(s) registrada(s).`);
      } catch (err) {
        setMsg('statusEstoqueCompras', `Falha ao listar compras: ${err.message}`, false);
      }
    }

    async function listarPosicaoAtualEstoque() {
      try {
        const itens = await api('/estoque/posicao-atual');
        const tb = document.getElementById('tbEstoquePosicao');
        if (!tb) return;
        tb.innerHTML = '';
        (Array.isArray(itens) ? itens : []).forEach(item => {
          const tr = document.createElement('tr');
          const produtoId = item.produto_id != null ? String(item.produto_id) : '-';
          const quantidade = Number(item.quantidade || 0);
          tr.innerHTML = `<td>${produtoId}</td><td>${escapeHtml(item.nome || '-')}</td><td>${escapeHtml(item.unidade || 'UN')}</td><td>${quantidade.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 4 })}</td>`;
          tb.appendChild(tr);
        });
        setMsg('statusEstoquePosicao', `${Array.isArray(itens) ? itens.length : 0} item(ns) em estoque.`);
      } catch (err) {
        setMsg('statusEstoquePosicao', `Falha ao carregar posicao: ${err.message}`, false);
      }
    }

    function preencherProdutoAjustePorCodigo() {
      const codigo = Number(document.getElementById('estAjusteCodigo').value || 0);
      const sel = document.getElementById('estAjusteProduto');
      if (!sel || !codigo) return;
      const existe = produtosCache.find(p => Number(p.id) === codigo);
      if (existe) sel.value = String(existe.id);
    }

    async function carregarProdutosAjusteEstoque() {
      produtosCache = await api('/produtos');
      const sel = document.getElementById('estAjusteProduto');
      if (!sel) return;
      sel.innerHTML = '<option value="">Selecione...</option>';
      produtosCache.forEach(item => {
        const op = document.createElement('option');
        op.value = String(item.id);
        op.textContent = `${item.id} - ${item.nome}`;
        sel.appendChild(op);
      });
    }

    async function listarAjustesEstoque() {
      try {
        await carregarProdutosAjusteEstoque();
        const itens = await api('/estoque/ajustes');
        const tb = document.getElementById('tbEstoqueAjustes');
        if (!tb) return;
        tb.innerHTML = '';
        (Array.isArray(itens) ? itens : []).forEach(item => {
          const tr = document.createElement('tr');
          const marcado = Number(ajusteEstoqueSelecionadoId || 0) === Number(item.id) ? 'checked' : '';
          tr.innerHTML = `<td><input type="radio" name="ajusteEstoqueSel" ${marcado} onclick="selecionarAjusteEstoque(${Number(item.id)}, ${Number(item.produto_id)}, ${Number(item.novo_estoque || 0)}, ${JSON.stringify(String(item.motivo || '')).replace(/"/g, '&quot;')})"></td><td>${item.id}</td><td>${formatDataBr(item.created_at)}</td><td>${escapeHtml(item.produto_nome || ('Produto ' + item.produto_id))}</td><td>${Number(item.novo_estoque || 0).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 4 })}</td><td>${escapeHtml(item.motivo || '')}</td>`;
          tb.appendChild(tr);
        });
        setMsg('statusEstoqueAjuste', `${Array.isArray(itens) ? itens.length : 0} ajuste(s) listado(s).`);
      } catch (err) {
        setMsg('statusEstoqueAjuste', `Falha ao listar ajustes: ${err.message}`, false);
      }
    }

    function selecionarAjusteEstoque(ajusteId, produtoId, novoEstoque, motivo) {
      ajusteEstoqueSelecionadoId = Number(ajusteId || 0) || null;
      document.getElementById('estAjusteProduto').value = String(Number(produtoId || 0) || '');
      document.getElementById('estAjusteCodigo').value = String(Number(produtoId || 0) || '');
      document.getElementById('estAjusteNovoEstoque').value = String(Number(novoEstoque || 0));
      document.getElementById('estAjusteMotivo').value = String(motivo || '');
      setMsg('statusEstoqueAjuste', `Ajuste #${ajusteEstoqueSelecionadoId} selecionado para edicao.`);
    }

    function limparSelecaoAjusteEstoque() {
      ajusteEstoqueSelecionadoId = null;
      document.getElementById('estAjusteCodigo').value = '';
      document.getElementById('estAjusteProduto').value = '';
      document.getElementById('estAjusteNovoEstoque').value = '';
      document.getElementById('estAjusteMotivo').value = '';
    }

    async function salvarAjusteEstoque() {
      const produtoId = Number(document.getElementById('estAjusteProduto').value || 0);
      const novoEstoque = Number(document.getElementById('estAjusteNovoEstoque').value || 0);
      const motivo = document.getElementById('estAjusteMotivo').value.trim();
      if (!produtoId) {
        setMsg('statusEstoqueAjuste', 'Selecione um produto para ajustar.', false);
        return;
      }
      if (!Number.isFinite(novoEstoque) || novoEstoque < 0) {
        setMsg('statusEstoqueAjuste', 'Informe um novo estoque valido.', false);
        return;
      }
      if (!motivo) {
        setMsg('statusEstoqueAjuste', 'Informe o motivo do ajuste.', false);
        return;
      }
      try {
        await api('/estoque/ajustes', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ produto_id: produtoId, novo_estoque: novoEstoque, motivo: motivo }),
        });
        setMsg('statusEstoqueAjuste', 'Ajuste salvo com sucesso.');
        limparSelecaoAjusteEstoque();
        await listarAjustesEstoque();
        await listarPosicaoAtualEstoque();
      } catch (err) {
        setMsg('statusEstoqueAjuste', err.message, false);
      }
    }

    async function editarAjusteEstoqueSelecionado() {
      if (!ajusteEstoqueSelecionadoId) {
        setMsg('statusEstoqueAjuste', 'Selecione um ajuste na lista para editar.', false);
        return;
      }
      const produtoId = Number(document.getElementById('estAjusteProduto').value || 0);
      const novoEstoque = Number(document.getElementById('estAjusteNovoEstoque').value || 0);
      const motivo = document.getElementById('estAjusteMotivo').value.trim();
      if (!produtoId) {
        setMsg('statusEstoqueAjuste', 'Selecione um produto para ajustar.', false);
        return;
      }
      if (!Number.isFinite(novoEstoque) || novoEstoque < 0) {
        setMsg('statusEstoqueAjuste', 'Informe um novo estoque valido.', false);
        return;
      }
      if (!motivo) {
        setMsg('statusEstoqueAjuste', 'Informe o motivo do ajuste.', false);
        return;
      }
      try {
        await api(`/estoque/ajustes/${Number(ajusteEstoqueSelecionadoId)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ produto_id: produtoId, novo_estoque: novoEstoque, motivo: motivo }),
        });
        setMsg('statusEstoqueAjuste', 'Ajuste atualizado com sucesso.');
        limparSelecaoAjusteEstoque();
        await listarAjustesEstoque();
        await listarPosicaoAtualEstoque();
      } catch (err) {
        setMsg('statusEstoqueAjuste', err.message, false);
      }
    }

    async function excluirAjusteEstoqueSelecionado() {
      if (!ajusteEstoqueSelecionadoId) {
        setMsg('statusEstoqueAjuste', 'Selecione um ajuste na lista para excluir.', false);
        return;
      }
      const permitido = await validarPermissaoExclusao();
      if (!permitido) {
        setMsg('statusEstoqueAjuste', 'Exclusao cancelada.', false);
        return;
      }
      try {
        await api(`/estoque/ajustes/${Number(ajusteEstoqueSelecionadoId)}`, { method: 'DELETE' });
        setMsg('statusEstoqueAjuste', 'Ajuste excluido com sucesso.');
        limparSelecaoAjusteEstoque();
        await listarAjustesEstoque();
        await listarPosicaoAtualEstoque();
      } catch (err) {
        setMsg('statusEstoqueAjuste', err.message, false);
      }
    }

    async function abrirProdutos() {
      var pHome = document.getElementById('onixHomePanel');
      var pCad = document.getElementById('cadastroPanel');
      var pFat = document.getElementById('faturasPanel');
      var pVendas = document.getElementById('vendasPanel');
      var pEstoque = document.getElementById('estoquePanel');
      var pContador = document.getElementById('contadorPanel');
      var pDash = document.getElementById('dashboardPanel');
      var pRel = document.getElementById('relatoriosPanel');
      var pIa = document.getElementById('onixIaPanel');
      if (!pCad || !pDash) return;
      if (pHome) pHome.classList.add('hidden');
      ocultarSeletorHomeConfig();
      pCad.classList.remove('hidden');
      if (pRel) pRel.classList.add('hidden');
      if (pFat) pFat.classList.add('hidden');
      if (pVendas) pVendas.classList.add('hidden');
      if (pEstoque) pEstoque.classList.add('hidden');
      if (pContador) pContador.classList.add('hidden');
      if (pIa) pIa.classList.add('hidden');
      pDash.classList.add('hidden');
      ativarMenuPrincipal('cadastro');
      abrirAbaCadastro('produtos');
    }

    function formatarPctExibicao(val) {
      const n = Number(val);
      if (!Number.isFinite(n)) return '0%';
      return n.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 2 }) + '%';
    }

    function decorarTitulosSecaoPremium() {
      const icones = [
        { re: /home|dashboard|kpi|previsao/i, icon: '⬢' },
        { re: /cadastro|pessoas|produto|usuarios/i, icon: '◎' },
        { re: /financeiro|contas|banco|caixa/i, icon: '◈' },
        { re: /vendas|pedido|orcamento|nf-e|nfs-e/i, icon: '◆' },
        { re: /estoque|compra|ajuste/i, icon: '◉' },
        { re: /fatura|cartao/i, icon: '◌' },
        { re: /relatorio/i, icon: '◍' },
        { re: /contador/i, icon: '◈' },
        { re: /onix_ia|assistente|chat/i, icon: '◊' },
      ];
      const titulos = document.querySelectorAll('.section-title');
      titulos.forEach(function(el) {
        if (!el || el.dataset.premiumIcon === '1') return;
        const texto = (el.textContent || '').trim();
        let icon = '⬢';
        for (let i = 0; i < icones.length; i++) {
          if (icones[i].re.test(texto)) {
            icon = icones[i].icon;
            break;
          }
        }
        const badge = document.createElement('span');
        badge.className = 'section-title-icon';
        badge.textContent = icon;
        el.insertBefore(badge, el.firstChild);
        el.dataset.premiumIcon = '1';
      });
    }

    function parsePorcentagemParaNumero(str) {
      const s = String(str || '').replace(/%/g, '').trim().replace(/\./g, '').replace(',', '.');
      const n = Number(s);
      if (!Number.isFinite(n) || n < 0) return 0;
      if (n > 100) return 100;
      return n;
    }

    function aplicarMascaraPorcentagemInput(el) {
      if (!el) return;
      const n = parsePorcentagemParaNumero(el.value);
      el.value = formatarPctExibicao(n);
    }

    function selecionarCategoriaProduto(id) {
      categoriaProdutoSelecionadaId = id;
      setMsg('statusCategoriasProduto', `Categoria ID ${id} selecionada.`);
    }

    async function listarCategoriasProdutoPainel() {
      try {
        categoriasProdutoCache = await api('/categorias-produto');
        categoriaProdutoSelecionadaId = null;
        const tb = document.getElementById('tbCategoriasProduto');
        if (!tb) return;
        tb.innerHTML = '';
        categoriasProdutoCache.forEach(c => {
          const tr = document.createElement('tr');
          const tdSel = document.createElement('td');
          const r = document.createElement('input');
          r.type = 'radio';
          r.name = 'catProdSelect';
          r.onchange = function() {
            selecionarCategoriaProduto(c.id);
          };
          tdSel.appendChild(r);
          const tdCod = document.createElement('td');
          tdCod.textContent = c.codigo || '';
          const tdNom = document.createElement('td');
          tdNom.textContent = c.nome || '';
          const tdPct = document.createElement('td');
          tdPct.textContent = formatarPctExibicao(c.percentual_comissao);
          tr.appendChild(tdSel);
          tr.appendChild(tdCod);
          tr.appendChild(tdNom);
          tr.appendChild(tdPct);
          tb.appendChild(tr);
        });
        setMsg('statusCategoriasProduto', `${categoriasProdutoCache.length} categoria(s). Selecione uma para editar ou excluir.`);
      } catch (err) {
        setMsg('statusCategoriasProduto', err.message, false);
      }
    }

    function abrirModalEdicaoCategoriaProduto() {
      if (!categoriaProdutoSelecionadaId) {
        setMsg('statusCategoriasProduto', 'Selecione uma categoria (radio) na tabela.', false);
        return;
      }
      const c = categoriasProdutoCache.find(x => Number(x.id) === Number(categoriaProdutoSelecionadaId));
      if (!c) {
        setMsg('statusCategoriasProduto', 'Categoria nao encontrada. Atualize a lista.', false);
        return;
      }
      const imut = codigosCategoriaProdutoImutaveis.includes(c.codigo);
      document.getElementById('catModalId').value = String(c.id);
      document.getElementById('catModalCodigo').textContent = c.codigo || '';
      const nomeEl = document.getElementById('catModalNome');
      nomeEl.value = c.nome || '';
      nomeEl.readOnly = imut;
      nomeEl.title = imut ? 'Nome fixo nas categorias padrao' : '';
      const pctEl = document.getElementById('catModalPct');
      pctEl.value = formatarPctExibicao(c.percentual_comissao);
      pctEl.onblur = function() {
        aplicarMascaraPorcentagemInput(pctEl);
      };
      document.getElementById('tituloModalCategoriaProduto').textContent = imut ? 'Editar Categoria (padrao)' : 'Editar Categoria';
      setMsg('statusModalCategoriaProduto', '');
      document.getElementById('modalCategoriaProduto').classList.remove('hidden');
    }

    function fecharModalCategoriaProduto() {
      document.getElementById('modalCategoriaProduto').classList.add('hidden');
    }

    async function salvarModalCategoriaProduto() {
      const id = Number(document.getElementById('catModalId').value);
      if (!Number.isFinite(id) || id < 1) {
        setMsg('statusModalCategoriaProduto', 'ID invalido.', false);
        return;
      }
      const cod = String(document.getElementById('catModalCodigo').textContent || '').trim();
      const imut = codigosCategoriaProdutoImutaveis.includes(cod);
      const pct = parsePorcentagemParaNumero(document.getElementById('catModalPct').value);
      const body = { percentual_comissao: pct };
      if (!imut) {
        const nome = document.getElementById('catModalNome').value.trim();
        if (!nome) {
          setMsg('statusModalCategoriaProduto', 'Informe o nome.', false);
          return;
        }
        body.nome = nome;
      }
      try {
        await api('/categorias-produto/' + id, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        fecharModalCategoriaProduto();
        await listarCategoriasProdutoPainel();
        setMsg('statusCategoriasProduto', 'Categoria salva.');
        await carregarSelectCategoriasProduto();
      } catch (err) {
        setMsg('statusModalCategoriaProduto', err.message, false);
      }
    }

    async function excluirCategoriaProdutoSelecionada() {
      if (!categoriaProdutoSelecionadaId) {
        setMsg('statusCategoriasProduto', 'Selecione uma categoria para excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const c = categoriasProdutoCache.find(x => Number(x.id) === Number(categoriaProdutoSelecionadaId));
      if (!c) {
        setMsg('statusCategoriasProduto', 'Selecione novamente apos atualizar a lista.', false);
        return;
      }
      if (codigosCategoriaProdutoImutaveis.includes(c.codigo)) {
        setMsg('statusCategoriasProduto', 'Categorias padrao nao podem ser excluidas.', false);
        return;
      }
      if (!window.confirm('Excluir a categoria "' + (c.nome || c.codigo) + '"? So e permitido se nenhum produto a usar.')) return;
      try {
        await api('/categorias-produto/' + c.id, { method: 'DELETE' });
        categoriaProdutoSelecionadaId = null;
        await listarCategoriasProdutoPainel();
        setMsg('statusCategoriasProduto', 'Categoria excluida.');
        await carregarSelectCategoriasProduto();
      } catch (err) {
        setMsg('statusCategoriasProduto', err.message, false);
      }
    }

    async function carregarSelectCategoriasProduto() {
      categoriasProdutoCache = await api('/categorias-produto');
      const sel = document.getElementById('proCategoria');
      if (!sel) return;
      sel.innerHTML = '';
      categoriasProdutoCache.forEach(c => {
        const o = document.createElement('option');
        o.value = String(c.id);
        o.textContent = (c.nome || c.codigo) + ' — ' + formatarPctExibicao(c.percentual_comissao);
        sel.appendChild(o);
      });
    }

    function definirCategoriaPadraoNoSelect(categoriaIdPreferida) {
      const sel = document.getElementById('proCategoria');
      if (!sel || !categoriasProdutoCache.length) return;
      const pref = Number(categoriaIdPreferida);
      if (Number.isFinite(pref) && categoriasProdutoCache.some(c => Number(c.id) === pref)) {
        sel.value = String(pref);
        return;
      }
      const def = categoriasProdutoCache.find(c => c.codigo === 'PRODUTOS');
      sel.value = String((def || categoriasProdutoCache[0]).id);
    }

    async function listarProdutosPainel() {
      try {
        produtosCache = await api('/produtos');
        const tb = document.getElementById('tbProdutosCadastro');
        if (!tb) return;
        tb.innerHTML = '';
        produtosCache.forEach(item => {
          const tr = document.createElement('tr');
          const td1 = document.createElement('td');
          td1.textContent = String(item.id);
          const td2 = document.createElement('td');
          td2.textContent = item.nome || '';
          const td3 = document.createElement('td');
          td3.textContent = item.sku || '-';
          const td4 = document.createElement('td');
          td4.textContent = item.categoria_nome || '-';
          const td5 = document.createElement('td');
          td5.textContent = moeda(item.preco_venda);
          const td6 = document.createElement('td');
          td6.textContent = item.ncm || '-';
          const td7 = document.createElement('td');
          td7.textContent = item.cfop_venda || '-';
          const td8 = document.createElement('td');
          td8.textContent = item.csosn || '-';
          const tdAc = document.createElement('td');
          const btnEd = document.createElement('button');
          btnEd.type = 'button';
          btnEd.textContent = 'Editar';
          btnEd.onclick = function() {
            void abrirModalProduto(item.id);
          };
          const btnEx = document.createElement('button');
          btnEx.type = 'button';
          btnEx.className = 'alt';
          btnEx.style.marginLeft = '6px';
          btnEx.textContent = 'Excluir';
          btnEx.onclick = function() {
            void excluirProdutoCadastro(item.id);
          };
          tdAc.appendChild(btnEd);
          tdAc.appendChild(btnEx);
          tr.appendChild(td1);
          tr.appendChild(td2);
          tr.appendChild(td3);
          tr.appendChild(td4);
          tr.appendChild(td5);
          tr.appendChild(td6);
          tr.appendChild(td7);
          tr.appendChild(td8);
          tr.appendChild(tdAc);
          tb.appendChild(tr);
        });
        setMsg('statusProdutosCadastro', `${produtosCache.length} produto(s) carregado(s).`);
      } catch (err) {
        setMsg('statusProdutosCadastro', err.message, false);
      }
    }

    async function abrirModalProduto(idEdicao) {
      const tituloEl = document.getElementById('tituloModalProduto');
      const idNum = idEdicao != null && idEdicao !== '' ? Number(idEdicao) : null;
      produtoEdicaoId = Number.isFinite(idNum) && idNum > 0 ? idNum : null;
      if (tituloEl) {
        tituloEl.textContent = produtoEdicaoId ? 'Editar Produto/Servico' : 'Cadastro de Produto/Servico';
      }
      try {
        await carregarSelectCategoriasProduto();
      } catch (e) {
        setMsg('statusProdutoModal', 'Nao foi possivel carregar categorias: ' + e.message, false);
        return;
      }
      if (produtoEdicaoId) {
        const item = produtosCache.find(p => Number(p.id) === produtoEdicaoId);
        if (!item) {
          setMsg('statusProdutoModal', 'Produto nao encontrado na lista. Atualize e tente de novo.', false);
          produtoEdicaoId = null;
          if (tituloEl) tituloEl.textContent = 'Cadastro de Produto/Servico';
          return;
        }
        document.getElementById('proNome').value = item.nome || '';
        document.getElementById('proSku').value = item.sku || '';
        definirCategoriaPadraoNoSelect(item.categoria_produto_id);
        document.getElementById('proPrecoCusto').value = String(item.preco_custo != null ? item.preco_custo : '0');
        document.getElementById('proPrecoVenda').value = String(item.preco_venda != null ? item.preco_venda : '0');
        document.getElementById('proNcm').value = item.ncm || '';
        document.getElementById('proCest').value = item.cest || '';
        document.getElementById('proCfopCompra').value = item.cfop_compra || '1102';
        document.getElementById('proCfopVenda').value = item.cfop_venda || '5102';
        document.getElementById('proCsosn').value = item.csosn || '102';
        document.getElementById('proAliqSaida').value = String(item.aliquota_icms_saida != null ? item.aliquota_icms_saida : '0');
        document.getElementById('proDescricao').value = item.descricao || '';
      } else {
        document.getElementById('proNome').value = '';
        document.getElementById('proSku').value = '';
        definirCategoriaPadraoNoSelect(null);
        document.getElementById('proPrecoCusto').value = '0.00';
        document.getElementById('proPrecoVenda').value = '0.00';
        document.getElementById('proNcm').value = '';
        document.getElementById('proCest').value = '';
        document.getElementById('proCfopCompra').value = '1102';
        document.getElementById('proCfopVenda').value = '5102';
        document.getElementById('proCsosn').value = '102';
        document.getElementById('proAliqSaida').value = '0.00';
        document.getElementById('proDescricao').value = '';
      }
      setMsg('statusProdutoModal', '');
      document.getElementById('modalProduto').classList.remove('hidden');
    }

    function fecharModalProduto() {
      produtoEdicaoId = null;
      const tituloEl = document.getElementById('tituloModalProduto');
      if (tituloEl) tituloEl.textContent = 'Cadastro de Produto/Servico';
      document.getElementById('modalProduto').classList.add('hidden');
    }

    async function excluirProdutoCadastro(id) {
      const idNum = Number(id);
      if (!Number.isFinite(idNum) || idNum < 1) return;
      if (!(await validarPermissaoExclusao())) return;
      if (!window.confirm('Excluir este produto? Itens de venda vinculados podem impedir a exclusao.')) return;
      try {
        await api(`/produtos/${idNum}`, { method: 'DELETE' });
        await listarProdutosPainel();
        setMsg('statusProdutosCadastro', 'Produto excluido.');
      } catch (err) {
        setMsg('statusProdutosCadastro', err.message, false);
      }
    }

    async function salvarProduto() {
      const selCat = document.getElementById('proCategoria');
      const catId = selCat ? Number(selCat.value) : 0;
      const payload = {
        nome: document.getElementById('proNome').value.trim(),
        categoria_produto_id: catId,
        sku: document.getElementById('proSku').value.trim() || null,
        is_servico: false,
        unidade: 'UN',
        preco_custo: Number(document.getElementById('proPrecoCusto').value) || 0,
        preco_venda: Number(document.getElementById('proPrecoVenda').value) || 0,
        ncm: document.getElementById('proNcm').value.trim() || null,
        cest: document.getElementById('proCest').value.trim() || null,
        cfop_compra: document.getElementById('proCfopCompra').value.trim() || null,
        cfop_venda: document.getElementById('proCfopVenda').value.trim() || null,
        csosn: document.getElementById('proCsosn').value.trim() || null,
        aliquota_icms_entrada: 0,
        aliquota_icms_saida: Number(document.getElementById('proAliqSaida').value) || 0,
        descricao: document.getElementById('proDescricao').value.trim() || null,
        ativa: true,
      };
      if (!payload.nome) {
        setMsg('statusProdutoModal', 'Informe o nome do produto.', false);
        return;
      }
      if (!Number.isFinite(catId) || catId < 1) {
        setMsg('statusProdutoModal', 'Selecione uma categoria.', false);
        return;
      }
      const editando = !!produtoEdicaoId;
      try {
        if (produtoEdicaoId) {
          await api(`/produtos/${produtoEdicaoId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
        } else {
          await api('/produtos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
        }
        fecharModalProduto();
        await listarProdutosPainel();
        setMsg('statusProdutosCadastro', editando ? 'Produto atualizado com sucesso.' : 'Produto salvo com sucesso.');
      } catch (err) {
        setMsg('statusProdutoModal', err.message, false);
      }
    }

    async function listarVendasPainel() {
      try {
        vendasCache = await api('/vendas');
        const cad = await api('/cadastros-gerais?contexto=pessoas');
        const map = new Map(cad.map(x => [x.id, x.razao_social || `Pessoa ${x.id}`]));
        const tb = document.getElementById('tbVendas');
        if (!tb) return;
        tb.innerHTML = '';
        vendasCache.forEach(v => {
          const ehOrcamento = String(v.numero || '').toUpperCase().startsWith('ORC');
          if (abaVendasAtiva === 'pedidos' && ehOrcamento) return;
          if (abaVendasAtiva === 'orcamentos' && !ehOrcamento) return;
          if (abaVendasAtiva === 'nfe' && !v.nfe_gerada) return;
          if (abaVendasAtiva === 'nfse' && !v.nfse_gerada) return;
          const tr = document.createElement('tr');
          const marcado = vendasSelecionadas.has(Number(v.id)) ? 'checked' : '';
          const cli = v.cliente_id ? (map.get(v.cliente_id) || `ID ${v.cliente_id}`) : '-';
          const vend = v.vendedor_id ? (map.get(v.vendedor_id) || `ID ${v.vendedor_id}`) : '-';
          const condNome = v.condicao_pagamento_nome ? escapeHtml(v.condicao_pagamento_nome) : '-';
          const prazo = v.prazo_pagamento ? escapeHtml(v.prazo_pagamento) : '-';
          const stFinanceiro = `<span class="venda-status-item"><span class="venda-status-dot ${v.financeiro_gerado ? 'ok' : 'pend'}"></span>R$</span>`;
          const stNfse = `<span class="venda-status-item"><span class="venda-status-dot ${v.nfse_gerada ? 'ok' : 'pend'}"></span>NFS-e</span>`;
          const stNfe = `<span class="venda-status-item"><span class="venda-status-dot ${v.nfe_gerada ? 'ok' : 'pend'}"></span>NF-e</span>`;
          const acaoPdf = 'Gerar PDF Pedido';
          const acaoPdfNfe = 'Abrir PDF NF-e';
          const acaoNfse = v.nfse_gerada ? 'NFS-e gerada' : 'Gerar NFS-e';
          const acaoNfe = v.nfe_gerada ? 'NF-e gerada' : 'Gerar NF-e';
          const acaoFinanceiro = v.financeiro_gerado ? 'Financeiro gerado' : 'Gerar Financeiro';
          const acaoEstorno = 'Estornar Financeiro';
          tr.innerHTML = `<td><input type="checkbox" ${marcado} onclick="event.stopPropagation();toggleVendaSelecionada(${v.id}, this.checked)" /></td><td>${v.id}</td><td>${escapeHtml(v.numero)}</td><td>${escapeHtml(cli)}</td><td>${escapeHtml(vend)}</td><td>${condNome}</td><td>${prazo}</td><td>${moeda(v.total_liquido)}</td><td>${formatDataBr(v.created_at)}</td><td><div class="venda-status-tags">${stFinanceiro}${stNfse}${stNfe}</div></td><td class="venda-acoes-cell"><button type="button" class="alt" onclick="abrirModalEditarVenda(${v.id})">Editar</button> <button type="button" class="alt" onclick="excluirVendaPainel(${v.id})">Excluir</button> <button type="button" class="alt btn-kebab" data-venda-menu-btn="${v.id}" onclick="abrirMenuAcoesVenda(event, ${v.id}, '${escapeHtml(acaoPdf)}', '${escapeHtml(acaoPdfNfe)}', '${escapeHtml(acaoFinanceiro)}', '${escapeHtml(acaoEstorno)}', '${escapeHtml(acaoNfse)}', '${escapeHtml(acaoNfe)}')">...</button></td>`;
          tb.appendChild(tr);
        });
        var qtd = document.querySelectorAll('#tbVendas tr').length;
        setMsg('statusVendas', `${qtd} registro(s) em ${labelCardVendas(abaVendasAtiva)}.`);
      } catch (err) {
        setMsg('statusVendas', err.message, false);
      }
    }

    async function preencherSelectCondicoesPedido(selectEl, valorId) {
      if (!selectEl) return;
      const lista = await api('/condicoes-pagamento');
      selectEl.innerHTML = '<option value="">Selecione...</option>';
      lista.forEach(c => {
        const o = document.createElement('option');
        o.value = String(c.id);
        o.textContent = c.nome != null ? String(c.nome) : '';
        if (valorId != null && Number(valorId) === Number(c.id)) o.selected = true;
        selectEl.appendChild(o);
      });
    }

    async function abrirModalNovoPedido() {
      try {
        venEditVendaId = null;
        const titulo = document.getElementById('tituloModalPedidoVenda');
        if (titulo) titulo.textContent = 'Novo Pedido de Venda';
        const [cadastros, produtos] = await Promise.all([
          api('/cadastros-gerais?contexto=pessoas'),
          api('/produtos'),
        ]);
        produtosCache = produtos;
        const selCli = document.getElementById('venCliente');
        const selVend = document.getElementById('venVendedor');
        selCli.innerHTML = '<option value="">Selecione...</option>';
        selVend.innerHTML = '<option value="">Selecione...</option>';
        cadastros.filter(x => !!x.is_cliente).forEach(x => {
          const o = document.createElement('option');
          o.value = String(x.id);
          o.textContent = `${x.id} - ${x.razao_social || ''}`;
          selCli.appendChild(o);
        });
        cadastros.filter(x => !!x.is_vendedor).forEach(x => {
          const o = document.createElement('option');
          o.value = String(x.id);
          o.textContent = `${x.id} - ${x.razao_social || ''}`;
          selVend.appendChild(o);
        });
        const selCond = document.getElementById('venCondicaoPagId');
        await preencherSelectCondicoesPedido(selCond, null);
        itensVendaTemp = [];
        document.getElementById('venObs').value = '';
        document.getElementById('venPrazoPag').value = '';
        const venF = document.getElementById('venFrete');
        if (venF) venF.value = formatMoedaBrCampo(0);
        instalarMascaraCampoFreteVenda();
        document.getElementById('tbItensVenda').innerHTML = '';
        adicionarLinhaItemVenda();
        setMsg('statusVendaModal', '');
        document.getElementById('modalNovoPedido').classList.remove('hidden');
      } catch (err) {
        setMsg('statusVendas', err.message, false);
      }
    }

    async function abrirModalEditarVenda(id) {
      try {
        venEditVendaId = Number(id) || null;
        const titulo = document.getElementById('tituloModalPedidoVenda');
        if (titulo) titulo.textContent = 'Editar Pedido de Venda';
        const v = await api('/vendas/' + encodeURIComponent(String(id)));
        const [cadastros, produtos] = await Promise.all([
          api('/cadastros-gerais?contexto=pessoas'),
          api('/produtos'),
        ]);
        produtosCache = produtos;
        const selCli = document.getElementById('venCliente');
        const selVend = document.getElementById('venVendedor');
        selCli.innerHTML = '<option value="">Selecione...</option>';
        selVend.innerHTML = '<option value="">Selecione...</option>';
        cadastros.filter(x => !!x.is_cliente).forEach(x => {
          const o = document.createElement('option');
          o.value = String(x.id);
          o.textContent = `${x.id} - ${x.razao_social || ''}`;
          if (v.cliente_id != null && Number(v.cliente_id) === Number(x.id)) o.selected = true;
          selCli.appendChild(o);
        });
        cadastros.filter(x => !!x.is_vendedor).forEach(x => {
          const o = document.createElement('option');
          o.value = String(x.id);
          o.textContent = `${x.id} - ${x.razao_social || ''}`;
          if (v.vendedor_id != null && Number(v.vendedor_id) === Number(x.id)) o.selected = true;
          selVend.appendChild(o);
        });
        const selCond = document.getElementById('venCondicaoPagId');
        await preencherSelectCondicoesPedido(selCond, v.condicao_pagamento_id);
        document.getElementById('venObs').value = v.observacao || '';
        document.getElementById('venPrazoPag').value = v.prazo_pagamento || '';
        const venF = document.getElementById('venFrete');
        if (venF) venF.value = formatMoedaBrCampo(Number(v.valor_frete || 0));
        instalarMascaraCampoFreteVenda();
        itensVendaTemp = (v.itens || []).map(it => ({
          produto_id: Number(it.produto_id),
          quantidade: Number(it.quantidade),
          valor_unitario: Number(it.valor_unitario || 0),
          desconto: Number(it.desconto || 0),
        }));
        if (!itensVendaTemp.length) {
          itensVendaTemp.push({ produto_id: null, quantidade: 1, valor_unitario: 0, desconto: 0 });
        }
        renderItensVendaTemp();
        setMsg('statusVendaModal', '');
        document.getElementById('modalNovoPedido').classList.remove('hidden');
      } catch (err) {
        setMsg('statusVendas', err.message, false);
        venEditVendaId = null;
      }
    }

    async function excluirVendaPainel(id) {
      if (!(await validarPermissaoExclusao())) return;
      if (!window.confirm('Confirma excluir este pedido de venda? Esta acao nao pode ser desfeita.')) return;
      try {
        await api('/vendas/' + encodeURIComponent(String(id)), { method: 'DELETE' });
        await listarVendasPainel();
        setMsg('statusVendas', 'Pedido excluido.');
      } catch (err) {
        setMsg('statusVendas', err.message, false);
      }
    }

    function toggleVendaSelecionada(id, checked) {
      const k = Number(id);
      if (!Number.isFinite(k)) return;
      if (checked) vendasSelecionadas.add(k);
      else vendasSelecionadas.delete(k);
    }

    function garantirMenuAcoesVenda() {
      if (vendaMenuPopoverEl) return vendaMenuPopoverEl;
      const el = document.createElement('div');
      el.className = 'venda-menu-popover hidden';
      document.body.appendChild(el);
      vendaMenuPopoverEl = el;
      return el;
    }

    function fecharMenuAcoesVenda() {
      if (!vendaMenuPopoverEl) return;
      vendaMenuPopoverEl.classList.add('hidden');
      vendaMenuPopoverEl.innerHTML = '';
      vendaMenuAnchorId = null;
    }

    function abrirMenuAcoesVenda(ev, id, acaoPdf, acaoPdfNfe, acaoFinanceiro, acaoEstorno, acaoNfse, acaoNfe) {
      ev.preventDefault();
      ev.stopPropagation();
      const btn = ev.currentTarget;
      if (!btn) return;
      if (vendaMenuAnchorId === Number(id) && vendaMenuPopoverEl && !vendaMenuPopoverEl.classList.contains('hidden')) {
        fecharMenuAcoesVenda();
        return;
      }
      const menu = garantirMenuAcoesVenda();
      menu.innerHTML = `
        <button type="button" class="alt" onclick="gerarPdfVenda(${id});fecharMenuAcoesVenda();">${acaoPdf}</button>
        <button type="button" class="alt" onclick="abrirPdfNfeVenda(${id});fecharMenuAcoesVenda();">${acaoPdfNfe}</button>
        <button type="button" class="alt" onclick="gerarFinanceiroVenda(${id});fecharMenuAcoesVenda();">${acaoFinanceiro}</button>
        <button type="button" class="alt" onclick="estornarFinanceiroVenda(${id});fecharMenuAcoesVenda();">${acaoEstorno}</button>
        <button type="button" class="alt" onclick="gerarNfseVenda(${id});fecharMenuAcoesVenda();">${acaoNfse}</button>
        <button type="button" class="alt" onclick="gerarNfeVenda(${id});fecharMenuAcoesVenda();">${acaoNfe}</button>
      `;
      const rect = btn.getBoundingClientRect();
      const largura = 210;
      const left = Math.max(8, Math.min(window.innerWidth - largura - 8, rect.right - largura));
      const top = Math.max(8, rect.bottom + 6);
      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;
      menu.classList.remove('hidden');
      vendaMenuAnchorId = Number(id);
    }

    document.addEventListener('click', function(ev) {
      if (!vendaMenuPopoverEl || vendaMenuPopoverEl.classList.contains('hidden')) return;
      const target = ev.target;
      if (!(target instanceof Element)) return;
      if (target.closest('.venda-menu-popover')) return;
      if (target.closest('[data-venda-menu-btn]')) return;
      fecharMenuAcoesVenda();
    });

    document.addEventListener('click', function(ev) {
      if (!seletorHomeConfigVisivel) return;
      var target = ev.target;
      if (!(target instanceof Element)) return;
      if (target.closest('#homeConfigSelector')) return;
      if (target.closest('#btnHomeConfiguracoes')) return;
      ocultarSeletorHomeConfig();
    });

    document.addEventListener('click', function(ev) {
      if (!seletorContadorVisivel) return;
      var target = ev.target;
      if (!(target instanceof Element)) return;
      if (target.closest('#contadorPanel .vertical-tab-strip')) return;
      if (target.closest('#menuContador')) return;
      ocultarSeletorContador();
    });

    window.addEventListener('resize', function() {
      fecharMenuAcoesVenda();
      if (seletorHomeConfigVisivel) posicionarSeletorHomeConfig();
      if (seletorEstoqueVisivel) posicionarSeletorEstoque();
      if (seletorContadorVisivel) posicionarSeletorContador();
    });
    window.addEventListener('scroll', fecharMenuAcoesVenda, true);

    async function gerarFinanceiroVenda(id) {
      try {
        const v = await api('/vendas/' + encodeURIComponent(String(id)) + '/gerar-financeiro', { method: 'POST' });
        await listarVendasPainel();
        setMsg('statusVendas', `Financeiro gerado para o pedido ${v.numero}.`);
      } catch (err) {
        setMsg('statusVendas', err.message, false);
      }
    }

    function gerarPdfVenda(id) {
      const url = '/api/vendas/' + encodeURIComponent(String(id)) + '/pdf';
      window.open(url, '_blank', 'noopener,noreferrer');
    }

    function abrirPdfNfeVenda(id) {
      const base = '/api/vendas/' + encodeURIComponent(String(id)) + '/nfe/pdf';
      const url = base + '?_ts=' + Date.now();
      window.open(url, '_blank', 'noopener,noreferrer');
    }

    async function estornarFinanceiroVenda(id) {
      if (!window.confirm('Confirma estornar o financeiro deste pedido? Esta acao remove as contas a receber vinculadas que ainda nao foram recebidas.')) return;
      try {
        const v = await api('/vendas/' + encodeURIComponent(String(id)) + '/estornar-financeiro', { method: 'POST' });
        await listarVendasPainel();
        setMsg('statusVendas', `Financeiro estornado para o pedido ${v.numero}.`);
      } catch (err) {
        setMsg('statusVendas', err.message, false);
      }
    }

    async function gerarNfseVenda(id) {
      try {
        const v = await api('/vendas/' + encodeURIComponent(String(id)) + '/gerar-nfs-e', { method: 'POST' });
        await listarVendasPainel();
        setMsg('statusVendas', `NFS-e sinalizada para o pedido ${v.numero}.`);
      } catch (err) {
        setMsg('statusVendas', err.message, false);
      }
    }

    async function gerarNfeVenda(id) {
      const pedidoId = encodeURIComponent(String(id));
      const pdfTab = window.open('about:blank', '_blank');
      try {
        const resp = await api('/vendas/' + pedidoId + '/gerar-nf-e', { method: 'POST' });
        const v = resp?.venda || resp || {};
        const nfe = resp?.nfe || {};
        await listarVendasPainel();
        const detalhes = [];
        if (nfe.chave) detalhes.push(`chave ${nfe.chave}`);
        if (nfe.arquivo_xml_assinado) detalhes.push(`XML: ${nfe.arquivo_xml_assinado}`);
        const sufixo = detalhes.length ? ` (${detalhes.join(' | ')})` : '';
        setMsg('statusVendas', `NF-e gerada para o pedido ${v.numero || id}${sufixo}.`);
        const chaveParam = nfe?.chave ? `chave=${encodeURIComponent(String(nfe.chave))}&` : '';
        const pdfUrl = `/api/vendas/${pedidoId}/nfe/pdf?${chaveParam}_ts=${Date.now()}`;
        if (pdfTab) {
          pdfTab.location.href = pdfUrl;
        } else {
          window.open(pdfUrl, '_blank');
        }
      } catch (err) {
        if (pdfTab && !pdfTab.closed) pdfTab.close();
        setMsg('statusVendas', err.message, false);
      }
    }

    function instalarMascaraCampoFreteVenda() {
      const el = document.getElementById('venFrete');
      if (!el || el.dataset.venFreteMask === '1') return;
      el.dataset.venFreteMask = '1';
      el.addEventListener('focus', function() {
        const v = parseMoedaBr(el.value);
        el.value = v ? v.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '';
      });
      el.addEventListener('blur', function() {
        let v = parseMoedaBr(el.value);
        if (!Number.isFinite(v) || v < 0) v = 0;
        el.value = formatMoedaBrCampo(v);
      });
    }

    function fecharModalNovoPedido() {
      venEditVendaId = null;
      document.getElementById('modalNovoPedido').classList.add('hidden');
    }

    function adicionarLinhaItemVenda() {
      itensVendaTemp.push({ produto_id: null, quantidade: 1, valor_unitario: 0, desconto: 0 });
      renderItensVendaTemp();
    }

    function removerLinhaItemVenda(idx) {
      itensVendaTemp.splice(idx, 1);
      renderItensVendaTemp();
    }

    function renderItensVendaTemp() {
      const tb = document.getElementById('tbItensVenda');
      if (!tb) return;
      tb.innerHTML = '';
      itensVendaTemp.forEach((item, idx) => {
        const tr = document.createElement('tr');
        const tdP = document.createElement('td');
        const sel = document.createElement('select');
        sel.className = 'ven-sel-produto';
        const o0 = document.createElement('option');
        o0.value = '';
        o0.textContent = 'Selecione...';
        sel.appendChild(o0);
        produtosCache.forEach(p => {
          const o = document.createElement('option');
          o.value = String(p.id);
          o.textContent = p.nome != null ? String(p.nome) : '';
          if (Number(item.produto_id) === Number(p.id)) o.selected = true;
          sel.appendChild(o);
        });
        sel.addEventListener('change', function() {
          const pid = Number(sel.value) || null;
          itensVendaTemp[idx].produto_id = pid;
          if (pid) {
            const pr = produtosCache.find(x => Number(x.id) === pid);
            if (pr && pr.preco_venda != null) {
              itensVendaTemp[idx].valor_unitario = Number(pr.preco_venda) || 0;
            }
          }
          renderItensVendaTemp();
        });
        tdP.appendChild(sel);

        const tdTot = document.createElement('td');
        tdTot.setAttribute('data-ven-total', '1');
        function atualizarTotalCelula() {
          tdTot.textContent = moeda(calcTotalLinhaVendaItem(itensVendaTemp[idx]));
        }
        atualizarTotalCelula();

        const tdQ = document.createElement('td');
        const inpQ = document.createElement('input');
        inpQ.type = 'text';
        inpQ.inputMode = 'decimal';
        inpQ.className = 'ven-inp-compact';
        inpQ.value = formatQtdBr(item.quantidade);
        inpQ.addEventListener('input', function() {
          itensVendaTemp[idx].quantidade = parseDecimalBr(inpQ.value);
          atualizarTotalCelula();
        });
        inpQ.addEventListener('blur', function() {
          let v = parseDecimalBr(inpQ.value);
          if (!Number.isFinite(v) || v <= 0) v = 1;
          itensVendaTemp[idx].quantidade = v;
          inpQ.value = formatQtdBr(v);
          atualizarTotalCelula();
        });
        tdQ.appendChild(inpQ);

        const tdVu = document.createElement('td');
        const inpVu = document.createElement('input');
        inpVu.type = 'text';
        inpVu.inputMode = 'decimal';
        inpVu.className = 'ven-inp-compact';
        inpVu.placeholder = 'R$ 0,00';
        inpVu.value = formatMoedaBrCampo(item.valor_unitario);
        inpVu.addEventListener('focus', function() {
          const raw = Number(itensVendaTemp[idx].valor_unitario || 0);
          inpVu.value = raw ? raw.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '';
        });
        inpVu.addEventListener('input', function() {
          itensVendaTemp[idx].valor_unitario = parseMoedaBr(inpVu.value);
          atualizarTotalCelula();
        });
        inpVu.addEventListener('blur', function() {
          let v = parseMoedaBr(inpVu.value);
          if (!Number.isFinite(v) || v < 0) v = 0;
          itensVendaTemp[idx].valor_unitario = v;
          inpVu.value = formatMoedaBrCampo(v);
          atualizarTotalCelula();
        });
        tdVu.appendChild(inpVu);

        const tdD = document.createElement('td');
        const inpD = document.createElement('input');
        inpD.type = 'text';
        inpD.inputMode = 'decimal';
        inpD.className = 'ven-inp-compact';
        inpD.placeholder = '0,00';
        inpD.value = formatDescBr(item.desconto);
        inpD.addEventListener('input', function() {
          itensVendaTemp[idx].desconto = parseDecimalBr(inpD.value);
          atualizarTotalCelula();
        });
        inpD.addEventListener('blur', function() {
          let v = parseDecimalBr(inpD.value);
          if (!Number.isFinite(v) || v < 0) v = 0;
          itensVendaTemp[idx].desconto = v;
          inpD.value = formatDescBr(v);
          atualizarTotalCelula();
        });
        tdD.appendChild(inpD);

        const tdAc = document.createElement('td');
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'alt';
        btn.textContent = 'Remover';
        btn.addEventListener('click', function() {
          removerLinhaItemVenda(idx);
        });
        tdAc.appendChild(btn);

        tr.appendChild(tdP);
        tr.appendChild(tdQ);
        tr.appendChild(tdVu);
        tr.appendChild(tdD);
        tr.appendChild(tdTot);
        tr.appendChild(tdAc);
        tb.appendChild(tr);
      });
    }

    async function salvarVenda() {
      const cliente_id = Number(document.getElementById('venCliente').value) || null;
      const vendedor_id = Number(document.getElementById('venVendedor').value) || null;
      const observacao = document.getElementById('venObs').value.trim() || null;
      const itens = itensVendaTemp
        .filter(x => x.produto_id && Number(x.quantidade) > 0)
        .map(x => ({
          produto_id: Number(x.produto_id),
          quantidade: Number(x.quantidade),
          valor_unitario: Number(x.valor_unitario || 0),
          desconto: Number(x.desconto || 0),
        }));
      if (!itens.length) {
        setMsg('statusVendaModal', 'Adicione ao menos um produto.', false);
        return;
      }
      const valor_frete = parseMoedaBr(document.getElementById('venFrete') && document.getElementById('venFrete').value);
      const condicao_pagamento_id = (function() {
        const el = document.getElementById('venCondicaoPagId');
        if (!el || !el.value) return null;
        const n = Number(el.value);
        return Number.isFinite(n) && n > 0 ? n : null;
      })();
      const prazo_pagamento = document.getElementById('venPrazoPag')
        ? document.getElementById('venPrazoPag').value.trim() || null
        : null;
      const payload = {
        cliente_id,
        vendedor_id,
        observacao,
        valor_frete,
        prazo_pagamento,
        condicao_pagamento_id,
        itens,
      };
      try {
        const isEdicao = venEditVendaId != null;
        const ep = isEdicao ? '/vendas/' + encodeURIComponent(String(venEditVendaId)) : '/vendas';
        const method = isEdicao ? 'PUT' : 'POST';
        await api(ep, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        fecharModalNovoPedido();
        await listarVendasPainel();
        setMsg('statusVendas', isEdicao ? 'Pedido atualizado com sucesso.' : 'Pedido salvo com sucesso.');
      } catch (err) {
        setMsg('statusVendaModal', err.message, false);
      }
    }

    async function listarCondicoesPagamentoPainel() {
      try {
        const itens = await api('/condicoes-pagamento');
        const tbody = document.getElementById('tbCondicoesPagamento');
        if (!tbody) return;
        tbody.innerHTML = '';
        condicoesPagamentoCache.clear();
        condicaoPagSelecionadaId = null;
        itens.forEach(item => {
          condicoesPagamentoCache.set(item.id, item);
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><input type="radio" name="condicaoPagSelect" onchange="selecionarCondicaoPagamento(${item.id})" /></td><td>${item.id}</td><td>${escapeHtml(item.nome)}</td>`;
          tbody.appendChild(tr);
        });
        setMsg('statusCondicoesPagamento', `${itens.length} condicao(oes) de pagamento listada(s).`);
      } catch (err) {
        setMsg('statusCondicoesPagamento', `Falha ao listar: ${err.message}`, false);
      }
    }

    function selecionarCondicaoPagamento(id) {
      condicaoPagSelecionadaId = id;
      const item = condicoesPagamentoCache.get(id);
      setMsg('statusCondicoesPagamento', `Selecionado: ${item ? item.nome : id}`);
    }

    function abrirModalNovaCondicaoPagamento() {
      cadastroBasicoTipo = 'condicao_pag';
      cadastroBasicoEditId = null;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Nova condicao de pagamento';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome';
      document.getElementById('inputModalCadastroBasico').value = '';
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    function abrirModalEdicaoCondicaoPagamento() {
      if (!condicaoPagSelecionadaId) {
        setMsg('statusCondicoesPagamento', 'Selecione uma condicao para editar.', false);
        return;
      }
      const item = condicoesPagamentoCache.get(condicaoPagSelecionadaId);
      if (!item) {
        setMsg('statusCondicoesPagamento', 'Registro selecionado nao encontrado.', false);
        return;
      }
      cadastroBasicoTipo = 'condicao_pag';
      cadastroBasicoEditId = item.id;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Editar condicao de pagamento';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome';
      document.getElementById('inputModalCadastroBasico').value = item.nome || '';
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    async function excluirCondicaoPagamentoSelecionada() {
      if (!condicaoPagSelecionadaId) {
        setMsg('statusCondicoesPagamento', 'Selecione uma condicao para excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const item = condicoesPagamentoCache.get(condicaoPagSelecionadaId);
      const nome = item ? item.nome : `ID ${condicaoPagSelecionadaId}`;
      if (!window.confirm(`Confirma exclusao de "${nome}"?`)) return;
      try {
        await api('/condicoes-pagamento/' + encodeURIComponent(String(condicaoPagSelecionadaId)), { method: 'DELETE' });
        setMsg('statusCondicoesPagamento', 'Condicao excluida com sucesso.');
        condicaoPagSelecionadaId = null;
        await listarCondicoesPagamentoPainel();
      } catch (err) {
        setMsg('statusCondicoesPagamento', err.message, false);
      }
    }

    function abrirAbaCadastro(aba) {
      document.getElementById('abaGeral').classList.add('hidden');
      document.getElementById('abaPessoas').classList.add('hidden');
      document.getElementById('abaProdutos').classList.add('hidden');
      document.getElementById('abaCategoriasProduto').classList.add('hidden');
      var elCondPagPanel = document.getElementById('abaCondPag');
      if (elCondPagPanel) elCondPagPanel.classList.add('hidden');
      document.getElementById('abaGrupoDespesas').classList.add('hidden');
      document.getElementById('abaPlanoContas').classList.add('hidden');
      document.getElementById('abaGrupoContas').classList.add('hidden');
      document.getElementById('abaContasCorrentes').classList.add('hidden');

      document.getElementById('abaBtnGeral').classList.remove('active');
      document.getElementById('abaBtnPessoas').classList.remove('active');
      document.getElementById('abaBtnProdutos').classList.remove('active');
      document.getElementById('abaBtnCatProd').classList.remove('active');
      var elCondPagBtn = document.getElementById('abaBtnCondPag');
      if (elCondPagBtn) elCondPagBtn.classList.remove('active');
      document.getElementById('abaBtnGrupo').classList.remove('active');
      document.getElementById('abaBtnPlano').classList.remove('active');
      document.getElementById('abaBtnGrupoContas').classList.remove('active');
      document.getElementById('abaBtnContas').classList.remove('active');
      var elUsuariosBtn = document.getElementById('abaBtnUsuarios');
      if (elUsuariosBtn) elUsuariosBtn.classList.remove('active');

      if (cardsCadastroAbertos.indexOf(aba) < 0) {
        cardsCadastroAbertos.push(aba);
      }
      cardCadastroAtivo = aba;
      ocultarSeletorCardsCadastro();

      if (aba === 'geral') {
        document.getElementById('abaGeral').classList.remove('hidden');
        document.getElementById('abaBtnGeral').classList.add('active');
        renderCardsAbertosCadastro();
        return;
      }
      if (aba === 'produtos') {
        document.getElementById('abaProdutos').classList.remove('hidden');
        document.getElementById('abaBtnProdutos').classList.add('active');
        renderCardsAbertosCadastro();
        void listarProdutosPainel();
        return;
      }
      if (aba === 'catProd') {
        document.getElementById('abaCategoriasProduto').classList.remove('hidden');
        document.getElementById('abaBtnCatProd').classList.add('active');
        renderCardsAbertosCadastro();
        void listarCategoriasProdutoPainel();
        return;
      }
      if (aba === 'condPag') {
        var pCondPag = document.getElementById('abaCondPag');
        if (pCondPag) pCondPag.classList.remove('hidden');
        var bCondPag = document.getElementById('abaBtnCondPag');
        if (bCondPag) bCondPag.classList.add('active');
        renderCardsAbertosCadastro();
        void listarCondicoesPagamentoPainel();
        return;
      }
      if (aba === 'grupo') {
        document.getElementById('abaGrupoDespesas').classList.remove('hidden');
        document.getElementById('abaBtnGrupo').classList.add('active');
        renderCardsAbertosCadastro();
        listarGruposDespesas();
        return;
      }
      if (aba === 'plano') {
        document.getElementById('abaPlanoContas').classList.remove('hidden');
        document.getElementById('abaBtnPlano').classList.add('active');
        renderCardsAbertosCadastro();
        listarPlanosContas();
        return;
      }
      if (aba === 'grupoContas') {
        document.getElementById('abaGrupoContas').classList.remove('hidden');
        document.getElementById('abaBtnGrupoContas').classList.add('active');
        renderCardsAbertosCadastro();
        listarGruposContas();
        listarSubgruposContas();
        return;
      }
      if (aba === 'contas') {
        document.getElementById('abaContasCorrentes').classList.remove('hidden');
        document.getElementById('abaBtnContas').classList.add('active');
        renderCardsAbertosCadastro();
        listarContasCorrentes();
        listarPendenciasConciliacao();
        return;
      }
      if (aba === 'usuarios') {
        var pUsuarios = document.getElementById('abaUsuarios');
        if (pUsuarios) pUsuarios.classList.remove('hidden');
        var bUsuarios = document.getElementById('abaBtnUsuarios');
        if (bUsuarios) bUsuarios.classList.add('active');
        renderCardsAbertosCadastro();
        void listarUsuariosSistema();
        return;
      }
      document.getElementById('abaPessoas').classList.remove('hidden');
      document.getElementById('abaBtnPessoas').classList.add('active');
      renderCardsAbertosCadastro();
    }

    function abrirModalNovoGrupoDespesa() {
      cadastroBasicoTipo = 'grupo';
      cadastroBasicoEditId = null;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Novo Grupo de Despesas';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome do Grupo';
      document.getElementById('inputModalCadastroBasico').value = '';
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    function abrirModalEdicaoGrupoDespesa() {
      if (!grupoDespesaSelecionadoId) {
        setMsg('statusGrupoDespesa', 'Selecione um grupo para editar.', false);
        return;
      }
      const item = gruposDespesasCache.get(grupoDespesaSelecionadoId);
      if (!item) {
        setMsg('statusGrupoDespesa', 'Grupo selecionado nao encontrado.', false);
        return;
      }
      cadastroBasicoTipo = 'grupo';
      cadastroBasicoEditId = item.id;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Editar Grupo de Despesas';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome do Grupo';
      document.getElementById('inputModalCadastroBasico').value = item.nome || '';
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    function selecionarGrupoDespesa(id) {
      grupoDespesaSelecionadoId = id;
      const item = gruposDespesasCache.get(id);
      setMsg('statusGrupoDespesa', `Grupo selecionado: ${item ? item.nome : id}`);
    }

    async function listarGruposDespesas() {
      try {
        const itens = await api('/grupos-despesas');
        const tbody = document.getElementById('tbGrupoDespesas');
        tbody.innerHTML = '';
        gruposDespesasCache.clear();
        grupoDespesaSelecionadoId = null;
        itens.forEach(item => {
          gruposDespesasCache.set(item.id, item);
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><input type="radio" name="grupoDespesaSelect" onchange="selecionarGrupoDespesa(${item.id})" /></td><td>${item.id}</td><td>${item.nome}</td>`;
          tbody.appendChild(tr);
        });
      } catch (err) {
        setMsg('statusGrupoDespesa', `Falha ao listar grupos: ${err.message}`, false);
      }
    }

    async function excluirGrupoDespesa() {
      if (!grupoDespesaSelecionadoId) {
        setMsg('statusGrupoDespesa', 'Selecione um grupo para excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const confirmou = window.confirm('Confirma exclusao do grupo de despesa selecionado?');
      if (!confirmou) return;
      try {
        await api(`/grupos-despesas/${grupoDespesaSelecionadoId}`, { method: 'DELETE' });
        setMsg('statusGrupoDespesa', 'Grupo excluido com sucesso.');
        grupoDespesaSelecionadoId = null;
        await listarGruposDespesas();
      } catch (err) {
        setMsg('statusGrupoDespesa', err.message, false);
      }
    }

    function abrirModalNovoPlanoConta() {
      cadastroBasicoTipo = 'plano';
      cadastroBasicoEditId = null;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Novo Plano de Contas';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome do Plano';
      document.getElementById('inputModalCadastroBasico').value = '';
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    function abrirModalEdicaoPlanoConta() {
      if (!planoContaSelecionadoId) {
        setMsg('statusPlanoConta', 'Selecione um plano para editar.', false);
        return;
      }
      const item = planosContasCache.get(planoContaSelecionadoId);
      if (!item) {
        setMsg('statusPlanoConta', 'Plano selecionado nao encontrado.', false);
        return;
      }
      cadastroBasicoTipo = 'plano';
      cadastroBasicoEditId = item.id;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Editar Plano de Contas';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome do Plano';
      document.getElementById('inputModalCadastroBasico').value = item.nome || '';
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    function selecionarPlanoConta(id) {
      planoContaSelecionadoId = id;
      const item = planosContasCache.get(id);
      setMsg('statusPlanoConta', `Plano selecionado: ${item ? item.nome : id}`);
    }

    async function listarPlanosContas() {
      try {
        const itens = await api('/planos-contas');
        const tbody = document.getElementById('tbPlanosContas');
        tbody.innerHTML = '';
        planosContasCache.clear();
        planoContaSelecionadoId = null;
        itens.forEach(item => {
          planosContasCache.set(item.id, item);
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><input type="radio" name="planoContaSelect" onchange="selecionarPlanoConta(${item.id})" /></td><td>${item.id}</td><td>${item.nome}</td>`;
          tbody.appendChild(tr);
        });
      } catch (err) {
        setMsg('statusPlanoConta', `Falha ao listar planos: ${err.message}`, false);
      }
    }

    async function excluirPlanoConta() {
      if (!planoContaSelecionadoId) {
        setMsg('statusPlanoConta', 'Selecione um plano para excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const confirmou = window.confirm('Confirma exclusao do plano de conta selecionado?');
      if (!confirmou) return;
      try {
        await api(`/planos-contas/${planoContaSelecionadoId}`, { method: 'DELETE' });
        setMsg('statusPlanoConta', 'Plano excluido com sucesso.');
        planoContaSelecionadoId = null;
        await listarPlanosContas();
      } catch (err) {
        setMsg('statusPlanoConta', err.message, false);
      }
    }

    async function carregarOpcoesGrupoContaModal(selecionadoId = null) {
      const select = document.getElementById('inputModalCadastroBasicoGrupoConta');
      const lista = gruposContasCache.size ? Array.from(gruposContasCache.values()) : await api('/grupos-contas');
      if (!gruposContasCache.size) {
        lista.forEach(item => gruposContasCache.set(item.id, item));
      }
      select.innerHTML = '';
      lista.forEach(item => {
        const opt = document.createElement('option');
        opt.value = String(item.id);
        opt.textContent = item.nome;
        select.appendChild(opt);
      });
      if (selecionadoId) {
        select.value = String(selecionadoId);
      } else if (grupoContaSelecionadoId) {
        select.value = String(grupoContaSelecionadoId);
      }
    }

    function selecionarGrupoConta(id) {
      grupoContaSelecionadoId = id;
      const item = gruposContasCache.get(id);
      setMsg('statusGrupoConta', `Grupo selecionado: ${item ? item.nome : id}`);
      const info = document.getElementById('grupoContaSelecionadoInfo');
      if (info) info.textContent = item ? `Grupo selecionado: ${item.nome}` : 'Selecione um grupo para listar os subgrupos.';
      listarSubgruposContas();
    }

    async function listarGruposContas() {
      try {
        const itens = await api('/grupos-contas');
        const tbody = document.getElementById('tbGruposContas');
        tbody.innerHTML = '';
        gruposContasCache.clear();
        grupoContaSelecionadoId = null;
        itens.forEach(item => {
          gruposContasCache.set(item.id, item);
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><input type="radio" name="grupoContaSelect" onchange="selecionarGrupoConta(${item.id})" /></td><td>${item.id}</td><td>${item.nome}</td>`;
          tbody.appendChild(tr);
        });
        const info = document.getElementById('grupoContaSelecionadoInfo');
        if (info) info.textContent = 'Selecione um grupo para listar os subgrupos.';
      } catch (err) {
        setMsg('statusGrupoConta', `Falha ao listar grupos de contas: ${err.message}`, false);
      }
    }

    function abrirModalNovoGrupoConta() {
      cadastroBasicoTipo = 'grupo_conta';
      cadastroBasicoEditId = null;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Novo Grupo de Contas';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome do Grupo';
      document.getElementById('inputModalCadastroBasico').value = '';
      document.getElementById('cadastroBasicoGrupoContainer').classList.add('hidden');
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    function abrirModalEdicaoGrupoConta() {
      if (!grupoContaSelecionadoId) {
        setMsg('statusGrupoConta', 'Selecione um grupo de contas para editar.', false);
        return;
      }
      const item = gruposContasCache.get(grupoContaSelecionadoId);
      if (!item) {
        setMsg('statusGrupoConta', 'Grupo de contas selecionado nao encontrado.', false);
        return;
      }
      cadastroBasicoTipo = 'grupo_conta';
      cadastroBasicoEditId = item.id;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Editar Grupo de Contas';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome do Grupo';
      document.getElementById('inputModalCadastroBasico').value = item.nome || '';
      document.getElementById('cadastroBasicoGrupoContainer').classList.add('hidden');
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    async function excluirGrupoConta() {
      if (!grupoContaSelecionadoId) {
        setMsg('statusGrupoConta', 'Selecione um grupo de contas para excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const confirmou = window.confirm('Confirma exclusao do grupo de contas selecionado?');
      if (!confirmou) return;
      try {
        await api(`/grupos-contas/${grupoContaSelecionadoId}`, { method: 'DELETE' });
        setMsg('statusGrupoConta', 'Grupo de contas excluido com sucesso.');
        await listarGruposContas();
        await listarSubgruposContas();
      } catch (err) {
        setMsg('statusGrupoConta', err.message, false);
      }
    }

    function selecionarSubgrupoConta(id) {
      subgrupoContaSelecionadoId = id;
      const item = subgruposContasCache.get(id);
      setMsg('statusSubgrupoConta', `Subgrupo selecionado: ${item ? item.nome : id}`);
    }

    async function listarSubgruposContas() {
      try {
        const tbody = document.getElementById('tbSubgruposContas');
        tbody.innerHTML = '';
        subgruposContasCache.clear();
        subgrupoContaSelecionadoId = null;
        if (!grupoContaSelecionadoId) return;

        const itens = await api(`/subgrupos-contas?grupo_conta_id=${grupoContaSelecionadoId}`);
        itens.forEach(item => {
          subgruposContasCache.set(item.id, item);
          const grupoNome = (gruposContasCache.get(item.grupo_conta_id) || {}).nome || item.grupo_conta_id;
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><input type="radio" name="subgrupoContaSelect" onchange="selecionarSubgrupoConta(${item.id})" /></td><td>${item.id}</td><td>${grupoNome}</td><td>${item.nome}</td>`;
          tbody.appendChild(tr);
        });
      } catch (err) {
        setMsg('statusSubgrupoConta', `Falha ao listar subgrupos: ${err.message}`, false);
      }
    }

    async function abrirModalNovoSubgrupoConta() {
      if (!gruposContasCache.size) {
        await listarGruposContas();
      }
      if (!gruposContasCache.size) {
        setMsg('statusSubgrupoConta', 'Cadastre um grupo de contas antes de criar subgrupo.', false);
        return;
      }
      cadastroBasicoTipo = 'subgrupo_conta';
      cadastroBasicoEditId = null;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Novo Subgrupo de Contas';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome do Subgrupo';
      document.getElementById('inputModalCadastroBasico').value = '';
      document.getElementById('cadastroBasicoGrupoContainer').classList.remove('hidden');
      await carregarOpcoesGrupoContaModal();
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    async function abrirModalEdicaoSubgrupoConta() {
      if (!subgrupoContaSelecionadoId) {
        setMsg('statusSubgrupoConta', 'Selecione um subgrupo para editar.', false);
        return;
      }
      const item = subgruposContasCache.get(subgrupoContaSelecionadoId);
      if (!item) {
        setMsg('statusSubgrupoConta', 'Subgrupo selecionado nao encontrado.', false);
        return;
      }
      cadastroBasicoTipo = 'subgrupo_conta';
      cadastroBasicoEditId = item.id;
      document.getElementById('tituloModalCadastroBasico').textContent = 'Editar Subgrupo de Contas';
      document.getElementById('rotuloModalCadastroBasico').textContent = 'Nome do Subgrupo';
      document.getElementById('inputModalCadastroBasico').value = item.nome || '';
      document.getElementById('cadastroBasicoGrupoContainer').classList.remove('hidden');
      await carregarOpcoesGrupoContaModal(item.grupo_conta_id);
      setMsg('statusModalCadastroBasico', '');
      document.getElementById('modalCadastroBasico').classList.remove('hidden');
    }

    async function excluirSubgrupoConta() {
      if (!subgrupoContaSelecionadoId) {
        setMsg('statusSubgrupoConta', 'Selecione um subgrupo para excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const confirmou = window.confirm('Confirma exclusao do subgrupo selecionado?');
      if (!confirmou) return;
      try {
        await api(`/subgrupos-contas/${subgrupoContaSelecionadoId}`, { method: 'DELETE' });
        setMsg('statusSubgrupoConta', 'Subgrupo excluido com sucesso.');
        await listarSubgruposContas();
      } catch (err) {
        setMsg('statusSubgrupoConta', err.message, false);
      }
    }

    function selecionarContaCorrente(id) {
      contaCorrenteSelecionadaId = id;
      const item = contasCorrentesCache.get(id);
      setMsg('statusContasCorrentes', `Conta selecionada: ${item ? `${item.banco} / ${item.numero}` : id}`);
    }

    async function listarContasCorrentes() {
      try {
        const itens = await api('/contas-correntes');
        const tbody = document.getElementById('tbContasCorrentes');
        const totalEl = document.getElementById('totalContasCorrentes');
        tbody.innerHTML = '';
        contasCorrentesCache.clear();
        contaCorrenteSelecionadaId = null;
        let total = 0;
        itens.forEach(item => {
          contasCorrentesCache.set(item.id, item);
          const saldo = Number(item.saldo_atual || 0);
          total += saldo;
          const saldoClass = saldo < 0 ? 'cc-saldo-negativo' : '';
          const tr = document.createElement('tr');
          tr.innerHTML =
            `<td><input type="radio" name="contaCorrenteSelect" onchange="selecionarContaCorrente(${item.id})" /></td>` +
            `<td>${item.id}</td>` +
            `<td>${item.banco || ''}</td>` +
            `<td>${item.agencia || ''}</td>` +
            `<td>${item.numero || ''}</td>` +
            `<td>${item.nome_conta || ''}</td>` +
            `<td class="${saldoClass}">${moeda(saldo)}</td>`;
          tbody.appendChild(tr);
        });
        if (totalEl) {
          const valorFormatado = Math.abs(Number(total || 0)).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
          const valorClass = total < 0 ? 'cc-total-valor-negativo' : 'cc-total-valor-positivo';
          const sinal = total < 0 ? '-' : '';
          totalEl.innerHTML = `<span class="cc-total-label">Total: R$ </span><span class="${valorClass}">${sinal}${valorFormatado}</span>`;
        }
      } catch (err) {
        setMsg('statusContasCorrentes', `Falha ao listar contas correntes: ${err.message}`, false);
        const totalEl = document.getElementById('totalContasCorrentes');
        if (totalEl) {
          totalEl.innerHTML = '<span class="cc-total-label">Total: R$ </span><span class="cc-total-valor-positivo">0,00</span>';
        }
      }
    }

    function toggleSelecaoPendenciaConciliacao(id, checked) {
      if (checked) pendenciasConciliacaoSelecionadas.add(id);
      else pendenciasConciliacaoSelecionadas.delete(id);
      const qtd = pendenciasConciliacaoSelecionadas.size;
      if (qtd) {
        setMsg('statusPendenciasConciliacao', `${qtd} lancamento(s) pendente(s) selecionado(s).`);
      } else {
        setMsg('statusPendenciasConciliacao', 'Selecione os lancamentos para conciliar.');
      }
    }

    async function listarPendenciasConciliacao() {
      try {
        const itens = await api('/contas-correntes/lancamentos-pendentes');
        const tbody = document.getElementById('tbPendenciasConciliacao');
        tbody.innerHTML = '';
        pendenciasConciliacaoSelecionadas.clear();
        if (!itens.length) {
          setMsg('statusPendenciasConciliacao', 'Nenhum lancamento pendente.');
          return;
        }
        itens.forEach(item => {
          const tr = document.createElement('tr');
          const data = item.data_movimento ? String(item.data_movimento).slice(0, 10) : '';
          const tipo = item.tipo === 'debito' ? 'Debito' : 'Credito';
          const valorClass = item.tipo === 'debito' ? 'cc-saldo-negativo' : '';
          tr.innerHTML =
            `<td><input type="checkbox" onchange="toggleSelecaoPendenciaConciliacao(${item.id}, this.checked)" /></td>` +
            `<td>${data}</td>` +
            `<td>${item.conta_nome || item.conta_id}</td>` +
            `<td>${tipo}</td>` +
            `<td>${item.descricao || ''}</td>` +
            `<td class="${valorClass}">${moeda(item.valor)}</td>`;
          tbody.appendChild(tr);
        });
        setMsg('statusPendenciasConciliacao', 'Selecione os lancamentos para conciliar.');
      } catch (err) {
        setMsg('statusPendenciasConciliacao', `Falha ao carregar pendencias: ${err.message}`, false);
      }
    }

    async function autorizarConciliacaoSelecionada() {
      if (!pendenciasConciliacaoSelecionadas.size) {
        setMsg('statusPendenciasConciliacao', 'Selecione ao menos um lancamento pendente.', false);
        return;
      }
      const qtd = pendenciasConciliacaoSelecionadas.size;
      const confirmou = window.confirm(`Autorizar conciliacao de ${qtd} lancamento(s)?`);
      if (!confirmou) return;
      try {
        const resposta = await api('/contas-correntes/lancamentos-pendentes/conciliar', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: Array.from(pendenciasConciliacaoSelecionadas) })
        });
        pendenciasConciliacaoSelecionadas.clear();
        setMsg('statusPendenciasConciliacao', `${resposta.conciliados || 0} lancamento(s) conciliado(s) com sucesso.`);
        await listarPendenciasConciliacao();
        await listarContasCorrentes();
      } catch (err) {
        setMsg('statusPendenciasConciliacao', `Falha ao conciliar: ${err.message}`, false);
      }
    }

    function abrirModalNovaContaCorrente() {
      contaCorrenteSelecionadaId = null;
      document.getElementById('tituloModalContaCorrente').textContent = 'Nova Conta Corrente';
      document.getElementById('ccBanco').value = '';
      document.getElementById('ccAgencia').value = '';
      document.getElementById('ccNumero').value = '';
      document.getElementById('ccNomeConta').value = '';
      document.getElementById('ccSaldo').value = '0';
      setMsg('statusModalContaCorrente', '');
      document.getElementById('modalContaCorrente').classList.remove('hidden');
      document.getElementById('ccBanco').focus();
    }

    function abrirModalEdicaoContaCorrente() {
      if (!contaCorrenteSelecionadaId) {
        setMsg('statusContasCorrentes', 'Selecione uma conta corrente para editar.', false);
        return;
      }
      const item = contasCorrentesCache.get(contaCorrenteSelecionadaId);
      if (!item) {
        setMsg('statusContasCorrentes', 'Conta corrente selecionada nao encontrada.', false);
        return;
      }
      document.getElementById('tituloModalContaCorrente').textContent = 'Editar Conta Corrente';
      document.getElementById('ccBanco').value = item.banco || '';
      document.getElementById('ccAgencia').value = item.agencia || '';
      document.getElementById('ccNumero').value = item.numero || '';
      document.getElementById('ccNomeConta').value = item.nome_conta || '';
      document.getElementById('ccSaldo').value = Number(item.saldo_atual || 0);
      setMsg('statusModalContaCorrente', '');
      document.getElementById('modalContaCorrente').classList.remove('hidden');
      document.getElementById('ccBanco').focus();
    }

    function fecharModalContaCorrente() {
      document.getElementById('modalContaCorrente').classList.add('hidden');
      setMsg('statusModalContaCorrente', '');
    }

    async function abrirModalTransferenciaContas() {
      try {
        const contas = await api('/contas-correntes');
        if (!contas.length) {
          setMsg('statusContasCorrentes', 'Cadastre contas correntes antes de transferir.', false);
          return;
        }
        if (contas.length < 2) {
          setMsg('statusContasCorrentes', 'Necessario ao menos duas contas para transferencia.', false);
          return;
        }

        const origem = document.getElementById('transfContaOrigem');
        const destino = document.getElementById('transfContaDestino');
        origem.innerHTML = '';
        destino.innerHTML = '';

        contas.forEach(item => {
          const nomeConta = (item.nome_conta || '').trim();
          const texto = nomeConta
            ? `${item.id} - ${nomeConta}`
            : `${item.id} - ${item.banco} / ${item.numero}`;
          const optOrigem = document.createElement('option');
          optOrigem.value = String(item.id);
          optOrigem.textContent = texto;
          origem.appendChild(optOrigem);

          const optDestino = document.createElement('option');
          optDestino.value = String(item.id);
          optDestino.textContent = texto;
          destino.appendChild(optDestino);
        });

        if (contaCorrenteSelecionadaId && contas.some(x => x.id === contaCorrenteSelecionadaId)) {
          origem.value = String(contaCorrenteSelecionadaId);
          const contaAlternativa = contas.find(x => x.id !== contaCorrenteSelecionadaId);
          if (contaAlternativa) destino.value = String(contaAlternativa.id);
        } else {
          origem.value = String(contas[0].id);
          destino.value = String(contas[1].id);
        }

        document.getElementById('transfValor').value = '';
        document.getElementById('transfMotivo').value = '';
        setMsg('statusModalTransferenciaContas', '');
        document.getElementById('modalTransferenciaContas').classList.remove('hidden');
      } catch (err) {
        setMsg('statusContasCorrentes', `Falha ao preparar transferencia: ${err.message}`, false);
      }
    }

    function fecharModalTransferenciaContas() {
      document.getElementById('modalTransferenciaContas').classList.add('hidden');
      setMsg('statusModalTransferenciaContas', '');
    }

    async function confirmarTransferenciaContas() {
      const contaOrigemId = Number(document.getElementById('transfContaOrigem').value) || 0;
      const contaDestinoId = Number(document.getElementById('transfContaDestino').value) || 0;
      const valor = Number(document.getElementById('transfValor').value || 0);
      const motivo = document.getElementById('transfMotivo').value.trim();

      if (!contaOrigemId || !contaDestinoId) {
        setMsg('statusModalTransferenciaContas', 'Selecione origem e destino.', false);
        return;
      }
      if (contaOrigemId === contaDestinoId) {
        setMsg('statusModalTransferenciaContas', 'Origem e destino devem ser diferentes.', false);
        return;
      }
      if (!valor || Number.isNaN(valor) || valor <= 0) {
        setMsg('statusModalTransferenciaContas', 'Informe um valor valido maior que zero.', false);
        return;
      }
      if (!motivo) {
        setMsg('statusModalTransferenciaContas', 'Informe o motivo da transferencia.', false);
        return;
      }

      try {
        await api('/contas-correntes/transferencias', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conta_origem_id: contaOrigemId,
            conta_destino_id: contaDestinoId,
            valor,
            motivo
          })
        });
        fecharModalTransferenciaContas();
        setMsg('statusContasCorrentes', 'Transferencia realizada com sucesso.');
        await listarContasCorrentes();
      } catch (err) {
        setMsg('statusModalTransferenciaContas', err.message, false);
      }
    }

    async function salvarContaCorrenteModal() {
      const banco = document.getElementById('ccBanco').value.trim();
      const agencia = document.getElementById('ccAgencia').value.trim();
      const numero = document.getElementById('ccNumero').value.trim();
      const nomeConta = document.getElementById('ccNomeConta').value.trim();
      const saldoInformado = document.getElementById('ccSaldo').value;
      const saldo = saldoInformado === '' ? 0 : Number(saldoInformado);

      if (!banco || !agencia || !numero) {
        setMsg('statusModalContaCorrente', 'Preencha banco, agencia e conta corrente.', false);
        return;
      }
      if (Number.isNaN(saldo)) {
        setMsg('statusModalContaCorrente', 'Saldo invalido.', false);
        return;
      }

      const payload = {
        banco,
        agencia,
        numero,
        nome_conta: nomeConta,
        saldo_atual: saldo,
        ativa: true
      };
      const endpoint = contaCorrenteSelecionadaId ? `/contas-correntes/${contaCorrenteSelecionadaId}` : '/contas-correntes';
      const method = contaCorrenteSelecionadaId ? 'PUT' : 'POST';

      try {
        await api(endpoint, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        fecharModalContaCorrente();
        setMsg('statusContasCorrentes', contaCorrenteSelecionadaId ? 'Conta corrente atualizada com sucesso.' : 'Conta corrente cadastrada com sucesso.');
        await listarContasCorrentes();
      } catch (err) {
        setMsg('statusModalContaCorrente', err.message, false);
      }
    }

    async function excluirContaCorrenteSelecionada() {
      if (!contaCorrenteSelecionadaId) {
        setMsg('statusContasCorrentes', 'Selecione uma conta corrente para excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const confirmou = window.confirm('Confirma exclusao da conta corrente selecionada?');
      if (!confirmou) return;
      try {
        await api(`/contas-correntes/${contaCorrenteSelecionadaId}`, { method: 'DELETE' });
        setMsg('statusContasCorrentes', 'Conta corrente excluida com sucesso.');
        contaCorrenteSelecionadaId = null;
        await listarContasCorrentes();
      } catch (err) {
        setMsg('statusContasCorrentes', `Falha ao excluir conta corrente: ${err.message}`, false);
      }
    }

    async function salvarModalCadastroBasico() {
      const nome = document.getElementById('inputModalCadastroBasico').value.trim();
      if (!nome) {
        setMsg('statusModalCadastroBasico', 'Informe um nome.', false);
        return;
      }
      const tipo = cadastroBasicoTipo;
      if (!tipo) {
        setMsg('statusModalCadastroBasico', 'Tipo de cadastro nao definido.', false);
        return;
      }
      let endpointBase = '/planos-contas';
      if (tipo === 'grupo') endpointBase = '/grupos-despesas';
      if (tipo === 'grupo_conta') endpointBase = '/grupos-contas';
      if (tipo === 'subgrupo_conta') endpointBase = '/subgrupos-contas';
      if (tipo === 'condicao_pag') endpointBase = '/condicoes-pagamento';
      const endpoint = cadastroBasicoEditId ? `${endpointBase}/${cadastroBasicoEditId}` : endpointBase;
      const method = cadastroBasicoEditId ? 'PUT' : 'POST';
      const payload = { nome };
      if (tipo === 'subgrupo_conta') {
        const grupoContaId = Number(document.getElementById('inputModalCadastroBasicoGrupoConta').value) || 0;
        if (!grupoContaId) {
          setMsg('statusModalCadastroBasico', 'Selecione o grupo de contas.', false);
          return;
        }
        payload.grupo_conta_id = grupoContaId;
      }

      try {
        await api(endpoint, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        fecharModalCadastroBasico();
        if (tipo === 'grupo') {
          setMsg('statusGrupoDespesa', cadastroBasicoEditId ? 'Grupo atualizado com sucesso.' : 'Grupo cadastrado com sucesso.');
          await listarGruposDespesas();
        } else if (tipo === 'plano') {
          setMsg('statusPlanoConta', cadastroBasicoEditId ? 'Plano atualizado com sucesso.' : 'Plano cadastrado com sucesso.');
          await listarPlanosContas();
        } else if (tipo === 'grupo_conta') {
          setMsg('statusGrupoConta', cadastroBasicoEditId ? 'Grupo de contas atualizado com sucesso.' : 'Grupo de contas cadastrado com sucesso.');
          await listarGruposContas();
          await listarSubgruposContas();
        } else if (tipo === 'subgrupo_conta') {
          setMsg('statusSubgrupoConta', cadastroBasicoEditId ? 'Subgrupo atualizado com sucesso.' : 'Subgrupo cadastrado com sucesso.');
          await listarSubgruposContas();
        } else if (tipo === 'condicao_pag') {
          setMsg('statusCondicoesPagamento', cadastroBasicoEditId ? 'Condicao atualizada com sucesso.' : 'Condicao cadastrada com sucesso.');
          await listarCondicoesPagamentoPainel();
        }
      } catch (err) {
        setMsg('statusModalCadastroBasico', err.message, false);
      }
    }

    function fecharModalCadastroBasico() {
      document.getElementById('modalCadastroBasico').classList.add('hidden');
      document.getElementById('inputModalCadastroBasico').value = '';
      document.getElementById('cadastroBasicoGrupoContainer').classList.add('hidden');
      cadastroBasicoTipo = null;
      cadastroBasicoEditId = null;
      setMsg('statusModalCadastroBasico', '');
    }

    function fazerBackup() {
      window.location.href = '/api/sistema/backup';
      const status = document.getElementById('statusGeral');
      if (status) status.textContent = 'Gerando download de backup...';
    }

    async function excluirHistoricosLiquidados() {
      if (!(await validarPermissaoExclusao())) return;
      const status = document.getElementById('statusGeral');
      const msg =
        'Confirma EXCLUSAO PERMANENTE de:\\n' +
        '- todas as contas a pagar ja pagas;\\n' +
        '- todas as contas a receber ja recebidas;\\n' +
        '- todas as faturas de cartao ja pagas;\\n' +
        '- movimentacoes bancarias ligadas a esses registros (saldo conciliado sera revertido).\\n\\n' +
        'Contas em aberto e pendentes nao serao removidas.';
      if (!window.confirm(msg)) return;
      if (!window.confirm('Ultima confirmacao: os dados serao apagados sem recuperacao (exceto se tiver backup). Continuar?')) return;
      try {
        if (status) status.textContent = 'Excluindo historicos liquidados...';
        const r = await api('/sistema/excluir-historicos-liquidados', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirmar: true }),
        });
        const resumo = [
          `Pagas: ${r.contas_pagar_excluidas}`,
          `Recebidas: ${r.contas_receber_excluidas}`,
          `Faturas: ${r.faturas_cartao_excluidas}`,
          `Mov.: ${r.movimentacoes_excluidas}`,
        ].join(' | ');
        if (status) status.textContent = `Historicos removidos. ${resumo}`;
        await carregarTudo();
      } catch (err) {
        if (status) status.textContent = `Erro: ${err.message}`;
      }
    }

    async function restaurarBackup(input) {
      const file = input.files && input.files[0];
      if (!file) return;
      const status = document.getElementById('statusGeral');
      const confirmou = window.confirm(`Confirma restaurar backup do arquivo ${file.name}? Isso substituirá os dados atuais.`);
      if (!confirmou) {
        input.value = '';
        return;
      }
      try {
        if (status) status.textContent = 'Restaurando backup...';
        const formData = new FormData();
        formData.append('arquivo', file);
        const res = await fetch('/api/sistema/restaurar', { method: 'POST', body: formData });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || 'Falha ao restaurar backup.');
        if (status) status.textContent = 'Backup restaurado com sucesso. Recarregando dados...';
        await carregarTudo();
        await listarCadastros();
        await carregarEmpresaPadrao();
      } catch (err) {
        if (status) status.textContent = `Erro: ${err.message}`;
      } finally {
        input.value = '';
      }
    }

    async function abrirModalNfeConfig() {
      try {
        const cfg = await api('/sistema/nfe/config');
        document.getElementById('nfeCfgEnabled').value = String(!!cfg.enabled);
        document.getElementById('nfeCfgAmbiente').value = cfg.ambiente || 'homologacao';
        document.getElementById('nfeCfgUf').value = (cfg.uf || 'PR').toUpperCase();
        document.getElementById('nfeCfgCnpj').value = cfg.cnpj_emitente || '';
        document.getElementById('nfeCfgIe').value = cfg.ie_emitente || '';
        document.getElementById('nfeCfgCrt').value = cfg.crt || 'simples';
        document.getElementById('nfeCfgSerie').value = String(cfg.serie || 1);
        document.getElementById('nfeCfgCfop').value = cfg.cfop_padrao || '';
        document.getElementById('nfeCfgCsosn').value = cfg.csosn_padrao || '';
        document.getElementById('nfeCfgIdCsrt').value = cfg.id_csrt || '';
        document.getElementById('nfeCfgCsrt').value = cfg.csrt || '';
        document.getElementById('nfeCfgCnpjRespTec').value = cfg.cnpj_responsavel_tecnico || '';
        document.getElementById('nfeCfgCnaePrincipal').value = cfg.cnae_principal || '';
        document.getElementById('nfeCfgCnaesSecundarios').value = cfg.cnaes_secundarios || '';
        document.getElementById('nfeCfgCertPath').value = cfg.cert_path || '';
        document.getElementById('nfeCfgSenha').value = cfg.cert_password || '';
        setMsg('statusModalNfeConfig', '');
        document.getElementById('modalNfeConfig').classList.remove('hidden');
        await atualizarPainelStatusNfe();
      } catch (err) {
        setMsg('statusGeral', `Falha ao abrir configuracao NF-e: ${err.message}`, false);
      }
    }

    function fecharModalNfeConfig() {
      document.getElementById('modalNfeConfig').classList.add('hidden');
    }

    async function salvarNfeConfig() {
      const payload = {
        enabled: document.getElementById('nfeCfgEnabled').value === 'true',
        ambiente: (document.getElementById('nfeCfgAmbiente').value || 'homologacao').trim().toLowerCase(),
        uf: (document.getElementById('nfeCfgUf').value || 'PR').trim().toUpperCase(),
        cert_path: document.getElementById('nfeCfgCertPath').value.trim(),
        cert_password: document.getElementById('nfeCfgSenha').value,
        cnpj_emitente: document.getElementById('nfeCfgCnpj').value.trim(),
        ie_emitente: document.getElementById('nfeCfgIe').value.trim(),
        crt: (document.getElementById('nfeCfgCrt').value || 'simples').trim().toLowerCase(),
        serie: Number(document.getElementById('nfeCfgSerie').value) || 1,
        cfop_padrao: document.getElementById('nfeCfgCfop').value.trim(),
        csosn_padrao: document.getElementById('nfeCfgCsosn').value.trim(),
        id_csrt: document.getElementById('nfeCfgIdCsrt').value.trim(),
        csrt: document.getElementById('nfeCfgCsrt').value.trim(),
        cnpj_responsavel_tecnico: document.getElementById('nfeCfgCnpjRespTec').value.trim(),
        cnae_principal: document.getElementById('nfeCfgCnaePrincipal').value.trim(),
        cnaes_secundarios: document.getElementById('nfeCfgCnaesSecundarios').value.trim(),
      };
      try {
        await api('/sistema/nfe/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        setMsg('statusModalNfeConfig', 'Configuracao salva com sucesso.');
        await atualizarPainelStatusNfe();
      } catch (err) {
        setMsg('statusModalNfeConfig', err.message, false);
      }
    }

    async function uploadNfeCertificado(input) {
      const file = input.files && input.files[0];
      if (!file) return;
      try {
        setMsg('statusModalNfeConfig', 'Enviando certificado...');
        const formData = new FormData();
        formData.append('arquivo', file);
        const res = await fetch('/api/sistema/nfe/certificado', { method: 'POST', body: formData });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || 'Falha ao enviar certificado.');
        document.getElementById('nfeCfgCertPath').value = body.cert_path || '';
        setMsg('statusModalNfeConfig', 'Certificado enviado com sucesso. Salve a configuracao para finalizar.');
        await atualizarPainelStatusNfe();
      } catch (err) {
        setMsg('statusModalNfeConfig', err.message, false);
      } finally {
        input.value = '';
      }
    }

    async function testarStatusNfeConfig() {
      try {
        const st = await atualizarPainelStatusNfe();
        if (st.pronto) {
          if (st.autorizacao_implantada) {
            setMsg('statusModalNfeConfig', 'NF-e pronta para autorizacao no ambiente selecionado.');
          } else {
            setMsg('statusModalNfeConfig', 'NF-e pronta para gerar XML assinado. Autorizacao SEFAZ ainda em implantacao.');
          }
        } else {
          const faltas = Array.isArray(st.faltando) && st.faltando.length ? st.faltando.join(' | ') : 'Ajustes pendentes.';
          setMsg('statusModalNfeConfig', `Pendencias: ${faltas}`, false);
        }
      } catch (err) {
        setMsg('statusModalNfeConfig', err.message, false);
      }
    }

    function formatarDataIsoParaBr(iso) {
      const txt = String(iso || '').trim();
      if (!txt) return '-';
      const d = new Date(txt);
      if (Number.isNaN(d.getTime())) return txt;
      const dd = String(d.getDate()).padStart(2, '0');
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const yyyy = d.getFullYear();
      return `${dd}/${mm}/${yyyy}`;
    }

    async function atualizarPainelStatusNfe() {
      const st = await api('/sistema/nfe/status');
      const badge = document.getElementById('nfeStatusBadge');
      const arq = document.getElementById('nfeStatusArquivo');
      const val = document.getElementById('nfeStatusValidade');
      if (badge) {
        badge.textContent = st.pronto ? 'PRONTO' : 'PENDENTE';
        badge.style.background = st.pronto ? '#dcfce7' : '#fee2e2';
        badge.style.color = st.pronto ? '#166534' : '#991b1b';
      }
      const cert = st.certificado || {};
      if (arq) arq.textContent = `Arquivo: ${cert.arquivo || '-'}`;
      if (val) {
        const ini = formatarDataIsoParaBr(cert.validade_inicio);
        const fim = formatarDataIsoParaBr(cert.validade_fim);
        val.textContent = `Validade: ${ini} até ${fim}`;
      }
      return st;
    }

    async function carregarEmpresaPadrao() {
      const box = document.getElementById('dadosEmpresaPadrao');
      if (!box) return;
      try {
        const itens = await api('/cadastros-gerais?contexto=geral');
        if (!itens.length) {
          box.textContent = 'Empresa padrao nao cadastrada.';
          return;
        }
        const e = itens[0];
        box.textContent = `Empresa padrao: ${e.razao_social} (${e.nome_fantasia || '-'}) - CNPJ ${e.cnpj}`;
      } catch (err) {
        box.textContent = `Falha ao carregar empresa padrao: ${err.message}`;
      }
    }

    async function listarCadastros() {
      try {
        document.getElementById('cadBusca').value = '';
        const cadastros = await api('/cadastros-gerais?contexto=pessoas');
        const tbody = document.getElementById('tbCadastros');
        tbody.innerHTML = '';
        cadastrosCache.clear();
        cadastroSelecionadoId = null;
        cadastros.slice(0, 20).forEach(c => {
          cadastrosCache.set(c.id, c);
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><input type="radio" name="cadSelect" onchange="selecionarCadastro(${c.id})" /></td><td>${c.id}</td><td>${c.razao_social}</td><td>${c.cidade_uf || '-'}</td><td>${c.nome_fantasia || '-'}</td><td>${c.cnpj}</td><td>${c.telefone}</td><td>${c.cep}</td>`;
          tbody.appendChild(tr);
        });
      } catch (err) {
        setMsg('statusCadastro', `Falha ao listar cadastros: ${err.message}`, false);
      }
    }

    async function pesquisarCadastros() {
      const q = document.getElementById('cadBusca').value.trim();
      if (!q) {
        listarCadastros();
        return;
      }
      try {
        const cadastros = await api(`/cadastros-gerais/buscar?q=${encodeURIComponent(q)}&contexto=pessoas`);
        const tbody = document.getElementById('tbCadastros');
        tbody.innerHTML = '';
        cadastrosCache.clear();
        cadastroSelecionadoId = null;
        cadastros.forEach(c => {
          cadastrosCache.set(c.id, c);
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><input type="radio" name="cadSelect" onchange="selecionarCadastro(${c.id})" /></td><td>${c.id}</td><td>${c.razao_social}</td><td>${c.cidade_uf || '-'}</td><td>${c.nome_fantasia || '-'}</td><td>${c.cnpj}</td><td>${c.telefone}</td><td>${c.cep}</td>`;
          tbody.appendChild(tr);
        });
        setMsg('statusCadastro', `${cadastros.length} cadastro(s) encontrado(s).`);
      } catch (err) {
        setMsg('statusCadastro', `Falha na pesquisa: ${err.message}`, false);
      }
    }

    async function consultarCnpjModal() {
      const cnpj = document.getElementById('editCnpj').value.trim();
      if (!cnpj) {
        setMsg('statusEdicao', 'Digite um CNPJ para consultar.', false);
        return;
      }
      try {
        setMsg('statusEdicao', 'Consultando CNPJ na base de dados...');
        const dados = await api(`/cadastros-gerais/consultar-cnpj/${encodeURIComponent(cnpj)}`);
        document.getElementById('editCnpj').value = dados.cnpj || cnpj;
        document.getElementById('editRazao').value = dados.razao_social || '';
        document.getElementById('editCidadeUf').value = dados.cidade_uf || '';
        document.getElementById('editNomeFantasia').value = dados.nome_fantasia || '';
        document.getElementById('editEndereco').value = dados.endereco || '';
        if (dados.telefone) document.getElementById('editTelefone').value = dados.telefone;
        if (dados.cep) document.getElementById('editCep').value = dados.cep;
        setMsg('statusEdicao', 'Dados do CNPJ carregados com sucesso.');
      } catch (err) {
        setMsg('statusEdicao', `Nao foi possivel consultar CNPJ: ${err.message}`, false);
      }
    }

    function copiarRazaoParaFantasia() {
      const razao = document.getElementById('editRazao').value.trim();
      const fantasia = document.getElementById('editNomeFantasia').value.trim();
      if (!razao) {
        setMsg('statusEdicao', 'Informe a Razao Social antes de copiar.', false);
        return;
      }
      if (fantasia) {
        setMsg('statusEdicao', 'Nome Fantasia ja preenchido. Limpe o campo se quiser copiar novamente.', false);
        return;
      }
      document.getElementById('editNomeFantasia').value = razao;
      setMsg('statusEdicao', 'Razao Social copiada para Nome Fantasia.');
    }

    async function abrirModalNovoCadastro(origem = 'pessoas') {
      origemCadastroModal = origem;
      limparFormularioModal();
      atualizarVisibilidadeFlagsCadastro();
      document.getElementById('tituloModalCadastro').textContent = origem === 'geral' ? 'Cadastro da Empresa' : 'Novo Cadastro';
      if (origem === 'geral') {
        try {
          const itens = await api('/cadastros-gerais?contexto=geral');
          if (itens.length) {
            const emp = itens[0];
            cadastroEditId = emp.id;
            document.getElementById('editCnpj').value = emp.cnpj || '';
            document.getElementById('editRazao').value = emp.razao_social || '';
            document.getElementById('editCidadeUf').value = emp.cidade_uf || '';
            document.getElementById('editNomeFantasia').value = emp.nome_fantasia || '';
            document.getElementById('editEndereco').value = emp.endereco || '';
            document.getElementById('editTelefone').value = emp.telefone || '';
            document.getElementById('editCep').value = emp.cep || '';
            document.getElementById('editIsCliente').checked = !!emp.is_cliente;
            document.getElementById('editIsFuncionario').checked = !!emp.is_funcionario;
            document.getElementById('editIsFornecedor').checked = !!emp.is_fornecedor;
            document.getElementById('editIsVendedor').checked = !!emp.is_vendedor;
            document.getElementById('editChavePix').value = emp.chave_pix || '';
            document.getElementById('editVendedorComissionado').checked = !!emp.vendedor_comissionado;
            atualizarVisibilidadeVendedor();
          }
        } catch (err) {
          setMsg('statusGeral', `Falha ao carregar empresa padrao: ${err.message}`, false);
        }
      }
      document.getElementById('modalEdicao').classList.remove('hidden');
    }

    function abrirModalEdicao() {
      origemCadastroModal = 'pessoas';
      atualizarVisibilidadeFlagsCadastro();
      if (!cadastroSelecionadoId) {
        setMsg('statusCadastro', 'Selecione um cliente/cadastro antes de editar.', false);
        return;
      }
      const cadastro = cadastrosCache.get(cadastroSelecionadoId);
      if (!cadastro) {
        setMsg('statusCadastro', 'Cadastro nao encontrado para edicao.', false);
        return;
      }
      document.getElementById('tituloModalCadastro').textContent = 'Editar Cadastro';
      cadastroEditId = cadastro.id;
      document.getElementById('editCnpj').value = cadastro.cnpj || '';
      document.getElementById('editRazao').value = cadastro.razao_social || '';
      document.getElementById('editCidadeUf').value = cadastro.cidade_uf || '';
      document.getElementById('editNomeFantasia').value = cadastro.nome_fantasia || '';
      document.getElementById('editEndereco').value = cadastro.endereco || '';
      document.getElementById('editTelefone').value = cadastro.telefone || '';
      document.getElementById('editCep').value = cadastro.cep || '';
      document.getElementById('editIsCliente').checked = !!cadastro.is_cliente;
      document.getElementById('editIsFuncionario').checked = !!cadastro.is_funcionario;
      document.getElementById('editIsFornecedor').checked = !!cadastro.is_fornecedor;
      document.getElementById('editIsVendedor').checked = !!cadastro.is_vendedor;
      document.getElementById('editChavePix').value = cadastro.chave_pix || '';
      document.getElementById('editVendedorComissionado').checked = !!cadastro.vendedor_comissionado;
      atualizarVisibilidadeVendedor();
      document.getElementById('statusEdicao').textContent = '';
      document.getElementById('modalEdicao').classList.remove('hidden');
    }

    function fecharModalEdicao() {
      document.getElementById('modalEdicao').classList.add('hidden');
    }

    function tipoFinanceiroAtual() {
      return (abaFinanceiroAtiva === 'receber' || abaFinanceiroAtiva === 'recebidas') ? 'receber' : 'pagar';
    }

    function statusFinalFinanceiroAtual() {
      return tipoFinanceiroAtual() === 'pagar' ? 'pago' : 'recebido';
    }

    function abaFinanceiroHistorico() {
      return abaFinanceiroAtiva === 'pagas' || abaFinanceiroAtiva === 'recebidas';
    }

    function selecionarAbaFinanceiro(tipo) {
      var ok = tipo === 'pagar' || tipo === 'receber' || tipo === 'pagas' || tipo === 'recebidas';
      abaFinanceiroAtiva = ok ? tipo : 'pagar';
      if (cardsFinanceiroAbertos.indexOf(abaFinanceiroAtiva) < 0) cardsFinanceiroAbertos.push(abaFinanceiroAtiva);
      cardFinanceiroAtivo = abaFinanceiroAtiva;
      ocultarSeletorFinanceiro();
      var a1 = document.getElementById('finAbaPagar');
      var a2 = document.getElementById('finAbaReceber');
      var a3 = document.getElementById('finAbaPagas');
      var a4 = document.getElementById('finAbaRecebidas');
      if (a1) a1.classList.toggle('active', abaFinanceiroAtiva === 'pagar');
      if (a2) a2.classList.toggle('active', abaFinanceiroAtiva === 'receber');
      if (a3) a3.classList.toggle('active', abaFinanceiroAtiva === 'pagas');
      if (a4) a4.classList.toggle('active', abaFinanceiroAtiva === 'recebidas');
      contaFinanceiraSelecionadaId = null;
      contasFinanceiroSelecionadas.clear();
      parteFinanceiroSelecionadaId = null;
      var busca = document.getElementById('finBuscaParteResumo');
      if (busca) busca.value = '';
      const btnNovo = document.getElementById('btnNovoLancamentoFinanceiro');
      const btnBaixa = document.getElementById('btnBaixaFinanceiro');
      const historico = abaFinanceiroHistorico();
      if (btnNovo) btnNovo.disabled = historico;
      if (btnBaixa) btnBaixa.disabled = historico;
      if (btnBaixa) btnBaixa.textContent = tipoFinanceiroAtual() === 'pagar' ? '💸 Baixar selecionada' : '💸 Receber selecionada';
      renderCardsAbertosFinanceiro();
      carregarTudo();
    }

    function abrirNovoLancamentoFinanceiro() {
      if (abaFinanceiroHistorico()) {
        setMsg('statusFinanceiro', 'Aba de historico: use Contas a Pagar/Receber para novo lancamento.', false);
        return;
      }
      abrirModalFinanceiro(tipoFinanceiroAtual());
    }

    function adicionarMeses(dataIso, meses) {
      const data = new Date(`${dataIso}T00:00:00`);
      data.setMonth(data.getMonth() + meses);
      return data.toISOString().slice(0, 10);
    }

    function primeiroVencimentoCartaoJs(isoEmissao, diaFechamento, diaVencimento) {
      const partes = String(isoEmissao || '').split('-');
      if (partes.length !== 3) return isoEmissao;
      let y = Number(partes[0]);
      let m = Number(partes[1]);
      const dd = Number(partes[2]);
      if (dd > diaFechamento) {
        m += 1;
        if (m > 12) {
          m = 1;
          y += 1;
        }
      }
      const ultimo = new Date(y, m, 0).getDate();
      const dia = Math.min(diaVencimento || 10, ultimo);
      return `${y}-${String(m).padStart(2, '0')}-${String(dia).padStart(2, '0')}`;
    }

    function atualizarEstadoCampoDataVencimentoPagar() {
      var elPc = document.getElementById('finPagamentoCartao');
      const pagCartao = !!(elPc && elPc.checked);
      const el = document.getElementById('finDataVencimento');
      if (el) {
        el.disabled = pagCartao;
        el.classList.toggle('fin-input-calculado', pagCartao);
      }
    }

    function atualizarTituloParcelasModal() {
      const el = document.getElementById('finTituloParcelas');
      if (!el) return;
      var elPc2 = document.getElementById('finPagamentoCartao');
      const pagCartao = !!(elPc2 && elPc2.checked);
      el.textContent = pagCartao ? 'Parcelas (vencimentos pelo cartao)' : 'Parcelas';
    }

    function atualizarFormaPagamentoFinanceiro() {
      var elPc3 = document.getElementById('finPagamentoCartao');
      const pagCartao = !!(elPc3 && elPc3.checked);
      const linhaCartao = document.getElementById('finCartaoCreditoLinha');
      const selCartao = document.getElementById('finCartaoCreditoId');
      const liq = document.getElementById('finLiquidacaoImediata');
      const liqBox = document.getElementById('finLiquidacaoContaBox');
      if (pagCartao) {
        if (linhaCartao) linhaCartao.classList.remove('hidden');
        if (selCartao) selCartao.disabled = false;
        if (liq) {
          liq.checked = false;
          liq.disabled = true;
        }
        if (liqBox) liqBox.classList.add('hidden');
      } else {
        if (linhaCartao) linhaCartao.classList.add('hidden');
        if (selCartao) {
          selCartao.disabled = true;
          selCartao.value = '';
        }
        if (liq) liq.disabled = false;
      }
      atualizarTituloParcelasModal();
      gerarParcelasFinanceiro();
    }

    function gerarParcelasFinanceiro() {
      atualizarEstadoCampoDataVencimentoPagar();
      const total = Number(document.getElementById('finValor').value) || 0;
      const qtd = Math.max(1, Number(document.getElementById('finParcelas').value) || 1);
      var elEm = document.getElementById('finDataEmissao');
      var elPc4 = document.getElementById('finPagamentoCartao');
      var elCs = document.getElementById('finCartaoCreditoId');
      const dataEmissao = elEm && elEm.value ? elEm.value : '';
      const pagCartao = !!(elPc4 && elPc4.checked);
      const cartaoId = Number(elCs && elCs.value ? elCs.value : '') || 0;
      let baseData = '';
      if (pagCartao && cartaoId && dataEmissao && cartoesCreditoFinanceiro.length) {
        const c = cartoesCreditoFinanceiro.find(x => x.id === cartaoId);
        if (c) {
          const dv = c.data_vencimento != null ? c.data_vencimento : 10;
          baseData = primeiroVencimentoCartaoJs(dataEmissao, c.data_fechamento, dv);
          const fv = document.getElementById('finDataVencimento');
          if (fv) fv.value = baseData;
        }
      } else if (!pagCartao) {
        baseData = document.getElementById('finDataVencimento').value || dataEmissao;
      }
      const tbody = document.getElementById('tbParcelasFinanceiro');
      if (!tbody) return;
      tbody.innerHTML = '';
      if (!baseData) return;

      const valorBase = qtd > 0 ? Math.round((total / qtd) * 100) / 100 : 0;
      let acumulado = 0;
      const travarDatasParcelas = pagCartao && !!baseData;
      for (let i = 0; i < qtd; i += 1) {
        const valorParcela = i === qtd - 1 ? Math.round((total - acumulado) * 100) / 100 : valorBase;
        acumulado += valorParcela;
        const venc = adicionarMeses(baseData, i);
        const tr = document.createElement('tr');
        const clsData = travarDatasParcelas ? ' fin-parcela-data-cartao' : '';
        const disData = travarDatasParcelas ? ' disabled' : '';
        tr.innerHTML = `<td>${i + 1}/${qtd}</td><td><input type="date" class="fin-parcela-data${clsData}" value="${venc}"${disData} /></td><td><input type="number" step="0.01" class="fin-parcela-valor" value="${valorParcela.toFixed(2)}" /></td>`;
        tbody.appendChild(tr);
      }
    }

    async function carregarCombosFinanceiro() {
      const [grupos, planos, gruposConta] = await Promise.all([
        api('/grupos-despesas'),
        api('/planos-contas'),
        api('/grupos-contas'),
      ]);
      gruposDespesaFinanceiro = grupos;
      planosContaFinanceiro = planos;
      gruposContaFinanceiro = gruposConta;

      const selGrupo = document.getElementById('finGrupoDespesaId');
      const selPlano = document.getElementById('finPlanoContaId');
      const selGrupoConta = document.getElementById('finGrupoContaId');
      selGrupo.innerHTML = '';
      selPlano.innerHTML = '';
      selGrupoConta.innerHTML = '';

      grupos.forEach(item => {
        const opt = document.createElement('option');
        opt.value = String(item.id);
        opt.textContent = item.nome;
        selGrupo.appendChild(opt);
      });
      planos.forEach(item => {
        const opt = document.createElement('option');
        opt.value = String(item.id);
        opt.textContent = item.nome;
        selPlano.appendChild(opt);
      });
      gruposConta.forEach(item => {
        const opt = document.createElement('option');
        opt.value = String(item.id);
        opt.textContent = item.nome;
        selGrupoConta.appendChild(opt);
      });
      await carregarSubgruposFinanceiro();
    }

    async function carregarSubgruposFinanceiro() {
      const selGrupoConta = document.getElementById('finGrupoContaId');
      const selSubgrupoConta = document.getElementById('finSubgrupoContaId');
      const grupoContaId = Number(selGrupoConta.value) || 0;
      selSubgrupoConta.innerHTML = '';
      if (!grupoContaId) {
        return;
      }
      subgruposContaFinanceiro = await api(`/subgrupos-contas?grupo_conta_id=${grupoContaId}`);
      subgruposContaFinanceiro.forEach(item => {
        const opt = document.createElement('option');
        opt.value = String(item.id);
        opt.textContent = item.nome;
        selSubgrupoConta.appendChild(opt);
      });
    }

    async function carregarContasCorrentesFinanceiro() {
      const contas = await api('/contas-correntes');
      contasCorrentesFinanceiro = contas;
      const select = document.getElementById('finLiquidacaoContaCorrenteId');
      if (!select) return;
      select.innerHTML = '';
      contas.forEach(item => {
        const opt = document.createElement('option');
        opt.value = String(item.id);
        const nomeConta = (item.nome_conta || '').trim();
        opt.textContent = nomeConta
          ? `${item.id} - ${nomeConta}`
          : `${item.id} - ${item.banco} / ${item.numero}`;
        select.appendChild(opt);
      });
    }

    function atualizarVisibilidadeLiquidacaoImediata() {
      const flag = document.getElementById('finLiquidacaoImediata');
      const box = document.getElementById('finLiquidacaoContaBox');
      if (!flag || !box) return;
      if (flag.checked) {
        const pc = document.getElementById('finPagamentoCartao');
        if (pc && pc.checked) {
          pc.checked = false;
          atualizarFormaPagamentoFinanceiro();
          return;
        }
        box.classList.remove('hidden');
      } else {
        box.classList.add('hidden');
      }
    }

    async function carregarCartoesCreditoFinanceiro() {
      try {
        const lista = await api('/cartoes-credito');
        cartoesCreditoFinanceiro = (lista || []).filter(c => c.ativa !== false);
        const sel = document.getElementById('finCartaoCreditoId');
        if (!sel) return;
        sel.innerHTML = '<option value="">Selecione o cartao</option>';
        cartoesCreditoFinanceiro.forEach(c => {
          const opt = document.createElement('option');
          opt.value = String(c.id);
          const nome = (c.nome_conta || '').trim();
          opt.textContent = nome ? `${c.banco} - ${nome}` : `${c.banco} (ID ${c.id})`;
          sel.appendChild(opt);
        });
      } catch (e) {
        cartoesCreditoFinanceiro = [];
      }
    }

    function limparFiltroParteFinanceiro() {
      document.getElementById('finBuscaParteResumo').value = '';
      parteFinanceiroSelecionadaId = null;
      renderResumoPartesFinanceiro();
      renderContasFinanceiro();
    }

    function isContaAberta(conta) {
      const status = String(conta.status || '').toLowerCase();
      const statusFinal = statusFinalFinanceiroAtual();
      return status !== statusFinal;
    }

    function isContaExibidaNaAba(conta) {
      return abaFinanceiroHistorico() ? !isContaAberta(conta) : isContaAberta(conta);
    }

    function isContaVencida(conta) {
      if (!isContaAberta(conta)) return false;
      const venc = String(conta.data_vencimento || '').slice(0, 10);
      if (!venc) return false;
      const hoje = new Date().toISOString().slice(0, 10);
      return venc < hoje;
    }

    function selecionarParteFinanceiroResumo(parteId) {
      parteFinanceiroSelecionadaId = parteFinanceiroSelecionadaId === parteId ? null : parteId;
      renderResumoPartesFinanceiro();
      renderContasFinanceiro();
    }

    function renderResumoPartesFinanceiro() {
      const termo = (document.getElementById('finBuscaParteResumo').value || '').trim().toLowerCase();
      const tbResumo = document.getElementById('tbResumoPartesFinanceiro');
      tbResumo.innerHTML = '';
      resumoPartesFinanceiroCache
        .filter(item => {
          const nome = item.nome.toLowerCase();
          return !termo || nome.includes(termo) || String(item.parteId).includes(termo);
        })
        .forEach(item => {
          const tr = document.createElement('tr');
          tr.className = `${item.temVencida ? 'row-vencida' : ''} ${parteFinanceiroSelecionadaId === item.parteId ? 'row-selected' : ''}`.trim();
          tr.style.cursor = 'pointer';
          tr.onclick = () => selecionarParteFinanceiroResumo(item.parteId);
          tr.innerHTML = `<td>${item.parteId}</td><td>${item.nome}</td><td>${item.qtd}</td><td>${moeda(item.total)}</td>`;
          tbResumo.appendChild(tr);
        });
    }

    function textoCartaoFaturaHtml(conta) {
      if (tipoFinanceiroAtual() !== 'pagar') return '-';
      const c = (conta.cartao_label || '').trim();
      const m = (conta.fatura_mes_referencia || '').trim();
      if (!c && !m) return '-';
      const full = c && m ? `${c} · ${m}` : (c || m);
      const safe = full.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
      return `<span class="tag tag-cartao-fatura" title="${safe}">${safe}</span>`;
    }

    function renderContasFinanceiro() {
      const tbContas = document.getElementById('tbContasFinanceiro');
      tbContas.innerHTML = '';
      const contasVisiveis = contasFinanceiroCache
        .filter(conta => isContaExibidaNaAba(conta))
        .filter(conta => {
          if (!parteFinanceiroSelecionadaId) return true;
          const parteId = tipoFinanceiroAtual() === 'pagar' ? conta.fornecedor_id : conta.cliente_id;
          return parteId === parteFinanceiroSelecionadaId;
        })
        .sort((a, b) => String(a.data_vencimento || '').localeCompare(String(b.data_vencimento || '')));

      const idsVisiveis = new Set(contasVisiveis.map(c => c.id));
      Array.from(contasFinanceiroSelecionadas).forEach(id => {
        if (!idsVisiveis.has(id)) contasFinanceiroSelecionadas.delete(id);
      });

      contasVisiveis.forEach(conta => {
        const parteId = tipoFinanceiroAtual() === 'pagar' ? conta.fornecedor_id : conta.cliente_id;
        const nomeParte = parteId ? (partesMapFinanceiroCache.get(parteId) || `Codigo ${parteId}`) : '-';
        const checkboxId = `selContaFin${conta.id}`;
        const tr = document.createElement('tr');
        tr.className = `${isContaVencida(conta) ? 'row-vencida' : ''}`.trim();
        tr.tabIndex = 0;
        tr.onclick = () => alternarSelecaoContaFinanceiraLinha(conta.id, checkboxId);
        tr.oncontextmenu = event => {
          event.preventDefault();
          if (abaFinanceiroHistorico()) return;
          contasFinanceiroSelecionadas.clear();
          contasFinanceiroSelecionadas.add(conta.id);
          contaFinanceiraSelecionadaId = conta.id;
          renderContasFinanceiro();
          abrirModalBaixaContaFinanceira(conta.id);
        };
        tr.onkeydown = event => {
          if (event.code === 'Space' || event.key === ' ') {
            event.preventDefault();
            alternarSelecaoContaFinanceiraLinha(conta.id, checkboxId);
          }
        };
        const checked = contasFinanceiroSelecionadas.has(conta.id) ? 'checked' : '';
        const cartFat = textoCartaoFaturaHtml(conta);
        tr.innerHTML = `<td><input id="${checkboxId}" type="checkbox" ${checked} onclick="event.stopPropagation()" onchange="selecionarContaFinanceira(${conta.id}, this.checked)" /></td><td>${conta.id}</td><td>${nomeParte}</td><td>${conta.descricao || '-'}</td><td>${cartFat}</td><td>${(conta.data_vencimento || '').slice(0, 10)}</td><td><span class="tag">${conta.status || '-'}</span></td><td>${moeda(conta.valor)}</td>`;
        tbContas.appendChild(tr);
      });
      const rotulo = abaFinanceiroHistorico() ? 'historico' : 'aberta(s)';
      setMsg('statusFinanceiro', `${contasVisiveis.length} conta(s) ${rotulo}. Selecionadas: ${contasFinanceiroSelecionadas.size}.`);
    }

    function alternarSelecaoContaFinanceira(id, checked) {
      if (checked) {
        contasFinanceiroSelecionadas.add(id);
      } else {
        contasFinanceiroSelecionadas.delete(id);
      }
      contaFinanceiraSelecionadaId = contasFinanceiroSelecionadas.size === 1 ? Array.from(contasFinanceiroSelecionadas)[0] : null;
      setMsg('statusFinanceiro', `${contasFinanceiroSelecionadas.size} lancamento(s) selecionado(s).`);
    }

    function selecionarContaFinanceira(id, checked) {
      alternarSelecaoContaFinanceira(id, checked);
    }

    function alternarSelecaoContaFinanceiraLinha(id, checkboxId) {
      const checkbox = document.getElementById(checkboxId);
      if (!checkbox) return;
      checkbox.checked = !checkbox.checked;
      alternarSelecaoContaFinanceira(id, checkbox.checked);
    }

    function abrirModalEdicaoContaFinanceira() {
      if (contasFinanceiroSelecionadas.size !== 1) {
        setMsg('statusFinanceiro', 'Selecione apenas um lancamento para editar.', false);
        return;
      }
      contaFinanceiraSelecionadaId = Array.from(contasFinanceiroSelecionadas)[0];
      const conta = contasFinanceiroCache.find(item => item.id === contaFinanceiraSelecionadaId);
      if (!conta) {
        setMsg('statusFinanceiro', 'Lancamento selecionado nao encontrado.', false);
        return;
      }
      document.getElementById('tituloModalEdicaoFinanceiro').textContent =
        tipoFinanceiroAtual() === 'pagar' ? 'Editar Conta a Pagar' : 'Editar Conta a Receber';
      document.getElementById('editFinDescricao').value = conta.descricao || '';
      document.getElementById('editFinValor').value = Number(conta.valor || 0);
      document.getElementById('editFinDataVencimento').value = (conta.data_vencimento || '').slice(0, 10);
      document.getElementById('editFinDocumento').value = conta.comprovante_url || '';
      setMsg('statusModalEdicaoFinanceiro', '');
      document.getElementById('modalEdicaoFinanceiro').classList.remove('hidden');
    }

    function fecharModalEdicaoContaFinanceira() {
      document.getElementById('modalEdicaoFinanceiro').classList.add('hidden');
    }

    async function salvarEdicaoContaFinanceira() {
      if (!contaFinanceiraSelecionadaId) {
        setMsg('statusModalEdicaoFinanceiro', 'Nenhum lancamento selecionado para editar.', false);
        return;
      }
      const descricao = document.getElementById('editFinDescricao').value.trim();
      const valor = Number(document.getElementById('editFinValor').value);
      const data_vencimento = document.getElementById('editFinDataVencimento').value;
      const comprovante_url = document.getElementById('editFinDocumento').value.trim() || null;
      if (!descricao || !valor || !data_vencimento) {
        setMsg('statusModalEdicaoFinanceiro', 'Preencha descricao, valor e data.', false);
        return;
      }
      try {
        const endpointBase = tipoFinanceiroAtual() === 'pagar' ? '/contas-pagar' : '/contas-receber';
        await api(`${endpointBase}/${contaFinanceiraSelecionadaId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            descricao,
            valor,
            data_vencimento,
            comprovante_url,
          }),
        });
        fecharModalEdicaoContaFinanceira();
        setMsg('statusFinanceiro', `Lancamento ${contaFinanceiraSelecionadaId} atualizado com sucesso.`);
        await carregarTudo();
      } catch (err) {
        setMsg('statusModalEdicaoFinanceiro', err.message, false);
      }
    }

    async function excluirContasFinanceirasSelecionadas() {
      if (!contasFinanceiroSelecionadas.size) {
        setMsg('statusFinanceiro', 'Selecione ao menos um lancamento para excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const qtd = contasFinanceiroSelecionadas.size;
      const confirmou = window.confirm(`Confirma exclusao de ${qtd} lancamento(s) selecionado(s)?`);
      if (!confirmou) return;
      try {
        const endpointBase = tipoFinanceiroAtual() === 'pagar' ? '/contas-pagar' : '/contas-receber';
        for (const id of Array.from(contasFinanceiroSelecionadas)) {
          await api(`${endpointBase}/${id}`, { method: 'DELETE' });
        }
        contasFinanceiroSelecionadas.clear();
        contaFinanceiraSelecionadaId = null;
        setMsg('statusFinanceiro', `${qtd} lancamento(s) excluido(s) com sucesso.`);
        await carregarTudo();
      } catch (err) {
        setMsg('statusFinanceiro', `Falha ao excluir selecionados: ${err.message}`, false);
      }
    }

    async function abrirModalBaixaContaFinanceira(contaId = null) {
      if (abaFinanceiroHistorico()) {
        setMsg('statusFinanceiro', 'Baixa/recebimento nao disponivel nas abas de historico.', false);
        return;
      }
      const idsSelecionados = contaId ? [contaId] : Array.from(contasFinanceiroSelecionadas);
      if (!idsSelecionados.length) {
        setMsg('statusFinanceiro', 'Selecione ao menos uma conta para baixar/receber.', false);
        return;
      }
      contasFinanceiroBaixaIds = idsSelecionados;
      contaFinanceiraSelecionadaId = idsSelecionados[0];
      const hoje = new Date().toISOString().slice(0, 10);
      document.getElementById('baixaData').value = hoje;
      document.getElementById('baixaComprovante').value = '';
      const tipoAcao = tipoFinanceiroAtual() === 'pagar' ? 'Baixar' : 'Receber';
      const qtd = idsSelecionados.length;
      document.getElementById('tituloModalBaixaFinanceiro').textContent = `${tipoAcao} Conta${qtd > 1 ? 's' : ''} (${qtd})`;
      const btnConfirm = document.getElementById('btnConfirmarBaixaFinanceiro');
      if (btnConfirm) {
        btnConfirm.textContent = tipoFinanceiroAtual() === 'pagar' ? 'Confirmar baixa' : 'Confirmar recebimento';
        btnConfirm.disabled = true;
      }
      setMsg('statusModalBaixaFinanceiro', '');
      document.getElementById('modalBaixaFinanceiro').classList.remove('hidden');
      setMsg('statusModalBaixaFinanceiro', 'Carregando contas correntes...');
      try {
        const contasCorrentes = await api('/contas-correntes');
        const select = document.getElementById('baixaContaCorrenteId');
        select.innerHTML = '';
        contasCorrentes.forEach(item => {
          const opt = document.createElement('option');
          opt.value = String(item.id);
          const nomeConta = (item.nome_conta || '').trim();
          opt.textContent = nomeConta
            ? `${item.id} - ${nomeConta}`
            : `${item.id} - ${item.banco} / ${item.numero}`;
          select.appendChild(opt);
        });
        if (!contasCorrentes.length) {
          setMsg('statusModalBaixaFinanceiro', 'Nenhuma conta corrente cadastrada. Cadastre uma conta para continuar.', false);
          return;
        }
        if (btnConfirm) btnConfirm.disabled = false;
        setMsg('statusModalBaixaFinanceiro', '');
      } catch (err) {
        setMsg('statusModalBaixaFinanceiro', `Falha ao carregar contas correntes: ${err.message}`, false);
      }
    }

    function fecharModalBaixaContaFinanceira() {
      contasFinanceiroBaixaIds = [];
      document.getElementById('modalBaixaFinanceiro').classList.add('hidden');
    }

    async function confirmarBaixaContaFinanceira() {
      if (!contasFinanceiroBaixaIds.length) {
        setMsg('statusModalBaixaFinanceiro', 'Selecione ao menos uma conta para baixa/recebimento.', false);
        return;
      }
      const conta_destino_id = Number(document.getElementById('baixaContaCorrenteId').value) || 0;
      const data = document.getElementById('baixaData').value;
      const comprovante = document.getElementById('baixaComprovante').value.trim() || null;
      if (!conta_destino_id || !data) {
        setMsg('statusModalBaixaFinanceiro', 'Informe conta corrente e data.', false);
        return;
      }
      try {
        const ids = [...contasFinanceiroBaixaIds];
        for (const id of ids) {
          if (tipoFinanceiroAtual() === 'pagar') {
            await api(`/contas-pagar/${id}/baixar`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                conta_destino_id,
                data_pagamento: data,
                comprovante_url: comprovante,
              }),
            });
          } else {
            await api(`/contas-receber/${id}/receber`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                conta_destino_id,
                data_recebimento: data,
                comprovante_url: comprovante,
              }),
            });
          }
        }
        fecharModalBaixaContaFinanceira();
        contasFinanceiroBaixaIds = [];
        setMsg('statusFinanceiro', `Baixa/recebimento registrado para ${ids.length} conta(s). Lancamento enviado para conciliacao pendente.`);
        await carregarTudo();
      } catch (err) {
        setMsg('statusModalBaixaFinanceiro', err.message, false);
      }
    }

    async function abrirModalFinanceiro(tipo) {
      tipoLancamentoFinanceiro = tipo;
      const hoje = new Date().toISOString().slice(0, 10);
      document.getElementById('finDescricao').value = '';
      document.getElementById('finValor').value = '';
      document.getElementById('finParteCodigo').value = '';
      document.getElementById('finParteNome').value = '';
      document.getElementById('finParteId').value = '';
      document.getElementById('finParteSelecionado').textContent = 'Nenhum selecionado';
      document.getElementById('finDataEmissao').value = hoje;
      document.getElementById('finDataVencimento').value = hoje;
      document.getElementById('finDocumentoOriginal').value = '';
      document.getElementById('finParcelas').value = '1';
      document.getElementById('finDescricaoReceber').value = '';
      document.getElementById('finValorReceber').value = '';
      document.getElementById('finDataEmissaoReceber').value = hoje;
      document.getElementById('finDataVencimentoReceber').value = hoje;
      document.getElementById('finDocumentoOriginalReceber').value = '';
      document.getElementById('finLiquidacaoImediata').checked = false;
      document.getElementById('finLiquidacaoContaBox').classList.add('hidden');
      document.getElementById('finLiquidacaoContaCorrenteId').innerHTML = '';
      const finLiqIm = document.getElementById('finLiquidacaoImediata');
      if (finLiqIm) finLiqIm.disabled = false;
      const finPagCartao = document.getElementById('finPagamentoCartao');
      if (finPagCartao) {
        finPagCartao.checked = false;
        finPagCartao.disabled = false;
      }
      const finContaPagarFlag = document.getElementById('finContaAPagarFlag');
      if (finContaPagarFlag) finContaPagarFlag.checked = false;
      const finSelCartao = document.getElementById('finCartaoCreditoId');
      if (finSelCartao) finSelCartao.innerHTML = '';
      document.getElementById('statusModalFinanceiro').textContent = '';

      const labelCartao = document.getElementById('finLabelPagamentoCartao');
      const labelContaAPagar = document.getElementById('finLabelContaAPagar');
      const linhaCartaoTopo = document.getElementById('finCartaoCreditoLinha');
      if (tipo === 'pagar') {
        document.getElementById('tituloModalFinanceiro').textContent = 'Nova Conta a Pagar';
        document.getElementById('finParteLabel').textContent = 'Fornecedor';
        document.getElementById('finLiquidacaoImediataLabel').textContent = 'Pagamento imediato';
        document.getElementById('finParteNome').placeholder = 'Buscar pela lupa';
        const subNome = document.getElementById('finParteSublabelNome');
        if (subNome) subNome.textContent = 'Selecionar fornecedor';
        const linhaParte = document.getElementById('finParteLinha');
        const colCod = document.getElementById('finParteColCodigo');
        if (linhaParte) linhaParte.classList.remove('fin-parte-linha--sem-codigo');
        if (colCod) colCod.classList.remove('hidden');
        document.getElementById('finCamposPagar').classList.remove('hidden');
        document.getElementById('finCamposReceber').classList.add('hidden');
        if (labelCartao) labelCartao.classList.remove('hidden');
        if (labelContaAPagar) labelContaAPagar.classList.remove('hidden');
        try {
          await Promise.all([carregarCombosFinanceiro(), carregarContasCorrentesFinanceiro(), carregarCartoesCreditoFinanceiro()]);
          atualizarFormaPagamentoFinanceiro();
        } catch (err) {
          setMsg('statusModalFinanceiro', `Falha ao carregar grupos/planos/contas: ${err.message}`, false);
        }
      } else {
        document.getElementById('tituloModalFinanceiro').textContent = 'Nova Conta a Receber';
        document.getElementById('finParteLabel').textContent = 'Cliente';
        document.getElementById('finLiquidacaoImediataLabel').textContent = 'Recebimento imediato';
        document.getElementById('finParteNome').placeholder = 'Buscar pela lupa';
        const subNomeR = document.getElementById('finParteSublabelNome');
        if (subNomeR) subNomeR.textContent = 'Selecionar cliente';
        const linhaParteR = document.getElementById('finParteLinha');
        const colCodR = document.getElementById('finParteColCodigo');
        if (linhaParteR) linhaParteR.classList.add('fin-parte-linha--sem-codigo');
        if (colCodR) colCodR.classList.add('hidden');
        document.getElementById('finCamposPagar').classList.add('hidden');
        document.getElementById('finCamposReceber').classList.remove('hidden');
        if (labelCartao) labelCartao.classList.add('hidden');
        if (labelContaAPagar) labelContaAPagar.classList.add('hidden');
        if (linhaCartaoTopo) linhaCartaoTopo.classList.add('hidden');
        const finSelCartaoReset = document.getElementById('finCartaoCreditoId');
        if (finSelCartaoReset) {
          finSelCartaoReset.disabled = true;
          finSelCartaoReset.value = '';
        }
        const fvRec = document.getElementById('finDataVencimento');
        if (fvRec) {
          fvRec.disabled = false;
          fvRec.classList.remove('fin-input-calculado');
        }
        try {
          await carregarContasCorrentesFinanceiro();
        } catch (err) {
          setMsg('statusModalFinanceiro', `Falha ao carregar contas correntes: ${err.message}`, false);
        }
        atualizarTituloParcelasModal();
        atualizarVisibilidadeLiquidacaoImediata();
        const tbParcelas = document.getElementById('tbParcelasFinanceiro');
        if (tbParcelas) tbParcelas.innerHTML = '';
      }
      document.getElementById('modalFinanceiro').classList.remove('hidden');
    }

    function fecharModalFinanceiro() {
      document.getElementById('modalFinanceiro').classList.add('hidden');
    }

    function selecionarParteFinanceira(id, nome, documento) {
      document.getElementById('finParteId').value = String(id);
      document.getElementById('finParteNome').value = nome || '';
      const doc = documento ? ` - ${documento}` : '';
      document.getElementById('finParteSelecionado').textContent = `Selecionado: ${id} - ${nome || ''}${doc}`;
      fecharModalBuscaParte();
    }

    function renderListaBuscaParte(lista) {
      const box = document.getElementById('buscaParteLista');
      box.innerHTML = '';
      if (!lista.length) {
        box.innerHTML = '<div class="result-item"><span>Nenhum registro encontrado.</span></div>';
        return;
      }

      lista.slice(0, 50).forEach(item => {
        const row = document.createElement('div');
        row.className = 'result-item';
        const nome = item.nome || 'Sem nome';
        const doc = item.cnpj_cpf || '';
        row.innerHTML = `<span>${nome}${doc ? ' - ' + doc : ''}</span>`;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-icon';
        btn.textContent = '✔';
        btn.onclick = () => selecionarParteFinanceira(item.id, nome, doc);
        row.appendChild(btn);
        box.appendChild(row);
      });
    }

    async function abrirModalBuscaParte() {
      if (!tipoLancamentoFinanceiro) return;
      try {
        if (tipoLancamentoFinanceiro === 'pagar') {
          const cadastros = await api('/cadastros-gerais?contexto=pessoas');
          partesFinanceiroCache = cadastros
            .filter(item => !!item.is_fornecedor)
            .map(item => ({ id: item.id, nome: item.razao_social, cnpj_cpf: item.cnpj }));
        } else {
          partesFinanceiroCache = await api('/clientes');
        }
        document.getElementById('tituloModalBuscaParte').textContent =
          tipoLancamentoFinanceiro === 'pagar' ? 'Buscar Fornecedor' : 'Buscar Cliente';
        document.getElementById('buscaParteInput').value = '';
        partesBuscaFiltradas = partesFinanceiroCache.slice();
        renderListaBuscaParte(partesBuscaFiltradas);
        document.getElementById('modalBuscaParte').classList.remove('hidden');
        document.getElementById('buscaParteInput').focus();
      } catch (err) {
        setMsg('statusModalFinanceiro', `Falha ao buscar registros: ${err.message}`, false);
      }
    }

    function fecharModalBuscaParte() {
      document.getElementById('modalBuscaParte').classList.add('hidden');
    }

    function filtrarBuscaParte() {
      const termo = document.getElementById('buscaParteInput').value.trim().toLowerCase();
      partesBuscaFiltradas = termo
        ? partesFinanceiroCache.filter(item =>
            (item.nome || '').toLowerCase().includes(termo) ||
            (item.cnpj_cpf || '').toLowerCase().includes(termo)
          )
        : partesFinanceiroCache.slice();
      renderListaBuscaParte(partesBuscaFiltradas);
    }

    function confirmarBuscaPartePorEnter() {
      if (!partesBuscaFiltradas.length) return;
      const item = partesBuscaFiltradas[0];
      selecionarParteFinanceira(item.id, item.nome || 'Sem nome', item.cnpj_cpf || '');
    }

    async function buscarPartePorCodigo() {
      const codigo = Number(document.getElementById('finParteCodigo').value);
      if (!codigo) {
        setMsg('statusModalFinanceiro', 'Informe um codigo valido.', false);
        return;
      }
      try {
        if (tipoLancamentoFinanceiro === 'pagar') {
          const cadastros = await api('/cadastros-gerais?contexto=pessoas');
          const fornecedor = cadastros.find(item => item.id === codigo && !!item.is_fornecedor);
          if (!fornecedor) {
            setMsg('statusModalFinanceiro', 'Fornecedor nao encontrado para o codigo informado.', false);
            return;
          }
          selecionarParteFinanceira(fornecedor.id, fornecedor.razao_social || 'Sem nome', fornecedor.cnpj || '');
          setMsg('statusModalFinanceiro', `Fornecedor ${fornecedor.razao_social} selecionado.`);
        } else {
          const clientes = await api('/clientes');
          const cliente = clientes.find(item => item.id === codigo);
          if (!cliente) {
            setMsg('statusModalFinanceiro', 'Cliente nao encontrado para o codigo informado.', false);
            return;
          }
          selecionarParteFinanceira(cliente.id, cliente.nome || 'Sem nome', cliente.cnpj_cpf || '');
          setMsg('statusModalFinanceiro', `Cliente ${cliente.nome} selecionado.`);
        }
      } catch (err) {
        setMsg('statusModalFinanceiro', `Falha ao buscar por codigo: ${err.message}`, false);
      }
    }

    async function salvarLancamentoFinanceiro() {
      if (!tipoLancamentoFinanceiro) {
        setMsg('statusModalFinanceiro', 'Tipo de lancamento nao definido.', false);
        return;
      }

      const parte_id = Number(document.getElementById('finParteId').value) || null;
      const descricao = tipoLancamentoFinanceiro === 'pagar'
        ? document.getElementById('finDescricao').value.trim()
        : document.getElementById('finDescricaoReceber').value.trim();
      const valor = tipoLancamentoFinanceiro === 'pagar'
        ? Number(document.getElementById('finValor').value)
        : Number(document.getElementById('finValorReceber').value);
      const data_emissao = tipoLancamentoFinanceiro === 'pagar'
        ? document.getElementById('finDataEmissao').value
        : document.getElementById('finDataEmissaoReceber').value;
      const data_vencimento = tipoLancamentoFinanceiro === 'pagar'
        ? document.getElementById('finDataVencimento').value
        : document.getElementById('finDataVencimentoReceber').value;
      const documento_original = tipoLancamentoFinanceiro === 'pagar'
        ? document.getElementById('finDocumentoOriginal').value.trim()
        : document.getElementById('finDocumentoOriginalReceber').value.trim();
      const categoria_id = tipoLancamentoFinanceiro === 'receber' ? 2 : 1;
      const centro_custos_id = 1;
      const liquidacaoImediata = !!document.getElementById('finLiquidacaoImediata').checked;
      const contaLiquidacaoId = Number(document.getElementById('finLiquidacaoContaCorrenteId').value) || 0;
      const dataLiquidacao = data_emissao || new Date().toISOString().slice(0, 10);
      var elPc5 = document.getElementById('finPagamentoCartao');
      var elCf = document.getElementById('finCartaoCreditoId');
      const pagCartao = tipoLancamentoFinanceiro === 'pagar' && !!(elPc5 && elPc5.checked);
      var elCpFlag = document.getElementById('finContaAPagarFlag');
      const contaAPagarFlag = tipoLancamentoFinanceiro === 'pagar' && !!(elCpFlag && elCpFlag.checked);
      const cartaoFinId = Number(elCf && elCf.value ? elCf.value : '') || 0;

      if (!descricao || !valor || !data_emissao) {
        setMsg('statusModalFinanceiro', 'Preencha os campos obrigatorios.', false);
        return;
      }
      if (valor <= 0) {
        setMsg('statusModalFinanceiro', 'Informe um valor maior que zero.', false);
        return;
      }
      if (tipoLancamentoFinanceiro === 'pagar' && !parte_id) {
        setMsg('statusModalFinanceiro', 'Selecione um fornecedor cadastrado.', false);
        return;
      }
      if (!pagCartao && !liquidacaoImediata && !contaAPagarFlag) {
        setMsg('statusModalFinanceiro', 'Marque ao menos uma opcao: Pagamento com cartao, Pagamento/recebimento imediato ou Contas a Pagar.', false);
        return;
      }
      if (liquidacaoImediata && !contaLiquidacaoId) {
        setMsg('statusModalFinanceiro', 'Selecione a conta corrente para pagamento/recebimento imediato.', false);
        return;
      }
      if (pagCartao && !cartaoFinId) {
        setMsg('statusModalFinanceiro', 'Selecione o cartao de credito.', false);
        return;
      }
      if (pagCartao && liquidacaoImediata) {
        setMsg('statusModalFinanceiro', 'Pagamento com cartao nao pode ser combinado com pagamento imediato na conta.', false);
        return;
      }

      try {
        if (tipoLancamentoFinanceiro === 'pagar') {
          const parcelas = Math.max(1, Number(document.getElementById('finParcelas').value) || 1);
          const grupoId = Number(document.getElementById('finGrupoDespesaId').value) || 0;
          const planoId = Number(document.getElementById('finPlanoContaId').value) || 0;
          const grupoContaId = Number(document.getElementById('finGrupoContaId').value) || 0;
          const subgrupoContaId = Number(document.getElementById('finSubgrupoContaId').value) || 0;
          if (!grupoId || !planoId || !grupoContaId || !subgrupoContaId) {
            setMsg('statusModalFinanceiro', 'Selecione grupo de despesas, plano de contas, grupo de contas e subgrupo de contas.', false);
            return;
          }

          const grupoNome = (gruposDespesaFinanceiro.find(item => item.id === grupoId) || {}).nome || '';
          const planoNome = (planosContaFinanceiro.find(item => item.id === planoId) || {}).nome || '';
          const grupoContaNome = (gruposContaFinanceiro.find(item => item.id === grupoContaId) || {}).nome || '';
          const subgrupoContaNome = (subgruposContaFinanceiro.find(item => item.id === subgrupoContaId) || {}).nome || '';
          const linhasParcelas = Array.from(document.querySelectorAll('#tbParcelasFinanceiro tr'));
          if (linhasParcelas.length !== parcelas) {
            setMsg('statusModalFinanceiro', 'Atualize e confira as parcelas antes de salvar.', false);
            return;
          }
          const parcelasEditadas = linhasParcelas.map((linha, idx) => {
            const dataInput = linha.querySelector('.fin-parcela-data');
            const valorInput = linha.querySelector('.fin-parcela-valor');
            return {
              idx,
              data: dataInput ? dataInput.value : '',
              valor: valorInput ? Number(valorInput.value) : 0,
            };
          });
          if (parcelasEditadas.some(p => !p.data || p.valor <= 0)) {
            setMsg('statusModalFinanceiro', 'Preencha data e valor de todas as parcelas.', false);
            return;
          }
          const somaParcelas = parcelasEditadas.reduce((acc, p) => acc + p.valor, 0);
          if (Math.abs(somaParcelas - valor) > 0.01) {
            setMsg('statusModalFinanceiro', 'A soma das parcelas deve ser igual ao valor total.', false);
            return;
          }

          const idsCriados = [];

          for (const parcela of parcelasEditadas) {
            const descricaoParcela = parcelas > 1 ? `${descricao} (${parcela.idx + 1}/${parcelas})` : descricao;
            const metadados = [
              `DOC:${documento_original || '-'}`,
              `EMISSAO:${data_emissao}`,
              `GRUPO:${grupoNome || grupoId}`,
              `PLANO:${planoNome || planoId}`,
              `GRUPO_CONTA:${grupoContaNome || grupoContaId}`,
              `SUBGRUPO_CONTA:${subgrupoContaNome || subgrupoContaId}`,
            ].join(' | ');

            const payload = {
              descricao: descricaoParcela,
              valor: parcela.valor,
              categoria_id,
              centro_custos_id,
              fornecedor_id: parte_id,
              conta_destino_id: liquidacaoImediata ? contaLiquidacaoId : null,
              cartao_id: pagCartao ? cartaoFinId : null,
              data_vencimento: parcela.data,
              comprovante_url: metadados,
              status: liquidacaoImediata ? 'pago' : 'pendente',
              data_pagamento: liquidacaoImediata ? dataLiquidacao : null
            };
            const res = await api('/contas-pagar', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload)
            });
            idsCriados.push(res.id);
          }
          if (liquidacaoImediata) {
            setMsg('statusModalFinanceiro', `${idsCriados.length} conta(s) registrada(s) com pagamento imediato. IDs: ${idsCriados.join(', ')}`);
            setMsg('statusFinanceiro', `${idsCriados.length} conta(s) enviada(s) para Contas Pagas e conciliacao pendente.`);
          } else {
            setMsg('statusModalFinanceiro', `${idsCriados.length} conta(s) a pagar criada(s). IDs: ${idsCriados.join(', ')}`);
            setMsg('statusFinanceiro', `${idsCriados.length} conta(s) a pagar criada(s) com sucesso.`);
          }
        } else {
          const payload = {
            descricao,
            valor,
            categoria_id,
            centro_custos_id,
            cliente_id: parte_id,
            conta_destino_id: liquidacaoImediata ? contaLiquidacaoId : null,
            data_vencimento: data_vencimento || data_emissao,
            comprovante_url: documento_original || null,
            status: liquidacaoImediata ? 'recebido' : 'pendente',
            data_recebimento: liquidacaoImediata ? dataLiquidacao : null
          };
          const res = await api('/contas-receber', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          if (liquidacaoImediata) {
            setMsg('statusModalFinanceiro', `Conta registrada com recebimento imediato (ID ${res.id}).`);
            setMsg('statusFinanceiro', `Conta enviada para Contas Recebidas e conciliacao pendente (ID ${res.id}).`);
          } else {
            setMsg('statusModalFinanceiro', `Conta a receber criada com ID ${res.id}.`);
            setMsg('statusFinanceiro', `Conta a receber criada com ID ${res.id}.`);
          }
        }
        await carregarTudo();
        fecharModalFinanceiro();
      } catch (err) {
        setMsg('statusModalFinanceiro', err.message, false);
      }
    }

    async function salvarCadastroModal() {
      const isPessoa = origemCadastroModal === 'pessoas';
      const payload = {
        cnpj: document.getElementById('editCnpj').value.trim(),
        contexto: isPessoa ? 'pessoas' : 'geral',
        razao_social: document.getElementById('editRazao').value.trim(),
        cidade_uf: document.getElementById('editCidadeUf').value.trim() || null,
        nome_fantasia: document.getElementById('editNomeFantasia').value.trim() || null,
        endereco: document.getElementById('editEndereco').value.trim(),
        telefone: document.getElementById('editTelefone').value.trim(),
        cep: document.getElementById('editCep').value.trim(),
        is_cliente: isPessoa ? document.getElementById('editIsCliente').checked : false,
        is_funcionario: isPessoa ? document.getElementById('editIsFuncionario').checked : false,
        is_fornecedor: isPessoa ? document.getElementById('editIsFornecedor').checked : false,
        is_vendedor: isPessoa ? document.getElementById('editIsVendedor').checked : false,
        chave_pix: isPessoa && document.getElementById('editIsVendedor').checked ? (document.getElementById('editChavePix').value.trim() || null) : null,
        vendedor_comissionado: isPessoa ? document.getElementById('editVendedorComissionado').checked : false,
      };
      if (!payload.cnpj || !payload.razao_social || !payload.endereco || !payload.telefone || !payload.cep) {
        setMsg('statusEdicao', 'Preencha todos os campos obrigatorios.', false);
        return;
      }
      try {
        const isEdicao = !!cadastroEditId;
        const endpoint = isEdicao ? `/cadastros-gerais/${cadastroEditId}` : '/cadastros-gerais';
        const method = isEdicao ? 'PUT' : 'POST';
        const res = await api(endpoint, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        setMsg('statusEdicao', isEdicao ? `Cadastro ${res.id} alterado com sucesso.` : `Cadastro ${res.id} criado com sucesso.`);
        if (origemCadastroModal === 'geral') {
          setMsg('statusGeral', isEdicao ? `Dados da empresa atualizados (ID ${res.id}).` : `Dados da empresa cadastrados (ID ${res.id}).`);
          await carregarEmpresaPadrao();
        } else {
          setMsg('statusCadastro', isEdicao ? `Alteracoes salvas para o cadastro ID ${res.id}.` : `Novo cadastro criado com ID ${res.id}.`);
        }
        fecharModalEdicao();
        await listarCadastros();
      } catch (err) {
        setMsg('statusEdicao', err.message, false);
      }
    }

    async function excluirCadastroSelecionado() {
      if (!cadastroSelecionadoId) {
        setMsg('statusCadastro', 'Selecione um cadastro antes de excluir.', false);
        return;
      }
      if (!(await validarPermissaoExclusao())) return;
      const cadastro = cadastrosCache.get(cadastroSelecionadoId);
      const nome = cadastro ? cadastro.razao_social : `ID ${cadastroSelecionadoId}`;
      const confirmou = window.confirm(`Confirma exclusao do cadastro ${nome}?`);
      if (!confirmou) return;
      try {
        await api(`/cadastros-gerais/${cadastroSelecionadoId}`, { method: 'DELETE' });
        setMsg('statusCadastro', 'Cadastro excluido com sucesso.');
        cadastroSelecionadoId = null;
        await listarCadastros();
      } catch (err) {
        setMsg('statusCadastro', `Falha ao excluir: ${err.message}`, false);
      }
    }

    async function carregarTudo() {
      try {
        if (!usuariosSistemaCache.length) {
          await listarUsuariosSistema();
        }
        const tipo = tipoFinanceiroAtual();
        const endpoint = tipo === 'pagar' ? '/contas-pagar' : '/contas-receber';
        const [contas, partes] = await Promise.all(
          tipo === 'pagar'
            ? [api(endpoint), api('/cadastros-gerais?contexto=pessoas')]
            : [api(endpoint), api('/clientes')]
        );
        partesMapFinanceiroCache.clear();
        if (tipo === 'pagar') {
          partes
            .filter(item => !!item.is_fornecedor)
            .forEach(item => partesMapFinanceiroCache.set(item.id, item.razao_social || `Fornecedor ${item.id}`));
        } else {
          partes.forEach(item => partesMapFinanceiroCache.set(item.id, item.nome || `Cliente ${item.id}`));
        }

        contasFinanceiroCache = contas.slice();
        const resumoMap = new Map();
        contas.filter(conta => isContaExibidaNaAba(conta)).forEach(conta => {
          const parteId = tipo === 'pagar' ? conta.fornecedor_id : conta.cliente_id;
          if (!parteId) return;
          const atual = resumoMap.get(parteId) || { parteId, nome: partesMapFinanceiroCache.get(parteId) || `Codigo ${parteId}`, qtd: 0, total: 0, temVencida: false };
          atual.qtd += 1;
          atual.total += Number(conta.valor || 0);
          if (isContaVencida(conta)) atual.temVencida = true;
          resumoMap.set(parteId, atual);
        });
        resumoPartesFinanceiroCache = Array.from(resumoMap.values()).sort((a, b) => a.parteId - b.parteId);
        if (parteFinanceiroSelecionadaId && !resumoMap.has(parteFinanceiroSelecionadaId)) {
          parteFinanceiroSelecionadaId = null;
        }
        renderResumoPartesFinanceiro();
        renderContasFinanceiro();
        await carregarIndicadoresOnixHome();
        await carregarEventoHome();
      } catch (err) {
        setMsg('statusFinanceiro', `Falha ao carregar financeiro: ${err.message}`, false);
      }
    }

    function normalizarDataRelatorio(dataTexto) {
      const valor = String(dataTexto || '').slice(0, 10);
      return valor || '';
    }

    function escapeHtmlRelatorio(texto) {
      return String(texto || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function escapeXml(texto) {
      return String(texto || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
    }

    function tituloRelatorioPorTipo(tipo) {
      if (tipo === 'pagar_abertas') return 'Relatorio de Contas a Pagar (Abertas)';
      if (tipo === 'receber_abertas') return 'Relatorio de Contas a Receber (Abertas)';
      if (tipo === 'pagas') return 'Relatorio de Contas Pagas';
      if (tipo === 'recebidas') return 'Relatorio de Contas Recebidas';
      if (tipo === 'saldos_bancos') return 'Relatorio de Saldos Bancarios';
      if (tipo === 'cadastros_pessoas') return 'Relatorio de Cadastros (Pessoas)';
      if (tipo === 'produtos') return 'Relatorio de Produtos';
      if (tipo === 'vendas_pedidos') return 'Relatorio de Vendas - Pedidos';
      if (tipo === 'vendas_orcamentos') return 'Relatorio de Vendas - Orcamentos';
      if (tipo === 'vendas_nfe') return 'Relatorio de Vendas - Notas NF-e';
      if (tipo === 'vendas_nfse') return 'Relatorio de Vendas - Notas NFS-e';
      if (tipo === 'faturas_abertas') return 'Relatorio de Faturas em Aberto';
      if (tipo === 'faturas_pagas') return 'Relatorio de Faturas Pagas';
      if (tipo === 'cartoes_credito') return 'Relatorio de Cartoes de Credito';
      if (tipo === 'estoque_posicao') return 'Relatorio de Posicao Atual de Estoque';
      if (tipo === 'estoque_compras') return 'Relatorio de Compras de Estoque';
      if (tipo === 'estoque_ajustes') return 'Relatorio de Ajustes de Estoque';
      if (tipo === 'usuarios_sistema') return 'Relatorio de Usuarios do Sistema';
      return 'Relatorio Financeiro Geral';
    }

    function colunasRelatorioPorTipo(tipo) {
      const baseFinanceiro = [
        { key: 'tipo', label: 'Tipo' },
        { key: 'id', label: 'ID' },
        { key: 'parte', label: 'Parte/Conta' },
        { key: 'descricao', label: 'Descricao' },
        { key: 'data_vencimento', label: 'Vencimento' },
        { key: 'data_baixa', label: 'Baixa/Receb.' },
        { key: 'status', label: 'Status', tag: true },
        { key: 'conta_corrente', label: 'Conta Corrente' },
        { key: 'valor', label: 'Valor', money: true },
      ];
      if (tipo === 'cadastros_pessoas') {
        return [
          { key: 'id', label: 'ID' },
          { key: 'parte', label: 'Razao Social' },
          { key: 'descricao', label: 'Fantasia / Documento' },
          { key: 'conta_corrente', label: 'Cidade / UF' },
          { key: 'status', label: 'Status', tag: true },
          { key: 'data_vencimento', label: 'Criado em' },
        ];
      }
      if (tipo === 'produtos') {
        return [
          { key: 'id', label: 'ID' },
          { key: 'parte', label: 'Produto' },
          { key: 'descricao', label: 'SKU / Categoria' },
          { key: 'conta_corrente', label: 'Unidade' },
          { key: 'status', label: 'Status', tag: true },
          { key: 'valor', label: 'Preco', money: true },
        ];
      }
      if (tipo.indexOf('vendas_') === 0) {
        return [
          { key: 'id', label: 'ID' },
          { key: 'descricao', label: 'Numero / Tipo' },
          { key: 'parte', label: 'Cliente' },
          { key: 'data_vencimento', label: 'Emissao' },
          { key: 'status', label: 'Status', tag: true },
          { key: 'conta_corrente', label: 'Pagamento' },
          { key: 'valor', label: 'Total', money: true },
        ];
      }
      if (tipo === 'faturas_abertas' || tipo === 'faturas_pagas') {
        return [
          { key: 'id', label: 'ID' },
          { key: 'parte', label: 'Cartao' },
          { key: 'descricao', label: 'Mes / Fechamento' },
          { key: 'data_vencimento', label: 'Vencimento' },
          { key: 'data_baixa', label: 'Pagamento' },
          { key: 'status', label: 'Status', tag: true },
          { key: 'valor', label: 'Valor', money: true },
        ];
      }
      if (tipo === 'cartoes_credito') {
        return [
          { key: 'id', label: 'ID' },
          { key: 'parte', label: 'Cartao / Conta' },
          { key: 'descricao', label: 'Fechamento / Vencimento' },
          { key: 'conta_corrente', label: 'Banco' },
          { key: 'status', label: 'Status', tag: true },
          { key: 'valor', label: 'Saldo Usado', money: true },
        ];
      }
      if (tipo.indexOf('estoque_') === 0) {
        return [
          { key: 'tipo', label: 'Tipo' },
          { key: 'id', label: 'ID' },
          { key: 'parte', label: 'Item' },
          { key: 'descricao', label: 'Descricao' },
          { key: 'data_vencimento', label: 'Data' },
          { key: 'status', label: 'Status', tag: true },
          { key: 'valor', label: 'Quantidade/Valor', money: true },
        ];
      }
      if (tipo === 'usuarios_sistema') {
        return [
          { key: 'id', label: 'ID' },
          { key: 'parte', label: 'Nome' },
          { key: 'descricao', label: 'Login' },
          { key: 'conta_corrente', label: 'Perfil' },
          { key: 'status', label: 'Status', tag: true },
          { key: 'data_vencimento', label: 'Criado em' },
        ];
      }
      return baseFinanceiro;
    }

    function renderCabecalhoRelatorio(colunas) {
      const tr = document.getElementById('relatorioHeadRow');
      if (!tr) return;
      tr.innerHTML = '';
      (Array.isArray(colunas) ? colunas : []).forEach(col => {
        const th = document.createElement('th');
        th.textContent = col.label || col.key || '';
        tr.appendChild(th);
      });
    }

    async function preencherFiltrosRelatorio() {
      try {
        const [cadastros, clientes, contasCorrentes] = await Promise.all([
          api('/cadastros-gerais?contexto=pessoas'),
          api('/clientes'),
          api('/contas-correntes'),
        ]);
        const selFornecedor = document.getElementById('relFornecedor');
        const selCliente = document.getElementById('relCliente');
        const selConta = document.getElementById('relContaCorrente');
        selFornecedor.innerHTML = '<option value="">Todos</option>';
        selCliente.innerHTML = '<option value="">Todos</option>';
        selConta.innerHTML = '<option value="">Todas</option>';

        cadastros
          .filter(item => !!item.is_fornecedor)
          .forEach(item => {
            const opt = document.createElement('option');
            opt.value = String(item.id);
            opt.textContent = `${item.id} - ${item.razao_social || 'Fornecedor'}`;
            selFornecedor.appendChild(opt);
          });
        clientes.forEach(item => {
          const opt = document.createElement('option');
          opt.value = String(item.id);
          opt.textContent = `${item.id} - ${item.nome || 'Cliente'}`;
          selCliente.appendChild(opt);
        });
        contasCorrentes.forEach(item => {
          const opt = document.createElement('option');
          opt.value = String(item.id);
          const nomeConta = (item.nome_conta || '').trim();
          opt.textContent = nomeConta
            ? `${item.id} - ${nomeConta}`
            : `${item.id} - ${item.banco} / ${item.numero}`;
          selConta.appendChild(opt);
        });
      } catch (err) {
        setMsg('statusRelatorios', `Falha ao carregar filtros: ${err.message}`, false);
      }
    }

    function limparFiltrosRelatorio() {
      document.getElementById('relTipo').value = 'geral';
      document.getElementById('relDataInicio').value = '';
      document.getElementById('relDataFim').value = '';
      document.getElementById('relFornecedor').value = '';
      document.getElementById('relCliente').value = '';
      document.getElementById('relContaCorrente').value = '';
      document.getElementById('relStatus').value = '';
      document.getElementById('relTextoLivre').value = '';
      window.gerarRelatorioFinanceiro();
    }

    function exportarRelatorioODF() {
      if (!relatorioRowsCache.length) {
        setMsg('statusRelatorios', 'Gere um relatorio antes de exportar em ODF.', false);
        return;
      }
      const meta = relatorioMetaCache || {};
      const colunas = relatorioColunasAtivas && relatorioColunasAtivas.length ? relatorioColunasAtivas : [{ key: 'id', label: 'ID' }];
      const linhas = relatorioRowsCache.map(item => {
        const textoLinha = colunas.map(col => {
          const val = col.money ? moeda(Number(item[col.key] || 0)) : (item[col.key] == null || item[col.key] === '' ? '-' : String(item[col.key]));
          return `${col.label}: ${val}`;
        }).join(' | ');
        return `<text:p>${escapeXml(textoLinha)}</text:p>`;
      }).join('\\n');

      const conteudoFodt = `<?xml version="1.0" encoding="UTF-8"?>
<office:document
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  office:version="1.2">
  <office:body>
    <office:text>
      <text:h text:outline-level="1">${escapeXml(meta.titulo || 'Relatorio Financeiro')}</text:h>
      <text:p><text:span text:style-name="T1">Empresa:</text:span> ${escapeXml(meta.empresaNome || '-')}</text:p>
      <text:p><text:span text:style-name="T1">CNPJ:</text:span> ${escapeXml(meta.empresaCnpj || '-')}</text:p>
      <text:p><text:span text:style-name="T1">Telefone:</text:span> ${escapeXml(meta.empresaTelefone || '-')}</text:p>
      <text:p><text:span text:style-name="T1">Endereco:</text:span> ${escapeXml(meta.empresaEndereco || '-')}</text:p>
      <text:p><text:span text:style-name="T1">Gerado em:</text:span> ${escapeXml(meta.geradoEm || '-')}</text:p>
      <text:p><text:span text:style-name="T1">Resumo:</text:span> ${escapeXml(meta.resumo || '-')}</text:p>
      <text:p> </text:p>
      ${linhas}
    </office:text>
  </office:body>
</office:document>`;

      const blob = new Blob([conteudoFodt], { type: 'application/vnd.oasis.opendocument.text' });
      const url = URL.createObjectURL(blob);
      const nome = `${(meta.titulo || 'relatorio').toLowerCase().replace(/[^a-z0-9]+/g, '_')}_${new Date().toISOString().slice(0, 10)}.fodt`;
      const a = document.createElement('a');
      a.href = url;
      a.download = nome;
      a.target = '_blank';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      setMsg('statusRelatorios', 'Relatorio ODF gerado e aberto para download.');
    }

    async function gerarRelatorioFinanceiro(abrirOdf = false) {
      try {
        const tipo = document.getElementById('relTipo').value || 'geral';
        const dataInicio = document.getElementById('relDataInicio').value;
        const dataFim = document.getElementById('relDataFim').value;
        const fornecedorId = Number(document.getElementById('relFornecedor').value) || 0;
        const clienteId = Number(document.getElementById('relCliente').value) || 0;
        const contaId = Number(document.getElementById('relContaCorrente').value) || 0;
        const status = (document.getElementById('relStatus').value || '').trim().toLowerCase();
        const textoLivre = (document.getElementById('relTextoLivre').value || '').trim().toLowerCase();

        const [
          contasPagar,
          contasReceber,
          cadastros,
          clientes,
          contasCorrentes,
          empresaGeral,
          produtos,
          vendas,
          cartoesCredito,
          faturasCartao,
          posicaoEstoque,
          comprasEstoque,
          ajustesEstoque,
          usuariosSistema,
        ] = await Promise.all([
          api('/contas-pagar'),
          api('/contas-receber'),
          api('/cadastros-gerais?contexto=pessoas'),
          api('/clientes'),
          api('/contas-correntes'),
          api('/cadastros-gerais?contexto=geral'),
          api('/produtos'),
          api('/vendas'),
          api('/cartoes-credito'),
          api('/cartoes-credito/faturas'),
          api('/estoque/posicao-atual'),
          api('/estoque/compras'),
          api('/estoque/ajustes'),
          api('/usuarios'),
        ]);

        const fornecedoresMap = new Map();
        cadastros
          .filter(item => !!item.is_fornecedor)
          .forEach(item => fornecedoresMap.set(item.id, item.razao_social || `Fornecedor ${item.id}`));
        const clientesMap = new Map();
        clientes.forEach(item => clientesMap.set(item.id, item.nome || `Cliente ${item.id}`));
        const contasMap = new Map();
        contasCorrentes.forEach(item => {
          const nomeConta = (item.nome_conta || '').trim();
          contasMap.set(item.id, nomeConta || `${item.banco} / ${item.numero}`);
        });

        const linhasPagar = contasPagar.map(item => ({
          tipo: 'PAGAR',
          id: item.id,
          parte: item.fornecedor_id ? (fornecedoresMap.get(item.fornecedor_id) || `Fornecedor ${item.fornecedor_id}`) : '-',
          descricao: item.descricao || '-',
          data_vencimento: normalizarDataRelatorio(item.data_vencimento),
          data_baixa: normalizarDataRelatorio(item.data_pagamento),
          status: String(item.status || '').toLowerCase(),
          conta_corrente: item.conta_destino_id ? (contasMap.get(item.conta_destino_id) || `Conta ${item.conta_destino_id}`) : '-',
          valor: Number(item.valor || 0),
          fornecedor_id: item.fornecedor_id || null,
          cliente_id: null,
          conta_destino_id: item.conta_destino_id || null,
        }));
        const linhasReceber = contasReceber.map(item => ({
          tipo: 'RECEBER',
          id: item.id,
          parte: item.cliente_id ? (clientesMap.get(item.cliente_id) || `Cliente ${item.cliente_id}`) : '-',
          descricao: item.descricao || '-',
          data_vencimento: normalizarDataRelatorio(item.data_vencimento),
          data_baixa: normalizarDataRelatorio(item.data_recebimento),
          status: String(item.status || '').toLowerCase(),
          conta_corrente: item.conta_destino_id ? (contasMap.get(item.conta_destino_id) || `Conta ${item.conta_destino_id}`) : '-',
          valor: Number(item.valor || 0),
          fornecedor_id: null,
          cliente_id: item.cliente_id || null,
          conta_destino_id: item.conta_destino_id || null,
        }));
        const linhasBancos = contasCorrentes.map(item => ({
          tipo: 'BANCO',
          id: item.id,
          parte: (item.nome_conta || `${item.banco} / ${item.numero}`),
          descricao: `Agencia ${item.agencia || '-'} - Conta ${item.numero || '-'}`,
          data_vencimento: '-',
          data_baixa: '-',
          status: item.ativa ? 'ativa' : 'inativa',
          conta_corrente: item.nome_conta || `${item.banco} / ${item.numero}`,
          valor: Number(item.saldo_atual || 0),
          fornecedor_id: null,
          cliente_id: null,
          conta_destino_id: item.id,
        }));
        const linhasCadastros = cadastros.map(item => ({
          tipo: 'CADASTRO',
          id: item.id,
          parte: item.razao_social || '-',
          descricao: `${item.nome_fantasia || '-'} | ${item.cnpj || item.cpf || '-'}`,
          data_vencimento: normalizarDataRelatorio(item.created_at || ''),
          data_baixa: '-',
          status: item.ativo === false ? 'inativo' : 'ativo',
          conta_corrente: `${item.cidade || '-'} / ${item.uf || '-'}`,
          valor: 0,
          fornecedor_id: item.is_fornecedor ? (item.id || null) : null,
          cliente_id: null,
          conta_destino_id: null,
        }));
        const linhasProdutos = produtos.map(item => ({
          tipo: 'PRODUTO',
          id: item.id,
          parte: item.nome || '-',
          descricao: `${item.sku || '-'} | ${item.categoria_nome || '-'}`,
          data_vencimento: '-',
          data_baixa: '-',
          status: item.ativo === false ? 'inativo' : 'ativo',
          conta_corrente: item.unidade || 'UN',
          valor: Number(item.preco_venda || 0),
          fornecedor_id: null,
          cliente_id: null,
          conta_destino_id: null,
        }));
        const linhasVendas = vendas.map(item => ({
          tipo: 'VENDA',
          id: item.id,
          parte: item.cliente_nome || '-',
          descricao: `Numero ${item.numero || '-'} | ${item.tipo || '-'}`,
          data_vencimento: normalizarDataRelatorio(item.data_emissao || ''),
          data_baixa: normalizarDataRelatorio(item.updated_at || ''),
          status: String(item.status || '').toLowerCase(),
          conta_corrente: item.forma_pagamento || '-',
          valor: Number(item.valor_total || 0),
          fornecedor_id: null,
          cliente_id: item.cliente_id || null,
          conta_destino_id: null,
        }));
        const linhasFaturas = faturasCartao.map(item => ({
          tipo: 'FATURA',
          id: item.id,
          parte: item.cartao_nome || item.cartao_banco || `Cartao ${item.cartao_id || '-'}`,
          descricao: `Mes ${item.mes_referencia || '-'} | Fechamento ${item.fechamento_dia || '-'}`,
          data_vencimento: normalizarDataRelatorio(item.data_vencimento || ''),
          data_baixa: normalizarDataRelatorio(item.data_pagamento || ''),
          status: String(item.status || '').toLowerCase(),
          conta_corrente: '-',
          valor: Number(item.valor || 0),
          fornecedor_id: null,
          cliente_id: null,
          conta_destino_id: null,
        }));
        const linhasCartoes = cartoesCredito.map(item => ({
          tipo: 'CARTAO',
          id: item.id,
          parte: item.nome_conta || `${item.banco || '-'} / ${item.numero || '-'}`,
          descricao: `Fechamento ${item.fechamento_dia || '-'} | Vencimento ${item.vencimento_dia || '-'}`,
          data_vencimento: '-',
          data_baixa: '-',
          status: item.ativo ? 'ativo' : 'inativo',
          conta_corrente: item.banco || '-',
          valor: Number(item.saldo_usado || 0),
          fornecedor_id: null,
          cliente_id: null,
          conta_destino_id: null,
        }));
        const linhasPosicaoEstoque = posicaoEstoque.map(item => ({
          tipo: 'ESTOQUE',
          id: item.produto_id,
          parte: item.nome || '-',
          descricao: `Unidade ${item.unidade || 'UN'}`,
          data_vencimento: '-',
          data_baixa: '-',
          status: 'atual',
          conta_corrente: 'Posicao',
          valor: Number(item.quantidade || 0),
          fornecedor_id: null,
          cliente_id: null,
          conta_destino_id: null,
        }));
        const linhasComprasEstoque = comprasEstoque.map(item => ({
          tipo: 'COMPRA_EST',
          id: item.id,
          parte: item.fornecedor_nome || '-',
          descricao: `Nota ${item.numero_nota || '-'} | ${item.tipo_lancamento || '-'}`,
          data_vencimento: normalizarDataRelatorio(item.data_emissao || ''),
          data_baixa: normalizarDataRelatorio(item.created_at || ''),
          status: item.entrada_nota ? 'entrada_nota' : 'compra_simples',
          conta_corrente: `${item.itens_count || 0} itens`,
          valor: Number(item.total || 0),
          fornecedor_id: item.fornecedor_id || null,
          cliente_id: null,
          conta_destino_id: null,
        }));
        const linhasAjustesEstoque = ajustesEstoque.map(item => ({
          tipo: 'AJUSTE_EST',
          id: item.id,
          parte: item.produto_nome || `Produto ${item.produto_id || '-'}`,
          descricao: item.motivo || '-',
          data_vencimento: normalizarDataRelatorio(item.created_at || ''),
          data_baixa: '-',
          status: 'ajustado',
          conta_corrente: 'Ajuste',
          valor: Number(item.novo_estoque || 0),
          fornecedor_id: null,
          cliente_id: null,
          conta_destino_id: null,
        }));
        const linhasUsuarios = usuariosSistema.map(item => ({
          tipo: 'USUARIO',
          id: item.id,
          parte: item.nome || '-',
          descricao: item.login || '-',
          data_vencimento: normalizarDataRelatorio(item.created_at || ''),
          data_baixa: '-',
          status: item.ativo ? 'ativo' : 'inativo',
          conta_corrente: item.perfil || '-',
          valor: 0,
          fornecedor_id: null,
          cliente_id: null,
          conta_destino_id: null,
        }));

        let base = [];
        if (tipo === 'pagar_abertas') {
          base = linhasPagar.filter(x => x.status !== 'pago');
        } else if (tipo === 'receber_abertas') {
          base = linhasReceber.filter(x => x.status !== 'recebido');
        } else if (tipo === 'pagas') {
          base = linhasPagar.filter(x => x.status === 'pago');
        } else if (tipo === 'recebidas') {
          base = linhasReceber.filter(x => x.status === 'recebido');
        } else if (tipo === 'saldos_bancos') {
          base = linhasBancos;
        } else if (tipo === 'cadastros_pessoas') {
          base = linhasCadastros;
        } else if (tipo === 'produtos') {
          base = linhasProdutos;
        } else if (tipo === 'vendas_pedidos') {
          base = linhasVendas.filter(x => x.descricao.toLowerCase().includes('pedido'));
        } else if (tipo === 'vendas_orcamentos') {
          base = linhasVendas.filter(x => x.descricao.toLowerCase().includes('orcamento'));
        } else if (tipo === 'vendas_nfe') {
          base = linhasVendas.filter(x => x.descricao.toLowerCase().includes('nfe'));
        } else if (tipo === 'vendas_nfse') {
          base = linhasVendas.filter(x => x.descricao.toLowerCase().includes('nfse'));
        } else if (tipo === 'faturas_abertas') {
          base = linhasFaturas.filter(x => x.status !== 'paga');
        } else if (tipo === 'faturas_pagas') {
          base = linhasFaturas.filter(x => x.status === 'paga');
        } else if (tipo === 'cartoes_credito') {
          base = linhasCartoes;
        } else if (tipo === 'estoque_posicao') {
          base = linhasPosicaoEstoque;
        } else if (tipo === 'estoque_compras') {
          base = linhasComprasEstoque;
        } else if (tipo === 'estoque_ajustes') {
          base = linhasAjustesEstoque;
        } else if (tipo === 'usuarios_sistema') {
          base = linhasUsuarios;
        } else {
          base = [...linhasPagar, ...linhasReceber];
        }

        const filtrado = base.filter(item => {
          if (fornecedorId && item.fornecedor_id !== fornecedorId) return false;
          if (clienteId && item.cliente_id !== clienteId) return false;
          if (contaId && item.conta_destino_id !== contaId) return false;
          if (status && item.status !== status) return false;

          const dataRef = item.data_baixa && item.data_baixa !== '-' ? item.data_baixa : item.data_vencimento;
          if (dataInicio && dataRef && dataRef !== '-' && dataRef < dataInicio) return false;
          if (dataFim && dataRef && dataRef !== '-' && dataRef > dataFim) return false;

          if (textoLivre) {
            const bloco = `${item.parte} ${item.descricao} ${item.conta_corrente}`.toLowerCase();
            if (!bloco.includes(textoLivre)) return false;
          }
          return true;
        });

        relatorioColunasAtivas = colunasRelatorioPorTipo(tipo);
        renderCabecalhoRelatorio(relatorioColunasAtivas);
        relatorioRowsCache = filtrado.slice();
        const tbody = document.getElementById('tbRelatoriosFinanceiro');
        tbody.innerHTML = '';
        let total = 0;
        filtrado.forEach(item => {
          total += Number(item.valor || 0);
          const tr = document.createElement('tr');
          tr.innerHTML = '';
          relatorioColunasAtivas.forEach(col => {
            const td = document.createElement('td');
            const bruto = item[col.key];
            if (col.money) {
              const n = Number(bruto || 0);
              if (n < 0) td.className = 'cc-saldo-negativo';
              td.textContent = moeda(n);
            } else if (col.tag) {
              const span = document.createElement('span');
              span.className = 'tag';
              span.textContent = bruto == null || bruto === '' ? '-' : String(bruto);
              td.appendChild(span);
            } else {
              td.textContent = bruto == null || bruto === '' ? '-' : String(bruto);
            }
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
        document.getElementById('resumoRelatorioFinanceiro').textContent = `Total: ${moeda(total)} | Registros: ${filtrado.length}`;
        setMsg('statusRelatorios', `${filtrado.length} registro(s) encontrado(s).`);
        const empresa = Array.isArray(empresaGeral) && empresaGeral.length ? empresaGeral[0] : null;
        relatorioMetaCache = {
          titulo: tituloRelatorioPorTipo(tipo),
          empresaNome: empresa ? (empresa.razao_social || 'Empresa') : 'Empresa nao informada',
          empresaCnpj: empresa ? (empresa.cnpj || '-') : '-',
          empresaTelefone: empresa ? (empresa.telefone || '-') : '-',
          empresaEndereco: empresa ? (empresa.endereco || '-') : '-',
          geradoEm: new Date().toLocaleString('pt-BR'),
          resumo: `Total: ${moeda(total)} | Registros: ${filtrado.length}`,
        };
        if (abrirOdf) {
          exportarRelatorioODF();
        }
      } catch (err) {
        setMsg('statusRelatorios', `Falha ao gerar relatorio: ${err.message}`, false);
      }
    }

    function exportarRelatorioPDF() {
      if (!relatorioRowsCache.length) {
        setMsg('statusRelatorios', 'Gere um relatorio antes de exportar.', false);
        return;
      }
      const dataHora = new Date().toLocaleString('pt-BR');
      const resumo = relatorioMetaCache.resumo || document.getElementById('resumoRelatorioFinanceiro').textContent || '';
      const colunas = relatorioColunasAtivas && relatorioColunasAtivas.length ? relatorioColunasAtivas : [{ key: 'id', label: 'ID' }];
      const cabecalho = colunas.map(col => `<th>${escapeHtmlRelatorio(col.label || col.key || '')}</th>`).join('');
      const linhas = relatorioRowsCache.map(item => {
        const tds = colunas.map(col => {
          if (col.money) return `<td>${escapeHtmlRelatorio(moeda(Number(item[col.key] || 0)))}</td>`;
          const val = item[col.key] == null || item[col.key] === '' ? '-' : String(item[col.key]);
          return `<td>${escapeHtmlRelatorio(val)}</td>`;
        }).join('');
        return `<tr>${tds}</tr>`;
      }).join('');

      const janela = window.open('', '_blank', 'width=1200,height=800');
      if (!janela) {
        setMsg('statusRelatorios', 'Nao foi possivel abrir a janela de exportacao.', false);
        return;
      }
      janela.document.write(`
        <html>
          <head>
            <title>Relatorio Financeiro</title>
            <style>
              body { font-family: Arial, sans-serif; padding: 20px; color: #111; }
              h2 { margin: 0 0 8px 0; }
              .muted { color: #555; margin-bottom: 10px; }
              table { width: 100%; border-collapse: collapse; font-size: 12px; }
              th, td { border: 1px solid #ddd; padding: 6px; text-align: left; }
              th { background: #f4f4f4; }
            </style>
          </head>
          <body>
            <h2>${escapeHtmlRelatorio(relatorioMetaCache.titulo || 'Relatorio Financeiro')}</h2>
            <div class="muted"><strong>Empresa:</strong> ${escapeHtmlRelatorio(relatorioMetaCache.empresaNome || '-')}</div>
            <div class="muted"><strong>CNPJ:</strong> ${escapeHtmlRelatorio(relatorioMetaCache.empresaCnpj || '-')} | <strong>Telefone:</strong> ${escapeHtmlRelatorio(relatorioMetaCache.empresaTelefone || '-')}</div>
            <div class="muted"><strong>Endereco:</strong> ${escapeHtmlRelatorio(relatorioMetaCache.empresaEndereco || '-')}</div>
            <div class="muted"><strong>Gerado em:</strong> ${escapeHtmlRelatorio(relatorioMetaCache.geradoEm || dataHora)}</div>
            <div class="muted">${escapeHtmlRelatorio(resumo)}</div>
            <table>
              <thead>
                <tr>${cabecalho}</tr>
              </thead>
              <tbody>${linhas}</tbody>
            </table>
          </body>
        </html>
      `);
      janela.document.close();
      janela.focus();
      janela.print();
    }

    window.abrirOnixHome = abrirOnixHome;
    window.abrirFinanceiro = abrirFinanceiro;
    window.carregarIndicadoresOnixHome = carregarIndicadoresOnixHome;
    window.abrirCadastro = abrirCadastro;
    window.voltarDashboard = voltarDashboard;
    window.abrirRelatorios = abrirRelatorios;
    window.abrirFaturas = abrirFaturas;
    window.abrirVendas = abrirVendas;
    window.abrirEstoque = abrirEstoque;
    window.abrirProdutos = abrirProdutos;
    window.aplicarTema = aplicarTema;
    window.gerarRelatorioFinanceiro = gerarRelatorioFinanceiro;
    window.exportarRelatorioPDF = exportarRelatorioPDF;
    window.exportarRelatorioODF = exportarRelatorioODF;
    window.abrirModalNovoPedido = abrirModalNovoPedido;
    window.fecharModalNovoPedido = fecharModalNovoPedido;
    window.salvarVenda = salvarVenda;
    window.adicionarLinhaItemVenda = adicionarLinhaItemVenda;
    window.removerLinhaItemVenda = removerLinhaItemVenda;
    window.abrirModalProduto = abrirModalProduto;
    window.fecharModalProduto = fecharModalProduto;
    window.salvarProduto = salvarProduto;
    window.listarProdutosPainel = listarProdutosPainel;
    window.listarCategoriasProdutoPainel = listarCategoriasProdutoPainel;
    window.abrirModalEdicaoCategoriaProduto = abrirModalEdicaoCategoriaProduto;
    window.fecharModalCategoriaProduto = fecharModalCategoriaProduto;
    window.salvarModalCategoriaProduto = salvarModalCategoriaProduto;
    window.excluirCategoriaProdutoSelecionada = excluirCategoriaProdutoSelecionada;
    window.excluirProdutoCadastro = excluirProdutoCadastro;
    window.listarVendasPainel = listarVendasPainel;
    window.abrirModalEditarVenda = abrirModalEditarVenda;
    window.excluirVendaPainel = excluirVendaPainel;
    window.listarCondicoesPagamentoPainel = listarCondicoesPagamentoPainel;
    window.selecionarCondicaoPagamento = selecionarCondicaoPagamento;
    window.abrirModalNovaCondicaoPagamento = abrirModalNovaCondicaoPagamento;
    window.abrirModalEdicaoCondicaoPagamento = abrirModalEdicaoCondicaoPagamento;
    window.excluirCondicaoPagamentoSelecionada = excluirCondicaoPagamentoSelecionada;
    window.atualizarVisibilidadeVendedor = atualizarVisibilidadeVendedor;
    window.abrirAbaCadastro = abrirAbaCadastro;
    window.abrirAbaFaturas = abrirAbaFaturas;
    window.selecionarAbaFinanceiro = selecionarAbaFinanceiro;
    window.selecionarAbaVendas = selecionarAbaVendas;
    window.executarAcaoHomeConfig = executarAcaoHomeConfig;
    window.abrirModalConfigBancoSistema = abrirModalConfigBancoSistema;
    window.fecharModalConfigBancoSistema = fecharModalConfigBancoSistema;
    window.testarConfigBancoSistema = testarConfigBancoSistema;
    window.salvarConfigBancoSistema = salvarConfigBancoSistema;
    window.abrirModalAtualizacaoSistema = abrirModalAtualizacaoSistema;
    window.fecharModalAtualizacaoSistema = fecharModalAtualizacaoSistema;
    window.verificarAtualizacaoSistema = verificarAtualizacaoSistema;
    window.aplicarAtualizacaoSistema = aplicarAtualizacaoSistema;
    window.listarHistoricoAtualizacoesSistema = listarHistoricoAtualizacoesSistema;
    window.selecionarAtualizacaoHistorico = selecionarAtualizacaoHistorico;
    window.rollbackAtualizacaoSistemaSelecionada = rollbackAtualizacaoSistemaSelecionada;
    window.abrirModalEventoHome = abrirModalEventoHome;
    window.fecharModalEventoHome = fecharModalEventoHome;
    window.salvarConfiguracaoEventoHome = salvarConfiguracaoEventoHome;
    window.marcarEventoHomeExecutado = marcarEventoHomeExecutado;
    window.excluirFaturaPagaPainel = excluirFaturaPagaPainel;
    window.selecionarUsuarioSistema = selecionarUsuarioSistema;
    window.salvarUsuarioSistema = salvarUsuarioSistema;
    window.listarUsuariosSistema = listarUsuariosSistema;
    window.editarUsuarioSistemaSelecionado = editarUsuarioSistemaSelecionado;
    window.excluirUsuarioSistemaSelecionado = excluirUsuarioSistemaSelecionado;
    window.limparFormularioUsuarioSistema = limparFormularioUsuarioSistema;
    window.trocarUsuarioSessao = trocarUsuarioSessao;
    window.confirmarAuthExclusaoAdmin = confirmarAuthExclusaoAdmin;
    window.fecharModalAuthExclusao = fecharModalAuthExclusao;
    window.abrirModalCompraEstoque = abrirModalCompraEstoque;
    window.fecharModalCompraEstoque = fecharModalCompraEstoque;
    window.importarXmlCompraEstoque = importarXmlCompraEstoque;
    window.adicionarLinhaItemCompraEstoque = adicionarLinhaItemCompraEstoque;
    window.salvarCompraEstoque = salvarCompraEstoque;
    window.listarComprasEstoque = listarComprasEstoque;
    window.listarPosicaoAtualEstoque = listarPosicaoAtualEstoque;
    window.selecionarAbaEstoque = selecionarAbaEstoque;
    window.selecionarAbaContador = selecionarAbaContador;
    window.abrirEspacoContador = abrirEspacoContador;
    window.registrarStatusEnvioContador = registrarStatusEnvioContador;
    window.baixarRelatorioFinanceiroContador = baixarRelatorioFinanceiroContador;
    window.baixarRelatorioPagarContador = baixarRelatorioPagarContador;
    window.baixarRelatorioReceberContador = baixarRelatorioReceberContador;
    window.baixarRelatorioVendasContador = baixarRelatorioVendasContador;
    window.baixarRelatorioEstoqueContador = baixarRelatorioEstoqueContador;
    window.preencherProdutoAjustePorCodigo = preencherProdutoAjustePorCodigo;
    window.listarAjustesEstoque = listarAjustesEstoque;
    window.salvarAjusteEstoque = salvarAjusteEstoque;

    (function instalarAbasPainel() {
      var c = [
        ['abaBtnGeral', 'geral'],
        ['abaBtnPessoas', 'pessoas'],
        ['abaBtnProdutos', 'produtos'],
        ['abaBtnCatProd', 'catProd'],
        ['abaBtnCondPag', 'condPag'],
        ['abaBtnGrupo', 'grupo'],
        ['abaBtnPlano', 'plano'],
        ['abaBtnGrupoContas', 'grupoContas'],
        ['abaBtnContas', 'contas'],
        ['abaBtnUsuarios', 'usuarios'],
      ];
      var fa = [
        ['fatAbaCartoes', 'cartoes'],
        ['fatAbaFaturasLista', 'faturas'],
        ['fatAbaFaturasPagas', 'faturasPagas'],
      ];
      var fi = [
        ['finAbaPagar', 'pagar'],
        ['finAbaReceber', 'receber'],
        ['finAbaPagas', 'pagas'],
        ['finAbaRecebidas', 'recebidas'],
      ];
      var ve = [
        ['venAbaPedidos', 'pedidos'],
        ['venAbaOrcamentos', 'orcamentos'],
        ['venAbaNfe', 'nfe'],
        ['venAbaNfse', 'nfse'],
      ];
      var es = [
        ['estAbaCompra', 'compra'],
        ['estAbaPosicao', 'posicao'],
        ['estAbaAjuste', 'ajuste'],
      ];
      var ct = [
        ['ctrAbaChecklist', 'checklist'],
        ['ctrAbaFiscal', 'fiscal'],
        ['ctrAbaFinanceiro', 'financeiro'],
        ['ctrAbaEnvio', 'envio'],
      ];
      var hc = [
        ['homeCfgEmpresa', 'empresa'],
        ['homeCfgBanco', 'banco'],
        ['homeCfgNfe', 'nfe'],
        ['homeCfgAtualizacoes', 'atualizacoes'],
        ['homeCfgEvento', 'evento'],
        ['homeCfgBackup', 'backup'],
        ['homeCfgRestore', 'restore'],
      ];
      var i, par, el;
      for (i = 0; i < c.length; i++) {
        par = c[i];
        (function(id, a) {
          el = document.getElementById(id);
          if (!el) return;
          el.addEventListener('click', function(ev) {
            try {
              if (ev.stopPropagation) ev.stopPropagation();
              if (ev.preventDefault) ev.preventDefault();
            } catch (e2) {}
            if (typeof window.abrirAbaCadastro === 'function') window.abrirAbaCadastro(a);
          }, false);
        })(par[0], par[1]);
      }
      for (i = 0; i < fa.length; i++) {
        par = fa[i];
        (function(id, a) {
          el = document.getElementById(id);
          if (!el) return;
          el.addEventListener('click', function(ev) {
            try {
              if (ev.stopPropagation) ev.stopPropagation();
              if (ev.preventDefault) ev.preventDefault();
            } catch (e3) {}
            if (typeof window.abrirAbaFaturas === 'function') window.abrirAbaFaturas(a);
          }, false);
        })(par[0], par[1]);
      }
      for (i = 0; i < fi.length; i++) {
        par = fi[i];
        (function(id, a) {
          el = document.getElementById(id);
          if (!el) return;
          el.addEventListener('click', function(ev) {
            try {
              if (ev.stopPropagation) ev.stopPropagation();
              if (ev.preventDefault) ev.preventDefault();
            } catch (e4) {}
            if (typeof window.selecionarAbaFinanceiro === 'function') window.selecionarAbaFinanceiro(a);
          }, false);
        })(par[0], par[1]);
      }
      for (i = 0; i < ve.length; i++) {
        par = ve[i];
        (function(id, a) {
          el = document.getElementById(id);
          if (!el) return;
          el.addEventListener('click', function(ev) {
            try {
              if (ev.stopPropagation) ev.stopPropagation();
              if (ev.preventDefault) ev.preventDefault();
            } catch (e5) {}
            if (typeof window.selecionarAbaVendas === 'function') window.selecionarAbaVendas(a);
          }, false);
        })(par[0], par[1]);
      }
      for (i = 0; i < es.length; i++) {
        par = es[i];
        (function(id, a) {
          el = document.getElementById(id);
          if (!el) return;
          el.addEventListener('click', function(ev) {
            try {
              if (ev.stopPropagation) ev.stopPropagation();
              if (ev.preventDefault) ev.preventDefault();
            } catch (e6) {}
            if (typeof window.selecionarAbaEstoque === 'function') window.selecionarAbaEstoque(a);
          }, false);
        })(par[0], par[1]);
      }
      for (i = 0; i < ct.length; i++) {
        par = ct[i];
        (function(id, a) {
          el = document.getElementById(id);
          if (!el) return;
          el.addEventListener('click', function(ev) {
            try {
              if (ev.stopPropagation) ev.stopPropagation();
              if (ev.preventDefault) ev.preventDefault();
            } catch (e6) {}
            if (typeof window.selecionarAbaContador === 'function') window.selecionarAbaContador(a);
          }, false);
        })(par[0], par[1]);
      }
      for (i = 0; i < hc.length; i++) {
        par = hc[i];
        (function(id, a) {
          el = document.getElementById(id);
          if (!el) return;
          el.addEventListener('click', function(ev) {
            try {
              if (ev.stopPropagation) ev.stopPropagation();
              if (ev.preventDefault) ev.preventDefault();
            } catch (e6) {}
            if (typeof window.executarAcaoHomeConfig === 'function') window.executarAcaoHomeConfig(a);
          }, false);
        })(par[0], par[1]);
      }
      var btnHomeCfg = document.getElementById('btnHomeConfiguracoes');
      if (btnHomeCfg) {
        btnHomeCfg.addEventListener('click', function(ev) {
          try {
            if (ev.stopPropagation) ev.stopPropagation();
            if (ev.preventDefault) ev.preventDefault();
          } catch (e7) {}
          if (seletorHomeConfigVisivel) ocultarSeletorHomeConfig();
          else mostrarSeletorHomeConfig();
        }, false);
      }
    })();

    try {
      ocultarSeletorCardsCadastro();
      ocultarSeletorFaturas();
      ocultarSeletorFinanceiro();
      ocultarSeletorVendas();
      ocultarSeletorEstoque();
      ocultarSeletorContador();
      decorarTitulosSecaoPremium();
      inicializarTema();
      void carregarTudo();
      renderHistoricoOnixIa();
      var onixIaInput = document.getElementById('onixIaMensagem');
      if (onixIaInput) {
        onixIaInput.addEventListener('keydown', function(ev) {
          if (ev.key === 'Enter' && !ev.shiftKey) {
            ev.preventDefault();
            enviarMensagemOnixIa();
          }
        });
      }
    } catch (e) {
      if (typeof console !== 'undefined' && console.error) console.error(e);
      var st = document.getElementById('statusFinanceiro');
      if (st) st.textContent = 'Erro ao iniciar interface: ' + (e && e.message ? e.message : String(e));
    }
  </script>
</body>
</html>
"""
    return HTMLResponse(
        content=payload,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


if __name__ == "__main__":
    import threading
    import time
    import webbrowser

    import uvicorn

    def _abrir_navegador() -> None:
        time.sleep(1.2)
        webbrowser.open("http://127.0.0.1:8000/")

    threading.Thread(target=_abrir_navegador, daemon=True).start()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
