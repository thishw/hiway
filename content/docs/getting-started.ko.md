---
title: "시작하기"
description: "플러그인을 설치하고, 작업 크기에 맞는 만큼만 절차를 태웁니다."
weight: 1
---

## 설치 전에

[Claude Code CLI](https://code.claude.com)가 필요합니다(`claude --version`). 킷의 훅은 이 머신의 `python3` 3.9 이상에서 돕니다. macOS 시스템 Python도 해당합니다. 더 낮은 버전이면 훅이 아무 일도 하지 않고, 세션이 한 번 경고합니다.

## Claude Code에 설치

두 경로 중 **하나만** 고르세요. 둘 다 설치하면 모든 스킬과 훅이 두 번 로드됩니다.

**Anthropic 디렉토리에서.** Claude Code에 내장돼 있어 마켓플레이스를 추가할 필요가 없습니다.

```text
/plugin install hiway-kit@anthropic-plugin-directory
```

새 버전은 Anthropic의 스캔을 거쳐 디렉토리에 올라가므로, 레포보다 잠시 늦을 수 있습니다.

**레포를 마켓플레이스로.** 업데이트하는 즉시 `main`을 따라갑니다.

```text
/plugin marketplace add This-HW/hiway-kit
/plugin install hiway-kit@hiway-kit
```

업데이트는 마켓플레이스를 새로 고치면 새 버전이 반영됩니다.

```text
/plugin marketplace update hiway-kit
```

### 설치는 이 프로젝트가 아니라 머신 전체를 바꾼다

플러그인은 사용자 범위로 설치됩니다. 설치·업데이트·제거는 이미 실행 중인 세션을 포함해 이 머신의 모든 세션의 훅 등록과 규칙 주입을 바꿉니다. 실행 중이던 세션은 처음 받은 컨텍스트를 그대로 갖지만, 훅은 중간에 경로를 잃을 수 있습니다. 긴 작업이 돌고 있지 않을 때 하거나, 끝난 뒤 실행 중이던 세션을 다시 시작하세요.

같은 스킬을 싣는 킷 두 개를 동시에 쓰지 마세요. 플러그인 별칭이 없어서 둘 다 등록됩니다.

## 첫 작업

세션이 시작되면 킷이 규칙과 짧은 워크플로 안내를 주입합니다. 그다음은 작업 크기가 경로를 정합니다.

| 크기 | 경로 |
| --- | --- |
| 작은 작업·버그 | 바로 구현하고 완료 조건 명령으로 검증 |
| 중간 | `/plan-task` → `/auto-dev` |
| 큰 새 기능 | `/brainstorming` → `/plan-task` → `/auto-dev` |

크기 판정은 `plan-task`가 맡습니다. 중간·큰 작업이면 `docs/plans/<날짜>-<slug>/plan.md`를 쓰고, 그 `## 완료 조건` 절에는 설명이 아니라 명령을 적습니다. `auto-dev`는 그 명령을 체크리스트 항목으로 만들고, 명령이 0으로 끝난 항목만 통과로 표시합니다.

작업 중 생기는 질문에는 등급을 매깁니다. 데이터 무결성·보안·금융·핵심 비즈니스에 닿는 P0만 작업을 멈추고 묻고, 나머지는 기본값을 적고 진행합니다.

자주 쓰게 될 다른 스킬: 현재 변경분에 린트·적대적 리뷰·(민감한 파일이 바뀌었으면) 보안 점검을 거는 `/review`, 에러나 트레이스백을 들고 가는 `/debug`, 테스트를 돌리고 실패를 고치는 `/test`. 이것들이 기대는 생각은 [개념](/ko/docs/concepts/)에서 설명합니다.

## Codex {#codex}

플러그인 루트에는 Codex 용 네이티브 매니페스트가 함께 들어 있습니다. 로컬 클론을 플러그인 마켓플레이스로 추가합니다.

```bash
git clone https://github.com/This-HW/hiway-kit
codex plugin marketplace add ./hiway-kit
codex plugin add hiway-kit@hiway-kit-marketplace
codex plugin list   # hiway-kit@hiway-kit-marketplace 가 보이면 성공
```

**그다음 훅 신뢰를 한 번 승인합니다.** Codex는 승인 전까지 플러그인 훅을 조용히 건너뛰고, 규칙이 주입되지 않았다는 사실을 세션 어디에서도 알려 주지 않습니다. 프로젝트에서 대화형 `codex` 세션을 한 번 열어 훅 신뢰 프롬프트를 승인하세요. 비대화형 `codex exec`에는 프롬프트가 없어서 `--dangerously-bypass-hook-trust`를 주지 않으면 훅이 계속 건너뛰어집니다. 이미 신뢰하는 환경에서만 쓰세요.

훅이 없어도 규칙은 `AGENTS.md`로 Codex에 닿습니다(`/harness-export`로 내보냅니다). Codex는 서브에이전트를 노출하지 않으므로, 에이전트를 지정하는 스킬은 같은 계약을 세션 안에서 수행합니다.

제거:

```bash
codex plugin remove hiway-kit@hiway-kit-marketplace
codex plugin marketplace remove hiway-kit-marketplace
```

## Antigravity {#antigravity}

로컬 클론의 `plugins/common`을 먼저 검증한 뒤 설치합니다.

```bash
agy plugin validate /path/to/hiway-kit/plugins/common
agy plugin install /path/to/hiway-kit/plugins/common
agy plugin list   # hiway-kit 이 보이면 성공
```

Antigravity는 스킬은 인식하지만 `rules/` 디렉토리와 중첩된 에이전트는 인식하지 않습니다. 그래서 규칙은 `AGENTS.md`·`GEMINI.md` 로만 전달됩니다. Google 문서에는 로컬·워크스페이스 설치만 나와 있고, 공개 레지스트리는 확인되지 않았습니다. 제거는 `agy plugin uninstall hiway-kit`.
