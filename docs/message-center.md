# Message Center and Planner

[Back to the docs](README.md)

`ldo news` reads the Microsoft 365 Message Center: the posts announcing what changes in the
tenant's services, and by when. `ldo planner` reads Planner, and raises a task for each post
a plan does not have one for yet, so a team can work through them on a board, or one task a
month summing up that month's posts.

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
ldo planner add-rollup "SOC changes" --bucket "To be discussed"            # this month's summary
ldo planner add-rollup "SOC changes" --bucket "To be discussed" --write    # raises or updates it
ldo planner add-rollup "SOC changes" --bucket "To be discussed" --date 2026-06-01..2026-08-31
```

## Signing in

Message Center needs `ServiceMessage.Read.All`, and raising tasks `Tasks.ReadWrite`, which
the Azure CLI's token has neither of. Add them to [your own app
registration](authentication.md#your-own-app-registration), and pass its profile with `-p`.
Reading plans and tasks works with the Azure CLI's sign-in too (its `Group.ReadWrite.All`
covers group plans). Planner needs a licence that includes it: without one, Graph answers
that the tenant has it disabled. Graph covers basic plans, not premium ones.

## Choosing posts

Every `news` command, `planner add-news` and `planner add-rollup` take the same filters:

| Option | Keeps the posts |
| --- | --- |
| `--date` | changed then: `today`, `29/09/2026`, `2026-09-01..2026-09-14`, `last 7d`, or a length of time such as `7d`. Days are read as [`--where`](configuration.md#options-every-command-takes) reads them |
| `--since` | changed in that length of time, e.g. `7d`, `36h` (the default: 30 days for `news`, 7 for `add-news` and `add-rollup`) |
| `--service` | for a service whose name holds this, ignoring case: `xdr` is Microsoft Defender XDR. Repeatable |
| `--security` | for the security services: Microsoft Defender (every product), Sentinel, Purview, Entra and Intune |
| `--category` | in one of Message Center's categories: plan for change, stay informed, or prevent or fix issue |
| `--major` | that are major changes |

## Raising tasks

`planner add-news PLAN --bucket NAME` looks at every task in the plan, in any bucket and done
or not, for one whose title holds the post's id in square brackets
(`[Microsoft Teams] ... [MC1183010]`, as Microsoft's own Message Center sync to Planner
titles them) or starts with it (`MC1183010: ...`): a post has a task already when one does,
so a board that sync fills, or that tasks were moved to from one, gets no second task for a
post. Without `--write` it only says which it would raise, and exits 3 when there are any;
run it weekly, look, then run it again with `--write`.

Each task it raises goes in that bucket, laid out as Microsoft's sync lays them out, so the
two look alike on a board:

```text
[Microsoft Defender XDR] Microsoft Defender for Endpoint: a new setting [MC1183010]

Message ID: MC1183010
Published date: 9/21/2026
Category: Stay informed
Tags: Admin impact, Feature update

https://admin.microsoft.com/#/MessageCenter/:/messages/MC1183010

The post's text, as Markdown.
```

The date is the day the post was published, month first as the sync writes it. A title
longer than Planner takes (255 characters) loses the end of the post's title, never its id.
`--layout short` titles a task `MC1183010:` and the post's title instead, with the link and
the text as its notes. Planner's labels and checklists are left as they are, for the team to
set.

## Monthly rollups

`planner add-rollup PLAN --bucket NAME` sums up each month's posts in one task, titled
`Message Center rollup: 2026-09 (12 messages)`. Its description counts the month's posts by
severity, service and category, then lists them one a line, newest change first:

```text
# Message Center summary (2026-09)

Total: 12 messages (0 critical, 1 high, 11 normal)

## By service
- Microsoft Teams: 5
...

## Messages
- MC1183010 2026-09-26 [Microsoft Teams] Microsoft Teams: ...
```

A month's rollup holds every post last changed in that month, the whole month and not only
the days asked for: the dates only choose the months, the last 7 days' by default, so a
weekly run keeps this month's rollup up to date and, in a month's first week, finishes last
month's. A month with a rollup already (a task in the plan, in any bucket and done or not,
whose title starts `Message Center rollup:` and the month) has it brought up to date rather
than raised again, its progress left as it is; one that says the same already is left alone.
A post changed again in a later month is in that month's rollup too, and one Microsoft has
since taken out of Message Center is in none: either way, a line a rollup had for it before
is kept, under `## Listed before`, so bringing a rollup up to date loses nothing it listed.
Without `--write` it only says which it would raise or update, and exits 3 when there are
any.

Raising and updating these tasks are the only changes `ldo` makes to a tenant, and only with
`--write`.
