# Message Center and Planner

[Back to the docs](README.md)

`ldo news` reads the Microsoft 365 Message Center: the posts announcing what changes in the
tenant's services, and by when. `ldo planner` reads Planner, and raises a task for each post
a plan does not have one for yet, so a team can work through them on a board.

```bash
ldo news messages --since 7d                       # the posts changed this week
ldo news messages --security                       # only Defender, Sentinel, Purview, Entra, Intune
ldo news messages --service xdr --date today       # a service by part of its name, and one day
ldo news messages --date 2026-09-01..2026-09-14 --major
ldo news message MC1183010                         # one post, and all it says, as Markdown
ldo news message MC1183010 --markdown > MC1183010.md
ldo planner plans                                  # your plans
ldo planner buckets "SOC changes"                  # a plan's buckets: the columns of its board
ldo planner tasks "SOC changes" --open             # its tasks not complete
ldo planner add-news "SOC changes" --bucket "To be discussed" --security            # what it would raise
ldo planner add-news "SOC changes" --bucket "To be discussed" --security --write    # raises them
```

## Signing in

Message Center needs `ServiceMessage.Read.All`, and raising tasks `Tasks.ReadWrite`, which
the Azure CLI's token has neither of. Add them to [your own app
registration](authentication.md#your-own-app-registration), and pass its profile with `-p`.
Reading plans and tasks works with the Azure CLI's sign-in too (its `Group.ReadWrite.All`
covers group plans). Planner needs a licence that includes it: without one, Graph answers
that the tenant has it disabled. Graph covers basic plans, not premium ones.

## Choosing posts

Every `news` command and `planner add-news` take the same filters:

| Option | Keeps the posts |
| --- | --- |
| `--date` | changed then: `today`, `29/09/2026`, `2026-09-01..2026-09-14`, `last 7d`, or a length of time such as `7d`. Days are read as [`--where`](configuration.md#options-every-command-takes) reads them |
| `--since` | changed in that length of time, e.g. `7d`, `36h` (the default: 30 days for `news`, 7 for `add-news`) |
| `--service` | for a service whose name holds this, ignoring case: `xdr` is Microsoft Defender XDR. Repeatable |
| `--security` | for the security services: Microsoft Defender (every product), Sentinel, Purview, Entra and Intune |
| `--category` | in one of Message Center's categories: plan for change, stay informed, or prevent or fix issue |
| `--major` | that are major changes |

## Raising tasks

`planner add-news PLAN --bucket NAME` looks at every task in the plan, in any bucket and done
or not, for one whose title starts with the post's id: a post has a task already when one
does. Each one it raises is titled `MC1183010:` and the post's title, in that bucket, with
the post's link in the admin centre and its text as the description. Without `--write` it
only says which it would raise, and exits 3 when there are any; run it weekly, look, then
run it again with `--write`. Raising a task is the one change `ldo` makes to a tenant, and
only then.
