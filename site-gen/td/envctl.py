"""Docker 자원 스냅샷, 누수 판정, compose 라벨 검사, Gradle daemon 식별(REQ-009, REQ-011).

귀속 규칙: compose project가 `td-` 접두(`td-<runId>-…`, 테스트는 `td-test-…`)인 새 자원은 owned(우리 책임),
그 밖의 새 자원은 foreign(공유 Docker 호스트의 다른 작업이므로 경고로만 분리한다).
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field

PROJECT_LABEL = "com.docker.compose.project"
OWNED_PREFIX = "td-"
RUN_LABEL_KEY = "test-run"


@dataclass(frozen=True)
class DockerSnap:
    # id -> compose project(없으면 None)
    containers: dict[str, str | None] = field(default_factory=dict)
    networks: dict[str, str | None] = field(default_factory=dict)
    volumes: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class Leak:
    owned: list[str]
    foreign: list[str]


def docker_lines(*args: str, timeout: int = 60) -> list[str]:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} 실패: {result.stderr.strip()[:300]}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def parse_listing(text: str) -> dict[str, str | None]:
    """`<id>\\t<labels>` 줄들을 {id: compose project}로 바꾼다."""
    parsed: dict[str, str | None] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        ident, _, labels = line.partition("\t")
        match = re.search(rf"(?:^|,){re.escape(PROJECT_LABEL)}=([^,]*)", labels)
        parsed[ident.strip()] = match.group(1) if match else None
    return parsed


def _listing(*args: str) -> dict[str, str | None]:
    # 볼륨은 ID가 아니라 Name이 식별자이고 --no-trunc 옵션이 없다.
    if args[0] == "volume":
        return parse_listing("\n".join(docker_lines(*args, "--format", "{{.Name}}\t{{.Labels}}")))
    return parse_listing("\n".join(docker_lines(*args, "--no-trunc", "--format", "{{.ID}}\t{{.Labels}}")))


def _quiet_ids(base: list[str], label: str) -> list[str]:
    extra = [] if base[0] == "volume" else ["--no-trunc"]
    return docker_lines(*base, "-q", *extra, "--filter", f"label={RUN_LABEL_KEY}={label}")


def snapshot() -> DockerSnap:
    return DockerSnap(
        containers=_listing("ps", "-a"),
        networks=_listing("network", "ls"),
        volumes=_listing("volume", "ls"),
    )


def _is_owned(project: str | None) -> bool:
    return bool(project) and project.startswith(OWNED_PREFIX)


def diff(before: DockerSnap, after: DockerSnap) -> Leak:
    """before 뒤에 새로 생겨 남아 있는 자원을 `<kind>:<id>`로 돌려준다(라벨과 무관, project로만 귀속)."""
    owned: list[str] = []
    foreign: list[str] = []
    for kind in ("container", "network", "volume"):
        old = getattr(before, kind + "s")
        for ident, project in getattr(after, kind + "s").items():
            if ident in old:
                continue
            (owned if _is_owned(project) else foreign).append(f"{kind}:{ident}")
    return Leak(owned=sorted(owned), foreign=sorted(foreign))


def unlabeled_resources(config: dict, label_value: str) -> list[str]:
    """`docker compose config --format json` 결과에서 test-run 라벨이 없거나 값이 다른 서비스, 네트워크, 볼륨.

    네트워크(`default`)와 볼륨은 명시적으로 선언돼 있어야 한다. 빠져 있으면 라벨을 달 수 없으므로 누락으로 본다.
    """
    problems: list[str] = []
    for kind, singular in (("services", "service"), ("networks", "network"), ("volumes", "volume")):
        entries = config.get(kind) or {}
        if kind == "networks" and "default" not in entries:
            problems.append("network:default")
        if kind == "volumes" and not entries:
            problems.append("volume:<none declared>")
        for name, spec in entries.items():
            labels = (spec or {}).get("labels") or {}
            if isinstance(labels, list):
                labels = dict(item.split("=", 1) for item in labels if "=" in item)
            if labels.get(RUN_LABEL_KEY) != label_value:
                problems.append(f"{singular}:{name}")
    return problems


def leak_gate(run_id: str) -> list[str]:
    """런 자원 잔존 목록. 라벨 `test-run=td-<runId>`가 붙은 것과, 라벨이 없어도 project가 `td-<runId>` 접두인 것."""
    label = f"td-{run_id}"
    project_prefix = label.lower()
    leftovers: list[str] = []
    for kind, base in (("container", ["ps", "-a"]), ("network", ["network", "ls"]), ("volume", ["volume", "ls"])):
        listing = _listing(*base)
        labeled = set(_quiet_ids(base, label))
        for ident, project in listing.items():
            by_project = bool(project) and (project == project_prefix or project.startswith(project_prefix + "-"))
            if ident in labeled or by_project:
                leftovers.append(f"{kind}:{ident}")
        for ident in labeled:  # 이름 줄임 차이로 listing에 없는 경우를 놓치지 않는다
            if f"{kind}:{ident}" not in leftovers and not any(item.split(":", 1)[1].startswith(ident) for item in leftovers):
                leftovers.append(f"{kind}:{ident}")
    return sorted(set(leftovers))


def parse_gradle_daemons(ps_output: str) -> list[tuple[int, str]]:
    """`ps -axo pid=,lstart=,command=` 출력에서 GradleDaemon의 (pid, 시작 시각) 목록."""
    found = []
    for line in ps_output.splitlines():
        match = re.match(r"\s*(\d+)\s+(\w{3} \w{3}\s+\d+ [\d:]{8} \d{4})\s+(.*)", line)
        if match and "GradleDaemon" in match.group(3):
            found.append((int(match.group(1)), match.group(2)))
    return found


def gradle_daemons() -> list[tuple[int, str]]:
    out = subprocess.run(["ps", "-axo", "pid=,lstart=,command="], capture_output=True, text=True, timeout=30).stdout
    return parse_gradle_daemons(out)


# --- 기동 실패 사유 ------------------------------------------------------------------------------------
def failure_reason(message: str, log_text: str, rel_log: str, budget: int = 1400, max_lines: int = 50) -> str:
    """사유 = 메시지 + 로그 마지막 `max_lines`줄 + `(full log: <상대 경로>)`. 전체 길이는 `budget`자(문자 기준) 이내.

    예산이 모자라면 로그 꼬리의 앞쪽을 잘라 낸다(마지막 줄이 남는다). 문자 단위(코드 포인트)로 자르므로 한글이 깨지지 않는다.
    """
    pointer = f"(full log: {rel_log})"
    message = message.strip()
    if len(message) > 300:
        message = message[:299] + "…"
    lines = log_text.replace("\r", "").rstrip().splitlines()[-max_lines:]
    tail = "\n".join(lines)
    head = f"{message}. 로그 마지막:\n"
    room = budget - len(head) - len(pointer) - 1
    if not tail:
        tail = "(로그 없음)"
    if len(tail) > room:
        tail = "…" + tail[len(tail) - max(room - 1, 0):]
    return f"{head}{tail}\n{pointer}"


def cap_chars(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- PID reap -----------------------------------------------------------------------------------------
def _ps(field: str, pid: int) -> str:
    result = subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
    return result.stdout.strip()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return not _ps("stat", pid).startswith("Z")  # 회수 전 좀비는 죽은 것으로 본다


def _started_after_registration(pid: int, registered_at: float) -> bool:
    """PID 재사용 방지: 등록(pid 파일 기록)보다 늦게 시작한 프로세스는 우리가 등록한 것이 아니다."""
    started = _ps("lstart", pid)
    try:
        begun = time.mktime(time.strptime(started, "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return False
    return begun > registered_at + 2


def reap_pids(run_dir, term_wait: float = 10.0, names: list[str] | None = None) -> list[int]:
    """`<run_dir>/pids/*.pid`의 살아 있는 프로세스를 TERM → 유예 → KILL로 정리한다. 정리한 PID를 돌려준다.

    names를 주면 그 이름(`<name>.pid`)만 대상으로 하고, 정리가 끝난 뒤 그 pid 파일을 지운다(단계가 자기 PID만 내릴 때).
    names가 없으면 전부 대상이고 파일은 남긴다(종료 검증이 파일로 PID를 확인한다).

    pid가 프로세스 그룹 리더면 그룹 전체에, 아니면 그 pid에만 신호를 보낸다(서브셸에서 등록한 PID도 파일로 찾는다).
    """
    reaped: list[int] = []
    pids_dir = os.path.join(str(run_dir), "pids")
    if not os.path.isdir(pids_dir):
        return reaped
    targets = []
    scoped_files = []
    for name in sorted(os.listdir(pids_dir)):
        path = os.path.join(pids_dir, name)
        if not name.endswith(".pid"):
            continue
        if names is not None:
            if name[: -len(".pid")] not in names:
                continue
            scoped_files.append(path)
        try:
            pid = int(open(path).read().split()[0])
            registered_at = os.path.getmtime(path)
        except (OSError, ValueError, IndexError):
            continue
        if pid <= 1 or not _pid_alive(pid) or _started_after_registration(pid, registered_at):
            continue
        try:
            is_leader = os.getpgid(pid) == pid
        except ProcessLookupError:
            continue
        targets.append((pid, is_leader))

    def send(sig: int) -> None:
        for pid, is_leader in targets:
            try:
                (os.killpg if is_leader else os.kill)(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    if targets:
        send(signal.SIGTERM)
        deadline = time.time() + term_wait
        while time.time() < deadline and any(_pid_alive(pid) for pid, _ in targets):
            time.sleep(0.2)
        send(signal.SIGKILL)
    for path in scoped_files:
        try:
            os.remove(path)
        except OSError:
            pass
    return [pid for pid, _ in targets]


def main(argv: list[str] | None = None) -> int:
    """bash용 CLI.

    check-labels <labelValue>   stdin의 compose config JSON을 검사한다. 누락이 있으면 목록을 출력하고 1.
    leak-gate <runId>           런 자원이 남아 있으면 목록을 출력하고 1.
    """
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) == 2 and args[0] == "check-labels":
            problems = unlabeled_resources(json.load(sys.stdin), args[1])
            if problems:
                print(f"compose에 test-run={args[1]} 라벨이 없다: {', '.join(problems)}")
                return 1
            return 0
        if len(args) == 2 and args[0] == "leak-gate":
            leftovers = leak_gate(args[1])
            if leftovers:
                print("남은 자원: " + ", ".join(leftovers))
                return 1
            return 0
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"envctl: {exc}", file=sys.stderr)
        return 2
    if len(args) in (4, 5) and args[0] == "failure-reason":
        # failure-reason <message> <logfile> <relLogPath> [budget]
        try:
            log_text = open(args[2], encoding="utf-8", errors="replace").read()
        except OSError:
            log_text = ""
        print(failure_reason(args[1], log_text, args[3], int(args[4]) if len(args) == 5 else 1400))
        return 0
    if len(args) == 2 and args[0] == "cap":
        print(cap_chars(sys.stdin.read(), int(args[1])), end="")
        return 0
    if len(args) >= 2 and args[0] == "reap-pids":
        reap_pids(args[1], names=args[2:] or None)
        return 0
    print("usage: td.envctl check-labels <labelValue> | leak-gate <runId> | failure-reason <msg> <log> <rel> | reap-pids <runDir>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
