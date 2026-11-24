"""Servidor MCP: supermercados de España y lista de la compra."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__, lista, perfiles, tiendas

mcp = MCPServer(
    "supermercados",
    version=__version__,
    log_level="WARNING",
    instructions=(
        "Busca productos y compara precios en supermercados de España (por defecto Mercadona, "
        "Carrefour, Dia, Lidl y Aldi), gestiona una lista de la compra local y guarda perfiles "
        "de hogar (gustos, alergias, costumbres, menús) para planificar menús. Los precios "
        "dependen del código postal: pásalo en codigo_postal salvo que el servidor tenga uno "
        "configurado. Solo lee catálogos públicos: no inicia sesión, no toca carritos y no compra."
    ),
)


async def _hilo(funcion: Any, *args: Any) -> Any:
    """Ejecuta una función bloqueante fuera del bucle de eventos."""

    try:
        return await asyncio.to_thread(funcion, *args)
    except (tiendas.ErrorDeUso, ValueError, KeyError) as error:
        return {"error": "uso", "motivo": str(error).strip("'\"")}


def _preparar(supermercados: list[str] | None, codigo_postal: str | None) -> tuple[list[str], str | None]:
    return tiendas.nombres(supermercados), tiendas.codigo_postal(codigo_postal)


@mcp.tool()
async def supermercados_disponibles() -> dict[str, Any]:
    """Lista los supermercados que se pueden consultar y cuáles publican ofertas."""

    from supermercapy import Capability

    return {
        "por_defecto": list(tiendas.POR_DEFECTO),
        "todos": {
            nombre: {
                "ofertas": clase.supports(Capability.OFFERS),
                "precio_segun_codigo_postal": clase.supports(Capability.POSTAL_CODE),
            }
            for nombre, clase in tiendas.CLIENTES.items()
        },
        "codigo_postal_configurado": tiendas.codigo_postal(None),
    }


@mcp.tool()
async def buscar_productos(
    consulta: str,
    supermercados: list[str] | None = None,
    codigo_postal: str | None = None,
    limite: int = 5,
) -> dict[str, Any]:
    """Busca un producto en varios supermercados a la vez.

    Devuelve por supermercado los productos más relevantes con precio, precio por
    kilo/litro/unidad, formato, ofertas y enlace. Si un supermercado falla, se
    indica el error y los demás responden igual.
    """

    def tarea() -> dict[str, Any]:
        nombres, cp = _preparar(supermercados, codigo_postal)
        return tiendas.buscar(consulta, nombres, cp, max(1, min(limite, 25)))

    return await _hilo(tarea)


@mcp.tool()
async def comparar_precios(
    consulta: str,
    supermercados: list[str] | None = None,
    codigo_postal: str | None = None,
    limite_por_supermercado: int = 8,
) -> dict[str, Any]:
    """Compara un producto entre supermercados, del más barato al más caro por kilo, litro o unidad."""

    def tarea() -> dict[str, Any]:
        nombres, cp = _preparar(supermercados, codigo_postal)
        return tiendas.comparar(consulta, nombres, cp, max(1, min(limite_por_supermercado, 25)))

    return await _hilo(tarea)


@mcp.tool()
async def detalle_producto(
    supermercado: str, producto_id: str, codigo_postal: str | None = None
) -> dict[str, Any]:
    """Ficha completa de un producto (ingredientes, nutrición, fotos...) a partir del id que devuelve la búsqueda."""

    def tarea() -> dict[str, Any]:
        nombres, cp = _preparar([supermercado], codigo_postal)
        return tiendas.detalle(nombres[0], producto_id, cp)

    return await _hilo(tarea)


@mcp.tool()
async def ofertas(
    supermercado: str,
    codigo_postal: str | None = None,
    contiene: str | None = None,
    limite: int = 30,
) -> dict[str, Any]:
    """Ofertas vigentes de un supermercado (Lidl, Dia y Aldi las publican; Mercadona y Carrefour no).

    ``contiene`` filtra por texto en el nombre. En Dia la consulta tarda porque
    recorre unas treinta páginas.
    """

    def tarea() -> dict[str, Any]:
        nombres, cp = _preparar([supermercado], codigo_postal)
        return tiendas.ofertas(nombres[0], cp, max(1, min(limite, 200)), contiene)

    return await _hilo(tarea)


@mcp.tool()
async def lista_ver(incluir_comprados: bool = True) -> dict[str, Any]:
    """Muestra la lista de la compra."""

    return {"articulos": await _hilo(lista.ver, incluir_comprados)}


@mcp.tool()
async def lista_anadir(articulo: str, cantidad: int = 1, nota: str | None = None) -> dict[str, Any]:
    """Añade un artículo a la lista. Si ya está pendiente, suma la cantidad.

    Cuanto más concreto sea el texto ("leche semidesnatada sin lactosa 1 l"),
    mejor sale el presupuesto.
    """

    return await _hilo(lista.anadir, articulo, cantidad, nota)


@mcp.tool()
async def lista_cambiar(
    articulo_id: int,
    cantidad: int | None = None,
    comprado: bool | None = None,
    nota: str | None = None,
) -> dict[str, Any]:
    """Cambia la cantidad o la nota de un artículo, o lo marca como comprado o pendiente."""

    return await _hilo(
        lambda: lista.cambiar(articulo_id, cantidad=cantidad, comprado=comprado, nota=nota)
    )


@mcp.tool()
async def lista_quitar(articulo_id: int) -> dict[str, Any]:
    """Quita un artículo de la lista."""

    return await _hilo(lista.quitar, articulo_id)


@mcp.tool()
async def lista_vaciar(solo_comprados: bool = True) -> dict[str, Any]:
    """Borra los artículos comprados o, con solo_comprados=false, la lista entera."""

    return {"eliminados": await _hilo(lista.vaciar, solo_comprados)}


@mcp.tool()
async def presupuestar_lista(
    supermercados: list[str] | None = None, codigo_postal: str | None = None
) -> dict[str, Any]:
    """Calcula cuánto costaría la lista pendiente en cada supermercado y cuál sale más barato.

    Es una estimación: usa el resultado más relevante de cada tienda para cada
    artículo y propone una alternativa cuando hay otra más barata por unidad.
    """

    def tarea() -> dict[str, Any]:
        nombres, cp = _preparar(supermercados, codigo_postal)
        pendientes = lista.ver(incluir_comprados=False)
        if not pendientes:
            return {"error": "lista_vacia", "motivo": "no hay artículos pendientes en la lista"}
        return tiendas.presupuestar(pendientes, nombres, cp)

    return await _hilo(tarea)


@mcp.tool()
async def lista_anadir_varios(articulos: list[dict[str, Any]]) -> dict[str, Any]:
    """Añade varios artículos de una vez. Cada uno: {"articulo": texto, "cantidad": 1, "nota": opcional}.

    Si alguno no es válido, no se añade ninguno.
    """

    def tarea() -> dict[str, Any]:
        preparados = []
        for articulo in articulos:
            sobran = set(articulo) - {"articulo", "cantidad", "nota"}
            if sobran or not str(articulo.get("articulo", "")).strip():
                raise ValueError(f"artículo no válido: {articulo!r}")
            cantidad = articulo.get("cantidad", 1)
            if not isinstance(cantidad, int) or isinstance(cantidad, bool) or cantidad < 1:
                raise ValueError(f"cantidad no válida en {articulo['articulo']!r}: debe ser un entero de 1 o más")
            preparados.append((articulo["articulo"], cantidad, articulo.get("nota")))
        return {"anadidos": [lista.anadir(*p) for p in preparados]}

    return await _hilo(tarea)


@mcp.tool()
async def perfiles_ver(nombre: str | None = None) -> dict[str, Any]:
    """Perfiles de hogar guardados (para quién se cocina, gustos, alergias, costumbres y lo aprendido).

    Sin nombre devuelve todos. Llámala al empezar a planificar un menú.
    """

    return await _hilo(perfiles.ver, nombre)


@mcp.tool()
async def perfil_guardar(
    nombre: str,
    comensales: str | None = None,
    dieta: str | None = None,
    gustos: list[str] | None = None,
    evitar: list[str] | None = None,
    alergias: list[str] | None = None,
    supermercados: list[str] | None = None,
    presupuesto_semanal: str | None = None,
    notas: str | None = None,
) -> dict[str, Any]:
    """Crea un perfil o actualiza los campos indicados; los que no se pasan no cambian.

    Las listas (gustos, evitar, alergias, supermercados) sustituyen a las anteriores:
    envía la lista completa. ``comensales`` es texto libre ("2 adultos y una niña de 6 años").
    """

    return await _hilo(
        lambda: perfiles.guardar(
            nombre, comensales=comensales, dieta=dieta, gustos=gustos, evitar=evitar,
            alergias=alergias, supermercados=supermercados,
            presupuesto_semanal=presupuesto_semanal, notas=notas,
        )
    )


@mcp.tool()
async def perfil_aprender(nombre: str, observacion: str, categoria: str = "costumbre") -> dict[str, Any]:
    """Apunta con fecha algo aprendido sobre un perfil. Categorías: gusto, evitar, costumbre, dieta, nota."""

    return await _hilo(perfiles.aprender, nombre, observacion, categoria)


@mcp.tool()
async def perfil_olvidar(nombre: str, apunte_id: int) -> dict[str, Any]:
    """Borra un apunte aprendido de un perfil."""

    return await _hilo(perfiles.olvidar, nombre, apunte_id)


@mcp.tool()
async def perfil_borrar(nombre: str) -> dict[str, Any]:
    """Borra un perfil entero, con lo aprendido y su historial de menús. No se puede deshacer."""

    return await _hilo(perfiles.borrar, nombre)


@mcp.tool()
async def menu_guardar(nombre: str, platos: dict[str, str], fecha: str | None = None) -> dict[str, Any]:
    """Guarda el menú de un día para un perfil (por defecto, hoy; fecha en formato AAAA-MM-DD).

    ``platos`` usa las claves desayuno, media_manana, comida, merienda y cena.
    Sustituye al menú que hubiera para esa fecha.
    """

    return await _hilo(perfiles.menu_guardar, nombre, platos, fecha)


@mcp.tool()
async def menu_valorar(
    nombre: str, puntuacion: int, comentario: str | None = None, fecha: str | None = None
) -> dict[str, Any]:
    """Puntúa el menú de un día de 1 (no repetir) a 5 (repetir a menudo), con un comentario opcional."""

    return await _hilo(perfiles.menu_valorar, nombre, puntuacion, comentario, fecha)


@mcp.tool()
async def menu_historial(nombre: str, dias: int = 14) -> dict[str, Any]:
    """Menús recientes de un perfil con sus puntuaciones, para no repetir y saber qué gustó."""

    return await _hilo(perfiles.menu_historial, nombre, dias)


def texto_agente() -> str:
    """Instrucciones del agente planificador (las mismas para Claude Code y para el prompt MCP)."""

    from importlib.resources import files

    return files(__package__).joinpath("agente.md").read_text(encoding="utf-8")


DESCRIPCION_AGENTE = (
    "Planifica el menú diario de un hogar y prepara la cesta de la compra en supermercados de "
    "España, recordando gustos, alergias y costumbres. Úsalo cuando pidan un menú, qué cocinar "
    "o hacer la compra."
)


def fichero_agente() -> str:
    """Definición del agente para Claude Code (~/.claude/agents/chef-compra.md)."""

    return (
        f"---\nname: chef-compra\ndescription: {DESCRIPCION_AGENTE}\n"
        # solo las herramientas de este servidor: el agente no toca ficheros ni la terminal
        f"tools: mcp__supermercados__*\n---\n\n{texto_agente()}"
    )


@mcp.prompt(name="chef_compra", title="Menú del día y cesta de la compra", description=DESCRIPCION_AGENTE)
def chef_compra() -> str:
    return texto_agente() + "\nEmpieza ahora: consulta los perfiles y saluda.\n"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="supermercados-mcp", description=mcp.instructions)
    parser.add_argument("--http", action="store_true", help="servir por HTTP (streamable-http) en vez de stdio")
    parser.add_argument("--host", default="127.0.0.1", help="interfaz para --http (por defecto, solo local)")
    parser.add_argument("--port", type=int, default=8765, help="puerto para --http")
    parser.add_argument(
        "--agente", action="store_true",
        help="imprime la definición del agente chef-compra para Claude Code y termina",
    )
    opciones = parser.parse_args()
    if opciones.agente:
        print(fichero_agente(), end="")
        return
    if opciones.http:
        mcp.run("streamable-http", host=opciones.host, port=opciones.port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
