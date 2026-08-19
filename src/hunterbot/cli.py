"""Interfaz CLI enriquecida para HunterBot (Typer + Rich)."""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hunterbot.config import load_config
from hunterbot.engine import HunterEngine
from hunterbot.models import ItemCategory, Operation, SearchCriteria

app = typer.Typer(help="🎯 HunterBot — Buscador Universal de Oportunidades y Chollos")
console = Console()


def _run_async(coro):
    return asyncio.run(coro)


@app.command("search")
def search_cmd(
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Término de búsqueda o palabra clave"),
    location: Optional[str] = typer.Option(None, "--location", "-l", help="Ubicación o zona geográfica (ej. Malaga, Madrid)"),
    category: Optional[str] = typer.Option("real_estate", "--category", "-c", help="Categoría: real_estate, product, boat, other"),
    provider: Optional[str] = typer.Option("all", "--provider", "-p", help="Provider específico o 'all'"),
    price_min: Optional[float] = typer.Option(None, "--min-price", help="Precio mínimo"),
    price_max: Optional[float] = typer.Option(None, "--max-price", help="Precio máximo"),
    min_score: float = typer.Option(5.0, "--min-score", "-s", help="Puntuación mínima a mostrar (1-10)"),
    project: Optional[str] = typer.Option(None, "--project", help="Nombre del proyecto para agrupar alertas"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Ruta a config.yaml"),
):
    """Ejecuta una búsqueda de oportunidades en tiempo real en los providers configurados."""
    cfg = load_config(config_path)

    cat_enum = None
    try:
        if category:
            cat_enum = ItemCategory(category)
    except ValueError:
        cat_enum = ItemCategory.OTHER

    criteria = SearchCriteria(
        provider=provider or "all",
        query=query,
        location=location,
        category=cat_enum,
        price_min=price_min,
        price_max=price_max,
        operation=Operation.SALE,
    )

    async def _exec():
        engine = HunterEngine(cfg)
        try:
            with console.status(f"[bold cyan]Buscando oportunidades en {provider or 'todos los providers'}...[/bold cyan]"):
                results = await engine.search_all(criteria, project_name=project)
            return results
        finally:
            await engine.close()

    results = _run_async(_exec())

    filtered = [r for r in results if r.score >= min_score]

    if not filtered:
        console.print(f"[yellow]No se encontraron oportunidades con score >= {min_score}[/yellow]")
        return

    table = Table(title=f"🎯 Oportunidades encontradas ({len(filtered)} items)", show_header=True, header_style="bold magenta")
    table.add_column("Score", style="bold", justify="center", width=8)
    table.add_column("Título", style="white", min_width=30)
    table.add_column("Precio", style="green", justify="right")
    table.add_column("Detalle / €/m²", style="cyan", justify="right")
    table.add_column("Fuente", style="dim", justify="center")
    table.add_column("Razones", style="yellow")

    for opp in filtered:
        item = opp.item
        price_str = f"{item.price:,.0f} {item.currency}".replace(",", ".")
        detail_str = f"{item.price_per_m2:.0f} €/m²" if item.price_per_m2 else (f"{item.length_m} m" if item.length_m else "-")
        reasons_str = "; ".join(opp.reasons[:2]) if opp.reasons else "-"

        table.add_row(
            f"{opp.emoji} {opp.score}",
            item.title[:45] + ("..." if len(item.title) > 45 else ""),
            price_str,
            detail_str,
            item.provider,
            reasons_str,
        )

    console.print(table)


@app.command("opportunities")
def opportunities_cmd(
    min_score: float = typer.Option(7.0, "--min-score", "-s", help="Score mínimo"),
    limit: int = typer.Option(20, "--limit", "-n", help="Número de items"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Ruta a config.yaml"),
):
    """Muestra los mejores chollos guardados en el historial local."""
    cfg = load_config(config_path)

    async def _exec():
        engine = HunterEngine(cfg)
        try:
            items = engine.db.get_items(limit=limit * 2)
            scored = [engine.scoring.score_item(i) for i in items]
            scored.sort(key=lambda x: x.score, reverse=True)
            return [s for s in scored if s.score >= min_score][:limit]
        finally:
            await engine.close()

    results = _run_async(_exec())

    if not results:
        console.print("[yellow]No hay oportunidades históricas almacenadas que cumplan el criterio.[/yellow]")
        return

    table = Table(title="💎 Top Chollos del Historial", show_header=True, header_style="bold blue")
    table.add_column("Score", justify="center")
    table.add_column("Título", min_width=30)
    table.add_column("Precio", justify="right")
    table.add_column("Fuente", justify="center")
    table.add_column("URL", style="dim")

    for opp in results:
        item = opp.item
        price_str = f"{item.price:,.0f} €".replace(",", ".")
        table.add_row(f"{opp.emoji} {opp.score}", item.title[:40], price_str, item.provider, item.url[:40])

    console.print(table)


@app.command("stats")
def stats_cmd(
    config_path: Optional[Path] = typer.Option(None, "--config", help="Ruta a config.yaml"),
):
    """Muestra estadísticas generales de la base de datos de oportunidades."""
    cfg = load_config(config_path)

    async def _exec():
        engine = HunterEngine(cfg)
        try:
            return engine.db.get_summary()
        finally:
            await engine.close()

    summary = _run_async(_exec())

    panel_content = (
        f"[bold]Total de Items Rastreados:[/bold] {summary['total_items']}\n"
        f"[bold]Items Activos:[/bold] {summary['active_items']}\n"
        f"[bold]Búsquedas Ejecutadas:[/bold] {summary['total_searches']}\n\n"
        f"[bold]Por Provider:[/bold]\n"
        + "\n".join([f"  • {p}: {c}" for p, c in summary['by_provider'].items()])
    )

    console.print(Panel(panel_content, title="📊 Estadísticas de HunterBot", border_style="cyan"))


@app.command("export")
def export_cmd(
    output: Path = typer.Option(Path("oportunidades.csv"), "--output", "-o", help="Archivo CSV de salida"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Ruta a config.yaml"),
):
    """Exporta todos los datos recopilados a formato CSV para Excel o análisis."""
    cfg = load_config(config_path)

    async def _exec():
        engine = HunterEngine(cfg)
        try:
            return engine.db.get_items(limit=10000)
        finally:
            await engine.close()

    items = _run_async(_exec())

    if not items:
        console.print("[yellow]No hay items para exportar.[/yellow]")
        return

    with open(output, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Provider", "Categoría", "Título", "Precio", "€/m²", "Ubicación", "URL", "Fecha"])
        for it in items:
            writer.writerow([it.id, it.provider, it.category.value, it.title, it.price, it.price_per_m2 or "", it.location or "", it.url, it.last_seen.isoformat()])

    console.print(f"[bold green]✅ Exportados {len(items)} items a {output}[/bold green]")


@app.command("providers")
def providers_cmd(
    config_path: Optional[Path] = typer.Option(None, "--config", help="Ruta a config.yaml"),
):
    """Muestra el estado de todos los providers disponibles y su configuración."""
    cfg = load_config(config_path)

    async def _exec():
        engine = HunterEngine(cfg)
        try:
            return engine.providers
        finally:
            await engine.close()

    active_p = _run_async(_exec())

    table = Table(title="🔌 Providers Registrados y Estado", show_header=True, header_style="bold green")
    table.add_column("Provider", style="bold")
    table.add_column("Nombre", justify="left")
    table.add_column("Categoría", justify="center")
    table.add_column("Requiere API Key", justify="center")
    table.add_column("Estado", justify="center")

    for p in active_p:
        table.add_row(
            p.name,
            p.display_name,
            p.category.value,
            "Sí" if p.requires_api_key else "No",
            "[green]Activo[/green]",
        )

    console.print(table)


if __name__ == "__main__":
    app()
