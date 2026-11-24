"""Acceso a las tiendas online de los supermercados a través de supermercapy.

Un cliente por (supermercado, código postal) se reutiliza entre llamadas para no
repetir las peticiones que cuesta asociarlo a un código postal. Cada cliente
atiende una llamada a la vez.
"""

from __future__ import annotations

import atexit
import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Callable, Iterator

import httpx
from supermercapy import (
    ALL_CLIENTS,
    BaseClient,
    Capability,
    OutOfCoverageError,
    SupermercapyError,
    to_dict,
)

CLIENTES: dict[str, type[BaseClient]] = {c.store_name: c for c in ALL_CLIENTS}
POR_DEFECTO: tuple[str, ...] = ("mercadona", "carrefour", "dia", "lidl", "aldi")
ALIAS = {"día": "dia", "ahorramás": "ahorramas", "bonàrea": "bonarea"}
# La librería devuelve rutas relativas en algunas tiendas.
WEB = {"lidl": "https://www.lidl.es"}
AVISO_SIN_COBERTURA = (
    "La tienda online no sirve a ese código postal: se muestran el surtido y los precios "
    "de su zona por defecto, que pueden diferir de los de tu tienda física."
)
ETIQUETA_UNIDAD = {
    "kg": "€/kg",
    "l": "€/l",
    "piece": "€/ud",
    "dose": "€/dosis",
    "m": "€/m",
    "m2": "€/m²",
}

# Solo para pruebas: transporte httpx que sustituye a la red real.
TRANSPORTE: httpx.BaseTransport | None = None
TIEMPO_ESPERA = float(os.environ.get("SUPERMERCADOS_TIMEOUT", "15"))


class ErrorDeUso(ValueError):
    """Argumentos no válidos; el mensaje se devuelve tal cual a quien llama."""


def codigo_postal(valor: str | None) -> str | None:
    """Normaliza el código postal, o usa SUPERMERCADOS_CP si no se indica."""

    valor = (valor or os.environ.get("SUPERMERCADOS_CP") or "").strip()
    if not valor:
        return None
    if not re.fullmatch(r"\d{5}", valor) or not "01" <= valor[:2] <= "52":
        raise ErrorDeUso(f"código postal no válido: {valor!r} (deben ser 5 dígitos de España)")
    return valor


def nombres(supermercados: list[str] | None) -> list[str]:
    """Valida y normaliza la lista de supermercados; por defecto, los cinco principales."""

    if not supermercados:
        return list(POR_DEFECTO)
    resultado: list[str] = []
    for nombre in supermercados:
        clave = nombre.strip().casefold()
        clave = ALIAS.get(clave, clave)
        if clave not in CLIENTES:
            raise ErrorDeUso(
                f"supermercado desconocido: {nombre!r}. Disponibles: {', '.join(CLIENTES)}"
            )
        if clave not in resultado:
            resultado.append(clave)
    return resultado


class _Pool:
    def __init__(self) -> None:
        self._guardia = threading.Lock()
        self._clientes: dict[tuple[str, str | None], BaseClient] = {}
        self._cerrojos: dict[tuple[str, str | None], threading.Lock] = {}
        self.avisos: dict[tuple[str, str | None], str] = {}

    def _crear(self, tienda: str, cp: str | None) -> BaseClient:
        clase = CLIENTES[tienda]
        opciones: dict[str, Any] = {"timeout": TIEMPO_ESPERA}
        if TRANSPORTE is not None:
            opciones["transport"] = TRANSPORTE
        if tienda == "lidl":
            # la búsqueda de Lidl mezcla bazar y alimentación; para la compra interesa la segunda
            familia = os.environ.get("SUPERMERCADOS_LIDL_FAMILIA", "grocery").strip().lower()
            if familia in ("grocery", "shop"):
                opciones["family"] = familia
        if cp and clase.supports(Capability.POSTAL_CODE):
            try:
                return clase.from_postal_code(cp, **opciones)
            except OutOfCoverageError:
                if tienda == "mercadona":
                    raise
                self.avisos[(tienda, cp)] = AVISO_SIN_COBERTURA
        if tienda == "mercadona":
            raise ErrorDeUso("Mercadona necesita un código postal para saber qué almacén consultar")
        return clase(**opciones)

    @contextmanager
    def usar(self, tienda: str, cp: str | None) -> Iterator[BaseClient]:
        clave = (tienda, cp)
        with self._guardia:
            cerrojo = self._cerrojos.setdefault(clave, threading.Lock())
        with cerrojo:
            cliente = self._clientes.get(clave)
            if cliente is None:
                cliente = self._crear(tienda, cp)
                self._clientes[clave] = cliente
            try:
                yield cliente
            except SupermercapyError:
                # tras un fallo se descarta: el siguiente uso abre una sesión limpia
                self._clientes.pop(clave, None)
                cliente.close()
                raise

    def cerrar(self) -> None:
        with self._guardia:
            clientes, self._clientes = list(self._clientes.values()), {}
        for cliente in clientes:
            cliente.close()


POOL = _Pool()
atexit.register(POOL.cerrar)


def _numero(valor: Decimal | None) -> float | None:
    return float(valor) if valor is not None else None


def resumen(producto: Any, tienda: str | None = None) -> dict[str, Any]:
    """Reduce un producto a los campos útiles para comprar y comparar."""

    precio = producto.price
    referencia = precio.reference if precio is not None else None
    url = producto.url
    if url and url.startswith("/") and tienda in WEB:
        url = WEB[tienda] + url
    datos: dict[str, Any] = {
        "id": producto.id,
        "nombre": producto.name,
        "marca": producto.brand,
        "formato": producto.pack_size_text,
        "precio": _numero(precio.amount) if precio is not None else None,
        "precio_anterior": _numero(precio.previous) if precio is not None else None,
        "precio_por_unidad": (
            f"{referencia.amount:.2f} {ETIQUETA_UNIDAD.get(referencia.unit.value, referencia.unit.value)}"
            if referencia is not None
            else (precio.unit_price_text if precio is not None else None)
        ),
        "en_oferta": bool(precio.is_discounted) if precio is not None else False,
        "promociones": [p.description for p in producto.promotions if p.description],
        "disponible": producto.availability.available if producto.availability else None,
        "ean": producto.ean,
        "url": url,
    }
    return {k: v for k, v in datos.items() if v not in (None, [], "")}


def _error(error: Exception) -> dict[str, Any]:
    if isinstance(error, OutOfCoverageError):
        return {"error": "sin_cobertura", "motivo": "no sirve a ese código postal"}
    return {"error": type(error).__name__, "motivo": str(error)[:300]}


def _en_paralelo(
    tiendas: list[str], cp: str | None, tarea: Callable[[str, BaseClient], Any]
) -> dict[str, Any]:
    """Ejecuta ``tarea`` en cada tienda; el fallo de una no oculta a las demás."""

    def una(tienda: str) -> Any:
        try:
            with POOL.usar(tienda, cp) as cliente:
                resultado = tarea(tienda, cliente)
        except (SupermercapyError, ErrorDeUso) as error:
            return _error(error)
        aviso = POOL.avisos.get((tienda, cp))
        if aviso and isinstance(resultado, dict):
            resultado["aviso"] = aviso
        return resultado

    with ThreadPoolExecutor(max_workers=max(1, len(tiendas))) as hilos:
        return dict(zip(tiendas, hilos.map(una, tiendas)))


def _limite(cliente: BaseClient, limite: int) -> int:
    maximo = getattr(cliente, "max_page_size", None) or limite
    return max(1, min(limite, maximo))


def buscar(consulta: str, tiendas: list[str], cp: str | None, limite: int) -> dict[str, Any]:
    consulta = consulta.strip()
    if not consulta:
        raise ErrorDeUso("la consulta no puede estar vacía")

    def tarea(tienda: str, cliente: BaseClient) -> dict[str, Any]:
        pagina = cliente.search_products(consulta, page_size=_limite(cliente, limite))
        return {
            "total": pagina.total_hits,
            "productos": [resumen(p, tienda) for p in pagina.products[:limite]],
        }

    return _en_paralelo(tiendas, cp, tarea)


def comparar(consulta: str, tiendas: list[str], cp: str | None, limite: int) -> dict[str, Any]:
    """Ordena los resultados de todas las tiendas por precio por kilo, litro o unidad."""

    consulta = consulta.strip()
    if not consulta:
        raise ErrorDeUso("la consulta no puede estar vacía")

    def tarea(tienda: str, cliente: BaseClient) -> list[Any]:
        return list(cliente.search_products(consulta, page_size=_limite(cliente, limite)).products)[
            :limite
        ]

    por_tienda = _en_paralelo(tiendas, cp, tarea)
    filas: list[tuple[str, Decimal, str, Any]] = []
    sin_referencia = 0
    errores: dict[str, Any] = {}
    for tienda, productos in por_tienda.items():
        if isinstance(productos, dict):
            errores[tienda] = productos
            continue
        for producto in productos:
            referencia = producto.price.reference if producto.price else None
            if referencia is None:
                sin_referencia += 1
            else:
                filas.append((referencia.unit.value, referencia.amount, tienda, producto))
    unidades = Counter(unidad for unidad, *_ in filas)
    principal = unidades.most_common(1)[0][0] if unidades else None
    ranking = [
        {"supermercado": tienda, **resumen(producto, tienda)}
        for unidad, _, tienda, producto in sorted(filas, key=lambda f: (f[1], f[2]))
        if unidad == principal
    ]
    return {
        "unidad_comparada": ETIQUETA_UNIDAD.get(principal, principal) if principal else None,
        "ranking": ranking,
        "omitidos_otra_unidad": sum(n for u, n in unidades.items() if u != principal),
        "omitidos_sin_precio_unitario": sin_referencia,
        "errores": errores,
        "avisos": {t: a for (t, c), a in POOL.avisos.items() if c == cp and t in tiendas},
    }


def presupuestar(
    articulos: list[dict[str, Any]], tiendas: list[str], cp: str | None, candidatos: int = 5
) -> dict[str, Any]:
    """Calcula cuánto costaría la lista en cada tienda.

    Para cada artículo se toma el resultado más relevante de la búsqueda de la
    tienda que tenga precio. No se comprueba que sea el mismo producto entre
    tiendas, así que el total es una estimación.
    """

    def tarea(tienda: str, cliente: BaseClient) -> dict[str, Any]:
        lineas: list[dict[str, Any]] = []
        faltan: list[str] = []
        total = Decimal("0")
        for articulo in articulos:
            pagina = cliente.search_products(
                articulo["articulo"], page_size=_limite(cliente, candidatos)
            )
            con_precio = [
                p
                for p in pagina.products[:candidatos]
                if p.price is not None
                and p.price.amount is not None
                and (p.availability is None or p.availability.available is not False)
            ]
            if not con_precio:
                faltan.append(articulo["articulo"])
                continue
            elegido = con_precio[0]
            subtotal = elegido.price.amount * articulo["cantidad"]
            total += subtotal
            linea: dict[str, Any] = {
                "articulo": articulo["articulo"],
                "cantidad": articulo["cantidad"],
                "subtotal": float(subtotal),
                "producto": resumen(elegido, tienda),
            }
            referencia = elegido.price.reference
            if referencia is not None:
                mejores = [
                    p
                    for p in con_precio[1:]
                    if p.price.reference is not None
                    and p.price.reference.unit is referencia.unit
                    and p.price.reference.amount < referencia.amount
                ]
                if mejores:
                    barato = min(mejores, key=lambda p: p.price.reference.amount)
                    linea["alternativa_mas_barata_por_unidad"] = resumen(barato, tienda)
            lineas.append(linea)
        return {
            "total": float(total),
            "articulos_encontrados": len(lineas),
            "no_encontrados": faltan,
            "lineas": lineas,
        }

    por_tienda = _en_paralelo(tiendas, cp, tarea)
    completos = {
        tienda: datos["total"]
        for tienda, datos in por_tienda.items()
        if "error" not in datos and not datos["no_encontrados"] and datos["lineas"]
    }
    return {
        "supermercados": por_tienda,
        "mas_barato_con_todo": min(completos, key=completos.get) if completos else None,
        "aviso": (
            "Estimación: cada línea usa el resultado más relevante de la búsqueda de cada "
            "tienda, que puede no ser el mismo producto ni el mismo formato entre tiendas. "
            "Revisa las líneas antes de decidir."
        ),
    }


def _compacto(valor: Any) -> Any:
    """Quita los valores vacíos de la salida completa de un producto."""

    if isinstance(valor, dict):
        limpio = {k: _compacto(v) for k, v in valor.items()}
        return {k: v for k, v in limpio.items() if v not in (None, [], {}, "")}
    if isinstance(valor, list):
        return [_compacto(v) for v in valor]
    return valor


def detalle(tienda: str, producto_id: str, cp: str | None) -> dict[str, Any]:
    try:
        with POOL.usar(tienda, cp) as cliente:
            return _compacto(to_dict(cliente.get_product(producto_id)))
    except SupermercapyError as error:
        return _error(error)


def ofertas(tienda: str, cp: str | None, limite: int, contiene: str | None) -> dict[str, Any]:
    clase = CLIENTES[tienda]
    if not clase.supports(Capability.OFFERS):
        con_ofertas = [n for n, c in CLIENTES.items() if c.supports(Capability.OFFERS)]
        return {
            "error": "sin_ofertas",
            "motivo": f"{tienda} no publica un listado de ofertas. Sí lo publican: {', '.join(con_ofertas)}",
        }
    try:
        with POOL.usar(tienda, cp) as cliente:
            productos = list(cliente.get_offers())
    except SupermercapyError as error:
        return _error(error)
    if contiene:
        aguja = contiene.casefold()
        productos = [p for p in productos if aguja in (p.name or "").casefold()]
    datos: dict[str, Any] = {
        "total": len(productos),
        "ofertas": [resumen(p, tienda) for p in productos[:limite]],
    }
    if POOL.avisos.get((tienda, cp)):
        datos["aviso"] = POOL.avisos[(tienda, cp)]
    return datos
