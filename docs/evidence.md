# 증거 기록 도구

Python 3.11 이상이 필요합니다. 표준 라이브러리만 사용합니다. 대상 프로젝트 폴더에서 실행하며, 아래 `SHOWWORK_REPO`를 실제 저장소 경로로 설정하세요.

이 도구는 명령을 실행하고 기존 파일을 복사해 보관합니다. 테스트를 작성하거나 브라우저를 조작하거나 이미지 내용을 판정하지 않습니다. 스킬을 사용하는 에이전트가 해당 작업을 수행하고 결과의 의미를 설명합니다.

## 실행 가능한 예시

다음은 제품 기능의 검증이 아닌, **기록 도구 자체를 시험하는 예시**입니다.

```bash
SHOWWORK_REPO=/absolute/path/to/showwork
SHOWWORK_RUN=$(python3 "$SHOWWORK_REPO/scripts/showwork.py" init smoke \
  --title "CLI 기록 기능 확인" \
  --criterion "Python 실행 결과가 파일로 남는다" \
  --criterion "관찰 기록을 첨부할 수 있다" | head -n 1)

python3 "$SHOWWORK_REPO/scripts/showwork.py" check "$SHOWWORK_RUN" \
  --criterion C1 -- python3 -c 'print("hello from the runtime")'

printf 'Observed the CLI output locally.\n' > "$SHOWWORK_RUN/observation.txt"
python3 "$SHOWWORK_REPO/scripts/showwork.py" attach "$SHOWWORK_RUN" \
  --criterion C2 --kind manual --path "$SHOWWORK_RUN/observation.txt" \
  --note "기록 도구 사용 예시이며 제품 기능의 증거는 아님"

python3 "$SHOWWORK_REPO/scripts/showwork.py" status "$SHOWWORK_RUN"
```

`SHOWWORK_RUN`은 `init`의 첫 줄에 나온 임시 경로입니다. 실제 검사 예시에서도 해당 작업의 경로를 사용하세요.

`init`의 각 `--criterion`은 순서대로 `C1`, `C2` 등의 식별자를 받습니다. 예전 프로젝트 안의 기록을 계속 쓰려면 먼저 프로젝트 밖 임시 폴더로 옮기세요. 원래 프로젝트 경로는 기록 안에 남아 있어 검사 명령은 그곳에서 실행됩니다. 같은 실행 이름을 덮어쓰지 않습니다. 새 작업이나 별도 검증에는 새 이름을 사용하세요.

## 실제 검사를 기록하기

`check`에서 `--` 뒤에 프로젝트의 실제 검사 명령과 인자를 넣습니다. 옵션은 `--` 앞에 둡니다.

```bash
python3 "$SHOWWORK_REPO/scripts/showwork.py" check "$SHOWWORK_RUN" \
  --criterion C1 --timeout 120 -- npm test -- --runInBand
```

위 `npm` 명령은 해당 테스트 구성이 있는 프로젝트에서만 사용하는 예시입니다. 저장소의 실제 명령으로 바꾸세요. 기본 작업 디렉터리는 `init`을 실행한 곳이며 `--cwd /absolute/project/path`로 지정할 수 있습니다.

명령은 셸을 거치지 않습니다. 리다이렉션과 파이프가 필요하면 의도한 셸을 명시해야 합니다. 예를 들어 `-- bash -lc 'command-a | command-b'`는 셸을 직접 실행합니다. 기록 도구는 명령을 샌드박스에서 실행하지 않으므로 평소와 같은 권한·작업 범위가 적용됩니다.

표준 출력과 오류는 한 로그에 저장합니다. 명령 인자, 작업 디렉터리, 시간, 종료 코드, Git HEAD와 변경 여부도 기록합니다. 마지막 두 값은 참고 정보이며 작업 트리 전체의 지문은 아닙니다. 제한 시간은 기본 300초입니다. POSIX에서는 시간 초과·Ctrl-C·SIGTERM 시 명령의 프로세스 그룹을 정리하고 결과를 기록합니다. Windows에서는 직접 실행한 프로세스만 종료하며, 하위 프로세스 정리와 Windows 동작은 이번 릴리스에서 검증하지 않았습니다.

`check`의 종료 코드는 실행한 명령을 따릅니다. 실행 실패는 `127`, 시간 초과는 `124`, Ctrl-C는 `130`, SIGTERM은 `143`입니다. 입력이나 저장 오류는 `2`입니다. 명령의 실패 결과도 기록됩니다.

## 화면·API·관찰 자료 연결하기

```bash
python3 "$SHOWWORK_REPO/scripts/showwork.py" attach "$SHOWWORK_RUN" \
  --criterion C1 --kind screenshot --path /absolute/path/to/actual-screen.png \
  --note "직접 실행한 취소 완료 화면. 다음 결제 중단 안내와 접근 종료일을 확인함"
```

지원 유형은 `screenshot`, `video`, `api`, `manual`입니다. 유형은 분류를 위한 표시이며 파일 내용이나 형식을 자동 판정하지 않습니다. `--note`에 관찰한 내용과 제한을 설명하세요. 실제로 관찰하지 않은 내용은 적지 않습니다. 첨부 파일은 복사되므로 원본을 나중에 수정해도 기록은 보존됩니다.

## 상태를 해석하기

`status`는 각 요구사항의 증거 유무, 마지막으로 기록된 검사의 성공 여부, 파일의 SHA-256 일치 여부를 확인합니다. 이전 실패 기록은 보존하고, 이후 성공한 검사로 최신 상태를 갱신합니다. 첨부 파일을 추가해도 실패한 검사를 숨기지 않습니다. 병렬 검사와 첨부는 잠금 안에서 최신 기록에 합쳐 저장합니다.

| 종료 코드 | 의미 |
| --- | --- |
| `0` | 모든 요구사항에 기록이 있고, 마지막 검사가 있다면 성공했으며, 기록 파일이 온전함 |
| `1` | 기록 누락, 마지막 검사 실패, 또는 파일 누락·변경 |
| `2` | 입력이나 기록 형식·읽기 오류 |

**`0`은 제품의 완료 판정이 아닙니다.** 수동 메모만으로도 증거 유무는 채워질 수 있습니다. 관련 없는 명령이 성공할 수도 있습니다. 에이전트는 기록을 읽어 요구사항을 실제로 입증하는지 평가해야 합니다. 이후 코드가 바뀌었는지도 자동 감지하지 않으므로 영향을 받는 검사는 다시 실행하세요.

결과물은 `init`이 출력한 임시 폴더의 `run.json`과 `evidence/`입니다. 기본 경로는 `/tmp/showwork-<uid>/<프로젝트 경로 해시>/runs/<이름>`이며 Windows에서는 운영체제의 임시 폴더를 사용합니다. 프로젝트 폴더에는 기록을 만들지 않습니다. `--root`도 프로젝트 밖의 임시 폴더만 허용합니다. 해시는 실수로 파일이 바뀐 것을 확인하는 용도이며, 위변조를 막는 서명은 아닙니다. 공유 전에 로그와 캡처에 포함된 정보를 확인하세요. 이 자료는 일회성이며 운영체제가 정리하면 사라질 수 있습니다. 검사가 끝나고 필요 없을 때 해당 실행 폴더만 지우세요.
