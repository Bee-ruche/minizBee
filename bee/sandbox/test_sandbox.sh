#!/usr/bin/env bash
# Proves what bee/sandbox/sans-docker.sh guarantees, on a throwaway git repository built here.
#
#   test_sandbox.sh <path of the sans-docker.sh to test> <existing empty folder for the fixtures>
#
# Every command run inside the sandbox is written in this file and harmless (touch, cat, sh -c, a few
# lines of python3): nothing of the project is built or run. Needs bash, git, python3, util-linux.
# As root, a launcher that does not confine writes WILL create marker files named bee-sandbox-test.*
# in /usr/bin, /etc, /root and /tmp: this script removes them (and the empty /tmp/bee-sandbox.* folders
# an old launcher leaves) before it ends. Fixtures are left in the folder given, for inspection.
# Exit status: 0 if no check failed.
set -u
[ $# -eq 2 ] && [ -f "$1" ] && [ -d "$2" ] || { echo "usage: $0 <sans-docker.sh> <folder>" >&2; exit 2; }
launcher=$(realpath "$1"); base=$(realpath "$2"); tag=bee-sandbox-test.$$
uid=$(id -u); npass=0; nfail=0; nskip=0; fixtures=0
export BEE_TEST_SECRET=s3cr3t-of-the-caller

pass() { printf 'PASS  %-3s %s\n' "$1" "$2"; npass=$((npass + 1)); }
fail() { printf 'FAIL  %-3s %s   <-- %s\n' "$1" "$2" "${3:-}"; nfail=$((nfail + 1)); }
skip() { printf 'SKIP  %-3s %s   (%s)\n' "$1" "$2" "$3"; nskip=$((nskip + 1)); }
# verdict <id> <description> <0 if the property holds> [detail shown on failure]
verdict() { if [ "$3" -eq 0 ]; then pass "$1" "$2"; else fail "$1" "$2" "${4:-}"; fi; }
first_line() { printf '%s' "$1" | head -n 1 | cut -c1-110; }
digest() { tar -C "$1" -cf - . 2>/dev/null | sha256sum | cut -d' ' -f1; }   # content, names, modes, dates
alive() {  # pids of the processes whose argv[0] is $1
  local f argv0; for f in /proc/[0-9]*/cmdline; do
    argv0=; IFS= read -r -d '' argv0 2>/dev/null <"$f" || true
    if [ "$argv0" = "$1" ]; then f=${f#/proc/}; echo "${f%/cmdline}"; fi
  done
}

# A fresh fixture: $top/home (the caller's home), $top/outside (files elsewhere on the machine),
# $top/parent/{registre,other} (clones next to the work tree), $top/parent/repo (the work tree).
fixture() {
  fixtures=$((fixtures + 1)); top=$base/fixture-$fixtures
  home=$top/home; outside=$top/outside; parent=$top/parent; repo=$parent/repo
  mkdir -p "$home" "$outside/dir" "$parent/registre/tools/hive" "$parent/other/.git" \
    "$repo/bee/sandbox" "$repo/.github/workflows"
  echo "token of the caller" >"$home/secret.txt"
  echo "outside the work tree" >"$outside/target.txt"
  echo "print('the hive tool')" >"$parent/registre/tools/hive/hive.py"
  printf '[remote "origin"]\n\turl = https://token-of-another-repository@example.invalid/x\n' >"$parent/other/.git/config"
  cp "$launcher" "$repo/bee/sandbox/sans-docker.sh"; chmod +x "$repo/bee/sandbox/sans-docker.sh"
  echo "tracked" >"$repo/file.txt"; echo "# agents" >"$repo/AGENTS.md"; echo "# claude" >"$repo/CLAUDE.md"
  echo "on: push" >"$repo/.github/workflows/ci.yml"
  ln -s "$outside/target.txt" "$repo/link-to-file"; ln -s "$outside/dir" "$repo/link-to-dir"
  ln -s ../registre/tools/hive/hive.py "$repo/link-to-sibling"
  cat >"$repo/attack.py" <<'EOF'
# Tries, by direct system calls, to undo the read-only mount of .git: first with the privileges the
# sandbox leaves, then with every capability of a nested user namespace. Exit 1 if anything worked,
# 2 if the nested user namespace could not be created (nothing proven), 0 if every attempt was refused.
import ctypes, os, sys
libc = ctypes.CDLL(None, use_errno=True)
MS_REMOUNT, MS_BIND, MS_MOVE, MNT_DETACH, CLONE_NEWNS, CLONE_NEWUSER = 32, 4096, 8192, 2, 0x20000, 0x10000000
def call(name, *args):
    return "WORKED" if getattr(libc, name)(*args) == 0 else os.strerror(ctypes.get_errno())
def attempts(who):
    results = [("umount .git", call("umount2", b".git", 0)),
               ("lazy umount .git", call("umount2", b".git", MNT_DETACH)),
               ("remount .git read-write", call("mount", None, b".git", None, MS_REMOUNT | MS_BIND, None)),
               ("bind the tree without its mounts", call("mount", b".", b"/tmp", None, MS_BIND, None)),
               ("move the .git mount", call("mount", b".git", b"/tmp", None, MS_MOVE, None)),
               ("lazy umount the tree", call("umount2", b".", MNT_DETACH))]
    try:
        open(".git/planted-by-syscall", "w").close(); results.append(("write in .git", "WORKED"))
    except OSError as error:
        results.append(("write in .git", error.strerror))
    for what, result in results:
        print(f"{who}: {what}: {result}")
    return any(result == "WORKED" for _, result in results)
won = attempts("sandbox user")
if libc.unshare(CLONE_NEWUSER | CLONE_NEWNS) != 0:
    print("nested user namespace: could not be created:", os.strerror(ctypes.get_errno()))
    sys.exit(1 if won else 2)
print("nested user namespace: created,", open("/proc/self/status").read().split("CapEff:")[1].split()[0], "effective capabilities")
won = attempts("nested user namespace") or won
sys.exit(1 if won else 0)
EOF
  git -C "$repo" init -q -b master
  git -C "$repo" add -A
  git -C "$repo" -c user.name=test -c user.email=test@example.invalid commit -q -m fixture
  # What a clone's .git may hold beside the history: an address with a token, a header, logs that quote them.
  git -C "$repo" remote add origin "https://token-of-the-clone@example.invalid/fork"
  git -C "$repo" config http.https://example.invalid/.extraheader "AUTHORIZATION: basic dG9rZW4tb2YtdGhlLWNsb25l"
  echo "0000 1111 fetch: from https://token-of-the-clone@example.invalid/fork" >>"$repo/.git/logs/HEAD"
  echo "1111		branch 'master' of https://token-of-the-clone@example.invalid/fork" >"$repo/.git/FETCH_HEAD"
}
# run <command…>: the launcher of the fixture, from the work tree, with the fixture's home as $HOME.
run() { (cd "$repo" && HOME=$home timeout -k 5 120 bee/sandbox/sans-docker.sh "$@"); }
# inside <shell script>: runs it in the sandbox; sets $out (stdout+stderr) and $rc.
inside() { out=$(run sh -c "$1" 2>&1); rc=$?; }
# refused <id> <description> <shell script that tries to write>: it must fail inside.
refused() { inside "$3"; verdict "$1" "$2" $((rc == 0)) "the write succeeded inside"; }

cleanup() {
  local d
  [ -z "${helper:-}" ] || kill "$helper" 2>/dev/null
  [ -z "${victim:-}" ] || kill "$victim" 2>/dev/null
  for d in $(alive bee-test-survivor); do kill -KILL "$d" 2>/dev/null; done
  rm -f -- "/usr/bin/$tag" "/etc/$tag" "/etc/$tag.target" "/root/$tag" "/tmp/$tag" 2>/dev/null
  for d in /tmp/bee-sandbox.*; do   # the empty folders an old launcher leaves: only those made during this run
    case " $litter_before " in *" $d "*) ;; *) [ ! -d "$d" ] || rmdir "$d" 2>/dev/null ;; esac
  done
}
litter_before=$(echo /tmp/bee-sandbox.*)
trap cleanup EXIT

echo "launcher: $launcher"
echo "user: uid $uid; kernel $(uname -r); $(unshare --version)"
echo

# ---------------------------------------------------------------------------------------------------
echo "== a. no network, no environment of the caller, an empty home"
fixture
python3 -I -c '
import os, socket, sys, time
os.chdir(sys.argv[1])                       # a unix socket path is limited to 107 bytes: bind it by a short name
tcp = socket.socket(); tcp.bind(("127.0.0.1", 0)); tcp.listen()
unix = socket.socket(socket.AF_UNIX); unix.bind("socket"); unix.listen()
open("port", "w").write(str(tcp.getsockname()[1])); time.sleep(600)' "$outside" &
helper=$!; helper_dir=$outside
for _ in $(seq 50); do [ -s "$outside/port" ] && break; sleep 0.1; done
port=$(cat "$outside/port")
connect_unix="import os, socket, sys; os.chdir(sys.argv[1]); socket.socket(socket.AF_UNIX).connect('socket')"
# Controls: from the host both servers answer, so a refusal inside is the sandbox's doing.
(exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null && python3 -I -c "$connect_unix" "$outside" \
  || { echo "test setup failed: the host's own servers cannot be reached" >&2; exit 3; }
inside "exec 3<>/dev/tcp/127.0.0.1/$port"
verdict a1 "a TCP server of the host (127.0.0.1:$port) cannot be reached" $((rc == 0)) "connected"
inside 'grep -c : /proc/net/dev; grep : /proc/net/dev | grep -vc "lo:"'
verdict a2 "the only network interface is lo" "$([ "$out" = "1
0" ]; echo $?)" "$(first_line "$out")"
inside 'env'
verdict a3 "no environment variable of the caller (BEE_TEST_SECRET)" "$(! grep -q "s3cr3t" <<<"$out"; echo $?)" "$(grep s3cr3t <<<"$out")"
names=$(printf '%s\n' "$out" | cut -d= -f1 | grep -vxE 'HOME|LANG|PATH|TERM|PWD|OLDPWD|SHLVL|_' | tr '\n' ' ')
verdict a4 "the only variables inside are HOME, LANG, PATH, TERM and the shell's own (PWD, SHLVL, _)" "$([ -z "$names" ]; echo $?)" "also: $names"
inside 'cd "$HOME" && [ -w . ] && [ -z "$(ls -A)" ]'
verdict a5 "\$HOME inside is an empty, writable folder" "$rc" "$(first_line "$out")"
inside "cat '$home/secret.txt'"
verdict a6 "a file of the caller's home cannot be read" $((rc == 0)) "$(first_line "$out")"

# ---------------------------------------------------------------------------------------------------
echo "== b. the work tree is writable, except .git and the other guarded paths"
before=$(digest "$repo/.git"); head_before=$(git -C "$repo" rev-parse HEAD)
inside 'echo built >new-file.txt && echo changed >>file.txt && mkdir -p bee/construction && echo o >bee/construction/out'
verdict b1 "files of the work tree can be created and changed" "$([ "$rc" -eq 0 ] && [ -f "$repo/new-file.txt" ] && [ -f "$repo/bee/construction/out" ] && grep -q changed "$repo/file.txt"; echo $?)" "$(first_line "$out")"
inside 'git rev-parse HEAD && git cat-file -p HEAD >/dev/null && git status --porcelain >/dev/null && git diff --stat >/dev/null'
verdict b2 "git can read inside (rev-parse, cat-file, status, diff)" "$([ "$rc" -eq 0 ] && [ "$(first_line "$out")" = "$head_before" ]; echo $?)" "$(first_line "$out")"
inside 'cat .git/config; git config --list; cat .git/FETCH_HEAD .git/logs/HEAD; grep -rs token-of-the-clone .git; grep -rs dG9rZW4t .git; true'
verdict b17 "what .git holds beside the history cannot be read: its settings (an address with a token, a header), its logs" "$(! grep -qE 'token-of-the-clone|dG9rZW4t' <<<"$out"; echo $?)" "$(grep -m1 -E 'token-of-the-clone|dG9rZW4t' <<<"$out" | cut -c1-80)"
inside 'ls -A .git | tr "\n" " "'
verdict b18 "of .git, the command sees HEAD, the refs, the objects, the index and empty settings, nothing else" "$([ "$out" = "HEAD config index objects refs " ]; echo $?)" "$out"
inside 'cp -a . "$HOME/copy" && cd "$HOME/copy" && git worktree add -q --detach "$HOME/checkout" HEAD && [ -f "$HOME/checkout/file.txt" ] && echo x >.git/written'
verdict b3 "a private copy of the clone (in the empty home) has a writable .git: git worktree add works there" "$rc" "$(first_line "$out")"
refused b4 "write to .git/config fails" 'echo "# planted" >>.git/config'
refused b5 "write to .git/hooks/pre-commit fails" 'printf "#!/bin/sh\n# planted\n" >.git/hooks/pre-commit'
refused b6 "write to .git/info/attributes fails" 'echo "# planted" >>.git/info/attributes'
refused b7 "write to .git/HEAD fails" 'echo "# planted" >>.git/HEAD'
refused b8 ".git cannot be renamed away (to put another in its place)" 'mv .git .git-moved'
[ ! -d "$repo/.git-moved" ] || mv -T "$repo/.git-moved" "$repo/.git"   # put the fixture back for the next checks
inside 'umount .git; umount -l .git; mount -o remount,bind,rw .git; echo x >.git/planted-after-remount'
verdict b9 ".git cannot be unmounted or remounted read-write (mount, umount)" $((rc == 0)) "the write succeeded inside"
inside 'python3 attack.py'
verdict b10 "nor by direct system calls, even with the capabilities of a nested user namespace" "$rc" "exit $rc of attack.py, see below"
printf '%s\n' "$out" | sed 's/^/          /'
verdict b11 "after all this, .git on the host is unchanged (content, names, modes, dates)" "$([ "$(digest "$repo/.git")" = "$before" ]; echo $?)" "new: $(cd "$repo" && ls -d .git/hooks/pre-commit .git/planted* 2>/dev/null | tr '\n' ' '); last line of .git/config: $(tail -n 1 "$repo/.git/config")"

fixture
before=$(digest "$repo/bee/sandbox"); agents=$(cat "$repo/AGENTS.md" "$repo/CLAUDE.md" "$repo/.github/workflows/ci.yml")
refused b12 "the launcher itself (bee/sandbox/sans-docker.sh) cannot be changed" 'echo "# planted" >>bee/sandbox/sans-docker.sh'
inside 'mv bee bee-moved && mkdir -p bee/sandbox && echo "echo planted" >bee/sandbox/sans-docker.sh'
verdict b13 "nor replaced by renaming the folder above it" "$([ "$rc" -ne 0 ] && [ "$(digest "$repo/bee/sandbox")" = "$before" ]; echo $?)" "bee/sandbox on the host: $(ls "$repo/bee/sandbox" 2>&1 | tr '\n' ' ')"
[ -d "$repo/bee-moved" ] && { mv "$repo/bee" "$repo/bee-planted"; mv "$repo/bee-moved" "$repo/bee"; }   # put the fixture back
inside 'echo "run this outside the sandbox" >>AGENTS.md; echo x >>CLAUDE.md; echo x >>.github/workflows/ci.yml; mv AGENTS.md A; mv .github G'
verdict b14 "agent instructions and CI (AGENTS.md, CLAUDE.md, .github) cannot be changed" "$([ "$(cat "$repo/AGENTS.md" "$repo/CLAUDE.md" "$repo/.github/workflows/ci.yml" 2>/dev/null)" = "$agents" ]; echo $?)" "changed on the host"
inside 'mkdir .claude && echo "{\"hooks\": {}}" >.claude/settings.json; echo "{}" >.mcp.json'
verdict b15 "a .claude/settings.json or .mcp.json created inside is not there afterwards" "$([ ! -e "$repo/.claude" ] && [ ! -e "$repo/.mcp.json" ]; echo $?)" "$(cd "$repo" && ls -d .claude .mcp.json 2>/dev/null | tr '\n' ' ')on the host"
inside 'mkdir .claude .claude.created-in-sandbox.1 created-in-sandbox.1 && echo "{}" >.claude/settings.json && chmod 555 .claude . ; exit 0'
verdict b16 "also when the command made it and the work tree read-only, and took likely names ($(first_line "$out" | cut -c1-60))" "$([ ! -e "$repo/.claude" ] && [ "$rc" -eq 0 ] && [ -n "$out" ]; echo $?)" "rc $rc; .claude is still there"
chmod u+rwx "$repo"

# ---------------------------------------------------------------------------------------------------
echo "== c. nothing outside the work tree and a private /tmp can be written"
fixture
before_parent=$(ls -A "$parent" | tr '\n' ' '); before_sibling=$(digest "$parent/registre"); before_home=$(digest "$home")
if [ "$uid" -eq 0 ]; then
  inside "touch /usr/bin/$tag"
  verdict c1 "a file created in /usr/bin does not exist on the host" "$([ ! -e "/usr/bin/$tag" ]; echo $?)" "/usr/bin/$tag exists (rc inside: $rc)"
  inside "touch /etc/$tag"
  verdict c2 "a file created in /etc does not exist on the host" "$([ ! -e "/etc/$tag" ]; echo $?)" "/etc/$tag exists (rc inside: $rc)"
  inside "touch /root/$tag"
  verdict c3 "a file created in /root does not exist on the host" "$([ ! -e "/root/$tag" ]; echo $?)" "/root/$tag exists (rc inside: $rc)"
else
  for id in c1 c2 c3; do skip $id "write to /usr/bin, /etc, /root" "not root: the kernel refuses anyway"; done
fi
inside "touch '$parent/planted' ../planted-too"
verdict c4 "a file created in the folder above the work tree does not exist on the host" "$([ "$(ls -A "$parent" | tr '\n' ' ')" = "$before_parent" ]; echo $?)" "now: $(ls -A "$parent" | tr '\n' ' ')"
inside "echo 'import os' >>'$parent/registre/tools/hive/hive.py'; echo x >'$parent/registre/tools/hive/planted.py'; echo x >>../registre/tools/hive/hive.py"
verdict c5 "the clone next to it (../registre/tools/hive/hive.py) is unchanged on the host" "$([ "$(digest "$parent/registre")" = "$before_sibling" ]; echo $?)" "$(tail -n 1 "$parent/registre/tools/hive/hive.py")"
inside "echo x >>'$home/secret.txt'; touch '$home/.bashrc'"
verdict c6 "the caller's home is unchanged on the host" "$([ "$(digest "$home")" = "$before_home" ]; echo $?)" "$(ls -A "$home" | tr '\n' ' ')"
inside "touch /tmp/$tag && [ -w /tmp ]"
verdict c7 "/tmp is writable inside, and what is written there is not in the host's /tmp" "$([ "$rc" -eq 0 ] && [ ! -e "/tmp/$tag" ]; echo $?)" "rc inside $rc; on the host: $(ls "/tmp/$tag" 2>&1)"
inside "ls /tmp/$tag"
verdict c8 "the next run starts with a /tmp that does not hold the previous run's file" $((rc == 0)) "still there"
inside 'ls /dev | tr "\n" " "'
verdict c9 "/dev holds no disk and no terminal" "$([ "$out" = "fd full null random shm stderr stdin stdout urandom zero " ]; echo $?)" "$(printf '%s' "$out" | wc -w) entries: $(first_line "$out")"
disk=$(findmnt -no SOURCE /)
if [ -b "$disk" ] && head -c 16 "$disk" >/dev/null 2>&1; then
  inside "head -c 16 '$disk' | wc -c"
  verdict c10 "the machine's disk ($disk) cannot be opened" "$([ "$out" != 16 ]; echo $?)" "16 raw bytes read: it could be written the same way"
else
  skip c10 "the machine's disk cannot be opened" "the caller cannot open $disk either"
fi
if [ -w /proc/sys/kernel/core_pattern ]; then
  inside '[ -w /proc/sys/kernel/core_pattern ]'
  verdict c11 "kernel settings (/proc/sys/kernel/core_pattern) are not writable" $((rc == 0)) "writable: a core_pattern runs a program as root on the host"
else
  skip c11 "kernel settings are not writable" "the caller cannot write them either"
fi
BEE_VICTIM_SECRET=s3cr3t-of-a-process sleep 600 & victim=$!
inside "[ -e /proc/$victim/cmdline ] && tr '\\0' ' ' </proc/$victim/cmdline"
verdict c12 "a process of the host (pid $victim) is not visible" $((rc == 0)) "its command line: $(first_line "$out")"
inside "tr '\\0' '\\n' </proc/$victim/environ | grep BEE_VICTIM || ls -d /proc/$victim/root/."
verdict c13 "the environment and the root folder of a process of the host cannot be read" $((rc == 0)) "$(first_line "$out")"
inside "kill -TERM $victim"; sleep 0.3
verdict c14 "a process of the host cannot be signalled" "$(kill -0 "$victim" 2>/dev/null; echo $?)" "the sandbox killed it"
kill "$victim" 2>/dev/null; victim=
inside "python3 -c \"$connect_unix\" '${helper_dir:-}'"
verdict c15 "a unix socket of the host (as the Docker, D-Bus or ssh-agent ones) cannot be reached" $((rc == 0)) "connected"
exec 9<"$outside"; inside 'ls /proc/self/fd/9/'; exec 9<&-
verdict c16 "a descriptor left open by the caller (9, on a folder outside) is closed inside" $((rc == 0)) "it lists: $(first_line "$out")"

# ---------------------------------------------------------------------------------------------------
echo "== d. what is next to the work tree, and the secrets of the machine, cannot be read"
inside "cat '$parent/registre/tools/hive/hive.py' || cat ../registre/tools/hive/hive.py"
verdict d1 "the clone next to the work tree cannot be read" $((rc == 0)) "$(first_line "$out")"
inside "cat '$parent/other/.git/config'"
verdict d2 "the .git/config of another repository (a token in its URL) cannot be read" $((rc == 0)) "$(first_line "$out" | cut -c1-60)"
inside 'ls -A .. | tr "\n" " "'
verdict d3 "the folder above the work tree shows the work tree only" "$([ "$out" = "repo " ]; echo $?)" "$(first_line "$out")"
inside 'ls / | tr "\n" " "'
way=${repo#/}; way=${way%%/*}; extra=$(for name in $out; do case $name in bin|dev|etc|lib*|proc|sbin|tmp|usr|"$way") ;; *) printf '%s ' "$name" ;; esac; done)
verdict d4 "the root holds only bin dev etc lib* proc sbin tmp usr and the way to the work tree" "$([ "$rc" -eq 0 ] && [ -z "$extra" ]; echo $?)" "also: $(first_line "$extra")"
if [ -r /etc/shadow ]; then
  inside '[ -s /etc/shadow ]'
  verdict d5 "/etc/shadow is empty inside" $((rc == 0)) "readable: $(run sh -c 'wc -l </etc/shadow' 2>&1) lines"
else
  skip d5 "/etc/shadow is empty inside" "the caller cannot read it either"
fi
inside 'pwd'
verdict d6 "the work tree is at the same path as on the host (paths in build outputs stay valid)" "$([ "$out" = "$repo" ]; echo $?)" "$(first_line "$out")"

# ---------------------------------------------------------------------------------------------------
echo "== e. no process survives the sandbox"
survivors() { sleep 0.5; alive bee-test-survivor | tr '\n' ' '; }
reap() { local p; for p in $(alive bee-test-survivor); do kill -KILL "$p" 2>/dev/null; done; }
run bash -c '(exec -a bee-test-survivor sleep 300) & disown; sleep 0.3' >/dev/null 2>&1
left=$(survivors); verdict e1 "a process left in the background is gone when the command ends" "$([ -z "$left" ]; echo $?)" "still running on the host: pid $left"; reap
(cd "$repo" && HOME=$home exec bee/sandbox/sans-docker.sh bash -c '(exec -a bee-test-survivor sleep 300) & wait') >/dev/null 2>&1 &
pid=$!; sleep 1.5; kill -TERM "$pid"; wait "$pid" 2>/dev/null; rc=$?
left=$(survivors); verdict e2 "SIGTERM to the launcher ends it (status $rc) and everything inside" "$([ -z "$left" ] && [ "$rc" -ne 0 ]; echo $?)" "still running on the host: pid $left"; reap
(cd "$repo" && HOME=$home exec bee/sandbox/sans-docker.sh bash -c '(exec -a bee-test-survivor sleep 300) & wait') >/dev/null 2>&1 &
pid=$!; sleep 1.5; kill -KILL "$pid"; wait "$pid" 2>/dev/null
left=$(survivors); verdict e3 "SIGKILL of the launcher ends everything inside" "$([ -z "$left" ]; echo $?)" "still running on the host: pid $left"; reap
inside 'ls /proc | grep -c "^[0-9]"'
verdict e4 "the command sees only its own processes (PID namespace)" "$([ "$out" -le 5 ] 2>/dev/null; echo $?)" "$out processes visible"
if [ "$out" -le 5 ] 2>/dev/null; then
  inside "python3 -c '
import ctypes, os, sys
libc = ctypes.CDLL(None, use_errno=True)
libc.ptrace.restype = ctypes.c_long
libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
if libc.ptrace(16, 1, None, None) == 0:      # PTRACE_ATTACH
    os.waitpid(1, 0x40000000); libc.ptrace(17, 1, None, None); print(\"ATTACHED\"); sys.exit(1)
print(\"refused:\", os.strerror(ctypes.get_errno()))'"
  verdict e5 "the command cannot trace process 1 of the sandbox (to disarm what kills it with the launcher)" "$([ "$rc" -eq 0 ] && grep -q "^refused" <<<"$out"; echo $?)" "$(first_line "$out")"
else
  skip e5 "the command cannot trace process 1 of the sandbox" "no PID namespace: process 1 is the machine's own, not tried"
fi

# ---------------------------------------------------------------------------------------------------
echo "== f. the exit status, the outputs and the arguments are the command's"
statuses=$(for s in 0 1 42 255; do run sh -c "exit $s" >/dev/null 2>&1; printf '%s ' $?; done)
verdict f1 "exit statuses 0, 1, 42, 255 come back" "$([ "$statuses" = "0 1 42 255 " ]; echo $?)" "$statuses"
run sh -c 'kill -SEGV $$' >/dev/null 2>&1; rc=$?
verdict f2 "a command killed by SIGSEGV gives 139 (128+11)" "$([ "$rc" -eq 139 ]; echo $?)" "$rc"
so=$(run sh -c 'echo to-stdout; echo to-stderr >&2' 2>"$top/stderr"); se=$(cat "$top/stderr")
verdict f3 "stdout and stderr pass through, apart and with nothing added" "$([ "$so" = to-stdout ] && [ "$se" = to-stderr ]; echo $?)" "stdout=[$so] stderr=[$se]"
got=$(run printf '[%s]\n' "a b" "c'd" 'e"f' '$HOME' '*' '' ' lead' 'tab	x' 'new
line' '--' '-n' 2>&1)
want=$(printf '[%s]\n' "a b" "c'd" 'e"f' '$HOME' '*' '' ' lead' 'tab	x' 'new
line' '--' '-n')
verdict f4 "arguments with spaces, quotes, \$, *, empty, tab, newline arrive unchanged" "$([ "$got" = "$want" ]; echo $?)" "$(first_line "$got")"
got=$(printf 'line 1\nline 2\n' | run cat 2>&1)
verdict f5 "stdin reaches the command" "$([ "$got" = "line 1
line 2" ]; echo $?)" "[$got]"
got=$(run grep SigIgn /proc/self/status 2>&1); want=$(grep SigIgn /proc/self/status)
verdict f6 "no signal is ignored inside that was not ignored outside" "$([ "$got" = "$want" ]; echo $?)" "inside: $got"
run sh -c 'exit 0' </dev/null >"$top/empty" 2>&1
verdict f7 "the launcher itself prints nothing" "$([ ! -s "$top/empty" ]; echo $?)" "$(head -c 200 "$top/empty")"

# ---------------------------------------------------------------------------------------------------
echo "== g. if a protection cannot be set up, the command is not run"
fixture
# "launching" is printed just before the launcher starts: without it, the simulation itself failed.
out=$(cd "$repo" && HOME=$home unshare -r bash -c 'echo 0 >/proc/sys/user/max_user_namespaces && echo launching && exec bee/sandbox/sans-docker.sh touch ran-without-namespaces' 2>&1); rc=$?
reason=$(grep -vx launching <<<"$out")
verdict g1 "user namespaces refused: no run, non-zero status ($rc), a reason on stderr" "$(grep -qx launching <<<"$out" && [ ! -e "$repo/ran-without-namespaces" ] && [ "$rc" -ne 0 ] && [ -n "$reason" ]; echo $?)" "rc $rc: $(first_line "$out")"
out=$(cd "$repo" && HOME=$home unshare -rm --propagation private bash -c 'mount -t tmpfs tmpfs /proc/bus && echo launching && exec bee/sandbox/sans-docker.sh touch ran-with-the-hosts-proc' 2>&1); rc=$?
reason=$(grep -vx launching <<<"$out")
verdict g2 "a private /proc cannot be mounted (masked /proc, as in a container): no run ($rc), a reason" "$(grep -qx launching <<<"$out" && [ ! -e "$repo/ran-with-the-hosts-proc" ] && [ "$rc" -ne 0 ] && [ -n "$reason" ]; echo $?)" "rc $rc, the command ran: $(ls "$repo" | grep ran- | tr '\n' ' ')"
mv "$repo/CLAUDE.md" "$repo/CLAUDE-real.md"; ln -s CLAUDE-real.md "$repo/CLAUDE.md"
inside 'touch ran-with-a-symlinked-guarded-path'
verdict g3 "a guarded path that is a symbolic link (cannot be protected): no run, a reason" "$([ ! -e "$repo/ran-with-a-symlinked-guarded-path" ] && [ "$rc" -ne 0 ] && [ -n "$out" ]; echo $?)" "rc $rc: $(first_line "$out")"
mv -T "$repo/CLAUDE-real.md" "$repo/CLAUDE.md"
mkdir -p "$home/bee/sandbox"; cp "$launcher" "$home/bee/sandbox/sans-docker.sh"; chmod +x "$home/bee/sandbox/sans-docker.sh"
out=$(cd "$home" && HOME=$home timeout -k 5 60 bee/sandbox/sans-docker.sh touch ran-with-the-home-as-work-tree 2>&1); rc=$?
verdict g4 "a launcher that sits in the home folder (the work tree would be the home): no run" "$([ ! -e "$home/ran-with-the-home-as-work-tree" ] && [ "$rc" -ne 0 ]; echo $?)" "rc $rc: $(first_line "$out")"
rm -rf "$home/bee"
out=$(cd "$home" && HOME=$home timeout -k 5 60 "$repo/bee/sandbox/sans-docker.sh" sh -c 'pwd; touch ran-from-elsewhere' 2>&1); rc=$?
verdict g5 "started from another folder, the work tree is still the launcher's own (and the command runs at its root)" "$([ "$rc" -eq 0 ] && [ "$out" = "$repo" ] && [ -e "$repo/ran-from-elsewhere" ] && [ ! -e "$home/ran-from-elsewhere" ]; echo $?)" "rc $rc: $(first_line "$out")"
# What the clone's own settings say changes nothing to it: git is not asked where the work tree is.
git -C "$repo" config core.worktree "$outside/dir"
inside "pwd; ls '$outside/dir' 2>&1; touch '$outside/dir/written-through-the-settings' 2>&1; true"
verdict g6 "a work tree named by the clone's settings (core.worktree) is neither entered nor shown" "$([ "$(head -n 1 <<<"$out")" = "$repo" ] && [ ! -e "$outside/dir/written-through-the-settings" ]; echo $?)" "$(first_line "$out"); $(ls "$outside/dir" | tr '\n' ' ')"
git -C "$repo" config --unset core.worktree
git -C "$repo" config core.repositoryformatversion 1
inside 'touch ran-in-another-format'
verdict g7 "a repository that is not in git's plain format (its settings say so, and are not shown): no run" "$([ ! -e "$repo/ran-in-another-format" ] && [ "$rc" -eq 125 ]; echo $?)" "rc $rc: $(first_line "$out")"
git -C "$repo" config core.repositoryformatversion 0
# What is shown of .git must be what it is.
mv "$repo/.git/HEAD" "$repo/.git/HEAD-real"; ln -s "$outside/target.txt" "$repo/.git/HEAD"
inside 'cat .git/HEAD; touch ran-with-a-linked-head'
verdict g8 "an entry of .git that is a symbolic link (it would show another file): no run" "$([ ! -e "$repo/ran-with-a-linked-head" ] && [ "$rc" -eq 125 ] && ! grep -q "outside the work tree" <<<"$out"; echo $?)" "rc $rc: $(first_line "$out")"
rm "$repo/.git/HEAD"; mv "$repo/.git/HEAD-real" "$repo/.git/HEAD"
for place in refs/planted objects/planted objects/pack/pack-planted.keep; do
  mkdir -p "$(dirname "$repo/.git/$place")"; ln "$outside/target.txt" "$repo/.git/$place"
  inside "cat .git/$place; touch ran-with-a-second-name"
  verdict g9 "a file of .git/${place%/*} that is a second name of a file elsewhere (a hard link): no run" "$([ ! -e "$repo/ran-with-a-second-name" ] && [ "$rc" -eq 125 ] && ! grep -q "outside the work tree" <<<"$out"; echo $?)" "rc $rc: $(first_line "$out")"
  rm "$repo/.git/$place"
done
printf 'PACK\0\0\0\2 a pack of another clone' >"$outside/shared.pack"; mkdir -p "$repo/.git/objects/pack"
ln "$outside/shared.pack" "$repo/.git/objects/pack/pack-shared.pack"
inside 'git rev-parse HEAD >/dev/null && touch ran-with-a-shared-pack'
verdict g10 "an object shared with another clone (a pack with a second name) is fine" "$([ -e "$repo/ran-with-a-shared-pack" ] && [ "$rc" -eq 0 ]; echo $?)" "rc $rc: $(first_line "$out")"
rm "$repo/.git/objects/pack/pack-shared.pack"
mv "$repo/.git" "$repo/.gitreal"; echo "gitdir: .gitreal" >"$repo/.git"
inside 'echo "# planted" >>.gitreal/config; touch ran-with-a-git-file'
verdict g11 "a .git that is a file pointing elsewhere (its real folder would stay writable): no run" "$([ ! -e "$repo/ran-with-a-git-file" ] && [ "$rc" -eq 125 ] && ! grep -q planted "$repo/.gitreal/config"; echo $?)" "rc $rc: $(first_line "$out")"
rm "$repo/.git"; mv "$repo/.gitreal" "$repo/.git"
mkdir "$repo/.git/objects/zz"; ln "$outside/target.txt" "$repo/.git/objects/zz/known-name"; chmod 111 "$repo/.git/objects/zz"
inside 'cat .git/objects/zz/known-name; touch ran-with-a-hidden-folder'
verdict g12 "a folder of .git that cannot be listed (it could hide a second name of a file elsewhere): no run" "$([ ! -e "$repo/ran-with-a-hidden-folder" ] && [ "$rc" -eq 125 ] && ! grep -q "outside the work tree" <<<"$out"; echo $?)" "rc $rc: $(first_line "$out")"
chmod 755 "$repo/.git/objects/zz"; rm -r "$repo/.git/objects/zz"
mv "$repo/.git/config" "$repo/.git/config-real"; mkfifo "$repo/.git/config"
inside 'touch ran-with-settings-that-are-a-pipe'
verdict g13 "settings of .git that are not a plain file (a pipe would make the launcher wait for ever): no run" "$([ ! -e "$repo/ran-with-settings-that-are-a-pipe" ] && [ "$rc" -eq 125 ]; echo $?)" "rc $rc: $(first_line "$out")"
rm "$repo/.git/config"; mv "$repo/.git/config-real" "$repo/.git/config"

# ---------------------------------------------------------------------------------------------------
echo "== h. symbolic links of the work tree that point outside give no write access"
before=$(digest "$outside"); before_sibling=$(digest "$parent/registre")
inside 'echo planted >>link-to-file; echo planted >link-to-dir/planted; echo planted >>link-to-sibling'
verdict h1 "through links to a file, a folder and the sibling clone: the host is unchanged" "$([ "$(digest "$outside")" = "$before" ] && [ "$(digest "$parent/registre")" = "$before_sibling" ]; echo $?)" "$(tail -n 1 "$outside/target.txt"); $(ls "$outside/dir" | tr '\n' ' ')"
if [ "$uid" -eq 0 ]; then
  echo "a file of /etc" >"/etc/$tag.target"; ln -s "/etc/$tag.target" "$repo/link-to-etc"
  inside 'echo planted >>link-to-etc'
  verdict h2 "through a link to a file of /etc: the host is unchanged" "$([ "$(cat "/etc/$tag.target")" = "a file of /etc" ]; echo $?)" "$(tail -n 1 "/etc/$tag.target")"
else
  skip h2 "through a link to a file of /etc" "not root: the kernel refuses anyway"
fi

# ---------------------------------------------------------------------------------------------------
echo "== x. other checks"
if command -v script >/dev/null; then
  cat >"$repo/inject.py" <<'EOF'
# Tries to push a character into the terminal's input queue (TIOCSTI): what a shell would then read.
import fcntl, os, termios
for name, opener in (("stdin", lambda: 0), ("/dev/tty", lambda: os.open("/dev/tty", os.O_RDWR))):
    try:
        fcntl.ioctl(opener(), termios.TIOCSTI, b"#")
        print("INJECTED through", name)
    except OSError as error:
        print("refused through", name, "-", error.strerror)
EOF
  out=$(cd "$repo" && HOME=$home script -qec "bee/sandbox/sans-docker.sh python3 inject.py" /dev/null 2>&1 </dev/null)
  verdict x1 "run from a terminal, the command cannot type into it (TIOCSTI)" "$(grep -q "refused through stdin" <<<"$out" && ! grep -q INJECTED <<<"$out"; echo $?)" "$(tr -d '\r' <<<"$out" | tr '\n' ';' | cut -c1-110)"
else
  skip x1 "run from a terminal, the command cannot type into it" "script(1) not installed"
fi
verdict x2 "the launcher leaves nothing in the host's /tmp" "$([ "$(echo /tmp/bee-sandbox.*)" = "$litter_before" ]; echo $?)" "$(($(echo /tmp/bee-sandbox.* | wc -w) - $(echo "$litter_before" | wc -w))) new empty folders /tmp/bee-sandbox.*"
mounts=$(findmnt -rno TARGET,OPTIONS | sha256sum)
inside 'true'
inside 'grep "Max core file size" /proc/self/limits | tr -s " "; ulimit -c unlimited 2>/dev/null; grep "Max core file size" /proc/self/limits | tr -s " "; sh -c "kill -SEGV \$\$"; ls core* 2>/dev/null; true'
verdict x4 "a crash inside leaves no core file: the limit is one byte and cannot be raised" "$([ "$(grep -c "^Max core file size 1 1 bytes" <<<"$out")" = 2 ] && [ -z "$(ls "$repo"/core* 2>/dev/null)" ]; echo $?)" "$(printf '%s' "$out" | tr '\n' ';' | cut -c1-110)"
out=$(cd "$repo" && HOME=$home python3 -I -c '
import socket, subprocess, sys
ours, theirs = socket.socketpair()   # a bash given a command reads a start-up file when its input is a network connection
done = subprocess.run(["bee/sandbox/sans-docker.sh", "true"], stdin=theirs, capture_output=True, timeout=120)
sys.stdout.write(f"{done.returncode}|{done.stdout.decode()}|{done.stderr.decode()}")' 2>&1); rc=$?
verdict x5 "started with a network connection as its input, the launcher reads no start-up file and adds nothing to the outputs" "$([ "$out" = "0||" ]; echo $?)" "$(first_line "$out")"
# The launcher itself runs on the host: it must take nothing from the work tree, whatever the caller's environment names.
mkdir -p "$repo/bin"
for tool in bash env realpath find unshare setpriv; do printf '#!/bin/sh\ntouch "%s/ran-on-the-host"\n' "$top" >"$repo/bin/$tool"; chmod +x "$repo/bin/$tool"; done
printf 'touch "%s/ran-on-the-host"\n' "$top" >"$repo/env.sh"
out=$(cd "$repo" && HOME=$home PATH="bin:$PATH" BASH_ENV=env.sh ENV=env.sh timeout -k 5 120 bee/sandbox/sans-docker.sh true 2>&1); rc=$?
verdict x6 "a program or a start-up file of the work tree that the caller's PATH or BASH_ENV names is not run on the host" "$([ ! -e "$top/ran-on-the-host" ] && [ "$rc" -eq 0 ]; echo $?)" "rc $rc: $(first_line "$out")"
rm -rf "$repo/bin" "$repo/env.sh" "$top/ran-on-the-host"
verdict x3 "the mounts of the host are unchanged by a run" "$([ "$(findmnt -rno TARGET,OPTIONS | sha256sum)" = "$mounts" ]; echo $?)" ""

echo
echo "result: $npass passed, $nfail failed, $nskip skipped"
[ "$nfail" -eq 0 ]
