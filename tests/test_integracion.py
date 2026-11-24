"""De extremo a extremo por el protocolo MCP, con las respuestas grabadas de las tiendas reales.

Las respuestas grabadas son fijas (no dependen de la consulta), así que aquí se
comprueba que cada tienda se consulta, se interpreta y se resume bien, no la
relevancia de la búsqueda, que es cosa de cada tienda.
"""

import pytest

from supermercados_mcp import tiendas

CINCO = ["mercadona", "carrefour", "dia", "lidl", "aldi"]
# códigos postales que las respuestas grabadas de cada tienda reconocen
CP = {"mercadona": "28001", "carrefour": "28232", "dia": "08001", "lidl": "08013", "aldi": "28001"}


def test_expone_las_herramientas():
    import asyncio

    from mcp import Client

    from supermercados_mcp.server import mcp

    async def nombres():
        async with Client(mcp) as cliente:
            return {h.name for h in (await cliente.list_tools()).tools}

    assert asyncio.run(nombres()) == {
        "supermercados_disponibles", "buscar_productos", "comparar_precios", "detalle_producto",
        "ofertas", "lista_ver", "lista_anadir", "lista_cambiar", "lista_quitar", "lista_vaciar",
        "presupuestar_lista", "lista_anadir_varios", "perfiles_ver", "perfil_guardar",
        "perfil_aprender", "perfil_olvidar", "perfil_borrar", "menu_guardar", "menu_valorar",
        "menu_historial",
    }


@pytest.mark.parametrize("tienda", CINCO)
def test_buscar_en_cada_tienda(tiendas_grabadas, llamar, tienda):
    datos = llamar("buscar_productos", consulta="leche", supermercados=[tienda], codigo_postal=CP[tienda])
    resultado = datos[tienda]
    assert "error" not in resultado, resultado
    assert "aviso" not in resultado, resultado
    assert resultado["productos"], resultado
    for producto in resultado["productos"]:
        assert producto["id"] and producto["nombre"]
        assert isinstance(producto["precio"], float) and producto["precio"] > 0
        if "url" in producto:
            assert producto["url"].startswith("https://")
    assert tiendas_grabadas.count(tienda) >= 1


def test_buscar_en_las_cinco_a_la_vez(tiendas_grabadas, llamar):
    datos = llamar("buscar_productos", consulta="leche", codigo_postal="28001", limite=2)
    assert list(datos) == CINCO
    for tienda in CINCO:
        assert "error" not in datos[tienda], (tienda, datos[tienda])
        assert 1 <= len(datos[tienda]["productos"]) <= 2
    # las grabaciones de carrefour y lidl no cubren el 28001: responden con su zona por defecto y avisan
    assert "aviso" in datos["carrefour"] and "aviso" in datos["lidl"]
    assert "aviso" not in datos["dia"]


def test_sin_codigo_postal_solo_falla_mercadona(tiendas_grabadas, llamar):
    datos = llamar("buscar_productos", consulta="leche")
    assert "código postal" in datos["mercadona"]["motivo"]
    for tienda in ("carrefour", "dia", "lidl", "aldi"):
        assert datos[tienda]["productos"]


def test_codigo_postal_del_entorno(tiendas_grabadas, llamar, monkeypatch):
    monkeypatch.setenv("SUPERMERCADOS_CP", "28001")
    assert llamar("buscar_productos", consulta="leche", supermercados=["mercadona"])["mercadona"]["productos"]
    assert llamar("supermercados_disponibles")["codigo_postal_configurado"] == "28001"


def test_una_tienda_caida_no_oculta_a_las_demas(tiendas_grabadas, llamar):
    from tests.canned import failing

    tiendas_grabadas.handlers["dia"] = failing(500)
    datos = llamar("buscar_productos", consulta="leche", supermercados=["dia", "aldi"], codigo_postal="28001")
    assert datos["dia"]["error"] and "productos" not in datos["dia"]
    assert datos["aldi"]["productos"]


def test_tras_un_fallo_el_cliente_se_recrea(tiendas_grabadas, llamar):
    from tests.canned import failing

    original = tiendas_grabadas.handlers["aldi"]
    tiendas_grabadas.handlers["aldi"] = failing(500)
    assert "error" in llamar("buscar_productos", consulta="leche", supermercados=["aldi"])["aldi"]
    tiendas_grabadas.handlers["aldi"] = original
    assert llamar("buscar_productos", consulta="leche", supermercados=["aldi"])["aldi"]["productos"]


def test_el_cliente_se_reutiliza_entre_llamadas(tiendas_grabadas, llamar):
    llamar("buscar_productos", consulta="leche", supermercados=["mercadona"], codigo_postal="28001")
    primera = tiendas_grabadas.count("mercadona")
    llamar("buscar_productos", consulta="pan", supermercados=["mercadona"], codigo_postal="28001")
    # la segunda llamada solo busca: no repite la petición que asocia el código postal
    assert tiendas_grabadas.count("mercadona") - primera == 1 < primera


def test_comparar_ordena_por_precio_unitario(tiendas_grabadas, llamar):
    datos = llamar("comparar_precios", consulta="leche", supermercados=["carrefour", "dia"], codigo_postal="08001")
    assert datos["unidad_comparada"] == "€/l"
    importes = [float(fila["precio_por_unidad"].split()[0]) for fila in datos["ranking"]]
    assert importes == sorted(importes) and len(importes) >= 2
    assert {fila["supermercado"] for fila in datos["ranking"]} == {"carrefour", "dia"}
    assert all(fila["precio_por_unidad"].endswith("€/l") for fila in datos["ranking"])


@pytest.mark.parametrize("tienda", CINCO)
def test_detalle_producto(tiendas_grabadas, llamar, tienda):
    from tests.harness import HARNESSES

    grabacion = HARNESSES[tienda]
    ficha = llamar("detalle_producto", supermercado=tienda, producto_id=grabacion.product_id, codigo_postal=CP[tienda])
    assert "error" not in ficha, ficha
    assert ficha["id"] == grabacion.product_id and ficha["name"]
    assert float(ficha["price"]["amount"]) > 0
    # la ficha no arrastra campos vacíos
    assert all(valor not in (None, [], {}, "") for valor in ficha.values())

    falta = llamar("detalle_producto", supermercado=tienda, producto_id=grabacion.missing_product_id, codigo_postal=CP[tienda])
    assert falta["error"] == "NotFoundError", falta


@pytest.mark.parametrize("tienda", ["dia", "aldi", "lidl"])
def test_ofertas(tiendas_grabadas, llamar, tienda):
    datos = llamar("ofertas", supermercado=tienda, codigo_postal=CP[tienda], limite=2)
    assert "error" not in datos, datos
    assert datos["total"] >= len(datos["ofertas"]) >= 1
    assert len(datos["ofertas"]) <= 2


def test_ofertas_filtra_por_texto(tiendas_grabadas, llamar):
    todas = llamar("ofertas", supermercado="aldi")
    uvas = llamar("ofertas", supermercado="aldi", contiene="UVA")
    assert 1 <= uvas["total"] < todas["total"]
    assert all("uva" in o["nombre"].lower() for o in uvas["ofertas"])


def test_ofertas_en_tienda_que_no_las_publica(tiendas_grabadas, llamar):
    datos = llamar("ofertas", supermercado="mercadona", codigo_postal="28001")
    assert datos["error"] == "sin_ofertas" and "lidl" in datos["motivo"]
    assert tiendas_grabadas.count("mercadona") == 0


def test_presupuestar_lista(tiendas_grabadas, llamar):
    llamar("lista_anadir", articulo="leche", cantidad=2)
    llamar("lista_anadir", articulo="pan")
    comprado = llamar("lista_anadir", articulo="ya comprado")
    llamar("lista_cambiar", articulo_id=comprado["id"], comprado=True)
    datos = llamar("presupuestar_lista", supermercados=["mercadona", "dia", "aldi"], codigo_postal="28001")
    for tienda in ("mercadona", "dia", "aldi"):
        presupuesto = datos["supermercados"][tienda]
        assert presupuesto["articulos_encontrados"] == 2 and not presupuesto["no_encontrados"]
        assert [linea["articulo"] for linea in presupuesto["lineas"]] == ["leche", "pan"]
        leche = presupuesto["lineas"][0]
        assert leche["subtotal"] == pytest.approx(leche["producto"]["precio"] * 2)
        assert presupuesto["total"] == pytest.approx(sum(l["subtotal"] for l in presupuesto["lineas"]))
    totales = {t: d["total"] for t, d in datos["supermercados"].items()}
    assert datos["mas_barato_con_todo"] == min(totales, key=totales.get)
    assert "Estimación" in datos["aviso"]


def test_presupuestar_lista_vacia(tiendas_grabadas, llamar):
    assert llamar("presupuestar_lista", codigo_postal="28001")["error"] == "lista_vacia"
    assert tiendas_grabadas.requests == []


@pytest.mark.parametrize(
    "herramienta,argumentos,texto",
    [
        ("buscar_productos", {"consulta": "leche", "supermercados": ["hipercor"]}, "hipercor"),
        ("buscar_productos", {"consulta": "leche", "codigo_postal": "123"}, "código postal"),
        ("buscar_productos", {"consulta": "   "}, "vacía"),
        ("comparar_precios", {"consulta": ""}, "vacía"),
        ("lista_quitar", {"articulo_id": 42}, "42"),
        ("lista_anadir", {"articulo": "pan", "cantidad": 0}, "cantidad"),
    ],
)
def test_errores_de_uso_no_hacen_peticiones(tiendas_grabadas, llamar, herramienta, argumentos, texto):
    datos = llamar(herramienta, **argumentos)
    assert datos["error"] == "uso" and texto in datos["motivo"]
    assert tiendas_grabadas.requests == []


def test_lista_por_mcp(llamar):
    pan = llamar("lista_anadir", articulo="pan", cantidad=2, nota="integral")
    llamar("lista_anadir", articulo="leche")
    assert [a["articulo"] for a in llamar("lista_ver")["articulos"]] == ["pan", "leche"]
    assert llamar("lista_cambiar", articulo_id=pan["id"], comprado=True)["comprado"] is True
    assert [a["articulo"] for a in llamar("lista_ver", incluir_comprados=False)["articulos"]] == ["leche"]
    assert llamar("lista_vaciar") == {"eliminados": 1}
    assert llamar("lista_vaciar", solo_comprados=False) == {"eliminados": 1}
    assert llamar("lista_ver") == {"articulos": []}
