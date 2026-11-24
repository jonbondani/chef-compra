#!/usr/bin/env python3
"""Genera las capturas del README (docs/capturas/*.svg) a partir de salidas reales del servidor.

    scripts/preparar_pruebas.sh
    python scripts/capturas.py

Llama a las herramientas por el protocolo MCP, igual que un cliente. Las tiendas
se sustituyen por las respuestas grabadas de las pruebas, así que los productos y
precios son datos de prueba, no precios de hoy. Cada captura lo indica.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "capturas"
GRABADAS = "Datos de prueba grabados (los mismos de la batería de pruebas), no precios de hoy"


def consola(ancho: int = 100) -> Console:
    return Console(record=True, width=ancho, file=open(os.devnull, "w"), force_terminal=True)


def guardar(c: Console, nombre: str, titulo: str) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    c.save_svg(str(SALIDA / f"{nombre}.svg"), title=titulo)
    print("escrita", SALIDA / f"{nombre}.svg")


async def main() -> None:
    os.environ["SUPERMERCADOS_MCP_DATOS"] = tempfile.mkdtemp(prefix="capturas-")
    sys.path.insert(0, str(RAIZ / "tests" / ".supermercapy"))
    from mcp import Client
    from tests.canned import Storefronts  # type: ignore[import-not-found]

    from supermercados_mcp import tiendas
    from supermercados_mcp.server import mcp

    tiendas.TRANSPORTE = Storefronts().transport

    async with Client(mcp) as cliente:
        async def llamar(herramienta: str, **argumentos):
            return (await cliente.call_tool(herramienta, argumentos)).structured_content

        # 1. herramientas
        c = consola(110)
        tabla = Table(title="Herramientas que expone el servidor MCP", title_justify="left", box=box.ASCII)
        tabla.add_column("Herramienta", style="cyan", no_wrap=True)
        tabla.add_column("Descripción")
        for h in (await cliente.list_tools()).tools:
            tabla.add_row(h.name, (h.description or "").strip().splitlines()[0])
        c.print(tabla)
        guardar(c, "herramientas", "supermercados-mcp: herramientas")

        # 2. buscar
        c = consola(118)
        c.print(Text('buscar_productos(consulta="leche", codigo_postal="28001", limite=2)', style="bold green"))
        datos = await llamar("buscar_productos", consulta="leche", codigo_postal="28001", limite=2,
                             supermercados=["mercadona", "carrefour", "dia", "aldi"])
        tabla = Table(box=box.ASCII)
        for columna in ("Supermercado", "Producto", "Precio", "Por unidad", "Oferta"):
            tabla.add_column(columna, justify="right" if columna in ("Precio", "Por unidad") else "left")
        for tienda, r in datos.items():
            for p in r["productos"]:
                tabla.add_row(tienda, p["nombre"][:52], f'{p["precio"]:.2f} €',
                              p.get("precio_por_unidad", "-"), "sí" if p.get("en_oferta") else "")
        c.print(tabla)
        avisos = [t for t, r in datos.items() if "aviso" in r]
        if avisos:
            c.print(Text(f"aviso en {', '.join(avisos)}: la tienda online no sirve a ese código postal, "
                         "se usan los precios de su zona por defecto", style="yellow"))
        c.print(Text(GRABADAS, style="dim italic"))
        guardar(c, "buscar", "buscar_productos")

        # 3. comparar
        c = consola(110)
        c.print(Text('comparar_precios(consulta="leche", supermercados=["carrefour","dia"], codigo_postal="08001")',
                     style="bold green"))
        datos = await llamar("comparar_precios", consulta="leche", supermercados=["carrefour", "dia"],
                             codigo_postal="08001")
        tabla = Table(title=f"Del más barato al más caro en {datos['unidad_comparada']}", title_justify="left", box=box.ASCII)
        for columna in ("#", "Por unidad", "Supermercado", "Producto", "Precio"):
            tabla.add_column(columna, justify="right" if columna in ("#", "Por unidad", "Precio") else "left")
        for i, f in enumerate(datos["ranking"], 1):
            tabla.add_row(str(i), f["precio_por_unidad"], f["supermercado"], f["nombre"][:56], f'{f["precio"]:.2f} €')
        c.print(tabla)
        c.print(Text(GRABADAS, style="dim italic"))
        guardar(c, "comparar", "comparar_precios")

        # 4. memoria del agente (no usa las tiendas: es exactamente lo que guarda el servidor)
        c = consola(104)
        await llamar("perfil_guardar", nombre="Casa", comensales="2 adultos y una niña de 6 años",
                     gustos=["legumbres", "arroces", "cocina mediterránea"], evitar=["coliflor"],
                     alergias=["cacahuete"], supermercados=["mercadona", "dia", "aldi"],
                     notas="Entre semana, 30 minutos para cocinar")
        await llamar("perfil_aprender", nombre="Casa", observacion="Entre semana cenan ligero", categoria="costumbre")
        await llamar("perfil_aprender", nombre="Casa", observacion="El pescado azul no les gusta", categoria="evitar")
        await llamar("menu_guardar", nombre="Casa", platos={
            "desayuno": "Tostadas con tomate y aceite", "comida": "Arroz con verduras",
            "cena": "Tortilla francesa con ensalada"})
        await llamar("menu_valorar", nombre="Casa", puntuacion=5, comentario="El arroz gustó mucho")
        perfil = await llamar("perfiles_ver", nombre="Casa")
        historial = await llamar("menu_historial", nombre="Casa")
        c.print(Text('perfiles_ver(nombre="Casa")', style="bold green"))
        tabla = Table(show_header=False, box=box.ASCII)
        tabla.add_column(style="cyan", no_wrap=True)
        tabla.add_column()
        for campo in ("comensales", "gustos", "evitar", "alergias", "supermercados", "notas"):
            valor = perfil[campo]
            tabla.add_row(campo, ", ".join(valor) if isinstance(valor, list) else str(valor))
        for apunte in perfil["aprendido"]:
            tabla.add_row(f"aprendido ({apunte['categoria']})", f"{apunte['observacion']}  [{apunte['fecha']}]")
        c.print(tabla)
        c.print(Text('menu_historial(nombre="Casa")', style="bold green"))
        tabla = Table(show_header=False, box=box.ASCII)
        tabla.add_column(style="cyan", no_wrap=True)
        tabla.add_column()
        menu = historial["menus"][0]
        tabla.add_row("fecha", menu["fecha"])
        for comida, plato in menu["platos"].items():
            tabla.add_row(comida, plato)
        tabla.add_row("puntuación", f"{menu['puntuacion']} de 5: {menu['comentario']}")
        c.print(tabla)
        c.print(Text("Perfil de ejemplo. Se guarda en perfiles.json, en tu equipo.", style="dim italic"))
        guardar(c, "memoria", "Memoria del agente: perfil y menús")

    # 5. pruebas
    c = consola(100)
    resultado = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
                               cwd=RAIZ, capture_output=True, text=True)
    c.print(Text("$ python -m pytest -q", style="bold green"))
    c.print(Text(resultado.stdout.strip()))
    guardar(c, "pruebas", "Batería de pruebas")


if __name__ == "__main__":
    asyncio.run(main())
