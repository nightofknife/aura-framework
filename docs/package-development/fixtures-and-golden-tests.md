# Fixtures and Golden Tests

Fixture 用于无真实桌面副作用的自动化验收。默认只允许 `fake` 或 `fixture` backend，不触发真实截图、键鼠、OCR、YOLO、进程控制或文件写入。

## Directory

```text
tests/fixtures/desktop/
  basic-click/
    fixture.yaml
    snapshot.json
  capture/basic-screen/
  vision/template-match/
  ocr/simple-text/
  yolo/simple-detections/
  window/basic-context/
  task/minimal-fake-e2e/
  failure/locator-not-found/
```

## Fixture Schema v2

v2 兼容读取 v1，并增加 capture、locator、OCR、YOLO、window、diagnostics 期望值。

```yaml
fixture_schema_version: 2
id: vision/template-match
desktop_profile: fixture
capture:
  backend: fake
  image: capture/basic-screen.png
window:
  title: Fake Window
  rect: [0, 0, 1280, 720]
expected:
  actions:
    - action: plans/aura_base/find_image
      backend: fake
      ok: true
  locators:
    - method: template_match
      bbox: [100, 120, 40, 30]
      score: 0.99
  diagnostics:
    error_category: none
```

## Commands

```powershell
python cli.py fixture list
python cli.py fixture run vision/template-match
python cli.py fixture verify vision/template-match
python cli.py fixture verify vision/template-match --update-snapshot
python cli.py fixture doctor
python cli.py fixture verify-all --format json
python cli.py fixture update vision/template-match --snapshot-only
```

`--update-snapshot` and `fixture update --snapshot-only` only update fixture snapshots. They must not update runtime code or package source.

## Release Gate

`release check` calls `fixture verify-all`. Snapshot drift returns a non-zero exit code and blocks local release readiness.
