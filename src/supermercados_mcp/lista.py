"""Lista de la compra guardada en un fichero JSON local."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def ruta_datos() -> Path:
    """Devuelve la carpeta de datos (variable SUPERMERCADOS_MCP_DATOS o ~/.supermercados-mcp)."""

    base = os.environ.get("SUPERMERCADOS_MCP_DATOS")
    return Path(base).expanduser() if base else Path.home() / ".supermercados-mcp"


def leer_json(nombre: str, defecto: dict[str, Any]) -> dict[str, Any]:
    """Lee un fichero de la carpeta de datos, o devuelve ``defecto`` si no existe."""

    fichero = ruta_datos() / nombre
    if not fichero.exists():
        return defecto
    return json.loads(fichero.read_text(encoding="utf-8"))


def guardar_json(nombre: str, datos: dict[str, Any]) -> None:
    """Escribe de forma atómica: un corte a medias nunca deja el fichero corrupto."""

    fichero = ruta_datos() / nombre
    fichero.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(dir=fichero.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as salida:
            json.dump(datos, salida, ensure_ascii=False, indent=2)
        os.replace(temporal, fichero)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise


def _leer() -> dict[str, Any]:
    datos = leer_json("lista.json", {})
    datos.setdefault("siguiente_id", 1)
    datos.setdefault("articulos", [])
    return datos


def _guardar(datos: dict[str, Any]) -> None:
    guardar_json("lista.json", datos)


def ver(incluir_comprados: bool = True) -> list[dict[str, Any]]:
    with _LOCK:
        articulos = _leer()["articulos"]
    if incluir_comprados:
        return articulos
    return [a for a in articulos if not a["comprado"]]


def anadir(articulo: str, cantidad: int = 1, nota: str | None = None) -> dict[str, Any]:
    nombre = " ".join(articulo.split())
    if not nombre:
        raise ValueError("el artículo no puede estar vacío")
    if cantidad < 1:
        raise ValueError("la cantidad debe ser 1 o más")
    with _LOCK:
        datos = _leer()
        for existente in datos["articulos"]:
            if existente["articulo"].casefold() == nombre.casefold() and not existente["comprado"]:
                existente["cantidad"] += cantidad
                if nota:
                    existente["nota"] = nota
                _guardar(datos)
                return existente
        nuevo = {
            "id": datos["siguiente_id"],
            "articulo": nombre,
            "cantidad": cantidad,
            "nota": nota,
            "comprado": False,
        }
        datos["siguiente_id"] += 1
        datos["articulos"].append(nuevo)
        _guardar(datos)
        return nuevo


def _buscar(datos: dict[str, Any], articulo_id: int) -> dict[str, Any]:
    for articulo in datos["articulos"]:
        if articulo["id"] == articulo_id:
            return articulo
    raise KeyError(f"no hay ningún artículo con id {articulo_id}")


def cambiar(
    articulo_id: int,
    *,
    cantidad: int | None = None,
    comprado: bool | None = None,
    nota: str | None = None,
) -> dict[str, Any]:
    if cantidad is not None and cantidad < 1:
        raise ValueError("la cantidad debe ser 1 o más")
    with _LOCK:
        datos = _leer()
        articulo = _buscar(datos, articulo_id)
        if cantidad is not None:
            articulo["cantidad"] = cantidad
        if comprado is not None:
            articulo["comprado"] = comprado
        if nota is not None:
            articulo["nota"] = nota or None
        _guardar(datos)
        return articulo


def quitar(articulo_id: int) -> dict[str, Any]:
    with _LOCK:
        datos = _leer()
        articulo = _buscar(datos, articulo_id)
        datos["articulos"].remove(articulo)
        _guardar(datos)
        return articulo


def vaciar(solo_comprados: bool = True) -> int:
    with _LOCK:
        datos = _leer()
        antes = len(datos["articulos"])
        datos["articulos"] = (
            [a for a in datos["articulos"] if not a["comprado"]] if solo_comprados else []
        )
        _guardar(datos)
        return antes - len(datos["articulos"])
