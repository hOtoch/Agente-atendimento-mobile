"""Cliente MCP do Mercado Phone: JSON-RPC 2.0 sobre HTTP, resposta em SSE ou JSON simples.

O backend fala direto com o servidor MCP (a IA nunca recebe as ferramentas). So as ferramentas da
`FERRAMENTAS_PERMITIDAS` passam; qualquer outra (`delete_*` inclusive) e recusada antes da rede.
A chave de API vai na query `key` (montada aqui) e e mascarada em `repr`, logs e mensagens de erro.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, NoReturn
from urllib.parse import quote, quote_plus

import httpx

from app.application.estoque import EstoqueIndisponivel
from app.application.relogio import RelogioPort
from app.infra.relogio import RelogioSistema

URL_PADRAO = "https://platform.mercadophone.tech/mcp/platform/"
VERSAO_PROTOCOLO = "2025-06-18"
LIMITE_MAXIMO_PAGINA = 300
ESPERA_RATE_LIMIT_PADRAO_S = 1.0
ESPERA_RATE_LIMIT_MAXIMA_S = 60.0
_MAX_PAGINAS = 1000
_MASCARA = "***"

FERRAMENTAS_PERMITIDAS: frozenset[str] = frozenset(
    {
        "list_my_stores",
        "list_inventory",
        "list_brands",
        "list_salespeople",
        "list_payment_methods",
        "list_customers",
        "create_customer",
        "create_estimate",
    }
)
"""Unicas ferramentas do MCP que o projeto usa. O servidor tem 81 (inclusive de exclusao)."""

_CODIGOS_CREDENCIAL = frozenset({"invalid_key", "store_missing_api_token"})
_CODIGOS_USO_INDEVIDO = frozenset({"validation_error", "store_selection_required"})


# --- erros -------------------------------------------------------------------------------------


class ErroMercadoPhone(EstoqueIndisponivel):
    """Falha ao falar com o Mercado Phone. `retentavel` diz se tentar de novo pode resolver."""

    retentavel = False

    def __init__(
        self,
        mensagem: str,
        *,
        codigo: str | None = None,
        status: int | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.status = status
        self.hint = hint


class MercadoPhoneIndisponivel(ErroMercadoPhone):
    """Servico fora, timeout, erro de rede ou 5xx: vale tentar de novo."""

    retentavel = True


class MercadoPhoneLimiteExcedido(MercadoPhoneIndisponivel):
    """`rate_limited` persistiu depois de todas as esperas: vale tentar mais tarde."""


class MercadoPhoneCredencialInvalida(ErroMercadoPhone):
    """Chave recusada ou loja sem token (erro de configuracao): retry nao resolve."""


class MercadoPhoneUsoIndevido(ErroMercadoPhone):
    """Erro de programacao (argumento invalido, loja nao escolhida): corrigir o codigo."""


class FerramentaNaoPermitida(MercadoPhoneUsoIndevido):
    """Ferramenta fora da allowlist: recusada sem tocar a rede."""


# --- mascara da chave --------------------------------------------------------------------------

_CHAVES_MASCARADAS: set[str] = set()


def _mascarar_chave(texto: str, chave: str | None) -> str:
    if not chave:
        return texto
    for forma in {chave, quote(chave, safe=""), quote_plus(chave)}:
        texto = texto.replace(forma, _MASCARA)
    return texto


class _FiltroMascaraChave(logging.Filter):
    """Os loggers do httpx registram a URL completa (com `?key=`): mascara antes de emitir."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _CHAVES_MASCARADAS:
            mensagem = record.getMessage()
            for chave in _CHAVES_MASCARADAS:
                mensagem = _mascarar_chave(mensagem, chave)
            record.msg = mensagem
            record.args = None
        return True


_FILTRO = _FiltroMascaraChave()


def _registrar_chave(chave: str | None) -> None:
    if not chave:
        return
    _CHAVES_MASCARADAS.add(chave)
    for nome in ("httpx", "httpcore"):
        logger = logging.getLogger(nome)
        if _FILTRO not in logger.filters:
            logger.addFilter(_FILTRO)


# --- cliente -----------------------------------------------------------------------------------


class ClienteMercadoPhone:
    """Cliente MCP assincrono. `initialize` roda uma vez, na primeira chamada."""

    def __init__(
        self,
        cliente: httpx.AsyncClient,
        url: str = URL_PADRAO,
        chave: str | None = None,
        *,
        relogio: RelogioPort | None = None,
        max_repeticoes_rate_limit: int = 3,
        timeout_s: float = 15.0,
        nome_cliente: str = "agente-atendimento-mobile",
        versao_cliente: str = "1.0",
    ) -> None:
        self._cliente = cliente
        self._url = httpx.URL(url)
        self._chave = chave or None
        self._relogio: RelogioPort = relogio or RelogioSistema()
        self._max_repeticoes = max_repeticoes_rate_limit
        self._timeout_s = timeout_s
        self._info_cliente = {"name": nome_cliente, "version": versao_cliente}
        self._iniciado = False
        self._trava = asyncio.Lock()
        self._session_id: str | None = None
        self._proximo_id = 0
        _registrar_chave(self._chave)

    def __repr__(self) -> str:
        chave = _MASCARA if self._chave else None
        return f"ClienteMercadoPhone(url={self._url_publica()!r}, chave={chave!r})"

    __str__ = __repr__

    def _url_publica(self) -> str:
        return _mascarar_chave(str(self._url), self._chave)

    # -- API publica --

    async def chamar(
        self, ferramenta: str, argumentos: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Chama uma ferramenta e devolve o payload JSON decodificado (sempre um dict).

        Uma resposta que e uma lista vira `{"items": lista, "total": len(lista)}`.
        """
        self._exigir_permitida(ferramenta)
        repeticoes = 0
        while True:
            try:
                # O handshake fica dentro do laco: um 429 nele tambem espera e repete.
                await self._garantir_inicializado()
                return await self._chamar_uma_vez(ferramenta, argumentos or {})
            except _RateLimited as limite:
                if repeticoes >= self._max_repeticoes:
                    raise MercadoPhoneLimiteExcedido(
                        f"rate limit do Mercado Phone persistiu apos {repeticoes} repeticoes",
                        codigo="rate_limited",
                        status=429,
                    ) from None
                repeticoes += 1
                await self._relogio.dormir(limite.espera_s)

    async def paginar(
        self, ferramenta: str, argumentos: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Junta os `items` de todas as paginas (`limit` <= 300), parando no fim ou no `total`."""
        self._exigir_permitida(ferramenta)
        base = dict(argumentos or {})
        limite = _normalizar_limite(base.get("limit"))
        itens: list[dict[str, Any]] = []
        for pagina in range(1, _MAX_PAGINAS + 1):
            resposta = await self.chamar(ferramenta, {**base, "page": pagina, "limit": limite})
            lote = resposta.get("items")
            if not isinstance(lote, list):
                raise ErroMercadoPhone(f"{ferramenta}: resposta paginada sem 'items'")
            itens.extend(lote)
            total = resposta.get("total")
            if len(lote) < limite or (isinstance(total, int) and len(itens) >= total):
                break
        return itens

    # -- protocolo --

    @staticmethod
    def _exigir_permitida(ferramenta: str) -> None:
        if ferramenta not in FERRAMENTAS_PERMITIDAS:
            raise FerramentaNaoPermitida(
                f"ferramenta {ferramenta!r} fora da allowlist do Mercado Phone",
                codigo="ferramenta_nao_permitida",
            )

    async def _garantir_inicializado(self) -> None:
        if self._iniciado:
            return
        async with self._trava:
            if self._iniciado:
                return
            await self._requisitar(
                "initialize",
                {
                    "protocolVersion": VERSAO_PROTOCOLO,
                    "capabilities": {},
                    "clientInfo": self._info_cliente,
                },
                capturar_sessao=True,
            )
            await self._notificar("notifications/initialized")
            self._iniciado = True

    async def _chamar_uma_vez(self, ferramenta: str, argumentos: dict[str, Any]) -> dict[str, Any]:
        resultado = await self._requisitar(
            "tools/call", {"name": ferramenta, "arguments": argumentos}
        )
        return _decodificar_resultado(resultado, self._chave)

    async def _requisitar(
        self, metodo: str, params: dict[str, Any], *, capturar_sessao: bool = False
    ) -> dict[str, Any]:
        self._proximo_id += 1
        req_id = self._proximo_id
        resposta = await self._enviar(
            {"jsonrpc": "2.0", "id": req_id, "method": metodo, "params": params}
        )
        if capturar_sessao:
            self._session_id = resposta.headers.get("mcp-session-id")
        mensagem = _decodificar_corpo(resposta.text, req_id)
        if "error" in mensagem:
            raise _erro_jsonrpc(mensagem["error"], self._chave)
        resultado = mensagem.get("result")
        if not isinstance(resultado, dict):
            raise ErroMercadoPhone(f"{metodo}: resposta sem 'result'")
        return resultado

    async def _notificar(self, metodo: str) -> None:
        await self._enviar({"jsonrpc": "2.0", "method": metodo})

    async def _enviar(self, corpo: dict[str, Any]) -> httpx.Response:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": VERSAO_PROTOCOLO,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        url = self._url.copy_merge_params({"key": self._chave}) if self._chave else self._url
        try:
            resposta = await self._cliente.post(
                url, json=corpo, headers=headers, timeout=self._timeout_s
            )
        except httpx.TimeoutException:
            raise MercadoPhoneIndisponivel("timeout ao falar com o Mercado Phone") from None
        except httpx.HTTPError as exc:
            # `from None`: a excecao original carrega a request (URL com a chave).
            detalhe = _mascarar_chave(str(exc), self._chave)
            raise MercadoPhoneIndisponivel(
                f"Mercado Phone inacessivel ({type(exc).__name__}): {detalhe}"
            ) from None
        _checar_http(resposta, self._chave)
        return resposta


class _RateLimited(Exception):
    def __init__(self, espera_s: float) -> None:
        super().__init__(espera_s)
        self.espera_s = espera_s


# --- helpers puros -----------------------------------------------------------------------------


def _normalizar_limite(pedido: Any) -> int:
    if isinstance(pedido, int) and not isinstance(pedido, bool) and pedido > 0:
        return min(pedido, LIMITE_MAXIMO_PAGINA)
    return LIMITE_MAXIMO_PAGINA


def _espera(valor: Any) -> float:
    try:
        espera = float(valor)
    except (TypeError, ValueError):
        return ESPERA_RATE_LIMIT_PADRAO_S
    if espera <= 0:
        return ESPERA_RATE_LIMIT_PADRAO_S
    return min(espera, ESPERA_RATE_LIMIT_MAXIMA_S)


def _checar_http(resposta: httpx.Response, chave: str | None) -> None:
    status = resposta.status_code
    if status < 400:
        return
    if status in (401, 403):
        raise MercadoPhoneCredencialInvalida(
            f"Mercado Phone recusou a chave (HTTP {status})", codigo="invalid_key", status=status
        )
    if status == 429:
        raise _RateLimited(_espera(resposta.headers.get("retry-after")))
    if status >= 500:
        raise MercadoPhoneIndisponivel(f"Mercado Phone respondeu HTTP {status}", status=status)
    # Outros 4xx: pode vir um envelope JSON-RPC com o motivo; senao e uso indevido.
    try:
        mensagem = _decodificar_corpo(resposta.text, None)
    except ErroMercadoPhone:
        mensagem = None
    if isinstance(mensagem, dict) and "error" in mensagem:
        raise _erro_jsonrpc(mensagem["error"], chave)
    raise MercadoPhoneUsoIndevido(f"Mercado Phone respondeu HTTP {status}", status=status)


def _eventos_sse(texto: str) -> list[str]:
    """Os `data:` de cada evento do SSE (varias linhas `data:` do mesmo evento sao juntadas)."""
    eventos: list[str] = []
    atuais: list[str] = []
    for linha in texto.splitlines():
        if not linha.strip():
            if atuais:
                eventos.append("\n".join(atuais))
                atuais = []
        elif linha.startswith("data:"):
            atuais.append(linha[5:].removeprefix(" "))
    if atuais:
        eventos.append("\n".join(atuais))
    return eventos


def _decodificar_corpo(texto: str, req_id: int | None) -> dict[str, Any]:
    corpo = texto.strip()
    candidatas = [corpo] if corpo.startswith(("{", "[")) else _eventos_sse(texto)
    mensagens: list[dict[str, Any]] = []
    for bruto in candidatas:
        try:
            analisado = json.loads(bruto)
        except ValueError:
            continue
        mensagens.extend(m for m in (analisado if isinstance(analisado, list) else [analisado]))
    validas = [m for m in mensagens if isinstance(m, dict)]
    if req_id is None:
        if validas:
            return validas[-1]
    else:
        for m in validas:
            if m.get("id") == req_id:
                return m
    raise ErroMercadoPhone("resposta do Mercado Phone ilegivel (sem mensagem JSON-RPC esperada)")


def _erro_jsonrpc(erro: Any, chave: str | None) -> ErroMercadoPhone:
    if not isinstance(erro, dict):
        return ErroMercadoPhone(_mascarar_chave(f"erro JSON-RPC: {erro}", chave))
    codigo = erro.get("code")
    mensagem = _mascarar_chave(str(erro.get("message", "erro JSON-RPC")), chave)
    if codigo == -32603 or (isinstance(codigo, int) and codigo <= -32000 and codigo > -32100):
        return MercadoPhoneIndisponivel(f"Mercado Phone: {mensagem}", codigo=str(codigo))
    return MercadoPhoneUsoIndevido(f"Mercado Phone: {mensagem}", codigo=str(codigo))


def _decodificar_resultado(resultado: dict[str, Any], chave: str | None) -> dict[str, Any]:
    conteudo = resultado.get("content")
    texto = None
    if isinstance(conteudo, list) and conteudo and isinstance(conteudo[0], dict):
        texto = conteudo[0].get("text")
    if not isinstance(texto, str):
        raise ErroMercadoPhone("resultado da ferramenta sem 'content[0].text'")
    try:
        payload = json.loads(texto)
    except ValueError:
        if resultado.get("isError"):
            raise ErroMercadoPhone(
                f"ferramenta falhou: {_mascarar_chave(texto[:300], chave)}"
            ) from None
        raise ErroMercadoPhone("resultado da ferramenta nao e JSON") from None
    if (
        isinstance(payload, dict)
        and "error" in payload
        and (resultado.get("isError") or "code" in payload or "status" in payload)
    ):
        _levantar_erro_da_ferramenta(payload, chave)
    if isinstance(payload, list):
        return {"items": payload, "total": len(payload)}
    if not isinstance(payload, dict):
        raise ErroMercadoPhone("resultado da ferramenta nao e um objeto JSON")
    if resultado.get("isError"):
        raise ErroMercadoPhone("ferramenta falhou sem detalhes")
    return payload


def _levantar_erro_da_ferramenta(payload: dict[str, Any], chave: str | None) -> NoReturn:
    codigo = payload.get("code")
    codigo = codigo if isinstance(codigo, str) else None
    status = payload.get("status")
    status = status if isinstance(status, int) else None
    hint = payload.get("hint")
    hint = _mascarar_chave(hint, chave) if isinstance(hint, str) else None
    mensagem = _mascarar_chave(str(payload.get("error")), chave)
    texto = f"Mercado Phone [{codigo or status}]: {mensagem}"
    detalhes: dict[str, Any] = {"codigo": codigo, "status": status, "hint": hint}
    if codigo == "rate_limited":
        raise _RateLimited(_espera(payload.get("retry_after_seconds")))
    if codigo in _CODIGOS_CREDENCIAL:
        raise MercadoPhoneCredencialInvalida(texto, **detalhes)
    if codigo in _CODIGOS_USO_INDEVIDO:
        raise MercadoPhoneUsoIndevido(texto, **detalhes)
    if codigo == "service_unavailable" or (status is not None and status >= 500):
        raise MercadoPhoneIndisponivel(texto, **detalhes)
    raise ErroMercadoPhone(texto, **detalhes)
