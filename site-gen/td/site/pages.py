"""사이트 페이지 공통 보조(Task 6이 최소분을 만들고 Task 7이 확장한다)."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from td.site import nav
from td.site.layout import (COPY_IGNORE, LINK_ONLY_IF_PRESENT, NAV_EXTRA_LABELS, NAV_INJECT, REPORT_NOTES, REPORTS,
                            REPORTS_EXTRA, RERENDER, expand_layout)
from td.site.nav import STAGE_LABELS

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


V2_DIR = STATIC_DIR / "v2"
APP_CSS = "app.css"  # 새 디자인 스타일 파일 이름(단독 열람용 사본도 같은 이름)


def static_href_of(css_href: str) -> str:
    """스타일 파일 주소(`…/static/v2/app.css`, 단독 열람은 `app.css`)에서 그 디렉터리 주소(`…/static/v2/`, 빈 문자열).
    `base_v2.html.j2`는 이 디렉터리에서 `app.js`를 불러온다."""
    head, separator, _ = css_href.rpartition("/")
    return f"{head}{separator}"


def copy_app_css(out_dir: Path) -> None:
    """단독 열람용: `static/v2/app.css`를 리포트 옆에 `app.css`로 둔다(사이트 조립은 COPY_IGNORE로 빼고 v2 주소를 넘긴다)."""
    shutil.copy2(V2_DIR / APP_CSS, Path(out_dir) / APP_CSS)


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


TEXT_SUFFIXES = {".html", ".htm", ".json", ".yml", ".yaml", ".xml", ".csv", ".txt", ".md", ".js", ".css", ".svg"}
PUBLISHABLE_STATUSES = ("passed", "degraded")


class SanitizeError(RuntimeError):
    pass


def path_variants(path) -> list[str]:
    """경로의 원본·resolve 표기(중복 제거, 긴 것 먼저). 공개 보조: 게시 치환과 S13 홈 경로 게이트가 함께 쓴다."""
    from td import redact
    return redact.path_variants(path)


def sanitize_site(out_dir, run_dir, repo_root=None) -> list[Path]:
    """게시 전 텍스트 파일을 공통 가림기(td.redact)로 치환한다: run 디렉터리 -> <run>, TD_WORK_DIR -> <work>,
    저장소 루트 -> <repo>, 임시 디렉터리 -> <tmp>, 홈 -> ~, 인프라 식별자 -> <redacted>, ARN -> <arn>.
    치환 뒤에도 홈·로컬 절대 경로·식별자가 남으면 SanitizeError(게이트). 바이너리는 건드리지 않는다. 바뀐 파일 목록을 돌려준다."""
    from td import redact
    repo_root = Path(repo_root or os.environ.get("TD_ROOT") or SITE_DIR.parents[2])
    changed = []
    for path in _text_files(out_dir):
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        new = redact.redact_text(text, run_dir=run_dir, repo_root=repo_root)
        if new != text:
            path.write_text(new)
            changed.append(path)
    check_no_home(out_dir)
    return changed


def _text_files(out_dir) -> list[Path]:
    return [p for p in sorted(Path(out_dir).rglob("*")) if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES]


def check_no_home(out_dir) -> None:
    """게이트: 텍스트 파일에 홈 경로, 로컬 절대 경로 접두(/Users/, /home/, /private/var/, /var/folders/),
    인프라 식별자, ARN이 남아 있으면 SanitizeError. 사유에는 파일 경로(사이트 상대)와 종류만 쓴다."""
    from td import redact
    leaked = []
    for path in _text_files(out_dir):
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        kinds = redact.find_leaks(text)
        if kinds:
            leaked.append(f"{path.relative_to(out_dir).as_posix()}({','.join(kinds)})")
    if leaked:
        raise SanitizeError(f"게시 사본에 홈 경로·로컬 절대 경로·식별자가 남았다: {', '.join(leaked[:5])}")


NAV_MISSING_REASON = "<body>를 찾지 못했다"
RENDER_RECORD = "render.json"  # 띠 누락 기록(게시하지 않는다: publish.EXCLUDED_SITE_FILES)
STAGE_IDS = tuple(STAGE_LABELS)  # S00~S13
DURATION_STAGES = STAGE_IDS[:-1]  # 전체 시간은 S00~S12의 가장 늦은 종료까지(S13은 게시)
STATUS_CLASS = {"passed": "s-good", "degraded": "s-warn", "failed": "s-crit"}
RUN_PAGE_LABEL = "실행 결과"


def _parse_time(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_duration(seconds) -> str:
    """걸린 시간 표기: 59초, 4분 19초, 1시간 2분. 값이 없으면 "측정 없음"."""
    if seconds is None:
        return "측정 없음"
    total = int(round(seconds))
    if total < 60:
        return f"{total}초"
    if total < 3600:
        return f"{total // 60}분 {total % 60}초"
    return f"{total // 3600}시간 {total % 3600 // 60}분"


def _stage_seconds(stage: dict) -> float | None:
    started, finished = _parse_time(stage.get("startedAt")), _parse_time(stage.get("finishedAt"))
    if started is None or finished is None or finished < started:
        return None
    return (finished - started).total_seconds()


def stage_view(run: dict, stages: dict) -> tuple[list[dict], str, str]:
    """run 페이지 단계 띠: 14단계(실행하지 않은 단계 포함) 표시 값, 처음 고른 단계, 전체 걸린 시간 표기."""
    items = []
    for stage_id in STAGE_IDS:
        stage = stages.get(stage_id)
        seconds = _stage_seconds(stage) if stage else None
        if stage_id == "S13":  # run.json과 같은 값으로 렌더하고, 최종 결과는 app.js가 publish-log로 바꾼다
            status, reason = "publishing", ""
        elif stage is None:
            status, reason = None, ""
        else:
            status, reason = stage.get("status"), stage.get("reason") or ""
        items.append({"id": stage_id, "label": STAGE_LABELS[stage_id], "status": status,
                      "statusText": status or "실행 안 함", "css": STATUS_CLASS.get(status, "s-none"), "reason": reason,
                      "seconds": seconds, "duration": format_duration(seconds),
                      "width": f"{max(1.0, math.sqrt((seconds or 0) + 1)):.2f}"})
    troubled = [item["id"] for item in items[:-1] if item["status"] in ("failed", "degraded")]
    measured = [item for item in items[:-1] if item["seconds"] is not None]
    selected = troubled[0] if troubled else (max(measured, key=lambda item: item["seconds"])["id"] if measured else "S00")
    started = _parse_time(run.get("startedAt"))
    finishes = [_parse_time(stages[sid].get("finishedAt")) for sid in DURATION_STAGES if sid in stages]
    finishes = [moment for moment in finishes if moment is not None]
    total = (max(finishes) - started).total_seconds() if started and finishes and max(finishes) >= started else None
    return items, selected, format_duration(total)


def _expand_nav_targets(out_dir: Path) -> list[str]:
    """NAV_INJECT의 대상 파일 중 실제로 복사된 것(사이트 상대 경로, 결정적 순서)."""
    targets = []
    for site_rel, entries in NAV_INJECT.items():
        if "*" in site_rel:
            parent, _, rest = site_rel.partition("*")
            base = out_dir / parent
            dirs = [f"{parent}{d.name}{rest}" for d in sorted(base.iterdir()) if d.is_dir()] if base.is_dir() else []
        else:
            dirs = [site_rel]
        for dir_rel in dirs:
            targets += [f"{dir_rel}{entry}" for entry in entries if (out_dir / dir_rel / entry).is_file()]
    return targets


def inject_nav(out_dir: Path, links: list[dict], *, sut_name: str | None, run_id: str | None) -> list[dict]:
    """복사된 외부 도구 HTML에 공통 띠를 끼운다. `<body>`가 없어 넣지 못한 파일 목록(render.json의 navMissing)을 돌려준다."""
    labels = {link["href"]: link["label"] for link in links}
    missing = []
    for rel in _expand_nav_targets(out_dir):
        label = labels.get(rel) or NAV_EXTRA_LABELS.get(rel) or rel.rsplit("/", 1)[-1]
        nav_html = nav.render(nav.links_for(rel, links, sut_name=sut_name, run_id=run_id), label)
        if not nav.inject(out_dir / rel, nav_html):
            missing.append({"report": label, "file": rel, "reason": NAV_MISSING_REASON})
    return missing


def rerender_own_reports(targets: list[tuple[str, Path]], links: list[dict], *, sut_name: str | None,
                         run_id: str | None) -> None:
    """복사된 직접 만드는 리포트(RERENDER)를 v2 스타일 주소와 템플릿이 그리는 공통 띠로 다시 렌더한다."""
    labels = {link["href"]: link["label"] for link in links}
    for site_rel, target in targets:
        entry = REPORTS[site_rel][1]
        report_rel = f"{site_rel}{entry}"
        css_href = f"{RUN_DEPTH_TO_ROOT}{'../' * (site_rel.strip('/').count('/') + 1)}static/v2/{APP_CSS}"
        nav_html = nav.render(nav.links_for(report_rel, links, sut_name=sut_name, run_id=run_id),
                              labels.get(report_rel) or REPORTS[site_rel][0])
        RERENDER[site_rel](target, css_href, nav_html)


def report_cards(links: list[dict], nav_missing: list[dict]) -> tuple[list[dict], list[dict]]:
    """리포트 카드와, 어느 카드에도 붙지 않은 띠 누락 항목. 누락은 같은 파일의 카드, 없으면 같은 디렉터리의 첫 카드에 붙인다."""
    cards = [{**link, "missing": []} for link in links]
    unmatched = []
    for item in nav_missing:
        directory = item["file"].rsplit("/", 1)[0] + "/"
        card = next((c for c in cards if c["href"] == item["file"]), None) or \
            next((c for c in cards if c["href"].startswith(directory)), None)
        (card["missing"] if card else unmatched).append(item)
    return cards, unmatched


def render_run(run_dir, out_dir) -> Path:
    """run 디렉터리의 정적 파일(index.html, run.json, stages/, 리포트)을 out_dir에 만든다. index.html 경로를 돌려준다.
    SITE_LAYOUT에 매핑된 산출물만 복사하고(매핑 밖 단계 디렉터리는 복사하지 않는다) 링크도 산출물이 있는 것만 단다.
    순서: 복사 -> RERENDER(새 틀과 템플릿이 그리는 띠) -> 외부 HTML에 공통 띠 주입 -> run 페이지 렌더 -> sanitize_site.
    띠를 넣지 못한 파일이 있으면 out_dir/render.json에 navMissing으로 적는다(없으면 이 파일을 만들지 않는다).
    out_dir이 run_dir과 같으면 run_dir/site에 만든다. dashboard.yaml은 읽지 않는다."""
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    if out_dir.resolve() == run_dir.resolve():
        out_dir = run_dir / PUBLISH_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    run = read_json(run_dir / "run.json", {})
    stages = {}
    for stage_id in sorted(run.get("stages", {})):
        stages[stage_id] = read_json(run_dir / "stages" / f"{stage_id}.json", {"status": run["stages"][stage_id], "reason": None})
    links = []
    rerender_targets = []  # (사이트 경로, 복사된 디렉터리): 띠에 같은 run의 모든 리포트가 들어가도록 링크를 다 모은 뒤 렌더한다
    for stage_id, stage in stages.items():
        if stage.get("status") not in PUBLISHABLE_STATUSES:  # 실패·건너뜀 단계의 부분 산출물은 게시하지 않는다
            continue
        outputs = stage.get("outputs") or {}
        for output_key, site_rel, report_key in expand_layout(stage_id, outputs):
            src = outputs.get(output_key)
            if not src or not Path(src).is_dir():
                continue
            target = out_dir / site_rel.rstrip("/")
            shutil.copytree(src, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*COPY_IGNORE))
            if site_rel in RERENDER:
                rerender_targets.append((site_rel, target))
            label, entry = REPORTS[report_key]
            for label, entry in [(label, entry), *REPORTS_EXTRA.get(site_rel, [])]:
                if site_rel in LINK_ONLY_IF_PRESENT and not (target / entry).exists():
                    continue
                links.append({"label": label.replace("{}", site_rel.strip("/").split("/")[-1]), "href": f"{site_rel}{entry}",
                              "note": REPORT_NOTES.get(f"{report_key}{entry}") or REPORT_NOTES.get(report_key, "")})
    rerender_own_reports(rerender_targets, links, sut_name=run.get("sut"), run_id=run.get("runId"))
    # 다시 렌더하다 진입 파일이 지워질 수 있다(예: 게시 사본의 det.html 렌더 실패). 존재 조건부 링크는 렌더 뒤 다시 거른다.
    kept = [link for link in links
            if not any(link["href"].startswith(rel) for rel in LINK_ONLY_IF_PRESENT) or (out_dir / link["href"]).exists()]
    if len(kept) != len(links):   # 이미 그린 공통 띠에 사라진 파일의 링크가 남지 않도록 줄어든 링크로 한 번 더 그린다
        links = kept
        rerender_own_reports(rerender_targets, links, sut_name=run.get("sut"), run_id=run.get("runId"))
    nav_missing = inject_nav(out_dir, links, sut_name=run.get("sut"), run_id=run.get("runId"))
    record = out_dir / RENDER_RECORD
    if nav_missing:
        record.write_text(json.dumps({"navMissing": nav_missing}, ensure_ascii=False, indent=2) + "\n")
    elif record.exists():
        record.unlink()
    if (run_dir / "run.json").exists():
        shutil.copy2(run_dir / "run.json", out_dir / "run.json")
    for stage_id, stage in stages.items():
        stage_file = out_dir / "stages" / f"{stage_id}.json"
        stage_file.parent.mkdir(parents=True, exist_ok=True)
        stage_file.write_text(json.dumps(publishable_stage(stage, run_dir), ensure_ascii=False, indent=2) + "\n")
    stage_items, selected_stage, total_duration = stage_view(run, stages)
    cards, unmatched_missing = report_cards(links, nav_missing)
    nav_html = nav.render(nav.links_for(None, links, sut_name=run.get("sut"), run_id=run.get("runId")), RUN_PAGE_LABEL)
    html = jinja_env().get_template("run.html.j2").render(
        run=run, stage_items=stage_items, selected_stage=selected_stage, total_duration=total_duration,
        cards=cards, unmatched_missing=unmatched_missing, nav_html=nav_html,
        static_href=f"{RUN_DEPTH_TO_ROOT}static/v2/", home_href=f"{RUN_DEPTH_TO_ROOT}index.html",
        sut_href="../../index.html", publish_log_url=f"../../publish-log/{run.get('runId', '')}.json")
    target = out_dir / "index.html"
    target.write_text(html)
    sanitize_site(out_dir, run_dir)
    return target
