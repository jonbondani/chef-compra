#!/usr/bin/env python3
"""Prueba en vivo contra las tiendas reales. Solo lee catálogos públicos.

    python scripts/prueba_en_vivo.py 28001            # las cinco principales
    python scripts/prueba_en_vivo.py 28001 dia aldi   # solo algunas

Arranca el servidor MCP como lo haría Claude (por stdio), llama a sus
herramientas y dice qué tienda responde y cuál no. Usa una carpeta de datos
temporal, así que no toca tu lista de la compra. Sale con 0 si todo va bien.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

from mcp import Client, StdioServerParameters

CONSULTA = "leche entera"


async def main(cp: str, tiendas: list[str]) -> int:
    entorno = {**os.environ, "SUPERMERCADOS_MCP_DATOS": tempfile.mkdtemp(prefix="supermercados-prueba-")}
    servidor = StdioServerParameters(
        command=sys.executable, args=["-m", "supermercados_mcp.server"], env=entorno
    )
    fallos = 0

    def linea(ok: bool, texto: str) -> None:
        nonlocal fallos
        fallos += not ok
        print(("  OK    " if ok else "  FALLO ") + texto)

    async with Client(servidor, read_timeout_seconds=180) as cliente:
        async def llamar(nombre: str, **argumentos):
            inicio = time.monotonic()
            resultado = await cliente.call_tool(nombre, argumentos)
            return resultado.structured_content, time.monotonic() - inicio

        print(f"1. Buscar '{CONSULTA}' (CP {cp})")
        datos, segundos = await llamar(
            "buscar_productos", consulta=CONSULTA, supermercados=tiendas or None, codigo_postal=cp, limite=3
        )
        respondieron = []
        for tienda, r in datos.items():
            if "error" in r:
                linea(False, f"{tienda}: {r['error']}: {r['motivo']}")
                continue
            respondieron.append(tienda)
            primero = r["productos"][0] if r["productos"] else None
            aviso = "  [AVISO: sin cobertura en ese CP, precios por defecto]" if "aviso" in r else ""
            linea(
                primero is not None and primero.get("precio", 0) > 0,
                f"{tienda}: {len(r['productos'])} de {r.get('total')} resultados; primero: "
                f"{primero['nombre'] if primero else '-'} | {primero.get('precio') if primero else '-'} € | "
                f"{primero.get('precio_por_unidad', 'sin precio unitario') if primero else ''}{aviso}",
            )
        print(f"   ({segundos:.1f} s)")

        print("2. Comparar precios por litro")
        datos, segundos = await llamar(
            "comparar_precios", consulta=CONSULTA, supermercados=respondieron, codigo_postal=cp
        )
        importes = [float(f["precio_por_unidad"].split()[0]) for f in datos["ranking"]]
        linea(bool(importes) and importes == sorted(importes),
              f"{len(importes)} productos ordenados en {datos['unidad_comparada']}; "
              f"tiendas en el ranking: {sorted({f['supermercado'] for f in datos['ranking']})}")
        for fila in datos["ranking"][:5]:
            print(f"        {fila['precio_por_unidad']:>12}  {fila['supermercado']:<10} {fila['nombre'][:60]}")

        print("3. Ficha del primer producto de cada tienda")
        busqueda, _ = await llamar(
            "buscar_productos", consulta=CONSULTA, supermercados=respondieron, codigo_postal=cp, limite=1
        )
        for tienda, r in busqueda.items():
            if not r.get("productos"):
                continue
            ficha, _ = await llamar(
                "detalle_producto", supermercado=tienda, producto_id=r["productos"][0]["id"], codigo_postal=cp
            )
            linea("error" not in ficha, f"{tienda}: {ficha.get('name') or ficha}")

        print("4. Ofertas (Lidl, Dia y Aldi)")
        for tienda in [t for t in respondieron if t in ("lidl", "dia", "aldi")]:
            datos, segundos = await llamar("ofertas", supermercado=tienda, codigo_postal=cp, limite=3)
            linea("error" not in datos and datos.get("total", 0) > 0,
                  f"{tienda}: {datos.get('total', datos)} ofertas ({segundos:.1f} s)")

        print("5. Lista de la compra y presupuesto")
        for articulo, cantidad in (("leche entera 1 l", 6), ("huevos docena", 1), ("arroz redondo 1 kg", 2)):
            await llamar("lista_anadir", articulo=articulo, cantidad=cantidad)
        datos, segundos = await llamar("presupuestar_lista", supermercados=respondieron, codigo_postal=cp)
        for tienda, r in datos["supermercados"].items():
            if "error" in r:
                linea(False, f"{tienda}: {r['error']}: {r['motivo']}")
                continue
            linea(r["articulos_encontrados"] > 0,
                  f"{tienda}: {r['total']:.2f} € con {r['articulos_encontrados']}/3 artículos"
                  + (f" (faltan: {', '.join(r['no_encontrados'])})" if r["no_encontrados"] else ""))
            for l in r["lineas"]:
                print(f"        {l['cantidad']} x {l['producto']['nombre'][:55]} = {l['subtotal']:.2f} €")
        print(f"   más barato con todo: {datos['mas_barato_con_todo']} ({segundos:.1f} s)")

    print(f"\n{'TODO CORRECTO' if not fallos else f'{fallos} COMPROBACIONES FALLIDAS'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2:])))
