# Sourced by the sh test suites. The same suites run in two layouts:
#   kit layout       <kit>/tests, <kit>/scripts, <kit>/githooks, <kit>/handoff     (this repository)
#   installed layout <project>/scripts/agentic-ops/tests, scripts and handoff checks flat in scripts/agentic-ops,
#                    git hooks in <project>/.githooks                              (what kit/install.* produces)
# Sets: KIT (parent of tests/), SC (folder with the scripts), HO (folder with handoff-check), GH (folder with the git hooks),
#       HK (folder with the Claude Code hooks: <kit>/claude/hooks, or <project>/.claude/hooks), LAYOUT.
_here=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)
KIT=$(cd "$_here/.." && pwd)
if [ -d "$KIT/scripts" ] && [ -d "$KIT/githooks" ]; then
  SC=$KIT/scripts; HO=$KIT/handoff; GH=$KIT/githooks; HK=$KIT/claude/hooks; LAYOUT=kit
else
  SC=$KIT; HO=$KIT; GH=$(cd "$KIT/../.." && pwd)/.githooks; HK=$(cd "$KIT/../.." && pwd)/.claude/hooks; LAYOUT=installed
fi
