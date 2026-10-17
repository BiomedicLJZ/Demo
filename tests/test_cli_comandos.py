from prompt_toolkit.document import Document

from ventas.cli.comandos import COMANDOS, CompletadorSlash, parsear


def _completar(texto: str) -> list[str]:
    return [c.text for c in CompletadorSlash().get_completions(Document(texto), None)]


def test_los_nueve_comandos_de_la_spec():
    assert [c.nombre for c in COMANDOS] == [
        "ayuda", "nuevo", "modelo", "herramientas", "todos", "catalogo", "pedido", "limpiar", "salir"]
    assert all(c.descripcion for c in COMANDOS)


def test_slash_solo_lista_todos():
    assert _completar("/") == ["/" + c.nombre for c in COMANDOS]


def test_prefijo_filtra():
    assert _completar("/p") == ["/pedido"]
    assert _completar("/ca") == ["/catalogo"]
    assert _completar("/PE") == ["/pedido"]  # sin distinguir mayúsculas


def test_no_completa_texto_normal_ni_argumentos():
    assert _completar("hola") == []
    assert _completar("/pedido 12") == []
    assert _completar("") == []


def test_completion_reemplaza_lo_escrito_y_muestra_descripcion():
    c = list(CompletadorSlash().get_completions(Document("/ca"), None))[0]
    assert c.start_position == -3 and "catálogo" in c.display_meta_text.lower()


def test_parsear():
    assert parsear("hola") is None
    assert parsear("/pedido 12") == ("pedido", ["12"])
    assert parsear("  /SALIR  ") == ("salir", [])
    assert parsear("/") == ("", [])
