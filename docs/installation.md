# Showwork 설치

Showwork 0.2.0은 일반 개발 요청에 자동으로 적용되도록 연결합니다. Codex는 프로젝트 지침, Claude Code는 요청 훅을 통해 같은 자동 판단 규칙과 `skills/`를 읽습니다. Python 3.11 이상이 필요합니다. 시각적 선택과 완료 설명을 위한 로컬 브라우저 서버가 스킬에 포함됩니다. 외부 서비스나 MCP는 필요하지 않습니다. 자동 적용 지침을 제공하며, 모델의 모든 행동이나 검증 성공을 강제하는 장치는 아닙니다.

## Claude Code: 로컬 플러그인

프로젝트 폴더에서 Showwork 저장소의 절대 경로를 전달합니다. 다음 두 경로를 실제 경로로 바꾸세요.

```bash
cd /absolute/path/to/your-project
claude --plugin-dir /absolute/path/to/showwork
```

세션 안에서 평소처럼 요청합니다.

```text
로그인 오류를 수정해줘
```

`UserPromptSubmit` 훅은 요청마다 자동 판단 지침과 스킬 위치를 전달합니다. 코드 작업인지와 필요한 절차는 모델이 판단합니다. 훅 자체가 사용자 문장을 키워드로 분류하거나 도구 실행을 차단하지 않습니다. 훅을 비활성화하는 실행 모드나 관리 정책에서는 자동 연결도 동작하지 않습니다. [Claude 요청 훅 문서](https://code.claude.com/docs/en/hooks#userpromptsubmit)

모드를 직접 지정하려면 다음 명령도 사용할 수 있습니다.

```text
/showwork:run 로그인 오류를 수정해줘
/showwork:plan 로그인 오류 수정 계획을 세워줘
/showwork:review 현재 변경사항을 리뷰해줘
/showwork:verify 로그인 오류가 해결됐는지 검증해줘
```

`commands/`의 짧은 명령은 `${CLAUDE_PLUGIN_ROOT}`를 통해 공통 스킬을 읽습니다. 공통 스킬도 `/showwork:showwork`, `/showwork:showwork-plan`, `/showwork:showwork-review`, `/showwork:showwork-verify` 이름으로 노출될 수 있습니다. 짧은 명령을 사용하면 됩니다.

`--plugin-dir`로 불러온 플러그인은 해당 세션에서만 활성화됩니다. 저장소를 수정했다면 새 세션을 시작하세요. 이 방법은 전역 설정이나 마켓플레이스를 수정하지 않습니다. 명령이 보이지 않으면 `claude --help`에서 `--plugin-dir` 지원 여부를 확인하세요. [Claude Code 플러그인 문서](https://code.claude.com/docs/en/plugins)

## Codex: 프로젝트에 스킬 복사

Python 3.11 이상과 프로젝트 스킬을 지원하는 Codex를 사용하세요. 대상 프로젝트는 이미 존재하는 폴더여야 합니다.

```bash
python3 /absolute/path/to/showwork/scripts/install_codex.py --target /absolute/path/to/your-project
codex -C /absolute/path/to/your-project
```

Codex 앱에서는 설치 후 대상 프로젝트에서 **새 채팅**을 엽니다. 이전 채팅에는 갱신된 프로젝트 지침이 반영되지 않을 수 있습니다. `$showwork` 없이 일반 요청을 입력하세요.

```text
로그인 오류를 수정해줘
```

특정 모드를 명시하고 싶다면 다음 명령도 사용할 수 있습니다.

```text
$showwork 로그인 오류를 수정해줘
$showwork-plan 로그인 오류 수정 계획을 세워줘
$showwork-review 현재 변경사항을 리뷰해줘
$showwork-verify 로그인 오류가 해결됐는지 검증해줘
```

프로젝트의 `.agents/skills` 검색과 `$`를 통한 호출은 [Codex 스킬 문서](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)에 설명되어 있습니다.

설치기는 네 스킬을 `.agents/skills/showwork*`에 함께 복사합니다. 서로 참조하므로 하나만 옮기지 마세요. 같은 스킬은 다시 복사하지 않습니다. 다른 내용이나 추가 파일이 있으면 전체 사전 검사에서 멈추며 기존 파일을 덮어쓰지 않습니다. 대상 `.agents`나 `skills`가 심볼릭 링크인 경우에도 멈춥니다.

자동 적용 규칙은 프로젝트 루트의 `AGENTS.md`에 `<!-- showwork:automatic:start -->`부터 `<!-- showwork:automatic:end -->`까지의 관리 블록으로 저장합니다. 내용이 있는 `AGENTS.override.md`가 있으면 그 파일에 기록합니다. 같은 위치에서는 override가 우선하며 빈 파일은 건너뛰기 때문입니다. 관리 블록 밖의 사용자 지침은 보존하고, 재실행해도 블록이 중복되지 않습니다. 불완전한 마커나 지침 파일의 심볼릭 링크는 수정 전에 거부합니다. 다른 스킬과 전역 설정은 수정하지 않습니다. [Codex 프로젝트 지침 문서](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

0.1.0의 스킬만 설치한 프로젝트는 같은 설치 명령을 다시 실행하면 자동 적용 블록이 추가됩니다. 스킬 내용이 달라진 경우는 아래 업데이트 방법을 따르세요.

스킬 내용이 바뀐 버전으로 업데이트하려면 네 Showwork 디렉터리의 사용자 변경을 먼저 확인하고, 백업하거나 스킬 검색 경로 밖으로 옮긴 후 설치기를 다시 실행하세요. 강제 덮어쓰기 옵션은 없습니다. 제거할 때는 해당 네 디렉터리와 지침 파일의 Showwork 관리 블록만 제거하세요. 사용자 지침이 있는 `AGENTS.md` 전체를 삭제하지 마세요.

선택 기능인 증거 기록 도구는 복사하지 않습니다. 스킬은 이 도구 없이 작동합니다. 기록 도구가 필요하면 대상 프로젝트에서 원본 저장소의 스크립트를 절대 경로로 실행하세요. Python 3.11 이상이 필요합니다.

브라우저 companion은 이 증거 기록 도구와 별개이며 `showwork` 스킬 안에 함께 복사됩니다. 설치 후 `<project>/.agents/skills/showwork/scripts/companion.py`와 `assets/companion.html`이 있어야 합니다. 시각적 선택이 필요한 경우 또는 완료 설명을 할 때 에이전트가 서버를 실행하고 페이지를 작성합니다. [Companion 사용법](../skills/showwork/references/companion.md)

```bash
cd /absolute/path/to/your-project
python3 /absolute/path/to/showwork/scripts/showwork.py --help
```

## Codex 네이티브 플러그인과의 차이

`.codex-plugin/plugin.json`은 네이티브 플러그인 배포용 매니페스트입니다. 이 개발 환경의 `codex plugin --help`에는 `add`, `list`, `marketplace`, `remove`가 있고, `codex plugin add`는 마켓플레이스에 등록된 `플러그인@마켓플레이스`를 받습니다. Claude의 `--plugin-dir`과 같은 로컬 로딩 명령은 현재 CLI 도움말에 없습니다.

이 저장소는 마켓플레이스를 등록하거나 전역 설정을 바꾸지 않습니다. 따라서 위의 프로젝트 설치가 자동 연결까지 포함한 Codex 설치 방법입니다. 이는 플러그인 설치 목록에 표시되는 네이티브 설치가 아니라 프로젝트 스킬·지침 설치이며, 자동 업데이트되지 않습니다. 기존 마켓플레이스로 배포하려면 운영자가 이 플러그인을 먼저 등록해야 합니다. 네이티브 플러그인 등록만으로 이 프로젝트 지침이 추가되지는 않습니다.

## 자동 적용 확인

새 채팅에서 다음을 그대로 입력하세요.

```text
HTML/CSS/JavaScript로 간단한 할 일 앱을 만들어줘.
추가, 완료 처리, 삭제가 가능하고 새로고침해도 목록이 유지되어야 해.
```

이처럼 단순하고 명확한 작업은 Showwork 적용과 경로를 짧게 알린 후 바로 구현해도 정상입니다. 미리보기나 UI 컨펌을 의무적으로 요구하지 않습니다. 최종 결과를 설명할 때는 브라우저에서 실제 결과 또는 설명용 흐름과 함께 추가·완료·삭제·새로고침 검증 근거와 미검증 사항을 보여줘야 합니다.

선택 기능은 실제로 두 레이아웃 중 결정할 필요가 있는 요청으로 따로 시험하세요. 브라우저 비교안 → 선택 기록 → 구현으로 이어지는지, 완료 화면에는 승인 버튼이 없는지 확인합니다.

아무 안내 없이 바로 구현한다면 대상 프로젝트의 스킬과 지침 블록이 있는지, 그 프로젝트에서 새 채팅을 시작했는지 확인하세요. Claude는 플러그인 로딩과 훅 활성화도 확인해야 합니다. 하위 폴더나 상위 우선순위의 지침이 적용 방식을 바꿀 수도 있습니다.

## 검증

Showwork 저장소에서 실행합니다.

```bash
python3 -m unittest discover -s tests -p 'test_install.py'
claude plugin validate . --strict
```

첫 명령은 임시 폴더에서 설치, 재실행, 충돌 시 보존, 심볼릭 링크 거부를 확인합니다. 두 번째는 Claude 플러그인 매니페스트를 검사합니다. 매니페스트 통과는 모델이 실제 작업에서 지시를 잘 따른다는 보장은 아닙니다.

형식 참고: [Claude 매니페스트 및 경로 변수](https://code.claude.com/docs/en/plugins-reference), [Claude 스킬과 명령 인자](https://code.claude.com/docs/en/skills).
