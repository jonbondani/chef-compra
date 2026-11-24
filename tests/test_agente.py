"""El agente: sus instrucciones, su definición para Claude Code y el recorrido de herramientas que sigue."""

import asyncio
import re
from datetime import date

import pytest

from supermercados_mcp import server

HOY = date.today().isoformat()


def herramientas():
    from mcp import Client

    async def una():
        async with Client(server.mcp) as cliente:
            return {h.name: h for h in (await cliente.list_tools()).tools}

    return asyncio.run(una())


def test_las_instrucciones_solo_nombran_herramientas_que_existen():
    existentes = set(herramientas())
    nombradas = set(re.findall(r"`([a-z_]+)`", server.texto_agente()))
    campos = {"comensales", "gustos", "evitar", "alergias", "dieta", "notas", "supermercados",
              "presupuesto_semanal"}
    assert nombradas - campos <= existentes, nombradas - campos - existentes
    # y usan las que hacen falta para el recorrido completo
    assert {"perfiles_ver", "perfil_guardar", "perfil_aprender", "perfil_olvidar", "menu_historial",
            "menu_guardar", "menu_valorar", "lista_anadir_varios", "presupuestar_lista",
            "buscar_productos", "detalle_producto"} <= nombradas


def test_los_campos_que_nombran_las_instrucciones_son_parametros_reales():
    parametros = set(herramientas()["perfil_guardar"].input_schema["properties"])
    assert parametros == {"nombre", "comensales", "gustos", "evitar", "alergias", "dieta", "notas",
                          "supermercados", "presupuesto_semanal"}


def test_las_instrucciones_cubren_lo_pedido():
    texto = server.texto_agente()
    for imprescindible in ("Para quién es", "Qué les gusta", "Qué quieren evitar", "Alergias",
                           "Costumbres", "Aprender", "restricción absoluta", "No puedes comprar"):
        assert imprescindible in texto, imprescindible
    assert "—" not in texto


def test_fichero_del_agente_para_claude_code():
    fichero = server.fichero_agente()
    cabecera, cuerpo = re.fullmatch(r"---\n(.*?)\n---\n\n(.*)", fichero, re.S).groups()
    campos = dict(linea.split(": ", 1) for linea in cabecera.splitlines())
    assert set(campos) == {"name", "description", "tools"}
    # limitado a este servidor, con el nombre con el que el README lo registra y el propio servidor se anuncia
    assert campos["tools"] == f"mcp__{server.mcp.name}__*" == "mcp__supermercados__*"
    assert re.fullmatch(r"[a-z][a-z0-9-]*", campos["name"])
    assert ":" not in campos["description"] and "\n" not in campos["description"]  # YAML sin comillas
    assert cuerpo == server.texto_agente()


def test_opcion_agente_de_la_linea_de_comandos(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["supermercados-mcp", "--agente"])
    server.main()
    assert capsys.readouterr().out == server.fichero_agente()


def test_prompt_mcp():
    from mcp import Client

    async def una():
        async with Client(server.mcp) as cliente:
            lista_prompts = (await cliente.list_prompts()).prompts
            return lista_prompts, await cliente.get_prompt("chef_compra")

    prompts, resultado = asyncio.run(una())
    assert [p.name for p in prompts] == ["chef_compra"]
    texto = resultado.messages[0].content.text
    assert texto.startswith(server.texto_agente()) and "consulta los perfiles" in texto


def test_recorrido_completo_del_agente(tiendas_grabadas, llamar):
    # 1. primera vez: no hay perfiles, toca entrevista
    assert llamar("perfiles_ver") == {"perfiles": []}
    llamar("perfil_guardar", nombre="Casa", comensales="2 adultos y una niña de 6 años")
    llamar("perfil_guardar", nombre="Casa", gustos=["legumbres", "arroces"], evitar=["coliflor"],
           alergias=["cacahuete"], supermercados=["mercadona", "dia", "aldi"])
    perfil = llamar("perfiles_ver", nombre="casa")
    assert perfil["comensales"].startswith("2 adultos") and perfil["alergias"] == ["cacahuete"]

    # 2. menú: sin historial todavía, se propone y se guarda
    assert llamar("menu_historial", nombre="Casa") == {"menus": []}
    menu = llamar("menu_guardar", nombre="Casa",
                  platos={"desayuno": "tostadas con tomate", "comida": "arroz con verduras", "cena": "tortilla"})
    assert menu["fecha"] == HOY

    # 3. cesta en los supermercados del perfil
    anadidos = llamar("lista_anadir_varios", articulos=[
        {"articulo": "arroz redondo 1 kg"}, {"articulo": "huevos docena", "cantidad": 2},
        {"articulo": "pan de molde", "nota": "integral"}])
    assert [a["cantidad"] for a in anadidos["anadidos"]] == [1, 2, 1]
    cesta = llamar("presupuestar_lista", supermercados=perfil["supermercados"], codigo_postal="28001")
    assert set(cesta["supermercados"]) == {"mercadona", "dia", "aldi"}
    for datos in cesta["supermercados"].values():
        assert datos["articulos_encontrados"] == 3 and datos["total"] > 0
    assert cesta["mas_barato_con_todo"] in perfil["supermercados"]

    # 4. aprende de lo que le dicen y de cómo salió el menú
    apunte = llamar("perfil_aprender", nombre="Casa", observacion="Entre semana cenan ligero", categoria="costumbre")
    llamar("menu_valorar", nombre="Casa", puntuacion=5, comentario="el arroz gustó mucho")
    llamar("perfil_olvidar", nombre="Casa", apunte_id=apunte["id"])
    llamar("perfil_aprender", nombre="Casa", observacion="Los viernes cenan fuera", categoria="costumbre")

    # 5. otro día: el agente lo encuentra todo sin volver a preguntar
    recordado = llamar("perfiles_ver")["perfiles"][0]
    assert [a["observacion"] for a in recordado["aprendido"]] == ["Los viernes cenan fuera"]
    historial = llamar("menu_historial", nombre="Casa")["menus"]
    assert historial[0]["puntuacion"] == 5 and historial[0]["platos"]["comida"] == "arroz con verduras"


@pytest.mark.parametrize(
    "herramienta,argumentos,texto",
    [
        ("perfiles_ver", {"nombre": "nadie"}, "nadie"),
        ("perfil_aprender", {"nombre": "nadie", "observacion": "x"}, "nadie"),
        ("perfil_aprender", {"nombre": "Casa", "observacion": "x", "categoria": "rara"}, "categoría"),
        ("menu_guardar", {"nombre": "Casa", "platos": {"brunch": "huevos"}}, "brunch"),
        ("menu_guardar", {"nombre": "Casa", "platos": {"cena": "sopa"}, "fecha": "mañana"}, "fecha"),
        ("menu_valorar", {"nombre": "Casa", "puntuacion": 9}, "puntuación"),
        ("menu_valorar", {"nombre": "Casa", "puntuacion": 3}, "no hay menú"),
        ("lista_anadir_varios", {"articulos": [{"articulo": "pan"}, {"articulo": "  "}]}, "no válido"),
        ("lista_anadir_varios", {"articulos": [{"articulo": "pan", "cantidad": 0}]}, "cantidad"),
        ("lista_anadir_varios", {"articulos": [{"articulo": "pan", "precio": 1}]}, "no válido"),
    ],
)
def test_errores_de_uso(llamar, herramienta, argumentos, texto):
    llamar("perfil_guardar", nombre="Casa")
    datos = llamar(herramienta, **argumentos)
    assert datos["error"] == "uso" and texto in datos["motivo"], datos
    assert llamar("lista_ver") == {"articulos": []}  # un lote no válido no añade nada
    assert llamar("menu_historial", nombre="Casa") == {"menus": []}
