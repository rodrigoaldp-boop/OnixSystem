"""Configuracoes da aplicacao usando variaveis de ambiente."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from sga_financeiro.env_bootstrap import aplicar_dotenv_no_ambiente
from sga_financeiro.local_config import load_local_config, montar_database_url

# Antes do Pydantic ler .env como UTF-8 estrito (quebra com Notepad ANSI no Windows).
aplicar_dotenv_no_ambiente()

class Settings(BaseSettings):
    """Configuracoes principais do Onix System."""

    APP_NAME: str = "Onix System"
    APP_VERSION: str = "0.1.1"
    DEBUG: bool = True
    API_PREFIX: str = "/api"

    # Exemplo: postgresql+psycopg2://usuario:senha@localhost:5432/onix_system
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/onix_system"

    # CORS para integracao com frontend.
    CORS_ORIGINS: list[str] = ["*"]

    # Integracao de IA (API compativel com OpenAI).
    AI_ENABLED: bool = False
    AI_PROVIDER: str = "openai"
    AI_API_KEY: str = ""
    AI_MODEL: str = "gpt-4o-mini"
    AI_BASE_URL: str = "https://api.openai.com/v1"
    AI_TIMEOUT_SECONDS: int = 30

    # NF-e (homologacao).
    NFE_ENABLED: bool = False
    NFE_AMBIENTE: str = "homologacao"  # homologacao | producao
    NFE_UF: str = "PR"
    NFE_CERT_PATH: str = ""
    NFE_CERT_PASSWORD: str = ""
    NFE_CNPJ_EMITENTE: str = ""
    NFE_IE_EMITENTE: str = ""
    NFE_CNAE_PRINCIPAL: str = ""
    NFE_CNAES_SECUNDARIOS: str = ""
    NFE_CRT: str = "simples"  # simples | presumido | real
    NFE_SERIE: int = 1
    NFE_CFOP_PADRAO: str = "5102"
    NFE_CSOSN_PADRAO: str = "0102"

    model_config = SettingsConfigDict(
        case_sensitive=True,
    )


settings = Settings()


def _aplicar_override_local() -> None:
    cfg = load_local_config()
    if not cfg:
        return
    db_url = montar_database_url(cfg)
    if db_url:
        settings.DATABASE_URL = db_url
    app_version = str(cfg.get("app_version") or "").strip()
    if app_version:
        settings.APP_VERSION = app_version


_aplicar_override_local()
