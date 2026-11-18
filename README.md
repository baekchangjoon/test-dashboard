# test-dashboard

테스트 파이프라인과 품질 대시보드 PoC. (골격 단계: 이후 Task에서 채운다.)

## 준비

- Python 3.12, uv
- Docker
- `infra/local.env`: `infra/local.env.example`을 복사해 실제 값으로 채운다(gitignore 대상).

## 수용 테스트

```
uv run --project site-gen pytest tests/acceptance -v
```

Python 버전은 `site-gen/.python-version`(3.12)으로 고정되어 있어 uv가 알아서 고른다. 첫 실행 전에 한 번 `uv run --project site-gen playwright install chromium`을 실행한다.

전제(AWS, SSH, Docker, claude)가 없으면 skip이 아니라 실패한다.
