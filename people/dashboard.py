"""The Celebrations panel on the admin landing page.

Wired in as `UNFOLD["DASHBOARD_CALLBACK"]`, which Unfold calls with the
index page's context for every user who opens the admin. The full report
lives at PersonAdmin.celebrations_view; this is the seven-day version, so
the Secretary sees the week's greetings on login without having to
remember to go and look.

**It reuses the same access gate as the full page.** Populating this for
everyone would hand the Board and Treasurer a report spec 7.7 withholds
from them, and would do it on the one screen every user lands on -- the
403 on the full page would then be decoration.

**It deliberately writes no AccessLog entry**, unlike the full report.
This callback runs on every single load of the admin index, so logging it
would put a row in the audit log every time a Secretariat user opens
AEGIS at all. Spec 7.6's rule against logging one entry per row exists
because "logging every row would bury the signal the log exists to
provide" -- an entry per index load buries it exactly the same way, and
this panel shows the least sensitive data in the system: a name someone
goes by, and a day and month that D17 already judged safe to show. The
full Celebrations page, which is where anyone actually works from this
data, is logged.
"""

from people.celebrations import (
    DASHBOARD_WINDOW_DAYS,
    may_view_celebrations,
    upcoming_anniversaries,
    upcoming_birthdays,
)


def dashboard_callback(request, context):
    context["celebrations_visible"] = may_view_celebrations(request.user)
    if not context["celebrations_visible"]:
        return context

    context["celebrations_days"] = DASHBOARD_WINDOW_DAYS
    context["celebrations_birthdays"] = upcoming_birthdays(days=DASHBOARD_WINDOW_DAYS)
    context["celebrations_anniversaries"] = upcoming_anniversaries(
        days=DASHBOARD_WINDOW_DAYS
    )
    return context
