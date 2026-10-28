"""Command-line interface: ``python -m medperplexity <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _cmd_pubmed(args: argparse.Namespace) -> int:
    from .pubmed import query_pubmed_realtime

    result = query_pubmed_realtime(args.question, retmax=args.retmax)
    _print_json(result)
    return 0 if result["status"] == "success" else 1


def _cmd_generic(args: argparse.Namespace) -> int:
    from .generic_finder import GenericFinder

    try:
        finder = GenericFinder.from_json(args.db)
    except FileNotFoundError:
        print(f"Database not found: {args.db or 'data/medicines.json'}", file=sys.stderr)
        return 2
    result = finder.search(args.name, limit=args.limit)
    _print_json(result)
    return 0 if result["found"] else 1


def _cmd_export(args: argparse.Namespace) -> int:
    from .pubmed_export import run_export

    summary = run_export(args.authors, args.topics, args.start, args.end, args.retmax, args.out)
    _print_json(summary)
    return 0


def _cmd_clean(args: argparse.Namespace) -> int:
    from .data_cleaning import build_clean_database

    _print_json(build_clean_database(args.input, args.output, args.merge))
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    from .build_database import build_database

    for label, path in (("Jan Aushadhi CSV", args.jan), ("brand catalogue CSV", args.brands)):
        if not Path(path).is_file():
            print(f"{label} not found: {path}", file=sys.stderr)
            return 2
    _print_json(build_database(args.jan, args.brands, args.output, max_brands=args.max_brands))
    return 0


def _cmd_specs(args: argparse.Namespace) -> int:
    from .agent_tools import get_tool_specs

    _print_json(get_tool_specs(args.style))
    return 0


def _cmd_call(args: argparse.Namespace) -> int:
    from .agent_tools import dispatch

    result = dispatch(args.tool, args.arguments)
    _print_json(result)
    return 0 if result["answered"] else 1


def _cmd_ask(args: argparse.Namespace) -> int:
    from .agent import AgentDeps, MedAgent
    from .llm import FallbackLLM
    from .patients import PatientStore

    llm = FallbackLLM.from_env()
    if not llm.providers:
        print("No LLM is configured (see .env.example): using the rule-based planner and returning evidence "
              "without an AI explanation.", file=sys.stderr)
    deps = AgentDeps(llm=llm, patients=PatientStore(args.patients) if args.patients else None)
    response = MedAgent(deps).ask(args.patient, args.question, thread_id=args.conversation)
    if not args.audit:
        response.pop("audit", None)
    _print_json(response)
    return 0


def _cmd_llm_check(args: argparse.Namespace) -> int:
    from .llm import FallbackLLM

    llm = FallbackLLM.from_env()
    if not llm.providers:
        print("No LLM provider is configured. Set OPENROUTER_API_KEY and OPENROUTER_MODEL (and optionally a "
              "fallback key) in .env.", file=sys.stderr)
        return 2
    results = llm.check()
    _print_json(results)
    return 0 if all(r["ok"] for r in results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="medperplexity", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="show progress logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pubmed", help="find PubMed evidence for a clinical question")
    p.add_argument("question", help='e.g. "Can I prescribe Clopidogrel with Omeprazole?"')
    p.add_argument("--retmax", type=int, default=5, help="max articles (default 5)")
    p.set_defaults(func=_cmd_pubmed)

    p = sub.add_parser("generic", help="find the Jan Aushadhi generic for a brand/generic name")
    p.add_argument("name", help='e.g. "Atorlip 10"')
    p.add_argument("--db", default=None, help="path to the medicine JSON (default data/medicines.json)")
    p.add_argument("--limit", type=int, default=3, help="max alternatives to show")
    p.set_defaults(func=_cmd_generic)

    p = sub.add_parser("export", help="search PubMed by author/topic and export to Excel")
    p.add_argument("--authors", nargs="*", default=[], help='e.g. "Anthony Fauci" "Mehmet Oz"')
    p.add_argument("--topics", nargs="*", default=[], help="terms searched in title/abstract")
    p.add_argument("--start", help="start date, YYYY/MM/DD")
    p.add_argument("--end", help="end date, YYYY/MM/DD")
    p.add_argument("--retmax", type=int, default=20)
    p.add_argument("--out", default="PubMed_results.xlsx")
    p.set_defaults(func=_cmd_export)

    p = sub.add_parser("build", help="build the medicine database from the raw Jan Aushadhi and brand CSVs")
    p.add_argument("--jan", default="data/jan_aushadhi.csv", help="Jan Aushadhi product list (CSV)")
    p.add_argument("--brands", default="data/brand_medicines.csv", help="brand catalogue (CSV, ~57 MB)")
    p.add_argument("-o", "--output", default="data/medicines.json")
    p.add_argument("--max-brands", type=int, default=20, help="example brands stored per product (default 20)")
    p.set_defaults(func=_cmd_build)

    p = sub.add_parser("specs", help="print the agent tool definitions (JSON Schema) for an LLM API")
    p.add_argument("--style", choices=["generic", "openai", "anthropic"], default="generic")
    p.set_defaults(func=_cmd_specs)

    p = sub.add_parser("call", help="run an agent tool exactly as an agent would, e.g. call find_generic_substitute '{\"drugs\": [\"Atorlip 10\"]}'")
    p.add_argument("tool", help="search_medical_evidence | find_generic_substitute")
    p.add_argument("arguments", nargs="?", default="{}", help="JSON object of arguments")
    p.set_defaults(func=_cmd_call)

    p = sub.add_parser("ask", help="ask the agent a clinical question about a patient (needs patients file; LLM optional)")
    p.add_argument("patient", help="patient id, e.g. PAT-001")
    p.add_argument("question", help='e.g. "Prescribe Diclofenac for joint pain"')
    p.add_argument("--patients", default=None, help="path to patients JSON (default data/patients.json)")
    p.add_argument("--audit", action="store_true", help="include the audit block in the output")
    p.add_argument("--conversation", default="default", help="conversation ID to resume across commands; each ID is bound to one patient")
    p.set_defaults(func=_cmd_ask)

    p = sub.add_parser("llm-check", help="test every configured LLM provider with a tiny request")
    p.set_defaults(func=_cmd_llm_check)

    p = sub.add_parser("clean", help="clean (and optionally merge) medicine JSON databases")
    p.add_argument("input", help="primary JSON database")
    p.add_argument("--merge", help="secondary JSON database; only new generic names are added")
    p.add_argument("-o", "--output", default="data/medicines.json")
    p.set_defaults(func=_cmd_clean)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
