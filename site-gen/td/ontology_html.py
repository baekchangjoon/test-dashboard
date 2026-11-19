"""S04: 온톨로지 JSON(ontology.schema.json) -> 단독으로 열리는 HTML 그래프(Cytoscape.js).

데이터, 라이브러리, CSS, 스크립트를 모두 한 파일에 인라인한다: 네트워크 요청이 없고(REQ-016), 게시본에서도 상대 경로에
의존하지 않는다. 데이터는 `<script type="application/json">`에 넣고(`<`, `>`, `&` 이스케이프), 화면 쪽은 textContent로만
그린다(innerHTML에 데이터를 넣지 않는다).

CLI: python -m td.ontology_html render <ontology.json> <out.html> [--variant jqa|owl]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema

from td.site.pages import STATIC_DIR, jinja_env, json_for_script

SCHEMA_FILE = Path(__file__).parent / "schemas" / "ontology.schema.json"
VENDOR_DIR = STATIC_DIR / "vendor"
TITLES = {"jqa": "jQA 온톨로지 그래프", "owl": "OWL 온톨로지 그래프"}
KINDS = ("Endpoint", "Controller", "Service", "Repository", "Entity", "Field", "Exception", "DTO")


def variant_of(doc: dict, out_html: Path) -> str:
    """파일 이름(jqa.html/owl.html)이 우선이고, 아니면 meta.tool로 정한다."""
    stem = Path(out_html).stem.lower()
    if stem in TITLES:
        return stem
    return "owl" if "owl" in str(doc.get("meta", {}).get("tool", "")).lower() else "jqa"


def render(ontology_json, out_html, variant: str | None = None, back_href: str = "../index.html") -> Path:
    """ontology_json(경로)을 읽어 out_html을 쓴다. 스키마를 통과하지 못하면 예외이고 파일은 만들지 않는다."""
    out_html = Path(out_html)
    doc = json.loads(Path(ontology_json).read_text())
    jsonschema.validate(doc, json.loads(SCHEMA_FILE.read_text()))
    variant = variant or variant_of(doc, out_html)
    html = jinja_env().get_template("ontology.html.j2").render(
        title=TITLES[variant], variant=variant, meta=doc["meta"], node_count=len(doc["nodes"]), edge_count=len(doc["edges"]),
        kinds=KINDS, back_href=back_href, data_json=json_for_script(doc),
        site_css=(STATIC_DIR / "site.css").read_text(), viz_css=(STATIC_DIR / "ontology.css").read_text(),
        viz_js=(STATIC_DIR / "ontology.js").read_text(), cytoscape_js=(VENDOR_DIR / "cytoscape.min.js").read_text())
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html)
    return out_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.ontology_html")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cmd = sub.add_parser("render")
    cmd.add_argument("ontology_json")
    cmd.add_argument("out_html")
    cmd.add_argument("--variant", choices=sorted(TITLES))
    args = parser.parse_args(argv)
    try:
        render(args.ontology_json, args.out_html, args.variant)
    except Exception as exc:  # noqa: BLE001 - bash 단계가 비-0을 보고 failed로 기록한다
        print(f"ontology_html: {type(exc).__name__}: {str(exc)[:600]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
