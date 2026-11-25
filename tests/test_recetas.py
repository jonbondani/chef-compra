"""El catálogo de recetas: cabecera, secciones, variantes e índice."""

import re
from pathlib import Path

import pytest

CARPETA = Path(__file__).resolve().parent.parent / "recetas"
INDICE = CARPETA / "README.md"
RECETAS = sorted(f for f in CARPETA.glob("*.md") if f.name != "README.md")

CLAVES = {"nombre", "categoria", "raciones", "etiquetas", "variantes", "alergenos"}
SECCIONES = ["## Ingredientes", "## Macros estimados por ración", "## Preparación", "## Alérgenos",
             "## Conservación"]
CATEGORIAS = {"desayuno", "almuerzo", "cena", "merienda"}


def lista(valor):
    return [parte.strip() for parte in valor.split(",") if parte.strip()]


def leer(fichero):
    texto = fichero.read_text(encoding="utf-8")
    partes = texto.split("---\n", 2)
    assert texto.startswith("---\n") and len(partes) == 3, f"{fichero.name}: falta la cabecera"
    cabecera = {}
    for linea in partes[1].splitlines():
        clave, separador, valor = linea.partition(":")
        assert separador, f"{fichero.name}: línea de cabecera sin clave: {linea!r}"
        cabecera[clave.strip()] = valor.strip()
    return cabecera, partes[2]


def tabla(cuerpo, seccion):
    """Filas de la primera tabla de una sección, cada una como lista de celdas."""
    trozo = cuerpo.split(seccion, 1)[1].split("\n## ", 1)[0]
    filas = [linea for linea in trozo.splitlines() if linea.startswith("|")]
    return [[celda.strip() for celda in fila.strip("|").split("|")] for fila in filas]


def test_hay_recetas():
    assert RECETAS, "el catálogo está vacío"


@pytest.mark.parametrize("fichero", RECETAS, ids=lambda f: f.name)
def test_nombre_de_fichero(fichero):
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*\.md", fichero.name)


@pytest.mark.parametrize("fichero", RECETAS, ids=lambda f: f.name)
def test_cabecera(fichero):
    cabecera, _ = leer(fichero)
    assert CLAVES <= set(cabecera), CLAVES - set(cabecera)
    assert all(cabecera[clave] for clave in CLAVES)
    assert cabecera["raciones"].isdigit() and int(cabecera["raciones"]) >= 1
    assert set(lista(cabecera["categoria"])) <= CATEGORIAS
    assert lista(cabecera["variantes"])
    assert "—" not in fichero.read_text(encoding="utf-8"), "sin rayas largas"


@pytest.mark.parametrize("fichero", RECETAS, ids=lambda f: f.name)
def test_secciones_en_orden(fichero):
    _, cuerpo = leer(fichero)
    posiciones = [cuerpo.find(f"\n{seccion}\n") for seccion in SECCIONES]
    assert -1 not in posiciones, [s for s, p in zip(SECCIONES, posiciones) if p == -1]
    assert posiciones == sorted(posiciones)


@pytest.mark.parametrize("fichero", RECETAS, ids=lambda f: f.name)
@pytest.mark.parametrize("seccion", ["## Ingredientes", "## Macros estimados por ración"])
def test_una_columna_por_variante(fichero, seccion):
    cabecera, cuerpo = leer(fichero)
    variantes = lista(cabecera["variantes"])
    filas = tabla(cuerpo, seccion)
    assert len(filas) >= 3, "la tabla necesita cabecera, separador y al menos una fila"
    assert [celda.lower() for celda in filas[0][1:]] == variantes
    for fila in filas[2:]:
        assert len(fila) == len(variantes) + 1 and all(fila), fila


def test_indice_y_ficheros_coinciden():
    enlazados = set(re.findall(r"\]\(([a-z0-9-]+\.md)\)", INDICE.read_text(encoding="utf-8")))
    assert enlazados == {f.name for f in RECETAS}


@pytest.mark.parametrize("fichero", RECETAS, ids=lambda f: f.name)
def test_el_indice_repite_los_datos_de_la_cabecera(fichero):
    cabecera, _ = leer(fichero)
    fila = next(linea for linea in INDICE.read_text(encoding="utf-8").splitlines()
                if f"]({fichero.name})" in linea)
    celdas = [celda.strip() for celda in fila.strip("|").split("|")]
    assert celdas[0] == cabecera["nombre"]
    assert lista(celdas[2]) == lista(cabecera["etiquetas"])
    assert lista(celdas[3]) == lista(cabecera["variantes"])
