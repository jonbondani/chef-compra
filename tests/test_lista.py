import json

import pytest

from supermercados_mcp import lista


def test_anadir_y_ver():
    a = lista.anadir("  Leche   entera ", 2)
    assert a == {"id": 1, "articulo": "Leche entera", "cantidad": 2, "nota": None, "comprado": False}
    assert lista.ver() == [a]


def test_anadir_repetido_suma_cantidad():
    lista.anadir("pan")
    repetido = lista.anadir("PAN", 3, nota="integral")
    assert repetido["cantidad"] == 4 and repetido["nota"] == "integral"
    assert len(lista.ver()) == 1


def test_comprado_no_se_fusiona():
    lista.cambiar(lista.anadir("huevos")["id"], comprado=True)
    lista.anadir("huevos")
    assert [a["comprado"] for a in lista.ver()] == [True, False]
    assert [a["articulo"] for a in lista.ver(incluir_comprados=False)] == ["huevos"]


def test_ids_no_se_reutilizan():
    primero = lista.anadir("a")
    lista.quitar(primero["id"])
    assert lista.anadir("b")["id"] == 2


def test_cambiar_y_quitar():
    a = lista.anadir("arroz")
    assert lista.cambiar(a["id"], cantidad=5, nota="bomba")["cantidad"] == 5
    assert lista.cambiar(a["id"], nota="")["nota"] is None
    assert lista.quitar(a["id"])["articulo"] == "arroz"
    assert lista.ver() == []


def test_vaciar():
    lista.cambiar(lista.anadir("a")["id"], comprado=True)
    lista.anadir("b")
    assert lista.vaciar() == 1
    assert [a["articulo"] for a in lista.ver()] == ["b"]
    assert lista.vaciar(solo_comprados=False) == 1
    assert lista.ver() == []


@pytest.mark.parametrize("articulo,cantidad", [("", 1), ("   ", 1), ("pan", 0), ("pan", -2)])
def test_anadir_rechaza_valores_no_validos(articulo, cantidad):
    with pytest.raises(ValueError):
        lista.anadir(articulo, cantidad)
    assert lista.ver() == []


def test_id_inexistente():
    with pytest.raises(KeyError):
        lista.quitar(99)
    with pytest.raises(KeyError):
        lista.cambiar(99, cantidad=2)


def test_fichero_persistente_y_legible():
    lista.anadir("café", nota="en grano")
    fichero = lista.ruta_datos() / "lista.json"
    datos = json.loads(fichero.read_text(encoding="utf-8"))
    assert datos["articulos"][0]["articulo"] == "café"
    assert "café" in fichero.read_text(encoding="utf-8")  # sin escapar, legible a mano
    assert not list(fichero.parent.glob("*.tmp"))
