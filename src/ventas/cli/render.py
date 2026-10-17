"""Renderizables Rich del CLI. Funciones puras: no imprimen, devuelven objetos para console.print."""
import json
from decimal import Decimal

from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ventas.cli.comandos import COMANDOS


def _m(valor) -> str:
    return f"{Decimal(str(valor)):,.2f}"


def _cortar(texto: str, n: int) -> str:
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def banner(nim_model: str, gemini_model: str) -> Panel:
    cuerpo = Text.assemble(
        ("Vendedor conversacional\n", "bold"),
        (f"NIM: {nim_model}  ·  Respaldo: {gemini_model}\n", "dim"),
        ("Escribe tu mensaje, o / para ver los comandos.", "cyan"),
    )
    return Panel(cuerpo, title="[bold green]🛒 Agente de ventas[/]", border_style="green")


def tabla_catalogo(filas: list[dict]) -> Table:
    t = Table(title="Catálogo", header_style="bold cyan")
    t.add_column("SKU", style="bold")
    t.add_column("Producto")
    t.add_column("Precio", justify="right")
    t.add_column("Stock", justify="right")
    for f in filas:
        estilo = "red" if f["stock"] == 0 else "yellow" if f["stock"] <= 5 else "green"
        t.add_row(f["sku"], f["nombre"], _m(f["precio"]), Text(str(f["stock"]), style=estilo))
    return t


def tabla_pedido(p: dict) -> Group:
    estilo = "green" if p["estado"] == "pagado" else "yellow"
    cab = Text.assemble((f"Pedido #{p['id']}", "bold"), "  ·  ", (p["estado"], estilo), f"  ·  {p['cliente']}")
    t = Table(header_style="bold cyan")
    t.add_column("SKU", style="bold")
    t.add_column("Producto")
    t.add_column("Cant.", justify="right")
    t.add_column("P. unit.", justify="right")
    t.add_column("Importe", justify="right")
    for i in p["items"]:
        t.add_row(i["sku"], i["nombre"], str(i["cantidad"]), _m(i["precio_unitario"]),
                  _m(Decimal(str(i["precio_unitario"])) * i["cantidad"]))
    pie = Text(f"Subtotal {_m(p['subtotal'])}  ·  Impuesto {_m(p['impuesto'])}  ·  Total {_m(p['total'])}", style="bold")
    extras = []
    if p.get("pago"):
        extras.append(Text(f"Pago: {p['pago']['metodo']}  ·  ref {p['pago']['referencia']}", style="green"))
    if p.get("comprobante"):
        extras.append(Text(f"Comprobante: {p['comprobante']['numero']}", style="green"))
    return Group(cab, t, pie, *extras)


def linea_herramienta(nombre: str, args: dict) -> Text:
    return Text(f"  ⚙ {nombre}({_cortar(json.dumps(args, ensure_ascii=False, default=str), 100)})", style="dim")


def resultado_herramienta(texto: str) -> Text:
    return Text(f"  ↳ {_cortar(texto.replace(chr(10), ' '), 120)}", style="dim")


def respuesta(texto: str, proveedor: str) -> Panel:
    estilo = "yellow" if "fallback" in proveedor else "green"
    return Panel(Markdown(texto), title="Vendedor", subtitle=proveedor, border_style=estilo)


_ICONO = {"completed": "✓", "in_progress": "▶", "pending": "○"}


def tabla_todos(todos: list[dict]) -> Table:
    t = Table(title="Plan del agente", header_style="bold cyan")
    t.add_column("", width=2)
    t.add_column("Tarea")
    for x in todos:
        t.add_row(_ICONO.get(x.get("status"), "?"), x.get("content", ""))
    return t


def tabla_herramientas(propias: list[str], integradas: list[str]) -> Table:
    t = Table(title="Herramientas", header_style="bold cyan")
    t.add_column("Nombre", style="bold")
    t.add_column("Tipo")
    for n in propias:
        t.add_row(n, "negocio")
    for n in integradas:
        t.add_row(n, Text("integrada (Deep Agents)", style="dim"))
    return t


def tabla_ayuda() -> Table:
    t = Table(title="Comandos", header_style="bold cyan")
    t.add_column("Comando", style="bold green")
    t.add_column("Descripción")
    for c in COMANDOS:
        t.add_row("/" + c.nombre, c.descripcion)
    return t


def error(msg: str) -> Text:
    return Text(f"✗ {msg}", style="bold red")
