"""Memoria del planificador de menús: para quién se cocina, qué les gusta y qué han comido.

Todo se guarda en ``perfiles.json`` dentro de la carpeta de datos local. Nada sale del equipo.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta
from typing import Any

from .lista import guardar_json, leer_json

_LOCK = threading.Lock()
FICHERO = "perfiles.json"
CAMPOS_TEXTO = ("comensales", "dieta", "presupuesto_semanal", "notas")
CAMPOS_LISTA = ("gustos", "evitar", "alergias", "supermercados")
CATEGORIAS = ("gusto", "evitar", "costumbre", "dieta", "nota")
COMIDAS = ("desayuno", "media_manana", "comida", "merienda", "cena")


def _leer() -> dict[str, Any]:
    datos = leer_json(FICHERO, {})
    datos.setdefault("perfiles", {})
    return datos


def _clave(nombre: str) -> str:
    clave = " ".join(nombre.split()).casefold()
    if not clave:
        raise ValueError("el nombre del perfil no puede estar vacío")
    return clave


def _perfil(datos: dict[str, Any], nombre: str) -> dict[str, Any]:
    try:
        return datos["perfiles"][_clave(nombre)]
    except KeyError:
        existentes = ", ".join(p["nombre"] for p in datos["perfiles"].values()) or "ninguno"
        raise KeyError(f"no hay ningún perfil llamado {nombre!r} (existentes: {existentes})") from None


def _fecha(valor: str | None) -> str:
    if not valor:
        return date.today().isoformat()
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError:
        raise ValueError(f"fecha no válida: {valor!r} (formato AAAA-MM-DD)") from None


def _limpiar(valores: list[str]) -> list[str]:
    vistos: list[str] = []
    for valor in valores:
        texto = " ".join(str(valor).split())
        if texto and texto.casefold() not in (v.casefold() for v in vistos):
            vistos.append(texto)
    return vistos


def _resumen(perfil: dict[str, Any]) -> dict[str, Any]:
    """El perfil sin el historial de menús, que se consulta aparte."""

    return {k: v for k, v in perfil.items() if k != "menus"}


def ver(nombre: str | None = None) -> dict[str, Any]:
    with _LOCK:
        datos = _leer()
        if nombre:
            return _resumen(_perfil(datos, nombre))
        return {"perfiles": [_resumen(p) for p in datos["perfiles"].values()]}


def guardar(nombre: str, **campos: Any) -> dict[str, Any]:
    """Crea el perfil o cambia los campos indicados. Los que no se pasan no se tocan."""

    desconocidos = set(campos) - set(CAMPOS_TEXTO) - set(CAMPOS_LISTA)
    if desconocidos:
        raise ValueError(f"campos desconocidos: {', '.join(sorted(desconocidos))}")
    with _LOCK:
        datos = _leer()
        clave = _clave(nombre)
        perfil = datos["perfiles"].setdefault(
            clave,
            {
                "nombre": " ".join(nombre.split()),
                **{c: None for c in CAMPOS_TEXTO},
                **{c: [] for c in CAMPOS_LISTA},
                "aprendido": [],
                "siguiente_id": 1,
                "menus": {},
            },
        )
        for campo, valor in campos.items():
            if valor is None:
                continue
            if campo in CAMPOS_LISTA:
                perfil[campo] = _limpiar(valor)
            else:
                perfil[campo] = " ".join(str(valor).split()) or None
        guardar_json(FICHERO, datos)
        return _resumen(perfil)


def aprender(nombre: str, observacion: str, categoria: str = "costumbre") -> dict[str, Any]:
    """Apunta algo observado sobre el perfil, con su fecha."""

    texto = " ".join(observacion.split())
    if not texto:
        raise ValueError("la observación no puede estar vacía")
    if categoria not in CATEGORIAS:
        raise ValueError(f"categoría no válida: {categoria!r} (usa una de: {', '.join(CATEGORIAS)})")
    with _LOCK:
        datos = _leer()
        perfil = _perfil(datos, nombre)
        for apunte in perfil["aprendido"]:
            if apunte["observacion"].casefold() == texto.casefold():
                return apunte
        apunte = {
            "id": perfil["siguiente_id"],
            "fecha": date.today().isoformat(),
            "categoria": categoria,
            "observacion": texto,
        }
        perfil["siguiente_id"] += 1
        perfil["aprendido"].append(apunte)
        guardar_json(FICHERO, datos)
        return apunte


def olvidar(nombre: str, apunte_id: int) -> dict[str, Any]:
    with _LOCK:
        datos = _leer()
        perfil = _perfil(datos, nombre)
        for apunte in perfil["aprendido"]:
            if apunte["id"] == apunte_id:
                perfil["aprendido"].remove(apunte)
                guardar_json(FICHERO, datos)
                return apunte
        raise KeyError(f"el perfil {perfil['nombre']!r} no tiene ningún apunte con id {apunte_id}")


def borrar(nombre: str) -> dict[str, Any]:
    with _LOCK:
        datos = _leer()
        perfil = _perfil(datos, nombre)
        del datos["perfiles"][_clave(nombre)]
        guardar_json(FICHERO, datos)
        return {"borrado": perfil["nombre"], "menus_borrados": len(perfil["menus"])}


def menu_guardar(
    nombre: str, platos: dict[str, str], fecha: str | None = None
) -> dict[str, Any]:
    """Guarda el menú de un día. Sustituye al que hubiera para esa fecha."""

    desconocidas = set(platos) - set(COMIDAS)
    if desconocidas:
        raise ValueError(
            f"comidas desconocidas: {', '.join(sorted(desconocidas))} (usa: {', '.join(COMIDAS)})"
        )
    limpio = {c: " ".join(platos[c].split()) for c in COMIDAS if platos.get(c, "").strip()}
    if not limpio:
        raise ValueError("el menú no tiene ningún plato")
    dia = _fecha(fecha)
    with _LOCK:
        datos = _leer()
        perfil = _perfil(datos, nombre)
        perfil["menus"][dia] = {"fecha": dia, "platos": limpio}
        guardar_json(FICHERO, datos)
        return perfil["menus"][dia]


def menu_valorar(
    nombre: str, puntuacion: int, comentario: str | None = None, fecha: str | None = None
) -> dict[str, Any]:
    if not 1 <= puntuacion <= 5:
        raise ValueError("la puntuación va de 1 (no repetir) a 5 (repetir a menudo)")
    dia = _fecha(fecha)
    with _LOCK:
        datos = _leer()
        perfil = _perfil(datos, nombre)
        if dia not in perfil["menus"]:
            raise KeyError(f"no hay menú guardado para {dia} en el perfil {perfil['nombre']!r}")
        menu = perfil["menus"][dia]
        menu["puntuacion"] = puntuacion
        if comentario and comentario.strip():
            menu["comentario"] = " ".join(comentario.split())
        guardar_json(FICHERO, datos)
        return menu


def menu_historial(nombre: str, dias: int = 14) -> dict[str, Any]:
    """Menús de los últimos ``dias`` días y de fechas futuras, del más reciente al más antiguo."""

    if dias < 1:
        raise ValueError("dias debe ser 1 o más")
    desde = (date.today() - timedelta(days=dias)).isoformat()
    with _LOCK:
        menus = _perfil(_leer(), nombre)["menus"]
    return {"menus": [menus[d] for d in sorted(menus, reverse=True) if d >= desde]}
