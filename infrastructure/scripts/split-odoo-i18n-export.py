#!/usr/bin/env python3
"""Split an Odoo combined PO export into one catalogue per Dally module.

The Odoo 19 CLI can export several modules into one canonical PO.  This helper
keeps each entry byte-for-byte and assigns it from its ``#. module:`` reference;
it deliberately performs no translation.
"""

from __future__ import annotations

import argparse
from pathlib import Path


MODULES = (
    "dally_api",
    "dally_crm",
    "dally_freight",
    "dally_freight_billing",
    "dally_freight_bridge",
    "dally_freight_dashboard",
    "dally_freight_data",
    "dally_freight_notifications",
    "dally_freight_routing",
    "dally_portal",
    "dally_tracking",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="combined Odoo PO export")
    parser.add_argument("addons", type=Path, help="custom-addons directory")
    args = parser.parse_args()

    chunks = args.export.read_text(encoding="utf-8").split("\n\n")
    if len(chunks) < 2 or '\nmsgid ""\nmsgstr ""' not in chunks[0]:
        raise SystemExit("unexpected Odoo PO export header")

    _, _, metadata = chunks[0].partition('\nmsgid ""')
    metadata = 'msgid ""' + metadata
    entries = [entry for entry in chunks[1:] if entry.strip()]
    assigned = set()
    for module in MODULES:
        selected = [
            entry for entry in entries
            if module in set(__import__("re").findall(r"\bdally_[a-z_]+", entry))
        ]
        header = (
            "# Translation of Odoo Server.\n"
            "# This file contains the translation of the following module:\n"
            f"#\t* {module}\n"
            "#\n\n"
            f"{metadata}\n"
        )
        destination = args.addons / module / "i18n" / "fr.po"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(header + "\n".join(f"\n{entry}\n" for entry in selected), encoding="utf-8")
        print(f"{module}\t{len(selected)}\t{destination}")
        assigned.update(
            index for index, entry in enumerate(entries)
            if module in set(__import__("re").findall(r"\bdally_[a-z_]+", entry))
        )

    if len(assigned) != len(entries):
        raise SystemExit(f"unassigned entries: expected {len(entries)}, assigned {len(assigned)}")


if __name__ == "__main__":
    main()
