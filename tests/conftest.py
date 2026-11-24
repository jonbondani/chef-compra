"""Preparación común de las pruebas.

Las pruebas de integración usan las respuestas grabadas de las tiendas reales que
acompañan a supermercapy (su carpeta tests/). Para tenerlas:

    scripts/preparar_pruebas.sh

Sin ellas, esas pruebas se saltan y el resto se ejecuta igual.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from supermercados_mcp import tiendas

REPO = Path(os.environ.get("SUPERMERCAPY_REPO", Path(__file__).parent / ".supermercapy"))


@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERMERCADOS_MCP_DATOS", str(tmp_path / "datos"))
    monkeypatch.delenv("SUPERMERCADOS_CP", raising=False)
    yield
    tiendas.POOL.cerrar()
    tiendas.TRANSPORTE = None


@pytest.fixture
def tiendas_grabadas():
    """Sustituye la red por las respuestas grabadas de supermercapy."""

    if not (REPO / "tests" / "canned.py").exists():
        pytest.skip("faltan las respuestas grabadas: ejecuta scripts/preparar_pruebas.sh")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tests.canned import Storefronts  # type: ignore[import-not-found]

    grabadas = Storefronts()
    tiendas.TRANSPORTE = grabadas.transport
    return grabadas


@pytest.fixture
def llamar():
    """Llama a una herramienta por el protocolo MCP, con un cliente en memoria."""

    from mcp import Client

    from supermercados_mcp.server import mcp

    def _llamar(herramienta: str, /, **argumentos: Any) -> Any:
        async def una() -> Any:
            async with Client(mcp) as cliente:
                resultado = await cliente.call_tool(herramienta, argumentos)
                assert not resultado.is_error, resultado.content
                return resultado.structured_content

        return asyncio.run(una())

    return _llamar
