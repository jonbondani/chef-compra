"""Lógica del presupuesto con una tienda simulada (sin red ni grabaciones)."""

from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest
from supermercapy import Unit

from supermercados_mcp import tiendas


def producto(id_, nombre, precio, por_litro=None, unidad=Unit.LITRE, disponible=True):
    referencia = NS(amount=Decimal(str(por_litro)), unit=unidad) if por_litro is not None else None
    precio_ = None
    if precio is not None:
        precio_ = NS(amount=Decimal(str(precio)), previous=None, reference=referencia,
                     unit_price_text=None, is_discounted=False)
    return NS(id=id_, name=nombre, brand=None, pack_size_text=None, price=precio_, promotions=(),
              availability=NS(available=disponible), ean=None, url=None)


class TiendaSimulada:
    max_page_size = 50

    def __init__(self, catalogo):
        self.catalogo = catalogo

    def search_products(self, consulta, page_size=None):
        return NS(products=tuple(self.catalogo.get(consulta, ())), total_hits=0)


@pytest.fixture
def simular(monkeypatch):
    def _simular(catalogos):
        @contextmanager
        def usar(tienda, cp):
            yield TiendaSimulada(catalogos[tienda])

        monkeypatch.setattr(tiendas.POOL, "usar", usar)

    return _simular


def articulo(nombre, cantidad=1):
    return {"articulo": nombre, "cantidad": cantidad}


def test_elige_el_mas_relevante_y_propone_el_mas_barato_por_unidad(simular):
    simular({"a": {"leche": [
        producto("1", "Leche marca", 1.50, 1.50),
        producto("2", "Leche pack 6", 5.40, 0.90),
        producto("3", "Leche barata", 1.10, 1.10),
        producto("4", "Queso", 1.00, 0.50, Unit.KILOGRAM),  # otra unidad: no es comparable
    ]}})
    datos = tiendas.presupuestar([articulo("leche", 3)], ["a"], None)
    linea = datos["supermercados"]["a"]["lineas"][0]
    assert linea["producto"]["id"] == "1" and linea["subtotal"] == 4.5
    assert linea["alternativa_mas_barata_por_unidad"]["id"] == "2"
    assert datos["supermercados"]["a"]["total"] == 4.5


def test_sin_alternativa_si_el_elegido_ya_es_el_mas_barato(simular):
    simular({"a": {"leche": [producto("1", "Leche", 0.80, 0.80), producto("2", "Otra", 1.2, 1.2)]}})
    linea = tiendas.presupuestar([articulo("leche")], ["a"], None)["supermercados"]["a"]["lineas"][0]
    assert "alternativa_mas_barata_por_unidad" not in linea


def test_salta_productos_sin_precio_o_agotados(simular):
    simular({"a": {"pan": [
        producto("1", "Sin precio", None),
        producto("2", "Agotado", 0.5, disponible=False),
        producto("3", "Pan", 0.9),
    ]}})
    datos = tiendas.presupuestar([articulo("pan")], ["a"], None)["supermercados"]["a"]
    assert datos["lineas"][0]["producto"]["id"] == "3"


def test_no_encontrados_y_mas_barato_con_todo(simular):
    simular({
        "a": {"pan": [producto("1", "Pan", 1.0)], "sal": [producto("2", "Sal", 0.5)]},
        "b": {"pan": [producto("3", "Pan", 0.2)]},              # más barato, pero le falta la sal
        "c": {"pan": [producto("4", "Pan", 1.2)], "sal": [producto("5", "Sal", 0.6)]},
    })
    datos = tiendas.presupuestar([articulo("pan"), articulo("sal")], ["a", "b", "c"], None)
    assert datos["supermercados"]["b"]["no_encontrados"] == ["sal"]
    assert datos["supermercados"]["b"]["total"] == 0.2
    assert datos["mas_barato_con_todo"] == "a"


def test_ninguna_tienda_lo_tiene_todo(simular):
    simular({"a": {}})
    datos = tiendas.presupuestar([articulo("pan")], ["a"], None)
    assert datos["mas_barato_con_todo"] is None
    assert datos["supermercados"]["a"] == {"total": 0.0, "articulos_encontrados": 0,
                                           "no_encontrados": ["pan"], "lineas": []}


def test_totales_sin_error_de_coma_flotante(simular):
    simular({"a": {"x": [producto("1", "X", 0.1)]}})
    assert tiendas.presupuestar([articulo("x", 3)], ["a"], None)["supermercados"]["a"]["total"] == 0.3
