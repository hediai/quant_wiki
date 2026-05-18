"""`kb` CLI."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import agentic as agentic_mod
from . import compile as compile_mod
from . import doctor as doctor_mod
from . import lint as lint_mod
from . import threads as threads_mod
from .ask import ask as run_ask
from .config import paths as get_paths
from .eval import run_faithfulness_eval, run_retrieval_eval
from .index import MetaStore, VectorStore, get_embedder
from .ingest import ingest_path
from .llm import get_llm
from .search import search as run_search
from .thread_review import review_thread

app = typer.Typer(no_args_is_help=True, add_completion=False, rich_markup_mode="rich")
console = Console()
log = logging.getLogger("kb")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.callback()
def _root(verbose: bool = typer.Option(False, "--verbose", "-v")):
    _setup_logging(verbose)


@app.command()
def ingest(
    path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=True),
    domain: str | None = typer.Option(None, help="Force domain (otherwise inferred)."),
    institution: str | None = typer.Option(None, help="Force institution (otherwise inferred)."),
    license: str = typer.Option("internal", help="public | subscription | internal"),
    no_embed: bool = typer.Option(False, "--no-embed", help="Skip vector index (FTS only)."),
):
    """Ingest a file or a directory of research materials."""
    paths = get_paths()
    meta = MetaStore(paths.meta_db)
    embedder = None if no_embed else get_embedder()
    vstore = VectorStore(paths.lance, dim=embedder.dim if embedder else 1024)
    try:
        results = ingest_path(
            path, paths=paths, meta=meta, vstore=vstore, embedder=embedder,
            domain_hint=domain, institution_hint=institution, license_hint=license,
        )
    finally:
        meta.close()

    tbl = Table(title=f"ingested {len(results)} item(s)")
    for col in ("id", "parser", "chunks", "tables", "figures", "errors", "note"):
        tbl.add_column(col)
    for r in results:
        tbl.add_row(
            r.source_id, r.parser, str(r.chunk_count),
            str(r.table_count), str(r.figure_count),
            "; ".join(r.errors)[:60], "skip:" + r.reason if r.skipped else "",
        )
    console.print(tbl)


@app.command()
def search(
    query: str = typer.Argument(...),
    top_k: int = typer.Option(10, "--top-k", "-k"),
    as_of: str | None = typer.Option(None, help="ISO date, e.g. 2024-12-31"),
    domain: list[str] = typer.Option(None, "--domain", help="Restrict to one or more domains"),
    no_rerank: bool = typer.Option(False, "--no-rerank"),
    no_embed: bool = typer.Option(False, "--no-embed"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Hybrid search across the knowledge base."""
    paths = get_paths()
    meta = MetaStore(paths.meta_db)
    embedder = None if no_embed else get_embedder()
    vstore = VectorStore(paths.lance, dim=embedder.dim if embedder else 1024)
    try:
        results = run_search(
            query, meta=meta, vstore=vstore, embedder=embedder,
            top_k=top_k, as_of=as_of, domains=domain, rerank=not no_rerank,
        )
    finally:
        meta.close()

    if as_json:
        console.print_json(data=[r.__dict__ for r in results])
        return

    if not results:
        console.print("[yellow]no hits[/]")
        return
    tbl = Table(title=f"top {len(results)} for: {query}")
    for col in ("source", "page", "score", "via", "snippet"):
        tbl.add_column(col)
    for r in results:
        snippet = r.text.replace("\n", " ")[:120]
        tbl.add_row(r.source_id, str(r.page), f"{r.score:.3f}", r.via, snippet)
    console.print(tbl)


@app.command()
def compile(
    source_id: str = typer.Argument(...),
    no_evidence: bool = typer.Option(False, "--no-evidence", help="Skip concept evidence aggregation."),
    no_embed: bool = typer.Option(False, "--no-embed"),
):
    """Generate or refresh a Source Card from the converted manifest."""
    from .llm import get_llm
    paths = get_paths()
    meta = MetaStore(paths.meta_db)
    embedder = None if no_embed else get_embedder()
    llm = get_llm()
    try:
        result = compile_mod.compile_source(
            source_id, paths=paths, meta=meta,
            embedder=embedder, llm=llm,
            aggregate_evidence=not no_evidence,
        )
    finally:
        meta.close()
    console.print(
        f"[green]wrote[/] {result.card_path.relative_to(paths.root)} "
        f"(evidence applied: {result.evidence_applied}, proposals: {result.proposals_written})"
    )


thread_app = typer.Typer(no_args_is_help=True)
app.add_typer(thread_app, name="thread", help="Research project archives.")


@thread_app.command("new")
def thread_new(topic: str = typer.Argument(...)):
    paths = get_paths()
    out = threads_mod.new_thread(topic, paths=paths)
    console.print(f"[green]thread:[/] {out.relative_to(paths.root)}")


@thread_app.command("list")
def thread_list():
    paths = get_paths()
    items = threads_mod.list_threads(paths)
    if not items:
        console.print("[yellow]no threads yet[/]")
        return
    tbl = Table(title="threads")
    for col in ("id", "title", "status", "path"):
        tbl.add_column(col)
    for t in items:
        tbl.add_row(t["id"], t["title"], t["status"], t["path"])
    console.print(tbl)


@thread_app.command("review")
def thread_review(thread_id: str = typer.Argument(...)):
    paths = get_paths()
    result = review_thread(thread_id, paths=paths)
    console.print(
        f"[green]reviewed[/] {result.thread_path.relative_to(paths.root)} "
        f"(memos seen: {result.memos_seen})"
    )


@app.command()
def ask(
    query: str = typer.Argument(...),
    thread: str | None = typer.Option(None, "--thread", help="Thread id to attach memo to."),
    top_k: int = typer.Option(8, "--top-k", "-k"),
    as_of: str | None = typer.Option(None),
    domain: list[str] = typer.Option(None, "--domain"),
    no_embed: bool = typer.Option(False, "--no-embed"),
):
    """Ask a question, retrieve, synthesise a memo, write to thread or outputs/."""
    paths = get_paths()
    meta = MetaStore(paths.meta_db)
    embedder = None if no_embed else get_embedder()
    vstore = VectorStore(paths.lance, dim=embedder.dim if embedder else 1024)
    llm = get_llm()
    try:
        r = run_ask(
            query, paths=paths, meta=meta, vstore=vstore, embedder=embedder,
            llm=llm, thread=thread, as_of=as_of, top_k=top_k, domains=domain,
        )
    finally:
        meta.close()
    console.print(
        f"[green]memo[/] {r.memo_path.relative_to(paths.root)} (hits: {r.hits}, "
        f"thread: {r.thread_id or 'outputs/'}, model: {llm.name})"
    )


concept_app = typer.Typer(no_args_is_help=True)
app.add_typer(concept_app, name="concept", help="Concept card management.")


@concept_app.command("new")
def concept_new(
    title: str = typer.Argument(...),
    definition: str = typer.Option("", "--definition", "-d"),
    domain: list[str] = typer.Option(None, "--domain"),
):
    from .concepts import create_concept_stub
    paths = get_paths()
    out = create_concept_stub(title, paths=paths, definition=definition, domains=list(domain) if domain else None)
    console.print(f"[green]concept:[/] {out.relative_to(paths.root)}")


factor_app = typer.Typer(no_args_is_help=True)
app.add_typer(factor_app, name="factor", help="Factor card + factor_mining linkage.")


@factor_app.command("new")
def factor_new(
    name: str = typer.Argument(...),
    version: str = typer.Option("1", "--version", "-v"),
    domain: str = typer.Option("选股", "--domain"),
):
    from .factors import create_factor_stub
    paths = get_paths()
    out = create_factor_stub(name, version, paths=paths, domain=domain)
    console.print(f"[green]factor:[/] {out.relative_to(paths.root)}")


@factor_app.command("link")
def factor_link(
    factor_ident: str = typer.Argument(..., help="Factor id or title fragment"),
    repo: Path = typer.Option(..., "--repo", help="Path to factor_mining repo"),
    module: str = typer.Option(..., "--module", help="Relative module path inside repo"),
    backtest: str | None = typer.Option(None, "--backtest", help="Relative path to backtest JSON"),
    no_pin: bool = typer.Option(False, "--no-pin", help="Skip pinning git HEAD commit"),
):
    """Pin a Factor Card to a concrete implementation in factor_mining."""
    from .factors import link_factor
    paths = get_paths()
    link = link_factor(
        factor_ident, paths=paths, repo_path=repo, module=module,
        backtest_path=backtest, pin_commit=not no_pin,
    )
    console.print_json(data={
        "factor_id": link.factor_id,
        "card_path": str(link.card_path.relative_to(paths.root)),
        "repo_path": str(link.repo_path),
        "module": link.module,
        "commit": link.commit,
        "backtest_path": link.backtest_path,
        "backtest_metrics": link.backtest_metrics,
    })


@factor_app.command("validate")
def factor_validate():
    """Check every Factor Card's implementation link."""
    from .factors import validate_factor_link
    paths = get_paths()
    cards = list(paths.factors.glob("*.md"))
    if not cards:
        console.print("[yellow]no factor cards yet[/]")
        return
    tbl = Table(title=f"validating {len(cards)} factor card(s)")
    for col in ("factor", "ok", "problems"):
        tbl.add_column(col)
    n_bad = 0
    for c in cards:
        problems = validate_factor_link(c)
        if problems:
            n_bad += 1
        tbl.add_row(c.stem, "✓" if not problems else "✗", "; ".join(problems)[:120])
    console.print(tbl)
    if n_bad:
        raise typer.Exit(code=1)


agentic_app = typer.Typer(no_args_is_help=True)
app.add_typer(agentic_app, name="agentic", help="Semi-autonomous factor experiment sandbox.")


@agentic_app.command("init")
def agentic_init(
    overwrite: bool = typer.Option(False, "--overwrite", help="Rewrite existing agent role cards."),
):
    """Create agent role cards and the semi-autonomous experiment folders."""
    paths = get_paths()
    result = agentic_mod.init_agentic(paths, overwrite=overwrite)
    console.print_json(data={
        "directories": [str(p.relative_to(paths.root)) for p in result.directories],
        "agents": [str(p.relative_to(paths.root)) for p in result.agent_paths],
    })


@agentic_app.command("new")
def agentic_new(
    topic: str = typer.Argument(...),
    domain: str = typer.Option("选股", "--domain"),
    thread: str | None = typer.Option(None, "--thread", help="Related thread id or slug."),
    hypothesis: str = typer.Option("", "--hypothesis", "-h", help="Initial hypothesis statement."),
    citation: list[str] = typer.Option(None, "--citation", help="Evidence citation, repeatable."),
):
    """Create one guarded experiment folder with templates for every agent handoff."""
    paths = get_paths()
    result = agentic_mod.new_experiment(
        topic, paths=paths, domain=domain, thread=thread,
        hypothesis=hypothesis, citations=list(citation) if citation else None,
    )
    console.print_json(data={
        "experiment_id": result.experiment_id,
        "path": str(result.experiment_dir.relative_to(paths.root)),
        "record": str(result.record_path.relative_to(paths.root)),
    })


@agentic_app.command("list")
def agentic_list():
    """List semi-autonomous factor experiments."""
    paths = get_paths()
    items = agentic_mod.list_experiments(paths)
    if not items:
        console.print("[yellow]no agentic experiments yet[/]")
        return
    tbl = Table(title="agentic experiments")
    for col in ("id", "topic", "status", "decision", "path"):
        tbl.add_column(col)
    for item in items:
        tbl.add_row(
            item.get("id") or "",
            item.get("topic") or "",
            item.get("status") or "",
            item.get("decision") or "",
            item.get("path") or "",
        )
    console.print(tbl)


@agentic_app.command("gate")
def agentic_gate(
    experiment: str = typer.Argument(..., help="Experiment id, slug fragment, or folder name."),
):
    """Apply the fixed promotion gate to an experiment."""
    paths = get_paths()
    result = agentic_mod.gate_experiment(experiment, paths=paths)
    console.print_json(data={
        "experiment_id": result.experiment_id,
        "decision": result.decision,
        "reasons": result.reasons,
        "decision_path": str(result.decision_path.relative_to(paths.root)),
    })


@app.command()
def eval(
    sample: int = typer.Option(20, help="Memo sample size for faithfulness check."),
    skip_faithfulness: bool = typer.Option(False, "--skip-faithfulness"),
):
    """Run retrieval recall@k/MRR over golden.jsonl and citation faithfulness over memos."""
    paths = get_paths()
    meta = MetaStore(paths.meta_db)
    embedder = get_embedder()
    vstore = VectorStore(paths.lance, dim=embedder.dim)
    try:
        report = run_retrieval_eval(paths, meta=meta, vstore=vstore, embedder=embedder)
        faith, n = (None, 0) if skip_faithfulness else run_faithfulness_eval(paths, meta=meta)
    finally:
        meta.close()

    console.print_json(data={
        "retrieval": {
            "mean_recall_5": round(report.mean_recall_5, 3),
            "mean_recall_10": round(report.mean_recall_10, 3),
            "mrr": round(report.mrr, 3),
            "mean_keyword_coverage": round(report.mean_keyword_coverage, 3),
            "n_cases": len(report.cases),
        },
        "faithfulness": {
            "ratio": None if faith is None else round(faith, 3),
            "claims_checked": n,
        },
        "regressions_file": str(paths.regressions.relative_to(paths.root)),
    })


@app.command("describe-figures")
def describe_figures_cmd(
    source_id: str = typer.Argument(...),
):
    """Generate VLM descriptions for figures of a source (writes alongside .png)."""
    from .parsers.figures_vlm import describe_figures
    paths = get_paths()
    result = describe_figures(source_id, paths.converted)
    console.print(
        f"[green]figures[/] described={result.described} skipped={result.skipped} "
        f"(source: {source_id})"
    )


@app.command()
def doctor():
    """Print KB health and capability snapshot."""
    paths = get_paths()
    report = doctor_mod.doctor(paths)
    console.print_json(data=report)


@app.command()
def lint(strict: bool = typer.Option(False, "--strict", help="Exit non-zero on warnings.")):
    """Structural checks on the wiki."""
    paths = get_paths()
    findings = lint_mod.lint(paths)
    if not findings:
        console.print("[green]clean[/]")
        return
    tbl = Table(title=f"{len(findings)} lint finding(s)")
    for col in ("severity", "rule", "file", "message"):
        tbl.add_column(col)
    for f in findings:
        tbl.add_row(f.severity, f.rule, str(f.file.relative_to(paths.root)), f.message[:120])
    console.print(tbl)
    errs = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]
    if errs or (strict and warns):
        raise typer.Exit(code=1)


@app.command()
def init():
    """Initialise an empty wiki layout in cwd (idempotent)."""
    cwd = Path.cwd()
    for d in ["raw", "inbox", "converted", "wiki/sources", "wiki/concepts",
              "wiki/factors", "wiki/strategies", "wiki/models", "wiki/threads",
              "wiki/outputs", "index/eval", "index/lance", "experiments",
              "agents", "inbox/factors", "scripts"]:
        (cwd / d).mkdir(parents=True, exist_ok=True)
    schema = cwd / "kb.schema.md"
    if not schema.exists():
        schema.write_text("# kb.schema.md placeholder\n", encoding="utf-8")
    console.print(f"[green]initialised[/] {cwd}")


if __name__ == "__main__":
    app()
