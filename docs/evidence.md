# Evidence recorder

Requires Python 3.11 or newer and uses only the standard library. Run it from the target project directory and set `SHOWWORK_REPO` below to the actual repository path.

This tool runs commands and copies existing files into a record. It does not write tests, control a browser, or judge image contents. The agent using the skill performs those tasks and explains what the results mean.

## Runnable example

This example tests **the recorder itself**, not a product feature.

```bash
SHOWWORK_REPO=/absolute/path/to/showwork
SHOWWORK_RUN=$(python3 "$SHOWWORK_REPO/scripts/showwork.py" init smoke \
  --title "Check CLI recording" \
  --criterion "Save Python output to a file" \
  --criterion "Attach an observation" | head -n 1)

python3 "$SHOWWORK_REPO/scripts/showwork.py" check "$SHOWWORK_RUN" \
  --criterion C1 -- python3 -c 'print("hello from the runtime")'

printf 'Observed the CLI output locally.\n' > "$SHOWWORK_RUN/observation.txt"
python3 "$SHOWWORK_REPO/scripts/showwork.py" attach "$SHOWWORK_RUN" \
  --criterion C2 --kind manual --path "$SHOWWORK_RUN/observation.txt" \
  --note "Recorder usage example; not evidence of a product feature"

python3 "$SHOWWORK_REPO/scripts/showwork.py" status "$SHOWWORK_RUN"
```

`SHOWWORK_RUN` is the temporary path printed on the first line by `init`. Use the path for the current task in real checks too.

Each `--criterion` passed to `init` receives an ID such as `C1` or `C2` in order. To continue using an old record inside a project, first move it to a temporary directory outside the project. The original project path remains in the record, so check commands still run there. A run name is never overwritten; use a new name for a new task or separate verification.

## Record a real check

Put the project's actual check command and arguments after `--` in `check`. Put recorder options before `--`.

```bash
python3 "$SHOWWORK_REPO/scripts/showwork.py" check "$SHOWWORK_RUN" \
  --criterion C1 --timeout 120 -- npm test -- --runInBand
```

That npm command is an example for projects with that test configuration. Replace it with the repository's actual command. The default working directory is where `init` ran; use `--cwd /absolute/project/path` to set another one.

Commands do not pass through a shell. If you need redirection or pipes, invoke the intended shell explicitly. For example, `-- bash -lc 'command-a | command-b'` runs a shell. The recorder does not sandbox commands, so normal permissions and work scope apply.

Standard output and errors go into one log. The record also includes command arguments, working directory, duration, exit code, Git HEAD, and whether Git reported changes. The last two are context, not a fingerprint of the entire working tree. The default timeout is 300 seconds. On POSIX, timeouts, Ctrl-C, and SIGTERM clean up the command's process group and record the result. On Windows, only the direct process is terminated; child cleanup and Windows behavior were not verified for this release.

`check` returns the command's exit code. A launch failure returns `127`, timeout `124`, Ctrl-C `130`, SIGTERM `143`, and input or storage errors `2`. Failed command results are recorded too.

## Attach screen, API, and observation evidence

```bash
python3 "$SHOWWORK_REPO/scripts/showwork.py" attach "$SHOWWORK_RUN" \
  --criterion C1 --kind screenshot --path /absolute/path/to/actual-screen.png \
  --note "Observed the completed cancellation screen, next-payment notice, and access end date"
```

Supported kinds are `screenshot`, `video`, `api`, and `manual`. The kind is a label; file contents and formats are not checked automatically. Describe the observation and its limits in `--note`. Do not claim to have observed something you did not see. Attachments are copied, so later changes to the original do not alter the record.

## Interpret status

`status` checks whether each criterion has evidence, whether its latest recorded check passed, and whether stored files match their SHA-256 hashes. Earlier failures remain in the record, while a later successful check updates the latest status. An attachment does not hide a failed check. Parallel checks and attachments merge into the latest record under a lock.

| Exit code | Meaning |
| --- | --- |
| `0` | Every criterion has a record; any latest check passed; recorded files are intact |
| `1` | Missing record, failed latest check, or missing/changed file |
| `2` | Input, record format, or read error |

**`0` does not mean the product is complete.** A manual note alone can fill the evidence field, and an unrelated command can succeed. The agent must read the record and decide whether it actually supports each requirement. The tool also cannot detect later code changes, so rerun affected checks when code changes.

Outputs are `run.json` and `evidence/` inside the temporary directory printed by `init`. The default path is `/tmp/showwork-<uid>/<project-path-hash>/runs/<name>`; Windows uses the OS temporary directory. No record is created in the project. `--root` also accepts only a temporary directory outside the project. Hashes detect accidental file changes; they are not tamper-proof signatures. Review logs and screenshots before sharing them. These records are disposable and may disappear when the OS cleans temporary files. Delete only the relevant run directory when checks are done and it is no longer needed.
