"""S11 SonarQube: 프로젝트 보장, CE 폴링, 결과 export, 렌더링, bash용 CLI(설계 §6.13, §13.3, §13.9).

토큰은 환경 변수 `SONAR_TOKEN`으로만 받는다. 명령줄 인자, URL, 요청 본문, 로그, 산출물에는 쓰지 않는다
(오류 사유에는 `redact`를 거친다). DB 토큰 수명주기(발급·정리)는 pipeline/lib/sonar-token.sh가 맡는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from td.site.pages import STATIC_DIR, jinja_env

CE_TIMEOUT_SECONDS = 600
CE_POLL_INTERVAL = 3.0
MAX_ITEMS = 10000
PAGE_SIZE = 500  # Sonar 검색 API의 최대 ps
HTTP_TIMEOUT = 30.0
MEASURE_KEYS = ["coverage", "bugs", "vulnerabilities", "code_smells", "duplicated_lines_density", "ncloc",
                "sqale_rating", "reliability_rating", "security_rating"]
HTML_ROWS = 200  # sonar.html 표에 보이는 항목 수(전체는 sonar.json)
SCHEMA_VERSION = 1


class SonarError(RuntimeError):
    pass


def redact(text: str, token: str | None = None) -> str:
    """사유 문구에서 토큰을 지운다(토큰은 어디에도 남지 않아야 한다)."""
    token = token if token is not None else os.environ.get("SONAR_TOKEN")
    return text.replace(token, "<token>") if token else text


# --- URL, 키 ------------------------------------------------------------------------------------
def base_url(env=None) -> str:
    """Sonar 서버 URL. TD_SONAR_URL_OVERRIDE는 테스트 실행(TD_SITE_PREFIX가 있을 때)에서만 쓴다."""
    env = os.environ if env is None else env
    override = (env.get("TD_SONAR_URL_OVERRIDE") or "").strip()
    if override and (env.get("TD_SITE_PREFIX") or "").strip():
        return override.rstrip("/")
    domain = (env.get("TD_DOMAIN") or "").strip()
    if not domain:
        raise SonarError("TD_DOMAIN이 없어 Sonar URL을 알 수 없다(infra/local.env)")
    return f"https://sonar.{domain}"


def project_key_for(sut_key: str, site_prefix: str) -> str:
    """주입(테스트) 실행은 `<key>-test-<sessionId>` 전용 프로젝트를 쓴다(보존). 접두는 `_test/<sessionId>/`다."""
    parts = [p for p in (site_prefix or "").split("/") if p]
    if len(parts) >= 2 and parts[0] == "_test":
        return f"{sut_key}-test-{parts[1]}"
    return sut_key


# --- HTTP 클라이언트 ------------------------------------------------------------------------------
class SonarClient:
    def __init__(self, url: str, token: str | None = None, timeout: float = HTTP_TIMEOUT):
        self.url = url.rstrip("/")
        self.token = token if token is not None else os.environ.get("SONAR_TOKEN")
        self.timeout = timeout

    def _request(self, method: str, path: str, params: dict | None = None, form: dict | None = None) -> dict:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        request = urllib.request.Request(f"{self.url}{path}{query}", data=data, method=method)
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise SonarError(f"HTTP {exc.code} {method} {path}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise SonarError(f"연결 실패 {method} {path}: {type(reason).__name__}") from exc
        try:
            return json.loads(body) if body else {}
        except ValueError as exc:
            raise SonarError(f"JSON이 아닌 응답 {method} {path}") from exc

    def get(self, path: str, **params) -> dict:
        return self._request("GET", path, params)

    def post(self, path: str, **form) -> dict:
        return self._request("POST", path, form=form)


def _client(client: SonarClient | None, url: str | None = None) -> SonarClient:
    return client or SonarClient(url or base_url())


# --- 사전 점검, 인증 확인 --------------------------------------------------------------------------
def status_up(url: str, timeout: float = 15.0) -> str | None:
    """인증 없이 api/system/status를 본다. UP이면 None, 아니면 사유."""
    try:
        status = SonarClient(url, token="", timeout=timeout).get("/api/system/status").get("status")
    except SonarError as exc:
        return f"api/system/status 실패: {exc}"
    return None if status == "UP" else f"api/system/status가 UP이 아니다: {status}"


def token_valid(client: SonarClient) -> bool:
    return bool(client.get("/api/authentication/validate").get("valid"))


# --- 프로젝트, CE -----------------------------------------------------------------------------------
def ensure_project(key: str, client: SonarClient | None = None) -> bool:
    """없으면 만든다. 만들었으면 True."""
    client = _client(client)
    found = client.get("/api/projects/search", projects=key).get("components") or []
    if any(component.get("key") == key for component in found):
        return False
    client.post("/api/projects/create", project=key, name=key)
    return True


def read_report_task(path) -> dict:
    """스캐너의 report-task.txt(key=value)를 읽는다. 없거나 ceTaskId가 없으면 SonarError."""
    path = Path(path)
    if not path.is_file():
        raise SonarError("report-task.txt가 없다(스캔이 분석을 제출하지 않았다)")
    values = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    if not values.get("ceTaskId"):
        raise SonarError("report-task.txt에 ceTaskId가 없다")
    return values


def wait_ce(task_id: str, timeout: float = CE_TIMEOUT_SECONDS, *, client: SonarClient | None = None,
            interval: float = CE_POLL_INTERVAL, sleep: Callable[[float], None] = time.sleep,
            clock: Callable[[], float] = time.monotonic) -> str:
    """CE 태스크가 끝날 때까지 폴링해 SUCCESS|FAILED|CANCELED|TIMEOUT을 돌려준다(일시적 연결 오류는 재시도)."""
    client = _client(client)
    deadline = clock() + timeout
    while True:
        try:
            status = (client.get("/api/ce/task", id=task_id).get("task") or {}).get("status")
        except SonarError:
            status = None
        if status in ("SUCCESS", "FAILED", "CANCELED"):
            return status
        if clock() >= deadline:
            return "TIMEOUT"
        sleep(interval)


def ce_failure_reason(task_id: str, status: str) -> str:
    if status == "TIMEOUT":
        return f"Sonar CE 태스크가 {CE_TIMEOUT_SECONDS}초 안에 끝나지 않았다(ceTaskId={task_id}, status=TIMEOUT)"
    return f"Sonar CE 태스크 실패(ceTaskId={task_id}, status={status})"


# --- export -----------------------------------------------------------------------------------------
def _paged(client: SonarClient, path: str, list_key: str, params: dict) -> tuple[int, list[dict]]:
    """끝 페이지까지 순회한다. 상한 MAX_ITEMS. (total, items)."""
    items: list[dict] = []
    total = 0
    page = 1
    while True:
        data = client.get(path, **params, p=page, ps=PAGE_SIZE)
        total = int((data.get("paging") or {}).get("total", data.get("total", 0)) or 0)
        rows = data.get(list_key) or []
        items.extend(rows)
        if not rows or len(items) >= min(total, MAX_ITEMS) or page * PAGE_SIZE >= MAX_ITEMS:
            break
        page += 1
    return total, items[:MAX_ITEMS]


def _part(total: int, items: list[dict]) -> dict:
    return {"total": total, "fetched": len(items), "truncated": total > len(items), "items": items}


def export(key: str, *, client: SonarClient | None = None, ce_task_id: str | None = None) -> dict:
    """CE 태스크가 끝난 뒤 호출한다. 품질 게이트 ERROR도 정상 결과다."""
    client = _client(client)
    url = client.url
    gate = client.get("/api/qualitygates/project_status", projectKey=key).get("projectStatus") or {}
    conditions = [{k: c.get(k) for k in ("status", "metricKey", "comparator", "errorThreshold", "actualValue")
                   if c.get(k) is not None} for c in gate.get("conditions") or []]
    component = client.get("/api/measures/component", component=key, metricKeys=",".join(MEASURE_KEYS)).get("component") or {}
    measures = {metric: None for metric in MEASURE_KEYS}
    for measure in component.get("measures") or []:
        if measure.get("metric") in measures:
            measures[measure["metric"]] = measure.get("value")
    issue_total, issue_rows = _paged(client, "/api/issues/search", "issues", {"componentKeys": key})
    hotspot_total, hotspot_rows = _paged(client, "/api/hotspots/search", "hotspots", {"projectKey": key})
    quoted = urllib.parse.quote(key, safe="")
    issues = [{"key": row["key"], "rule": row.get("rule"), "severity": row.get("severity"), "type": row.get("type"),
               "status": row.get("status"), "component": row.get("component"), "line": row.get("line"),
               "message": row.get("message"),
               "link": f"{url}/project/issues?id={quoted}&issues={row['key']}&open={row['key']}"} for row in issue_rows]
    hotspots = [{"key": row["key"], "rule": row.get("ruleKey"), "probability": row.get("vulnerabilityProbability"),
                 "status": row.get("status"), "component": row.get("component"), "line": row.get("line"),
                 "message": row.get("message"), "link": f"{url}/security_hotspots?id={quoted}&hotspots={row['key']}"}
                for row in hotspot_rows]
    return {"schemaVersion": SCHEMA_VERSION, "projectKey": key, "serverUrl": url, "ceTaskId": ce_task_id,
            "dashboardUrl": f"{url}/dashboard?id={quoted}",
            "qualityGate": {"status": gate.get("status") or "NONE", "conditions": conditions},
            "measures": measures, "issues": _part(issue_total, issues), "hotspots": _part(hotspot_total, hotspots)}


# --- 렌더링 -----------------------------------------------------------------------------------------
def render(doc: dict, out_dir, css_href: str = "site.css", copy_css: bool = True) -> Path:
    """`sonar.html`을 쓴다. copy_css=True면 단독 열람용으로 site.css를 같은 디렉터리에 둔다(사이트 조립은 False와 css_href)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if copy_css:
        shutil.copy2(STATIC_DIR / "site.css", out_dir / "site.css")
    html = jinja_env().get_template("sonar.html.j2").render(doc=doc, css_href=css_href, rows=HTML_ROWS, max_items=MAX_ITEMS)
    target = out_dir / "sonar.html"
    target.write_text(html)
    return target


# --- bash용 CLI ---------------------------------------------------------------------------------------
LOCAL_ENV_KEYS = ("TD_LIGHTSAIL_IP", "TD_SSH_KEY_PATH", "TD_DOMAIN")


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False))


def cmd_local_env(args) -> int:
    """infra/local.env에서 S11이 쓰는 키만 `export KEY=<quoted>`로 낸다(환경에 이미 있으면 그 값이 우선)."""
    from td.publish import load_local_env
    root = Path(os.environ.get("TD_ROOT") or Path(__file__).resolve().parents[2])
    values = load_local_env(root / "infra" / "local.env")
    for key in LOCAL_ENV_KEYS:
        value = os.environ.get(key) or values.get(key)
        if value:
            print(f"export {key}={shlex.quote(value)}")
    return 0


def cmd_url(args) -> int:
    print(base_url())
    return 0


def cmd_key(args) -> int:
    from td import sut_config
    print(project_key_for(sut_config.load(args.sut_file).sonar_project_key, os.environ.get("TD_SITE_PREFIX", "")))
    return 0


def cmd_preflight(args) -> int:
    reason = status_up(args.url)
    if reason:
        print(reason)
        return 1
    return 0


def cmd_validate(args) -> int:
    try:
        return 0 if token_valid(SonarClient(args.url)) else 1
    except SonarError as exc:
        print(redact(str(exc)), file=sys.stderr)
        return 1


def cmd_prepare(args) -> int:
    """스캔 인자와 커버리지 XML 해시를 JSON으로 낸다. XML이 없으면 coverageXmlSha256은 null이고 해당 속성을 뺀다."""
    from td import sut_config
    config = sut_config.load(args.sut_file)
    xml = Path(args.xml) if args.xml else None
    xml_ok = bool(xml and xml.is_file())
    scan_args = config.sonar_args(str(xml) if xml_ok else "", args.url, args.key)
    if not xml_ok:
        scan_args = [a for a in scan_args if not a.startswith("-Dsonar.coverage.jacoco.xmlReportPaths=")]
    digest = hashlib.sha256(xml.read_bytes()).hexdigest() if xml_ok else None
    _print_json({"args": scan_args, "coverageXmlSha256": digest, "build": shlex.split(config.sonar_cmd_build),
                 "scan": shlex.split(config.sonar_cmd_scan)})
    return 0


def cmd_ensure_project(args) -> int:
    try:
        created = ensure_project(args.key, SonarClient(args.url))
    except SonarError as exc:
        _print_json({"status": "failed", "reason": redact(f"프로젝트 보장 실패: {exc}")})
        return 1
    _print_json({"status": "passed", "created": created})
    return 0


def cmd_report_task(args) -> int:
    try:
        print(read_report_task(args.path)["ceTaskId"])
    except SonarError as exc:
        print(str(exc))
        return 1
    return 0


def cmd_wait_ce(args) -> int:
    status = wait_ce(args.task_id, args.timeout, client=SonarClient(args.url))
    print(status)
    return 0 if status == "SUCCESS" else 1


def cmd_finish(args) -> int:
    """export -> sonar.json/sonar.html -> kpis.sonar. 결과 JSON(status/reason/extra)을 낸다."""
    from td import state
    out_dir = Path(args.run_dir) / "S11" / "sonar"
    try:
        doc = export(args.key, client=SonarClient(args.url), ce_task_id=args.task_id)
    except SonarError as exc:
        _print_json({"status": "failed", "reason": redact(f"Sonar export 실패(ceTaskId={args.task_id}): {exc}")[:1200]})
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sonar.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    render(doc, out_dir)
    measures = doc["measures"]
    state.set_run_field(args.run_dir, "kpis.sonar", {
        "gate": doc["qualityGate"]["status"], "coverage": measures.get("coverage"), "bugs": measures.get("bugs"),
        "vulnerabilities": measures.get("vulnerabilities"), "codeSmells": measures.get("code_smells"),
        "issues": doc["issues"]["total"], "hotspots": doc["hotspots"]["total"]})
    _print_json({"status": "passed", "outputs": {"sonar": str(out_dir)},
                 "extra": {"ceTaskId": args.task_id, "projectKey": args.key, "qualityGate": doc["qualityGate"]["status"]}})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.sonar")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("local-env").set_defaults(fn=cmd_local_env)
    sub.add_parser("url").set_defaults(fn=cmd_url)
    key = sub.add_parser("key")
    key.add_argument("sut_file")
    key.set_defaults(fn=cmd_key)
    for name, fn in (("preflight", cmd_preflight), ("validate", cmd_validate)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--url", required=True)
        cmd.set_defaults(fn=fn)
    prep = sub.add_parser("prepare")
    prep.add_argument("--sut-file", required=True)
    prep.add_argument("--url", required=True)
    prep.add_argument("--key", required=True)
    prep.add_argument("--xml")
    prep.set_defaults(fn=cmd_prepare)
    ensure = sub.add_parser("ensure-project")
    ensure.add_argument("--url", required=True)
    ensure.add_argument("--key", required=True)
    ensure.set_defaults(fn=cmd_ensure_project)
    report = sub.add_parser("report-task")
    report.add_argument("path")
    report.set_defaults(fn=cmd_report_task)
    wait = sub.add_parser("wait-ce")
    wait.add_argument("--url", required=True)
    wait.add_argument("--task-id", required=True)
    wait.add_argument("--timeout", type=float, default=CE_TIMEOUT_SECONDS)
    wait.set_defaults(fn=cmd_wait_ce)
    finish = sub.add_parser("finish")
    finish.add_argument("run_dir")
    finish.add_argument("--url", required=True)
    finish.add_argument("--key", required=True)
    finish.add_argument("--task-id", required=True)
    finish.set_defaults(fn=cmd_finish)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except SonarError as exc:
        print(redact(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
