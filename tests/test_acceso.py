"""Login y aislamiento entre empresas: cada usuario solo alcanza la BD y el agente de su empresa."""
import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.fakes import ia, llamada
from tests.test_web import CLAVE, _eventos, contexto
from ventas import usuarios as modulo_usuarios
from ventas.db import Db
from ventas.usuarios import Usuarios
from ventas.web.app import crear_app

ESQUEMA = (Path(__file__).parent.parent / "db" / "schema_sqlite.sql").read_text()


def _bd(ruta, sku) -> Db:
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA)
    con.execute("INSERT INTO productos (sku, nombre, precio, stock) VALUES (?, ?, 10, 5)", (sku, f"Producto {sku}"))
    con.execute("INSERT INTO clientes (nombre, email) VALUES ('Cli', 'c@example.com')")
    con.execute("INSERT INTO pedidos (cliente_id, subtotal, impuesto, total) VALUES (1, 10, 0, 10)")
    con.commit()
    con.close()
    return Db(f"sqlite:///{ruta}", f"sqlite:///{ruta}")


@pytest.fixture
def dos_empresas(tmp_path, tasa):
    """agro tiene A-1 y fevasa tiene F-1; ana es de agro, beto y bea de fevasa."""
    dbs = {"agro": _bd(tmp_path / "agro.db", "A-1"), "fevasa": _bd(tmp_path / "fevasa.db", "F-1")}
    # la BD de fevasa tiene además el pedido 2: solo existe allí
    with dbs["fevasa"].rw.connection() as c:
        c.execute("INSERT INTO pedidos (cliente_id, subtotal, impuesto, total) VALUES (1, 20, 0, 20)")
    ctxs = {}
    u = Usuarios(tmp_path / "auth.db")
    for usuario, empresa in (("ana", "agro"), ("beto", "fevasa"), ("bea", "fevasa")):
        u.guardar(usuario, CLAVE, empresa)

    def contexto_de(id):
        if id not in ctxs:
            ctxs[id] = contexto(dbs[id], tasa, ia(tool_calls=[llamada("consulta_sql", sql="SELECT sku FROM productos")]),
                                ia("listo"), empresa=id)
        return ctxs[id]

    app = crear_app(contexto_de, u, "p", "r")

    def entrar(usuario):
        c = TestClient(app)
        assert c.post("/api/login", json={"usuario": usuario, "clave": CLAVE}).status_code == 200
        return c
    yield entrar, ctxs
    for d in dbs.values():
        d.close()


PROTEGIDOS = [("get", "/api/yo"), ("get", "/api/modelo"), ("get", "/api/catalogo"), ("get", "/api/pedidos/1"),
              ("post", "/api/chat")]


@pytest.mark.parametrize("metodo,ruta", PROTEGIDOS)
def test_sin_sesion_todo_es_401(dos_empresas, tmp_path, metodo, ruta):
    entrar, _ = dos_empresas
    sin_sesion = TestClient(entrar("ana").app)
    r = sin_sesion.request(metodo, ruta, **({"json": {"mensaje": "hola"}} if metodo == "post" else {}))
    assert r.status_code == 401


def test_paginas_publicas(dos_empresas):
    c = TestClient(dos_empresas[0]("ana").app)
    assert c.get("/").status_code == 200 and c.get("/api/salud").json() == {"ok": True}


@pytest.mark.parametrize("usuario,clave", [("ana", "otra-clave"), ("nadie", CLAVE), ("", "")])
def test_credenciales_malas_no_abren_sesion(dos_empresas, usuario, clave):
    c = TestClient(dos_empresas[0]("ana").app)
    r = c.post("/api/login", json={"usuario": usuario, "clave": clave})
    assert r.status_code == 401 and "sesion" not in r.cookies
    assert c.get("/api/yo").status_code == 401


def test_logout_invalida_la_sesion(dos_empresas):
    c = dos_empresas[0]("ana")
    assert c.get("/api/yo").json()["empresa"] == "Agroveterinaria"
    assert c.post("/api/logout").status_code == 200
    assert c.get("/api/yo").status_code == 401


def test_cada_usuario_ve_solo_los_datos_de_su_empresa(dos_empresas):
    entrar, _ = dos_empresas
    ana, beto = entrar("ana"), entrar("beto")
    assert [f["sku"] for f in ana.get("/api/catalogo").json()] == ["A-1"]
    assert [f["sku"] for f in beto.get("/api/catalogo").json()] == ["F-1"]
    assert ana.get("/api/pedidos/2").status_code == 404  # existe, pero en la BD de fevasa
    assert beto.get("/api/pedidos/2").status_code == 200
    assert beto.get("/api/yo").json()["empresa"] == "Almacenadora Fevasa"


def test_el_agente_y_consulta_sql_solo_alcanzan_su_empresa(dos_empresas):
    entrar, _ = dos_empresas
    for usuario, sku in (("ana", "A-1"), ("beto", "F-1")):
        evs = _eventos(entrar(usuario).post("/api/chat", json={"mensaje": "lista todo"}))
        resultado = next(d["texto"] for e, d in evs if e == "resultado")
        assert sku in resultado and ("F-1" if sku == "A-1" else "A-1") not in resultado


def test_el_hilo_es_de_quien_lo_abrio(dos_empresas):
    entrar, ctxs = dos_empresas
    beto, bea = entrar("beto"), entrar("bea")
    tid = _eventos(beto.post("/api/chat", json={"mensaje": "hola"}))[-1][1]["thread_id"]
    mensajes = lambda usuario: ctxs["fevasa"].agente.get_state(
        {"configurable": {"thread_id": f"{usuario}:{tid}"}}).values.get("messages", [])
    antes = len(mensajes("beto"))
    _eventos(bea.post("/api/chat", json={"mensaje": "intruso", "thread_id": tid}))
    assert antes > 0 and len(mensajes("beto")) == antes  # bea escribió en su propio hilo, no en el de beto
    assert not any("intruso" in json.dumps(m.content) for m in mensajes("beto"))


def test_clave_corta_se_rechaza_y_se_guarda_con_hash(tmp_path):
    u = Usuarios(tmp_path / "auth.db")
    with pytest.raises(ValueError):
        u.guardar("x", "corta", "agro")
    u.guardar("Ana ", CLAVE, "agro")
    assert u.verificar("ANA", CLAVE) == ("ana", "agro") and u.verificar("ana", "otra-clave-x") is None
    with sqlite3.connect(tmp_path / "auth.db") as c:
        assert CLAVE.encode() not in c.execute("SELECT hash FROM usuarios").fetchone()[0]


def test_la_sesion_expira(tmp_path, monkeypatch):
    u = Usuarios(tmp_path / "auth.db")
    token = u.abrir_sesion("ana", "agro")
    assert u.sesion(token) == ("ana", "agro")
    ahora = time.time()
    monkeypatch.setattr(modulo_usuarios.time, "time", lambda: ahora + modulo_usuarios.SESION_SEGUNDOS + 1)
    assert u.sesion(token) is None
