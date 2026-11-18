"""사이트 페이지 공통 보조(Task 6이 최소분을 만들고 Task 7이 확장한다)."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from td.site.layout import COPY_IGNORE, REPORTS, RERENDER, SITE_LAYOUT

SITE_DIR = Path(__file__).parent
TEMPLATES_DIR = SITE_DIR / "templates"
STATIC_DIR = SITE_DIR / "static"


def slug(test_id: str) -> str:
    """testId -> 파일 이름에 안전한 결정적 슬러그(sha1 앞 10자). `#`, 한글 등 어떤 문자도 안전하다."""
    return hashlib.sha1(test_id.encode("utf-8")).hexdigest()[:10]


def jinja_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html", "j2"]),
                       trim_blocks=True, lstrip_blocks=True)


def json_for_script(data) -> str:
    """`<script type="application/json">` 안에 안전하게 넣을 JSON(`</script>` 탈출 방지)."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


# --- run 페이지 ---------------------------------------------------------------------------
RUN_DEPTH_TO_ROOT = "../../../../"  # suts/<sut>/runs/<runId>/ -> 사이트(접두) 루트
PUBLISH_SUBDIR = "site"  # out_dir이 run_dir과 같으면 이 하위 디렉터리에 만든다(게시기는 여기만 올린다)


def publishable_stage(stage: dict, run_dir: Path) -> dict:
    """게시용 단계 JSON: outputs의 로컬 절대 경로는 run 디렉터리 기준 상대 경로로 바꾸고, run 밖을 가리키면 키를 뺀다."""
    root = run_dir.resolve()
    outputs = {}
    for key, value in (stage.get("outputs") or {}).items():
        if isinstance(value, str) and Path(value).is_absolute():
            try:
                outputs[key] = str(Path(value).resolve().relative_to(root))
            except ValueError:
                continue
        else:
            outputs[key] = value
    return {**stage, "outputs": outputs}


def render_run(run_dir, out_dir) -> Path:
    """run 디렉터리의 정적 파일(index.html, run.json, stages/, 리포트)을 out_dir에 만든다. index.html 경로를 돌려준다.
    SITE_LAYOUT에 매핑된 산출물만 복사하고(매핑 밖 단계 디렉터리는 복사하지 않는다) 링크도 산출물이 있는 것만 단다.
    out_dir이 run_dir과 같으면 run_dir/site에 만든다."""
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    if out_dir.resolve() == run_dir.resolve():
        out_dir = run_dir / PUBLISH_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    run = read_json(run_dir / "run.json", {})
    stages = {}
    for stage_id in sorted(run.get("stages", {})):
        stages[stage_id] = read_json(run_dir / "stages" / f"{stage_id}.json", {"status": run["stages"][stage_id], "reason": None})
    links = []
    for key, site_rel in SITE_LAYOUT.items():
        stage_id, output_key = key.split("/", 1)
        src = (stages.get(stage_id) or {}).get("outputs", {}).get(output_key)
        if not src or not Path(src).is_dir():
            continue
        target = out_dir / site_rel.rstrip("/")
        shutil.copytree(src, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*COPY_IGNORE))
        if site_rel in RERENDER:
            RERENDER[site_rel](target, f"{RUN_DEPTH_TO_ROOT}{'../' * (site_rel.strip('/').count('/') + 1)}static/site.css")
        label, entry = REPORTS[site_rel]
        links.append({"label": label, "href": f"{site_rel}{entry}"})
    if (run_dir / "run.json").exists():
        shutil.copy2(run_dir / "run.json", out_dir / "run.json")
    for stage_id, stage in stages.items():
        stage_file = out_dir / "stages" / f"{stage_id}.json"
        stage_file.parent.mkdir(parents=True, exist_ok=True)
        stage_file.write_text(json.dumps(publishable_stage(stage, run_dir), ensure_ascii=False, indent=2) + "\n")
    html = jinja_env().get_template("run.html.j2").render(
        run=run, stages=stages, links=links, css_href=f"{RUN_DEPTH_TO_ROOT}static/site.css",
        js_href=f"{RUN_DEPTH_TO_ROOT}static/site.js", home_href=f"{RUN_DEPTH_TO_ROOT}index.html",
        sut_href="../../index.html", publish_log_url=f"../../publish-log/{run.get('runId', '')}.json")
    target = out_dir / "index.html"
    target.write_text(html)
    return target
