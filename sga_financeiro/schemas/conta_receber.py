"""Schemas de contas a receber."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sga_financeiro.models.conta_receber import StatusContaReceber


class ContaReceberBase(BaseModel):
    descricao: str
    valor: Decimal
    categoria_id: int
    centro_custos_id: int
    cliente_id: Optional[int] = None
    conta_destino_id: Optional[int] = None
    data_vencimento: date
    comprovante_url: Optional[str] = None


class ContaReceberCreate(ContaReceberBase):
    status: StatusContaReceber = StatusContaReceber.PENDENTE
    data_recebimento: Optional[date] = None
    comissionar_recebimento: bool = False
    comissao_vendedor_id: Optional[int] = None
    comissao_percentual: Optional[Decimal] = None


class ContaReceberUpdate(BaseModel):
    descricao: Optional[str] = None
    valor: Optional[Decimal] = None
    categoria_id: Optional[int] = None
    centro_custos_id: Optional[int] = None
    cliente_id: Optional[int] = None
    conta_destino_id: Optional[int] = None
    data_vencimento: Optional[date] = None
    status: Optional[StatusContaReceber] = None
    comprovante_url: Optional[str] = None
    comissionar_recebimento: Optional[bool] = None
    comissao_vendedor_id: Optional[int] = None
    comissao_percentual: Optional[Decimal] = None


class ContaReceberBaixa(BaseModel):
    conta_destino_id: int
    data_recebimento: Optional[date] = None
    comprovante_url: Optional[str] = None
    valor_recebido: Optional[Decimal] = Field(
        default=None,
        description="Valor creditado na conta corrente. Se omitido, recebe o total (principal + encargos).",
    )
    perdoar_multa: bool = Field(
        default=False,
        description="Ignora multa de atraso no calculo do recebimento.",
    )
    perdoar_juros: bool = Field(
        default=False,
        description="Ignora juros de atraso no calculo do recebimento.",
    )


class ContaReceberSimularRecebimentoIn(BaseModel):
    conta_ids: list[int] = Field(..., min_length=1)
    data_recebimento: date
    perdoar_multa: bool = False
    perdoar_juros: bool = False


class ContaReceberSimularRecebimentoItemOut(BaseModel):
    conta_id: int
    valor_principal: Decimal
    dias_atraso: int
    multa: Decimal
    juros: Decimal
    total_devido: Decimal
    vencida: bool
    multa_percent: Optional[float] = None
    juros_percent_dia: Optional[float] = None
    valor_original: Optional[Decimal] = None
    juros_acumulados: Optional[Decimal] = None
    juros_novos: Optional[Decimal] = None
    multa_fixada: bool = False


class ContaReceberSimularRecebimentoOut(BaseModel):
    itens: list[ContaReceberSimularRecebimentoItemOut]
    total_principal: Decimal
    total_multa: Decimal
    total_juros: Decimal
    total_devido: Decimal


class ContaReceberOut(ContaReceberBase):
    id: int
    venda_id: Optional[int] = None
    data_recebimento: Optional[date] = None
    status: StatusContaReceber
    comissao_gerada: bool = False
    comissionar_recebimento: bool = False
    comissao_vendedor_id: Optional[int] = None
    comissao_percentual: Optional[Decimal] = None
    valor_original: Optional[Decimal] = None
    multa_fixada: Optional[Decimal] = None
    juros_acumulados: Optional[Decimal] = None
    juros_apos_data: Optional[date] = None
    created_at: datetime
    asaas_payment_id: Optional[str] = None
    asaas_boleto_url: Optional[str] = None
    asaas_linha_digitavel: Optional[str] = None
    asaas_status: Optional[str] = None
    asaas_pix_copia_cola: Optional[str] = None
    asaas_billing_type: Optional[str] = None
    boleto_email_enviado_at: Optional[datetime] = None
    boleto_email_destino: Optional[str] = None
    boleto_email_anexos: Optional[str] = None
    whatsapp_enviado: bool = False
    whatsapp_enviado_em: Optional[datetime] = None
    cliente_telefone_whatsapp: Optional[str] = None
    cliente_nome: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ContaReceberEnviarBoletoEmailIn(BaseModel):
    """Destino opcional; se omitido, usa e-mail do cliente (cadastro clientes ou pessoas)."""

    destinatario: Optional[str] = Field(default=None, max_length=200)
    notificar_whatsapp: bool = False


class ContaReceberEnviarBoletoEmailOut(BaseModel):
    destinatario: str
    anexos: list[str]
    enviado_em: datetime
    conta_id: int
    whatsapp_tentado: bool = False
    whatsapp_enviado: bool = False
    whatsapp_detalhe: str = ""


class ContaReceberEnviarBoletosEmailLoteIn(BaseModel):
    """Varias contas (mesmo cliente); um unico e-mail com todos os PDFs dos boletos Asaas."""

    conta_ids: list[int]
    destinatario: Optional[str] = Field(default=None, max_length=200)
    notificar_whatsapp: bool = False


class ContaReceberEnviarBoletosEmailLoteOut(BaseModel):
    destinatario: str
    anexos: list[str]
    enviado_em: datetime
    conta_ids: list[int]
    whatsapp_tentado: bool = False
    whatsapp_enviado: bool = False
    whatsapp_detalhe: str = ""


class ContaReceberBoletoAsaasIn(BaseModel):
    """Corpo opcional ao emitir boleto Asaas (complemento da descricao na cobranca)."""

    texto_extra_boleto: Optional[str] = Field(default=None, max_length=500)


class ContaReceberBoletoAsaasOut(BaseModel):
    """Resposta apos emitir ou atualizar boleto no Asaas."""

    conta: ContaReceberOut
    mensagem: str = ""


class ContaReceberPixAsaasIn(BaseModel):
    texto_extra_pix: Optional[str] = Field(default=None, max_length=500)


class ContaReceberPixAsaasOut(BaseModel):
    conta: ContaReceberOut
    mensagem: str = ""


class ContaReceberEnviarPixWhatsappOut(BaseModel):
    conta_id: int
    whatsapp_tentado: bool = False
    whatsapp_enviado: bool = False
    whatsapp_detalhe: str = ""


class ContaReceberBoletoLoteFalha(BaseModel):
    conta_id: int
    detail: str


class ContaReceberBoletosAsaasLoteIn(BaseModel):
    conta_ids: list[int]


class ContaReceberBoletosAsaasLoteOut(BaseModel):
    """Resumo ao emitir varios boletos (uma requisicao por conta com commit isolado)."""

    sucesso: int = 0
    falhas: list[ContaReceberBoletoLoteFalha] = Field(default_factory=list)


class ContaReceberBoletosPdfMergeIn(BaseModel):
    """IDs das contas a receber cujos PDFs de boleto (URLs salvas no Asaas) serao unificados em um arquivo."""

    conta_ids: list[int]


class ContaReceberImportCsvBlingOut(BaseModel):
    ok: bool = True
    linhas_lidas: int = 0
    inseridos: int = 0
    ignorados_subtotal: int = 0
    ignorados_duplicados: int = 0
    categoria_id: int = 0
    centro_custos_id: int = 0
    erros: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)


class RetornoSicoobLinhaPreview(BaseModel):
    indice: int
    status: str
    conta_receber_id: Optional[int] = None
    documento_retorno: str = ""
    nosso_numero: str = ""
    nome_pagador: str = ""
    valor_retorno: str = ""
    data_baixa_prevista: str = ""
    descricao_sistema: str = ""
    parte_sistema: str = ""
    data_vencimento_sistema: Optional[str] = None
    valor_sistema: Optional[str] = None
    motivo: str = ""
    selecionado_padrao: bool = False


class ContaReceberPreviewRetornoSicoobOut(BaseModel):
    ok: bool = True
    liquidacoes_arquivo: int = 0
    linhas: list[RetornoSicoobLinhaPreview] = Field(default_factory=list)
    resumo: dict = Field(default_factory=dict)


class ContaReceberImportRetornoSicoobOut(BaseModel):
    ok: bool = True
    liquidacoes_arquivo: int = 0
    baixados: int = 0
    ja_recebidos: int = 0
    nao_encontrados: int = 0
    conta_destino_id: int = 0
    erros: list[str] = Field(default_factory=list)
    detalhes: list[dict] = Field(default_factory=list)


class ContaReceberCancelarAsaasOut(BaseModel):
    ok: bool = True
    conta_id: int
    cancelado: bool = False
    mensagem: str = ""
    payment_id: Optional[str] = None
    status_anterior: Optional[str] = None
