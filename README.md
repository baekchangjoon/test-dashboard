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

전제(AWS, SSH, Docker, claude)가 없으면 skip이 아니라 실패한다.
