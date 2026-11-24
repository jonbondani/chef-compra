import pytest

from supermercados_mcp import tiendas


def test_supermercados_por_defecto():
    assert tiendas.nombres(None) == ["mercadona", "carrefour", "dia", "lidl", "aldi"]
    assert tiendas.nombres([]) == tiendas.nombres(None)


def test_nombres_normaliza_y_deduplica():
    assert tiendas.nombres([" Día ", "dia", "LIDL"]) == ["dia", "lidl"]


def test_nombre_desconocido():
    with pytest.raises(tiendas.ErrorDeUso, match="hipercor"):
        tiendas.nombres(["hipercor"])


@pytest.mark.parametrize("cp", ["2800", "280011", "abcde", "00123", "53001"])
def test_codigo_postal_no_valido(cp):
    with pytest.raises(tiendas.ErrorDeUso):
        tiendas.codigo_postal(cp)


def test_codigo_postal_del_entorno(monkeypatch):
    assert tiendas.codigo_postal(None) is None
    monkeypatch.setenv("SUPERMERCADOS_CP", "28001")
    assert tiendas.codigo_postal(None) == "28001"
    assert tiendas.codigo_postal(" 28001 ") == "28001"  # el argumento manda


def test_los_cinco_principales_existen():
    assert set(tiendas.POR_DEFECTO) <= set(tiendas.CLIENTES)
