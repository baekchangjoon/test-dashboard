"""사이트 페이지 공통 보조(Task 6이 최소분을 만들고 Task 7이 확장한다)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

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
    import json
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# --- run 페이지 ---------------------------------------------------------------------------
import json  # noqa: E402
import shutil  # noqa: E402

from td.site.layout import COPY_IGNORE, REPORTS, SITE_LAYOUT  # noqa: E402

RUN_DEPTH_TO_ROOT = "../../../../"  # suts/<sut>/runs/<runId>/ -> 사이트(접두) 루트


def _read(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def render_run(run_dir, out_dir) -> Path:
    """run 디렉터리의 정적 파일(index.html, run.json, stages/, 리포트)을 out_dir에 만든다.
    리포트 링크는 SITE_LAYOUT에 있고 산출물이 실제로 있는 것만 단다."""
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run = _read(run_dir / "run.json", {})
    stages = {}
    for stage_id in sorted(run.get("stages", {})):
        stages[stage_id] = _read(run_dir / "stages" / f"{stage_id}.json", {"status": run["stages"][stage_id], "reason": None})
    links = []
    for key, site_rel in SITE_LAYOUT.items():
        stage_id, output_key = key.split("/", 1)
        src = (stages.get(stage_id) or {}).get("outputs", {}).get(output_key)
        if not src or not Path(src).is_dir():
            continue
        target = out_dir / site_rel.rstrip("/")
        if target.resolve() != Path(src).resolve():
            shutil.copytree(src, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*COPY_IGNORE))
        _rerender_report(site_rel, target)
        label, entry = REPORTS[site_rel]
        links.append({"label": label, "href": f"{site_rel}{entry}"})
    if out_dir.resolve() != run_dir.resolve():
        for name in ("run.json",):
            if (run_dir / name).exists():
                shutil.copy2(run_dir / name, out_dir / name)
        if (run_dir / "stages").is_dir():
            shutil.copytree(run_dir / "stages", out_dir / "stages", dirs_exist_ok=True)
    html = jinja_env().get_template("run.html.j2").render(
        run=run, stages=stages, links=links, css_href=f"{RUN_DEPTH_TO_ROOT}static/site.css",
        js_href=f"{RUN_DEPTH_TO_ROOT}static/site.js", home_href=f"{RUN_DEPTH_TO_ROOT}index.html",
        sut_href="../../index.html", publish_log_url=f"../../publish-log/{run.get('runId', '')}.json")
    target = out_dir / "index.html"
    target.write_text(html)
    return target


def _rerender_report(site_rel: str, target: Path) -> None:
    """복사된 리포트 페이지를 사이트 공통 CSS로 다시 만든다(단독 열람용 사본 site.css는 복사에서 뺐다)."""
    if site_rel == "coverage/" and (target / "coverage.json").exists():
        from td import coverage
        coverage.render_page(target, json.loads((target / "coverage.json").read_text()),
                             css_href=f"{RUN_DEPTH_TO_ROOT}../static/site.css", copy_css=False)
