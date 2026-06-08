# Refreshing the quickapps-code-review checklist

Procedure for refreshing the `SKILL.md` checklist from recent review comments. Invoked from `SKILL.md` when its staleness check exceeds the threshold.

## How to refresh

1. Find merged PRs since the last refresh:
   ```bash
   gh pr list --repo $(gh repo view --json nameWithOwner -q .nameWithOwner) --state merged \
     --search "merged:>$(date -v-7d +%Y-%m-%d)" --limit 100 \
     --json number --jq '.[].number'
   ```
2. For each PR, pull inline review comments and review bodies:
   ```bash
   gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/pulls/<num>/comments --paginate \
     -q '.[] | {pr: <num>, path, body, user: .user.login}'
   gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/pulls/<num>/reviews --paginate \
     -q '.[] | select(.body != null and .body != "") | {pr: <num>, body, user: .user.login}'
   ```
   Skip bot accounts and PR-author self-comments.
3. Cluster substantive comments (drop pure "LGTM"/approval). For each cluster:
   - Does the pattern already exist in the checklist? Refine wording or add a missing sub-bullet.
   - If not, add a new numbered section (or fold it into the closest existing one).
4. Delete or downgrade rules that the last ~4 weeks of reviews show are no longer enforced (drift goes both ways).
5. Commit the change. The "last refreshed" date is derived from this commit's date — don't maintain it inline.

Keep the refresh PR small and self-contained — the same scope discipline rule (§2 in SKILL.md) applies to this file too.
