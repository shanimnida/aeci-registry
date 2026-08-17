from pathlib import Path

from django.core.management.base import BaseCommand

from imports.spreadsheet import write_blank_template_bytes


class Command(BaseCommand):
    help = (
        "Write a blank .xlsx member profiling import template -- the same file the "
        "'Download the blank template' link on the upload screen serves. Give this to the AI "
        "(as CSV; see docs/IMPORT_TEMPLATE.md) or fill it in by hand, so the layout matches "
        "exactly what AEGIS expects rather than something invented on the spot."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default="member_profiling_import_template.xlsx",
            help="Where to write the template (default: ./member_profiling_import_template.xlsx).",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        path.write_bytes(write_blank_template_bytes())
        self.stdout.write(self.style.SUCCESS(f"Wrote blank import template to {path}."))
