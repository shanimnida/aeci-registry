"""A static check across every template in the project.

Django's `{# ... #}` comment is SINGLE-LINE ONLY. A multi-line one is not
recognised as a comment token at all: it renders as literal text on the
page, or -- if it happens to contain a tag -- is parsed as real template
syntax. This has now happened twice. The first time it leaked explanatory
prose onto the Celebrations page and the admin dashboard; the second time
onto every row of a committee roster, where the church found it before any
test did, because the guard written the first time only checked the two
pages that had already broken.

So this checks the SOURCE rather than a rendered page. A per-page test
proves only that today's pages are clean; this one cannot be outgrown by
adding a template, which is exactly how the second instance got in.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = ("site-packages", "staticfiles", "node_modules", ".venv")


def project_templates():
    for path in REPO_ROOT.rglob("*.html"):
        if any(part in str(path) for part in SKIP):
            continue
        yield path


def test_there_are_templates_to_check():
    """A guard on the guard: a glob that silently matches nothing would
    make every assertion below vacuously true."""
    assert len(list(project_templates())) > 5


@pytest.mark.parametrize(
    "template", sorted(project_templates()), ids=lambda p: p.name
)
def test_no_multi_line_django_comment(template):
    offenders = []
    for number, line in enumerate(
        template.read_text(encoding="utf-8").splitlines(), 1
    ):
        if "{#" in line and "#}" not in line.split("{#", 1)[1]:
            offenders.append(f"line {number}: {line.strip()[:60]}")

    assert not offenders, (
        f"{template.relative_to(REPO_ROOT)} opens a {{# #}} comment that does "
        f"not close on the same line: {offenders}. Django only recognises "
        "single-line {# #}; use {% comment %} ... {% endcomment %} instead, "
        "or this text renders onto the page."
    )
