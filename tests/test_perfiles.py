import json
from datetime import date, timedelta

import pytest

from supermercados_mcp import lista, perfiles

HOY = date.today().isoformat()


def test_crear_y_ver():
    p = perfiles.guardar("  Casa ", comensales="2 adultos y una niña de 6 años",
                         gustos=["legumbres", "Legumbres", " arroz "], alergias=["cacahuete"])
    assert p["nombre"] == "Casa" and p["gustos"] == ["legumbres", "arroz"]
    assert p["alergias"] == ["cacahuete"] and p["dieta"] is None and p["aprendido"] == []
    assert "menus" not in p
    assert perfiles.ver("CASA") == p
    assert perfiles.ver() == {"perfiles": [p]}


def test_sin_perfiles():
    assert perfiles.ver() == {"perfiles": []}


def test_actualizar_no_toca_lo_que_no_se_pasa():
    perfiles.guardar("casa", dieta="vegetariana", gustos=["pasta"], alergias=["gluten"])
    p = perfiles.guardar("Casa", gustos=["curry"])
    assert p["gustos"] == ["curry"] and p["dieta"] == "vegetariana" and p["alergias"] == ["gluten"]
    assert len(perfiles.ver()["perfiles"]) == 1


def test_vaciar_un_campo():
    perfiles.guardar("casa", dieta="keto", evitar=["coliflor"])
    p = perfiles.guardar("casa", dieta="", evitar=[])
    assert p["dieta"] is None and p["evitar"] == []


def test_campo_desconocido_y_nombre_vacio():
    with pytest.raises(ValueError):
        perfiles.guardar("casa", edad=3)
    with pytest.raises(ValueError):
        perfiles.guardar("   ")


def test_perfil_inexistente_dice_cuales_hay():
    perfiles.guardar("Casa")
    with pytest.raises(KeyError, match="Casa"):
        perfiles.ver("abuelos")


def test_aprender_y_olvidar():
    perfiles.guardar("casa")
    a = perfiles.aprender("casa", " los lunes  cenan tarde ")
    assert a == {"id": 1, "fecha": HOY, "categoria": "costumbre", "observacion": "los lunes cenan tarde"}
    assert perfiles.aprender("casa", "Los lunes cenan tarde")["id"] == 1  # no se duplica
    b = perfiles.aprender("casa", "no les gusta el pescado azul", "evitar")
    assert [x["id"] for x in perfiles.ver("casa")["aprendido"]] == [1, 2]
    assert perfiles.olvidar("casa", a["id"]) == a
    assert perfiles.ver("casa")["aprendido"] == [b]
    assert perfiles.aprender("casa", "otra cosa")["id"] == 3  # los ids no se reutilizan
    with pytest.raises(KeyError):
        perfiles.olvidar("casa", 99)


@pytest.mark.parametrize("observacion,categoria", [("", "nota"), ("algo", "inventada")])
def test_aprender_rechaza(observacion, categoria):
    perfiles.guardar("casa")
    with pytest.raises(ValueError):
        perfiles.aprender("casa", observacion, categoria)
    assert perfiles.ver("casa")["aprendido"] == []


def test_menu_guardar_valorar_e_historial():
    perfiles.guardar("casa")
    ayer = (date.today() - timedelta(days=1)).isoformat()
    viejo = (date.today() - timedelta(days=40)).isoformat()
    perfiles.menu_guardar("casa", {"comida": "lentejas", "cena": "tortilla"}, viejo)
    perfiles.menu_guardar("casa", {"comida": "paella", "cena": " crema de  calabaza ", "merienda": " "}, ayer)
    hoy = perfiles.menu_guardar("casa", {"desayuno": "tostadas", "comida": "pollo al horno"})
    assert hoy == {"fecha": HOY, "platos": {"desayuno": "tostadas", "comida": "pollo al horno"}}
    v = perfiles.menu_valorar("casa", 2, "la crema quedó sosa", ayer)
    assert v["puntuacion"] == 2 and v["platos"]["cena"] == "crema de calabaza" and "merienda" not in v["platos"]
    assert [m["fecha"] for m in perfiles.menu_historial("casa")["menus"]] == [HOY, ayer]
    assert len(perfiles.menu_historial("casa", dias=60)["menus"]) == 3
    assert "menus" not in perfiles.ver("casa")


def test_menu_del_mismo_dia_se_sustituye():
    perfiles.guardar("casa")
    perfiles.menu_guardar("casa", {"cena": "pizza"})
    perfiles.menu_guardar("casa", {"cena": "ensalada"})
    assert perfiles.menu_historial("casa")["menus"] == [{"fecha": HOY, "platos": {"cena": "ensalada"}}]


@pytest.mark.parametrize("platos,fecha", [({}, None), ({"cena": "  "}, None), ({"brunch": "huevos"}, None),
                                          ({"cena": "sopa"}, "23/11/2026"), ({"cena": "sopa"}, "2026-13-01")])
def test_menu_guardar_rechaza(platos, fecha):
    perfiles.guardar("casa")
    with pytest.raises(ValueError):
        perfiles.menu_guardar("casa", platos, fecha)
    assert perfiles.menu_historial("casa") == {"menus": []}


def test_valorar_rechaza():
    perfiles.guardar("casa")
    with pytest.raises(KeyError):
        perfiles.menu_valorar("casa", 4)  # no hay menú de hoy
    perfiles.menu_guardar("casa", {"cena": "sopa"})
    for puntuacion in (0, 6):
        with pytest.raises(ValueError):
            perfiles.menu_valorar("casa", puntuacion)


def test_perfiles_independientes_y_borrar():
    perfiles.guardar("casa", alergias=["marisco"])
    perfiles.guardar("abuelos", dieta="baja en sal")
    perfiles.menu_guardar("abuelos", {"cena": "sopa"})
    assert perfiles.menu_historial("casa") == {"menus": []}
    assert perfiles.borrar("Abuelos") == {"borrado": "abuelos", "menus_borrados": 1}
    assert [p["nombre"] for p in perfiles.ver()["perfiles"]] == ["casa"]


def test_no_pisa_la_lista_de_la_compra_y_es_legible():
    lista.anadir("pan")
    perfiles.guardar("casa", gustos=["jamón"])
    assert lista.ver()[0]["articulo"] == "pan"
    carpeta = lista.ruta_datos()
    assert sorted(f.name for f in carpeta.iterdir()) == ["lista.json", "perfiles.json"]
    assert "jamón" in (carpeta / "perfiles.json").read_text(encoding="utf-8")
    assert json.loads((carpeta / "perfiles.json").read_text(encoding="utf-8"))["perfiles"]["casa"]
