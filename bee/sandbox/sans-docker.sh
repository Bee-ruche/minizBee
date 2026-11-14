#!/bin/bash -p
# Bee sandbox without Docker, for Linux (disposable cloud session, VM, workstation). It runs a command
# of the project at the root of the work tree (this git clone) and keeps it away from everything else:
#   - no network (empty network namespace), none of your environment variables (no token, no proxy);
#   - one writable place that lasts, the work tree, EXCEPT the paths of `guarded` below (.git, the
#     agent instructions, the CI, this folder): read-only inside, so that the command cannot plant a
#     hook, a config or an instruction for what you run next, outside;
#   - of .git, only HEAD, the refs, the objects and the index, read-only. Its settings, its logs, its
#     hooks and the rest are not shown (what a command reads, it can copy into the work tree, which
#     you push);
#   - an empty /tmp and an empty home (/tmp/home), private, gone when the command ends;
#   - /usr, /bin, /sbin, /lib*, /etc read-only (in /etc, without what only root or a group may read);
#     /dev reduced to null, zero, full, random, urandom and an empty /dev/shm; a /proc of its own
#     processes only, read-only;
#   - nothing else of the machine exists inside: your home, the folders next to the work tree, /var,
#     /run and its sockets, /sys, the disks, the terminal, the other processes, open descriptors > 2;
#   - no survivor: its processes live in a PID namespace of their own, killed when the command ends or
#     when this script is killed.
# If one protection cannot be set up, the command is NOT run: exit status 125 and the reason on stderr.
# Otherwise stdin, stdout, stderr and the exit status are the command's (128+N if signal N killed it).
# A guarded path that does not exist cannot be made read-only: if the command creates it, it is renamed
# <path>.created-in-sandbox.XXXXXX when the command ends (status 125 if that fails).
#
# Usage: bee/sandbox/sans-docker.sh <command> [arguments…]
#   e.g. bee/sandbox/sans-docker.sh make -C bee differentiel
#        bee/sandbox/sans-docker.sh bash          (a session: no job control, Ctrl-C ends it)
#
# The work tree is the folder this launcher sits in (<work tree>/bee/sandbox/): git is not asked.
# Needs bash, util-linux 2.33 or later, coreutils 8.31 or later, findutils, and user namespaces
# (unshare --user).
# It is not a virtual machine: what it does and does not guarantee is in bee/README.md ("Sandbox").
# This script itself runs on your machine, outside the sandbox, and takes nothing from the work tree nor
# from the caller's settings: bash is named by its path and started with -p (it reads no file named by
# BASH_ENV and no function of the environment), and the tools are found in the system's own folders.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

# Paths of the work tree that the command can read but neither change nor create.
guarded=(.git .github .claude .mcp.json AGENTS.md CLAUDE.md bee/sandbox)

refuse() { echo "bee-sandbox: $*: the command was NOT run." >&2; exit 125; }

# Makes the mount at $1 and the mounts below it read-only. The flags the kernel has locked (nosuid,
# nodev, noexec) are given again: mount(2) refuses a remount that would drop them.
readonly_tree() {
  local target options
  findmnt -Rrno TARGET,VFS-OPTIONS -M "$1" | while read -r target options; do
    mount -o "remount,bind,${options/#rw/ro}" "$(printf %b "$target")" || exit
  done
}

# Runs as process 1 of the new namespaces, as root of the user namespace: builds the view, then runs
# the command as a child without any privilege and waits for it. Arguments: work tree, empty folder
# for the new root, guarded paths, command.
inside() {
  set -Eeuo pipefail
  trap 'refuse "a protection could not be set up ($BASH_COMMAND)"' ERR
  PATH=/usr/sbin:/usr/bin:/sbin:/bin
  local repo=$1 new=$2 guarded=$3 d rest mode drop; shift 3
  for d in mount umount findmnt pivot_root setsid setpriv prlimit stat readlink; do
    type -P "$d" >/dev/null || refuse "$d not found (util-linux, coreutils)"
  done
  env --default-signal=INT true   # coreutils 8.31

  # The new root is an empty tmpfs: nothing of the machine is inside unless it is bound below.
  mount -t tmpfs -o mode=755,nosuid,nodev tmpfs "$new"
  for d in /usr /bin /sbin /lib /lib32 /lib64 /libx32 /etc; do
    if [ -L "$d" ]; then ln -s "$(readlink "$d")" "$new$d"      # merged /usr: /bin -> usr/bin
    elif [ -d "$d" ]; then mkdir "$new$d"; mount --rbind "$d" "$new$d"; readonly_tree "$new$d"; fi
  done
  # In /etc, what "others" cannot read (shadow, private keys…) is hidden: when the session is root, the
  # user namespace would otherwise read it. A file becomes empty, a folder becomes empty.
  shopt -s globstar dotglob nullglob
  { stat -c "%A %n" /etc/** 2>/dev/null || true; } | while read -r mode d; do
    if [[ $mode == ???????r* || ! -e $new$d ]]; then continue; fi
    if [ -d "$new$d" ]; then mount -t tmpfs -o ro,mode=555 tmpfs "$new$d" || exit
    else mount --bind /dev/null "$new$d" || exit; fi
  done

  # A /proc of the new PID namespace, read-only (as root, /proc/sys would otherwise be writable); a
  # /dev without disks or terminal; an empty /tmp, which holds the empty home.
  mkdir "$new/proc" "$new/dev" "$new/tmp"
  mount -t proc -o ro,nosuid,nodev,noexec proc "$new/proc"
  for d in null zero full random urandom; do : >"$new/dev/$d"; mount --bind "/dev/$d" "$new/dev/$d"; done
  ln -s /proc/self/fd "$new/dev/fd"
  ln -s fd/0 "$new/dev/stdin"; ln -s fd/1 "$new/dev/stdout"; ln -s fd/2 "$new/dev/stderr"
  mkdir "$new/dev/shm"; mount -t tmpfs -o mode=1777,nosuid,nodev tmpfs "$new/dev/shm"
  mount -t tmpfs -o mode=1777,nosuid,nodev tmpfs "$new/tmp"; mkdir "$new/tmp/home"

  # The work tree, writable, at its own path: the folders above it are empty, the ones next to it are
  # not there. Each guarded path is bound over itself read-only; the folders above it, inside the
  # tree, are bound over themselves too, because a mount point can be neither renamed nor removed.
  mkdir -p "$new$repo"; mount --bind "$repo" "$new$repo"
  for rest in $guarded; do
    if [ ! -e "$repo/$rest" ]; then continue; fi
    d=$new$repo
    while [[ $rest == */* ]]; do d=$d/${rest%%/*}; rest=${rest#*/}; mount --bind "$d" "$d"; done
    mount --bind "$d/$rest" "$d/$rest"; readonly_tree "$d/$rest"
  done

  # Of .git, the command sees the history and nothing else: over the read-only .git, an empty folder
  # that holds the objects, the refs, HEAD and the index, read-only, and empty settings.
  if [ -d "$repo/.git" ]; then
    # (A repository whose format is not the plain one says so in its settings, which are not shown.)
    if [ -e "$repo/.git/config" ] || [ -L "$repo/.git/config" ]; then
      [ -f "$repo/.git/config" ] && [ ! -L "$repo/.git/config" ] || refuse ".git/config is not a plain file"
    fi
    if type -P git >/dev/null && [ -f "$repo/.git/config" ]; then
      d=$(git config --file "$repo/.git/config" --get core.repositoryformatversion 2>/dev/null) || d=0
      [ "${d:-0}" = 0 ] || refuse "this repository is not in git's plain format, which this sandbox cannot show"
    fi
    d=$new$repo/.git
    mount -t tmpfs -o mode=755,nosuid,nodev tmpfs "$d"
    for rest in HEAD refs packed-refs objects shallow index; do
      [ ! -L "$repo/.git/$rest" ] || refuse ".git/$rest is a symbolic link, which cannot be shown read-only"
      if [ -d "$repo/.git/$rest" ]; then mkdir "$d/$rest"
      elif [ -f "$repo/.git/$rest" ]; then : >"$d/$rest"
      else continue; fi
      mount --bind "$repo/.git/$rest" "$d/$rest"; readonly_tree "$d/$rest"
    done
    : >"$d/config"
    mount -o remount,bind,ro,nosuid,nodev "$d"
  fi

  # Enter the view, drop the machine's own tree, and check the result before trusting it.
  mount -o remount,bind,ro,nosuid,nodev "$new"
  cd "$new"; pivot_root . .; umount -l .; cd "$repo"
  for d in / /usr /etc /proc/sys $guarded; do
    [ ! -w "$d" ] || refuse "$d is writable inside the sandbox"
  done
  [ -w . ] && [ -w /tmp/home ] || refuse "the work tree or /tmp is not writable inside the sandbox"

  # The command gets: no descriptor but 0, 1, 2; no variable but the four below; no controlling
  # terminal (setsid); no core file when it crashes (prlimit: a limit of one byte, which it cannot
  # raise); no capability, in particular over these mounts, and none to regain (setpriv).
  # This shell stays process 1 and keeps its own: the command cannot trace it, nor outlive it.
  for d in /proc/self/fd/*; do d=${d##*/}; [ "$d" -le 2 ] || eval "exec $d>&-"; done
  drop=(env -i --default-signal=INT,QUIT PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp/home LANG=C.UTF-8
    "TERM=${TERM:-dumb}" setsid prlimit --core=1:1 --
    setpriv --bounding-set -all --inh-caps -all --ambient-caps -all --no-new-privs)
  trap - ERR
  "${drop[@]}" "$@" || exit
  exit 0
}

[ $# -ge 1 ] || { echo "usage: $0 <command> [arguments…]" >&2; exit 2; }
# The work tree is where this launcher is, not what git would answer: git's answer depends on settings
# the clone itself holds.
here=$(realpath -- "${BASH_SOURCE[0]}")
[[ $here == /?*/bee/sandbox/* ]] || refuse "this launcher is not in <work tree>/bee/sandbox/"
repo=${here%/bee/sandbox/*}
[[ $repo != "${HOME:-}" ]] || refuse "the work tree ($repo) is your home"
created=()
for path in "${guarded[@]}"; do
  [ ! -L "$repo/$path" ] || refuse "$path is a symbolic link, which cannot be made read-only"
  [ -e "$repo/$path" ] || created+=("$path")
done
# What is shown of .git must be what it is. A .git that is a file points elsewhere (a linked work tree,
# a submodule): refused. A file under an entry shown that has a second name elsewhere (a hard link)
# would show that other file: refused, unless it is one of git's own stored objects, which a clone
# made from a folder shares with it (a pack, its indexes, a deflated object: told by how it begins).
if [ -e "$repo/.git" ]; then
  [ -d "$repo/.git" ] || refuse ".git is a file that points elsewhere (a linked work tree, a submodule), which this sandbox cannot show"
  type -P find od >/dev/null || refuse "find or od not found (findutils, coreutils)"
  shown=()
  for path in HEAD refs packed-refs objects shallow index; do
    [ ! -e "$repo/.git/$path" ] || shown+=("./$path")
  done
  if [ ${#shown[@]} -gt 0 ]; then
    # Every folder under them must be one this check can list: what it cannot list, it cannot vouch for.
    hidden=$(cd "$repo/.git" && find "${shown[@]}" \( ! -readable -o -type d ! -executable \) -print -quit 2>&1) || hidden=unreadable
    [ -z "$hidden" ] || refuse "a file or a folder of .git cannot be read (clone the repository again)"
    while IFS= read -r -d '' path; do
      start=
      [[ $path != ./objects/* ]] || start=$(head -c 4 -- "$repo/.git/$path" | od -An -tx1 | tr -d ' \n')
      case $start in
        5041434b|52494458|ff744f63|7801*|785e*|789c*|78da*) ;;
        *) refuse "a file of .git has a second name elsewhere and is not one of git's objects (clone the repository again)" ;;
      esac
    done < <(cd "$repo/.git" && find "${shown[@]}" -type f -links +1 -print0)
  fi
fi
for new in /tmp /var/tmp /mnt ""; do   # an existing folder that is not above the work tree
  if [ -d "$new" ] && [[ $repo/ != "$new"/* ]]; then break; fi
done
[ -n "$new" ] || refuse "no folder to build the view on"
spaces=(unshare --user --map-root-user --mount --net --pid --ipc --fork --kill-child --propagation private)
"${spaces[@]}" true 2>/dev/null || refuse "user namespaces are refused on this machine: use Docker (bee/README.md)"

# The sandbox is a child of this script, so that a signal sent to the script ends it: unshare itself
# defers SIGTERM and SIGINT. Killing process 1 of the PID namespace kills every process inside, and
# unshare then returns; if this script is killed outright, --pdeathsig and --kill-child do the same.
child=
trap 'kid=$(cat "/proc/$child/task/$child/children" 2>/dev/null) || kid=; kill -KILL ${kid:-$child} 2>/dev/null || true' HUP INT QUIT TERM
# (--norc: a bash given a command reads a start-up file of the home when its input is a network connection.)
setpriv --pdeathsig KILL "${spaces[@]}" -- env -i TERM="${TERM:-dumb}" bash --norc --noprofile -c \
  "$(declare -f refuse readonly_tree inside); inside \"\$@\"" bee-sandbox "$repo" "$new" "${guarded[*]}" "$@" <&0 &
child=$!
wait "$child" && status=0 || status=$?
wait "$child" 2>/dev/null || true   # a trapped signal interrupts the first wait: collect the sandbox

# A guarded path that did not exist cannot be covered by a mount: if the command created it, it is
# renamed, in place and under a name drawn now, when nothing of the sandbox runs any more.
for path in ${created[@]+"${created[@]}"}; do
  if [ ! -e "$repo/$path" ] && [ ! -L "$repo/$path" ]; then continue; fi
  aside=$(mktemp -u "$repo/$path.created-in-sandbox.XXXXXX")
  chmod u+rwx -- "$(dirname "$repo/$path")" 2>/dev/null || true
  mv -T -- "$repo/$path" "$aside" 2>/dev/null || true
  if [ -e "$repo/$path" ] || [ -L "$repo/$path" ]; then
    echo "bee-sandbox: the command created $path and it could NOT be set aside: remove it before anything else." >&2
    status=125
  else
    echo "bee-sandbox: the command created $path: set aside as ${aside#"$repo/"}, do not trust it." >&2
  fi
done
exit "$status"
