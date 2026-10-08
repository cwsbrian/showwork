# Showwork 설치와 업데이트

Showwork 0.4.0은 기본적으로 **Codex와 Claude Code 둘 다 사용자 단위로 설치**합니다. Node.js 20 이상(npm/npx 포함), Git, Python 3.11 이상이 필요합니다.

## 설치·업데이트는 같은 명령

어느 폴더에서든 실행하세요.

```bash
npx --yes github:cwsbrian/showwork
```

처음에는 설치하고, 다음부터는 GitHub 기본 브랜치의 최신 커밋으로 갱신합니다. 설치 후 원하는 도구에서 **새 채팅/세션**을 여세요. 프로젝트마다 반복 설치할 필요가 없습니다.

| 도구 | 사용자 스킬 | 자동 적용 지침 | 백업 |
| --- | --- | --- | --- |
| Codex | `~/.agents/skills/showwork*` | `~/.codex/AGENTS.md` | `~/.agents/showwork-backups/` |
| Claude Code | `~/.claude/skills/showwork*` | `~/.claude/CLAUDE.md` | `~/.claude/showwork-backups/` |

Codex 지침은 `CODEX_HOME`이 설정되면 그 위치를 사용하고, 내용이 있는 `AGENTS.override.md`가 있으면 그 파일을 갱신합니다. Claude는 `CLAUDE_CONFIG_DIR`이 설정되면 그 위치에 스킬과 지침을 설치합니다. 사용자 지침의 스킬 참조는 절대 경로입니다. Showwork 관리 블록 밖의 기존 지침과 다른 스킬은 보존합니다. Claude의 `settings.json`, 인증, MCP, 기존 훅 설정은 수정하지 않습니다.

Claude 사용자 설치는 개인 스킬과 `CLAUDE.md` 지침을 사용합니다. 별도 플러그인 실행 인자나 요청 훅 등록이 필요하지 않습니다. 네이티브 플러그인 목록에 등록되는 설치는 아닙니다. 관리 정책이 사용자 지침/스킬을 비활성화한 환경에서는 해당 정책이 우선합니다. [Claude 스킬 위치](https://code.claude.com/docs/en/skills#choose-where-skills-load) · [Claude 사용자 지침](https://code.claude.com/docs/en/memory) · [Codex 스킬 위치](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) · [Codex 지침 우선순위](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

## 한 도구 또는 한 프로젝트만 설치

```bash
npx --yes github:cwsbrian/showwork --runtime claude
npx --yes github:cwsbrian/showwork --runtime codex
npx --yes github:cwsbrian/showwork --target /absolute/path/to/your-project
npx --yes github:cwsbrian/showwork --help
```

`--runtime`은 `both`(기본), `codex`, `claude` 중 선택합니다. `--target`이 있으면 그 프로젝트에만 설치합니다. `--user`를 명시해도 기본 사용자 설치와 같으며 `--target`과 함께 쓸 수 없습니다.

| 프로젝트 설치 | 스킬 | 지침 |
| --- | --- | --- |
| Codex | `<project>/.agents/skills/showwork*` | `<project>/AGENTS.md` (활성 override 우선) |
| Claude Code | `<project>/.claude/skills/showwork*` | `<project>/.claude/CLAUDE.md` |

기존 프로젝트 루트 `CLAUDE.md`는 그대로 보존합니다. 대상 프로젝트는 이미 존재해야 합니다. 기본 사용자 설치는 현재 작업 폴더에 파일이나 npm 의존성을 추가하지 않습니다.

저장소를 직접 내려받아 Python만으로 실행할 수도 있습니다. 파일 이름은 이전 버전과의 호환성을 위해 유지합니다.

```bash
git clone https://github.com/cwsbrian/showwork.git
python3 /absolute/path/to/showwork/scripts/install_codex.py --user
```

Python 진입점도 기본은 두 도구이며 `--runtime`/`--target`을 지원합니다. 이 경우 업데이트 전에 원본 저장소를 먼저 갱신하세요. 설치기는 실행 중인 번들의 내용을 설치합니다.

## 업데이트와 복구

동일한 npx 명령을 다시 실행하면 됩니다. 0.2.x의 Codex 전용 설치도 갱신하면서 Claude 사용자 설치를 추가합니다. 최신 커밋 확인에는 네트워크가 필요합니다. `--offline` 또는 특정 커밋에 고정한 주소는 최신 확인용이 아닙니다. npm 10에서 같은 캐시·같은 명령으로 새 Git 커밋을 가져오는 동작을 검증했습니다.

- 달라진 스킬 디렉터리는 각 도구의 `showwork-backups/update-*/`에 이전 내용 전체를 보관하고 새 버전으로 교체합니다. 정확한 백업 위치를 출력합니다.
- 직접 수정하거나 추가한 파일도 백업에 남습니다. 활성 스킬에는 배포판이 적용되므로 계속 필요한 사용자 수정은 백업과 비교해 다시 반영하세요. 배포판에서 제거된 파일은 활성 스킬에서도 제거됩니다.
- 지침은 관리 블록만 갱신하며 변경 전 파일도 백업합니다. 같은 내용이면 재복사하거나 백업을 추가하지 않습니다.
- 두 도구 모두 먼저 경로·지침·소스·기존 잠금을 검사합니다. 실제 교체와 오류 복원은 도구별로 수행합니다. 두 번째 도구에서 예기치 않은 쓰기 실패가 나면 첫 번째 도구의 성공한 업데이트는 유지됩니다. 실패 원인을 해결하고 같은 명령을 다시 실행하세요.
- 스킬 교체나 지침 쓰기가 실패하면 해당 도구의 이전 파일을 복원합니다. 운영체제 강제 종료·전원 장애까지 자동 복원을 보장하지는 않습니다. 중단됐다면 백업을 확인하고, 실행 중인 설치가 없는데 잠금 오류가 남을 때만 해당 도구의 `.showwork-install.lock` 디렉터리를 제거한 뒤 재실행하세요.

백업은 스킬 검색 경로 밖에 보관하며 자동 삭제하지 않습니다. 복구하려면 설치가 실행 중이지 않은지 확인하고 해당 백업의 스킬 디렉터리를 원래 `skills/` 위치로 복원하세요. 이후 설치 명령을 다시 실행하면 다시 최신 배포판이 적용됩니다.

0.2.1까지의 기본 설치는 프로젝트 단위였습니다. 이전 프로젝트 파일이나 수동 플러그인 등록은 자동 삭제하지 않습니다. 사용자 설치로 통일하려면 기존 프로젝트의 Showwork 스킬 디렉터리와 지침의 관리 블록을 백업한 뒤 정리하세요. 같은 스킬의 사용자 설치와 플러그인 중복 활성화는 피하세요.

## 사용과 확인

새 세션에서 평소처럼 요청합니다.

```text
HTML/CSS/JavaScript로 간단한 할 일 앱을 만들어줘.
추가, 완료 처리, 삭제가 가능하고 새로고침해도 목록이 유지되어야 해.
```

단순하고 명확한 작업은 바로 구현해도 정상입니다. 시각적 선택이 필요할 때만 브라우저에서 비교합니다. 완료 설명은 바뀐 영역에 맞춰 라우트 흐름도·경로 표, 스키마 전후 비교·마이그레이션 상태, 시스템 구조·데이터 흐름, 검증 근거를 보여줍니다. 변경하지 않은 영역을 억지로 채우지 않습니다. 지침은 모델의 행동을 유도하며 모든 응답의 완전성을 강제하는 정책 엔진은 아닙니다.

직접 호출하려면 Codex는 `$showwork`, Claude는 `/showwork`를 사용합니다. `showwork-plan`, `showwork-review`, `showwork-verify`, `showwork-adverial-review`도 같은 접두사로 호출할 수 있습니다. 아무 안내 없이 진행한다면 설치 범위의 스킬·지침 블록과 새 세션 여부, 상위 관리 정책을 확인하세요.

`adverial-review`는 리뷰 결과를 localhost 브라우저에서 보여주고, 모바일 대상에서는 시뮬레이터/에뮬레이터 실행 및 실제 화면 캡처를 요구합니다. npx 사용자 설치에서는 Claude `/showwork-adverial-review`, Codex `$showwork-adverial-review`로 호출합니다. 아래 플러그인 로딩 방식에서만 콜론 명령 `/showwork:adverial-review`를 사용합니다.

## Claude 로컬 플러그인 방식 (선택)

npx 사용자 설치를 사용한다면 필요하지 않습니다. 저장소를 플러그인으로 직접 불러오려면:

```bash
claude --plugin-dir /absolute/path/to/showwork
```

이 방식은 세션에 플러그인을 로드하며, 함께 제공되는 `UserPromptSubmit` 훅으로 자동 판단 지침을 전달합니다. `/showwork:run`, `/showwork:plan`, `/showwork:review`, `/showwork:verify`, `/showwork:adverial-review` 단축 명령을 사용합니다. 훅은 도구 실행을 차단하지 않습니다. [Claude 플러그인](https://code.claude.com/docs/en/plugins)

## 제거와 검증

선택한 설치 범위에서 Showwork 스킬 디렉터리와 지침 파일의 `showwork:automatic:start`~`showwork:automatic:end` 관리 블록만 제거하세요. 다른 지침이 있는 파일 전체를 삭제하지 마세요. 선택 기능인 증거 기록 도구는 복사하지 않으며, 브라우저 companion은 `showwork` 스킬에 포함됩니다.

개발 검사는 저장소에서 실행합니다.

```bash
python3 -m unittest discover -s tests -v
npm test
claude plugin validate . --strict
```

실제 브라우저 검사는 Playwright와 Chromium이 있는 개발 환경에서 `tests/browser_companion.cjs`를 실행합니다. 자세한 검증 범위와 한계는 [검증 기록](validation.md)을 참고하세요.
