---
title: "hiway-kit"
description: "hiway-kit은 코딩 에이전트를 위한 에이전트·스킬·규칙 플러그인이다. 짜기 전에 계획하고, 적대적으로 리뷰하고, 완료를 명령의 출력으로 판정한다."

hero:
  headline: "완료는 주장이 아니라 종료 코드다."
  lede: "hiway-kit은 Claude Code·Codex·Antigravity에서 쓰는 에이전트·스킬·규칙 플러그인입니다. 큰 작업은 코드보다 계획을 먼저 거치고, 태스크는 그것을 확인하는 명령이 0으로 끝나야 완료로 칩니다."
  primary: "Claude Code에 설치"
  secondary: "시작하기 문서 읽기"

problem:
  heading: "계획 없는 에이전트는 너무 일찍 끝낸다."
  body: |
    코딩 에이전트에게 기능을 맡기면 곧바로 코드부터 씁니다. 한 시간 뒤에는 "다 됐습니다"라고 보고합니다. 그런데 아무도 정하지 않은 요구사항은 추측으로 채워져 있고, 돌렸다던 테스트는 실행된 적이 없으며, 설계가 기대던 모듈 경계는 조용히 깨져 있곤 합니다.

    에이전트가 거짓말을 하는 것은 아닙니다. 자기 판단 말고는 대조할 기준이 없을 뿐입니다. **hiway-kit은 대조할 기준을 줍니다.** 완료 조건이 명령으로 적힌 계획, 그리고 문장 대신 종료 코드를 읽는 관문입니다.

how:
  heading: "작동 방식"
  intro: "관문 두 개와 그 사이의 루프입니다. 관문에서는 사람이 결정하고, 루프는 끝나거나 가드에 걸리거나 사람만 답할 수 있는 질문을 만날 때까지 스스로 돕니다."
  svg:
    alt: "작업은 기획 관문을 지나 구현 루프를 돌고 검증 관문에 닿는다. verify 명령이 0으로 끝나면 완료로, 그 밖의 종료 코드면 다시 루프로 돌아간다."
    gate1: "기획 관문"
    gate1_sub: "plan-task"
    loop: "구현 루프"
    loop_sub: "auto-dev"
    gate2: "검증 관문"
    gate2_sub: "verify → exit 0"
    done: "완료"
    fail: "exit ≠ 0: 루프로 돌아감"
    fail_short: "exit ≠ 0"
  stations:
    - title: "기획 관문"
      body: "큰 새 기능은 `brainstorming`에서 시작하고, 중간 이상 규모의 작업은 `plan-task`가 `docs/plans/<날짜>-<slug>/plan.md`로 정리합니다. 완료 조건 하나하나가 실행할 수 있는 명령입니다. 작은 수정은 이 절차를 건너뜁니다."
    - title: "구현 루프"
      body: "`auto-dev`가 승인된 계획을 배치 단위로 끝까지 밀고 갑니다. P0 질문, 가드, 계획의 끝에서만 멈춥니다."
    - title: "검증 관문"
      body: "체크리스트 항목은 그 항목의 `verify` 명령이 실제로 실행돼 0으로 끝날 때만 통과합니다. 병합 전에는 리뷰와 보안 스캔이 변경을 봅니다."

features:
  heading: "킷이 실제로 하는 일"
  items:
    - title: "기획 관문"
      body: "명세로 확인되지 않은 전제를 P0부터 P3까지 등급으로 나눕니다. 데이터 무결성·보안·금융·핵심 비즈니스에 닿는 P0만 작업을 멈추고 묻고, 나머지는 기본값을 적고 진행합니다."
      where:
        label: "skills/plan-task"
        path: "tree/plugins/common/skills/plan-task"
    - title: "적대적 리뷰"
      body: "`review-code`는 작성자와 분리된 컨텍스트에서 완성된 diff를 해커·머피·미래의 나·까다로운 사용자, 네 페르소나로 읽습니다. 설계는 `multi-perspective-review`가 최대 열 가지 관점으로 검토합니다."
      where:
        label: "agents/review-code.md"
        path: "blob/plugins/common/agents/review-code.md"
    - title: "완료는 명령이 판정한다"
      body: "“완료”는 판단이 아닙니다. 검증 명령을 새로 실행해 출력을 읽기 전까지 에이전트는 “구현 완료, 검증 전”이라고 말하고 남은 것을 적습니다."
      where:
        label: "rules/definition-of-done.md"
        path: "blob/plugins/common/rules/definition-of-done.md"
    - title: "실패에서 배운다"
      body: "리뷰·검증에서 나온 결함은 `.git/kit/` 아래 피드백 원장에 쌓입니다(상한·중복 제거·감쇠). 다음 세션은 반복되는 결함을 교훈으로 받고 시작합니다."
      where:
        label: "tools/feedback_ledger.py"
        path: "blob/plugins/common/tools/feedback_ledger.py"
    - title: "경계는 프로젝트 도구로 지킨다"
      body: "프로젝트에 import-linter·dependency-cruiser 같은 경계 검사 도구가 있으면 `plan-task`가 그 명령을 계획의 완료 조건에 넣습니다. 도구가 없으면 없다고 적고, 도입은 사용자가 정합니다."
      where:
        label: "plan-task/references/boundary-check.md"
        path: "blob/plugins/common/skills/plan-task/references/boundary-check.md"
    - title: "코드 탐색과 변경 미리보기"
      body: "`code-intel`은 설치된 ast-grep으로 코드 구조를 검색하고 규칙에 따른 변경을 미리 보여줍니다. 지원하는 언어 서버가 있으면 정의·참조·진단도 조회할 수 있습니다. 미리보기는 원본을 그대로 두며, 언어 서버는 신뢰하는 작업 공간에서 사용하세요."
      where:
        label: "skills/code-intel"
        path: "tree/plugins/common/skills/code-intel"
    - title: "이전 세션에서 결정한 내용 찾기"
      body: "`session-history`는 직접 선택한 로컬 Codex·Claude Code 세션 로그를 검색하고, 근거가 있는 파일과 줄 번호를 알려줍니다."
      where:
        label: "skills/session-history"
        path: "tree/plugins/common/skills/session-history"
    - title: "여러 하네스에서"
      body: "공통 스킬과 규칙은 Claude Code·Codex·Antigravity에서 사용할 수 있습니다. 전용 서브에이전트는 Claude Code에서 지원하고, 도구 호출을 막는 훅은 Claude Code에 레포 마켓플레이스로 설치했을 때 지원합니다. 하네스별 적용 방식은 아래 표에서 확인할 수 있습니다."
      where:
        label: "README: Where it runs"
        path: "blob/README.md#where-it-runs"
  note: "[개발 노트: C/C++ 인덱싱과 프로젝트 설정](/ko/blog/code-navigation-and-project-setup/)"

harnesses:
  heading: "지원 하네스"
  intro: "아래 표는 저장소 릴리스 기준입니다. 설치한 버전과 하네스의 스킬·규칙·훅 지원 범위에 따라 쓸 수 있는 기능이 달라집니다."
  columns: ["규칙", "스킬", "서브에이전트", "차단 훅"]
  rows:
    - name: "Claude Code"
      cells:
        - { state: "yes", text: "세션 시작 시 주입(레포 마켓플레이스 설치)" }
        - { state: "yes", text: "네이티브" }
        - { state: "yes", text: "지원" }
        - { state: "yes", text: "지원(레포 마켓플레이스 설치)" }
    - name: "Codex"
      cells:
        - { state: "yes", text: "훅 신뢰 승인 후 주입, AGENTS.md 폴백" }
        - { state: "yes", text: "모두 인식" }
        - { state: "no", text: "없음 — 스킬이 세션 안에서 수행" }
        - { state: "no", text: "없음" }
    - name: "Antigravity"
      cells:
        - { state: "part", text: "AGENTS.md·GEMINI.md 로만" }
        - { state: "yes", text: "인식" }
        - { state: "no", text: "없음" }
        - { state: "no", text: "없음" }
  note: "Claude Code에서 Anthropic 디렉토리에는 훅 없는 축소판이 올라가므로 규칙이 주입되지 않고 아무것도 차단되지 않습니다(새 버전이 심사를 통과하기 전까지는 훅이 있는 이전 버전이 그대로 제공됩니다). Codex는 한 번 승인하기 전까지 플러그인 훅을 조용히 건너뜁니다. 방법은 [시작하기 문서](/ko/docs/getting-started/#codex)에 있습니다."

install:
  heading: "설치"
  claude:
    title: "Claude Code"
    body: "Claude Code에 내장된 Anthropic 디렉토리에서는 심사를 통과한 버전을 설치할 수 있습니다. 위에 표시된 저장소 릴리스보다 이전 버전일 수 있습니다. 디렉토리에는 축소판이 올라갑니다. 훅(규칙 주입·민감 경로 차단·자동 포맷·종료 시 검사), Python 도구, code-intel·session-history·harness-export 스킬이 없고, 파일을 고치는 에이전트는 worktree 격리 없이 돕니다. 새 버전이 심사를 통과하기 전까지는 이전 버전이 그대로 제공됩니다. 전체 기능은 레포 마켓플레이스로 설치하세요."
    alt: "`main`을 바로 따라가고 훅까지 쓰려면 이 레포를 마켓플레이스로 추가합니다. 훅은 이 머신의 `python3`(3.9 이상)에서 실행됩니다. 둘 중 하나만 설치하세요. 둘 다 설치하면 모든 스킬이 두 번 로드되고 버전이 섞입니다."
    after: "플러그인은 사용자 범위로 설치되므로, 이미 실행 중인 세션을 포함해 이 머신의 모든 세션이 바뀝니다. 긴 작업이 돌고 있지 않을 때 설치하세요. 레포 마켓플레이스로 설치했다면 업데이트는 `/plugin marketplace update hiway-kit`."
  others:
    - title: "Codex"
      body: "Codex에서 GitHub 저장소를 플러그인 마켓플레이스로 추가한 뒤 훅을 승인합니다. [단계 보기](/ko/docs/getting-started/#codex)."
    - title: "Antigravity"
      body: "GitHub 저장소에서 바로 설치하거나, 로컬 클론의 `plugins/common`을 검증한 뒤 설치합니다. [단계 보기](/ko/docs/getting-started/#antigravity)."

closing:
  label: "시작하기"
  line: "계획으로 시작해서 종료 코드로 끝낸다."
  primary: "시작하기"
  secondary: "GitHub 소스"
---
