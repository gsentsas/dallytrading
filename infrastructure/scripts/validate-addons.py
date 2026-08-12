#!/usr/bin/env python3
"""Static consistency checks for the DallyTrading Odoo modules.

Catches, without a running Odoo, the mistakes that otherwise only surface as a
failed module installation:

* a data file listed in a manifest but absent from disk (and the reverse)
* a view referencing a ``dally_*`` field that no model defines
* an ACL pointing at a model that does not exist
* an ``ir.model.access.csv`` referencing an unknown group
* a ``ref="..."`` to an external id defined in none of our modules
* a module whose ``__init__.py`` does not import a sibling model file

Native Odoo external ids and fields cannot be verified here — that requires the
real registry. They are reported as informational only.

Usage:
    python3 infrastructure/scripts/validate-addons.py [addons_dir]

Exit code 1 if any error is found, so it can gate a CI pipeline.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ERRORS: list[str] = []
WARNINGS: list[str] = []
INFO: list[str] = []

#: Odoo field-defining calls we recognise.
FIELD_CALL_RE = re.compile(r"^fields\.")

#: Fields Odoo adds to every model. A view may legitimately use them even though
#: no model file declares them.
MAGIC_FIELDS = {
    "id", "display_name", "create_date", "create_uid", "write_date", "write_uid",
    "__last_update", "active", "sequence",
}


def error(message: str) -> None:
    ERRORS.append(message)


def warn(message: str) -> None:
    WARNINGS.append(message)


def info(message: str) -> None:
    INFO.append(message)


# ─── Model parsing ────────────────────────────────────────────────────


def parse_models(addons: pathlib.Path) -> tuple[dict, dict, set]:
    """Return (fields_by_model, module_by_model, all_defined_models)."""
    fields_by_model: dict[str, set[str]] = {}
    module_by_model: dict[str, str] = {}
    owned_models: set[str] = set()

    for py_file in sorted(addons.rglob("models/*.py")):
        module = py_file.relative_to(addons).parts[0]
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            model_name = None
            inherits: list[str] = []
            is_own_model = False
            field_names: set[str] = set()

            for stmt in node.body:
                # _name = "..." / _inherit = "..." or [...]
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target = stmt.targets[0]
                    if not isinstance(target, ast.Name):
                        continue

                    if target.id == "_name" and isinstance(stmt.value, ast.Constant):
                        model_name = stmt.value.value
                        is_own_model = True
                    elif target.id == "_inherit":
                        if isinstance(stmt.value, ast.Constant):
                            inherits = [stmt.value.value]
                        elif isinstance(stmt.value, (ast.List, ast.Tuple)):
                            inherits = [
                                elt.value for elt in stmt.value.elts
                                if isinstance(elt, ast.Constant)
                            ]
                    # field = fields.Something(...)
                    elif isinstance(stmt.value, ast.Call):
                        func = stmt.value.func
                        source = ast.unparse(func) if hasattr(ast, "unparse") else ""
                        if FIELD_CALL_RE.match(source):
                            field_names.add(target.id)

            effective = model_name or (inherits[0] if inherits else None)
            if not effective:
                continue

            fields_by_model.setdefault(effective, set()).update(field_names)
            module_by_model.setdefault(effective, module)
            if is_own_model:
                owned_models.add(effective)

    return fields_by_model, module_by_model, owned_models


# ─── External ids ─────────────────────────────────────────────────────


def collect_external_ids(addons: pathlib.Path) -> set[str]:
    """Every external id our modules define, as module.xml_id."""
    ids: set[str] = set()

    for xml_file in sorted(addons.rglob("*.xml")):
        module = xml_file.relative_to(addons).parts[0]
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue  # reported by the XML syntax stage
        for element in root.iter():
            if element.tag in ("record", "menuitem", "template", "act_window"):
                rid = element.get("id")
                if rid:
                    ids.add(rid if "." in rid else f"{module}.{rid}")

    # Groups and models declared via CSV get ids too.
    for csv_file in sorted(addons.rglob("security/*.csv")):
        module = csv_file.relative_to(addons).parts[0]
        for line in csv_file.read_text(encoding="utf-8").splitlines()[1:]:
            if line.strip():
                ids.add(f"{module}.{line.split(',')[0]}")

    return ids


def check_refs(addons: pathlib.Path, known_ids: set[str]) -> None:
    """Every ref= must resolve to one of our ids, or be native."""
    for xml_file in sorted(addons.rglob("*.xml")):
        module = xml_file.relative_to(addons).parts[0]
        rel = xml_file.relative_to(addons)
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue

        referenced: set[str] = set()
        for element in root.iter():
            for attribute in ("ref", "parent", "action", "inherit_id"):
                value = element.get(attribute)
                if value:
                    referenced.add(value)
            # eval="[(4, ref('...'))]" and groups="a.b,c.d"
            for attribute in ("eval", "groups"):
                value = element.get(attribute) or ""
                referenced.update(re.findall(r"ref\(['\"]([^'\"]+)['\"]\)", value))
                if attribute == "groups":
                    referenced.update(
                        part.strip().lstrip("!")
                        for part in value.split(",")
                        if "." in part
                    )

        for ref in sorted(referenced):
            qualified = ref if "." in ref else f"{module}.{ref}"
            if qualified in known_ids:
                continue
            our_modules = {p.name for p in addons.iterdir() if p.is_dir()}
            if qualified.split(".")[0] in our_modules:
                error(f"{rel}: ref '{ref}' is not defined by any of our modules")
            else:
                info(f"{rel}: ref '{ref}' is native — verify at install time")


# ─── Views ────────────────────────────────────────────────────────────


def check_view_fields(addons: pathlib.Path, fields_by_model: dict,
                      owned_models: set) -> None:
    """Check field names used in view archs.

    For models we own, any unknown field is an error. For inherited native models
    only ``dally_*`` fields are checked — native ones cannot be resolved here.
    """
    for xml_file in sorted(addons.rglob("views/*.xml")):
        rel = xml_file.relative_to(addons)
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue

        for record in root.iter("record"):
            if record.get("model") != "ir.ui.view":
                continue

            model_field = record.find("./field[@name='model']")
            if model_field is None or not model_field.text:
                continue
            model = model_field.text.strip()

            arch = record.find("./field[@name='arch']")
            if arch is None:
                continue

            known = fields_by_model.get(model, set()) | MAGIC_FIELDS
            # iter() yields the arch element itself (it is a <field>), so walk
            # its descendants only.
            for field_element in arch.iterfind(".//field"):
                name = field_element.get("name")
                if not name:
                    continue
                if model in owned_models:
                    if name not in known:
                        error(
                            f"{rel}: view of {model} uses field '{name}' "
                            f"which the model does not define"
                        )
                elif name.startswith("dally_"):
                    if name not in known:
                        error(
                            f"{rel}: view of {model} uses custom field '{name}' "
                            f"which no model defines"
                        )


# ─── ACLs ─────────────────────────────────────────────────────────────


def check_acls(addons: pathlib.Path, owned_models: set, known_ids: set) -> None:
    for csv_file in sorted(addons.rglob("security/ir.model.access.csv")):
        rel = csv_file.relative_to(addons)
        lines = csv_file.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            error(f"{rel}: file is empty")
            continue

        header = [column.strip() for column in lines[0].split(",")]
        for expected in ("id", "model_id:id", "group_id:id"):
            if expected not in header:
                error(f"{rel}: missing '{expected}' column")
                break
        else:
            model_index = header.index("model_id:id")
            group_index = header.index("group_id:id")

            for number, line in enumerate(lines[1:], start=2):
                if not line.strip():
                    continue
                cells = [c.strip() for c in line.split(",")]
                if len(cells) != len(header):
                    error(f"{rel}:{number}: {len(cells)} columns, expected {len(header)}")
                    continue

                model_ref = cells[model_index]
                expected_models = {
                    f"model_{model.replace('.', '_')}" for model in owned_models
                }
                bare = model_ref.split(".")[-1]
                if bare not in expected_models:
                    error(
                        f"{rel}:{number}: model_id '{model_ref}' does not match any "
                        f"model defined by our modules"
                    )

                group_ref = cells[group_index]
                if group_ref and group_ref not in known_ids:
                    if group_ref.split(".")[0] in {
                        p.name for p in addons.iterdir() if p.is_dir()
                    }:
                        error(f"{rel}:{number}: unknown group '{group_ref}'")


# ─── Manifests ────────────────────────────────────────────────────────


def check_manifests(addons: pathlib.Path) -> None:
    for manifest_path in sorted(addons.glob("*/__manifest__.py")):
        module_dir = manifest_path.parent
        module = module_dir.name
        try:
            manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, SyntaxError) as exc:
            error(f"{module}/__manifest__.py: not a literal dict ({exc})")
            continue

        for key in ("name", "version", "license", "depends", "data"):
            if key not in manifest:
                warn(f"{module}: manifest has no '{key}'")

        declared = list(manifest.get("data", []))
        for relative in declared:
            if not (module_dir / relative).exists():
                error(f"{module}: manifest lists '{relative}' but the file is missing")

        # Every data file on disk should be declared, or it silently does nothing.
        for pattern in ("views/*.xml", "data/*.xml", "security/*.xml", "security/*.csv"):
            for found in sorted(module_dir.glob(pattern)):
                relative = str(found.relative_to(module_dir))
                if relative not in declared:
                    error(
                        f"{module}: '{relative}' exists but is not listed in the "
                        f"manifest — it will never be loaded"
                    )

        # Ordering: security before the data that references groups.
        indices = {name: i for i, name in enumerate(declared)}
        acl = next((n for n in declared if n.endswith("ir.model.access.csv")), None)
        groups = next((n for n in declared if "security" in n and n.endswith(".xml")), None)
        if acl and groups and indices[groups] > indices[acl]:
            error(
                f"{module}: '{groups}' must be listed before '{acl}' — the ACL "
                f"references groups defined there"
            )


def check_init_imports(addons: pathlib.Path) -> None:
    """Every models/*.py must be imported by models/__init__.py."""
    for init_path in sorted(addons.rglob("models/__init__.py")):
        module_dir = init_path.parent
        rel = init_path.relative_to(addons)
        imported = set(
            re.findall(r"^from\s+\.\s+import\s+(.+)$",
                       init_path.read_text(encoding="utf-8"), re.MULTILINE)
        )
        names: set[str] = set()
        for group in imported:
            names.update(part.strip() for part in group.split(","))

        for py_file in sorted(module_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            if py_file.stem not in names:
                error(f"{rel}: does not import '{py_file.stem}' — the model is dead code")


def main() -> int:
    addons = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not addons.is_dir():
        print(f"Not a directory: {addons}", file=sys.stderr)
        return 2

    print(f"Validating Odoo modules in {addons}\n")

    fields_by_model, _module_by_model, owned_models = parse_models(addons)
    known_ids = collect_external_ids(addons)

    print(f"  models defined      : {len(owned_models)}")
    print(f"  models touched      : {len(fields_by_model)}")
    print(f"  external ids        : {len(known_ids)}\n")

    check_manifests(addons)
    check_init_imports(addons)
    check_view_fields(addons, fields_by_model, owned_models)
    check_acls(addons, owned_models, known_ids)
    check_refs(addons, known_ids)

    for message in WARNINGS:
        print(f"  WARN  {message}")
    for message in ERRORS:
        print(f"  ERROR {message}")

    print()
    print(f"  {len(ERRORS)} error(s), {len(WARNINGS)} warning(s), "
          f"{len(INFO)} native reference(s) not verifiable here")

    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())
