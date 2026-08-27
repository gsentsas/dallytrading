#!/usr/bin/env python3
"""Static consistency checks for the DallyTrading Odoo modules.

Catches, without a running Odoo, the mistakes that otherwise only surface as a
failed module installation:

* a data file listed in a manifest but absent from disk (and the reverse)
* a view referencing a field no model defines — resolving inherited fields from
  our own mixins, and nested one2many/many2many fields against their comodel
* an ACL or record rule pointing at a model that does not exist
* a ``ref="..."`` to an external id defined in none of our modules
* a module whose ``models/__init__.py`` does not import a sibling model file

Native Odoo external ids and fields cannot be verified here — that needs the real
registry. They are counted as informational.

Usage:
    python3 infrastructure/scripts/validate-addons.py [addons_dir] [--verbose]

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

FIELD_CALL_RE = re.compile(r"^fields\.")

#: Fields Odoo adds to every model, and pseudo-fields valid in any arch.
MAGIC_FIELDS = {
    "id", "display_name", "create_date", "create_uid", "write_date", "write_uid",
    "__last_update", "sequence",
}

#: Relational field types whose children in an arch describe the comodel.
RELATIONAL_TYPES = {"One2many", "Many2many", "Many2one"}

#: Fields contributed by native Odoo mixins we inherit.
#:
#: Declaring them means a model of ours that mixes in mail.thread can still be
#: checked strictly: without this, inheriting a native mixin would force the
#: validator to give up on the whole model, and a typo like `weight_kilos` in a
#: view would pass unnoticed. Verified against Odoo's mail module; a missing entry
#: shows up as a false positive, never as a missed error.
NATIVE_MIXIN_FIELDS = {
    "mail.thread": {
        "message_ids", "message_follower_ids", "message_partner_ids",
        "message_needaction", "message_needaction_counter", "message_has_error",
        "message_has_error_counter", "message_attachment_count",
        "message_main_attachment_id", "message_is_follower", "message_unread",
        "message_unread_counter", "website_message_ids", "has_message",
        "message_has_sms_error",
    },
    "mail.activity.mixin": {
        "activity_ids", "activity_state", "activity_user_id", "activity_type_id",
        "activity_type_icon", "activity_date_deadline", "activity_summary",
        "activity_exception_decoration", "activity_exception_icon",
        "my_activity_date_deadline", "activity_calendar_event_id",
    },
    "portal.mixin": {"access_url", "access_token", "access_warning"},
    "mail.thread.cc": {"email_cc"},
}


def error(message: str) -> None:
    ERRORS.append(message)


def warn(message: str) -> None:
    WARNINGS.append(message)


def info(message: str) -> None:
    INFO.append(message)


class ModelIndex:
    """What our modules define, resolved across inheritance."""

    def __init__(self) -> None:
        #: model -> {field_name: comodel_or_None}
        self.fields: dict[str, dict[str, str | None]] = {}
        #: model -> list of models it inherits from
        self.inherits: dict[str, list[str]] = {}
        #: models declared with _name by our code (we own their full field set)
        self.owned: set[str] = set()
        #: models declared with _name AND non-abstract (get a model_* external id)
        self.concrete: set[str] = set()
        #: concrete model -> addon that declares its _name
        self.declaring_module: dict[str, str] = {}
        self._resolved: dict[str, dict[str, str | None]] = {}

    def resolve(self, model: str) -> dict[str, str | None]:
        """Fields of a model, including those inherited from models we define.

        A mixin's fields belong to every model inheriting it, so a view using
        `reference` on dally.shipment is legitimate even though the field is
        declared on dally.reference.mixin.
        """
        if model in self._resolved:
            return self._resolved[model]

        # Guard against a cycle in _inherit before recursing.
        self._resolved[model] = {}

        merged: dict[str, str | None] = {}
        for parent in self.inherits.get(model, []):
            if parent != model and parent in self.fields:
                merged.update(self.resolve(parent))
        merged.update(self.fields.get(model, {}))

        self._resolved[model] = merged
        return merged

    def native_mixin_fields(self, model: str) -> set[str]:
        """Fields a model gains from native mixins it inherits."""
        gained: set[str] = set()
        for parent in self.inherits.get(model, []):
            gained |= NATIVE_MIXIN_FIELDS.get(parent, set())
            if parent in self.fields and parent != model:
                gained |= self.native_mixin_fields(parent)
        return gained

    def is_fully_known(self, model: str) -> bool:
        """True when we declared the model, so its field set is ours to know.

        Native *mixins* are fine — their fields are declared in
        NATIVE_MIXIN_FIELDS. What disqualifies a model is extending a native
        *model* (crm.lead, res.partner), where only our own `dally_*` fields can
        be checked.
        """
        if model not in self.owned:
            return False
        for parent in self.inherits.get(model, []):
            if parent in self.fields:
                continue
            if parent in NATIVE_MIXIN_FIELDS:
                continue
            return False
        return True


def python_source_files(addons: pathlib.Path) -> list[pathlib.Path]:
    """Return production ORM Python sources, including wizard models."""
    paths: set[pathlib.Path] = set()
    for module_dir in addons.iterdir():
        if not module_dir.is_dir():
            continue
        for package_name in ("models", "wizard"):
            root = module_dir / package_name
            if root.is_dir():
                paths.update(root.rglob("*.py"))
    return sorted(paths)


def parse_models(addons: pathlib.Path) -> ModelIndex:
    index = ModelIndex()

    for py_file in python_source_files(addons):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        declaring_module = py_file.relative_to(addons).parts[0]

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            model_name: str | None = None
            inherits: list[str] = []
            is_abstract = any(
                isinstance(base, ast.Attribute) and base.attr == "AbstractModel"
                for base in node.bases
            )
            fields: dict[str, str | None] = {}

            for stmt in node.body:
                if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
                    continue
                target = stmt.targets[0]
                if not isinstance(target, ast.Name):
                    continue

                if target.id == "_name" and isinstance(stmt.value, ast.Constant):
                    model_name = stmt.value.value
                elif target.id == "_inherit":
                    if isinstance(stmt.value, ast.Constant):
                        inherits = [stmt.value.value]
                    elif isinstance(stmt.value, (ast.List, ast.Tuple)):
                        inherits = [
                            elt.value for elt in stmt.value.elts
                            if isinstance(elt, ast.Constant)
                        ]
                elif isinstance(stmt.value, ast.Call):
                    source = ast.unparse(stmt.value.func)
                    if not FIELD_CALL_RE.match(source):
                        continue
                    field_type = source.split(".", 1)[1]
                    comodel = None
                    if field_type in RELATIONAL_TYPES:
                        # comodel_name= keyword, or the first positional argument
                        for keyword in stmt.value.keywords:
                            if keyword.arg in ("comodel_name", "related") and \
                                    isinstance(keyword.value, ast.Constant):
                                if keyword.arg == "comodel_name":
                                    comodel = keyword.value.value
                        if comodel is None and stmt.value.args:
                            first = stmt.value.args[0]
                            if isinstance(first, ast.Constant) and \
                                    isinstance(first.value, str):
                                comodel = first.value
                    fields[target.id] = comodel

            effective = model_name or (inherits[0] if inherits else None)
            if not effective:
                continue

            index.fields.setdefault(effective, {}).update(fields)
            if inherits:
                existing = index.inherits.setdefault(effective, [])
                for parent in inherits:
                    if parent not in existing:
                        existing.append(parent)
            if model_name:
                index.owned.add(model_name)
                if not is_abstract:
                    index.concrete.add(model_name)
                    # ``_name`` combined with ``_inherit`` of the same model is
                    # an extension, not a new model declaration.  A model may
                    # legitimately inherit a mixin while still being new.
                    if model_name not in inherits:
                        index.declaring_module.setdefault(model_name, declaring_module)

    return index


def collect_external_ids(addons: pathlib.Path, index: ModelIndex) -> set[str]:
    ids: set[str] = set()
    our_modules = {p.name for p in addons.iterdir() if p.is_dir()}

    for xml_file in sorted(addons.rglob("*.xml")):
        module = xml_file.relative_to(addons).parts[0]
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue
        for element in root.iter():
            if element.tag in ("record", "menuitem", "template", "act_window"):
                rid = element.get("id")
                if rid:
                    ids.add(rid if "." in rid else f"{module}.{rid}")

    for csv_file in sorted(addons.rglob("security/*.csv")):
        module = csv_file.relative_to(addons).parts[0]
        for line in csv_file.read_text(encoding="utf-8").splitlines()[1:]:
            if line.strip():
                ids.add(f"{module}.{line.split(',')[0]}")

    # Odoo creates a model_<underscored_name> external id for every concrete
    # model, in the module that declares it. Record rules and ACLs reference
    # those, so they must be considered known.
    for model, module in index.declaring_module.items():
        ids.add(f"{module}.model_{model.replace('.', '_')}")

    return ids


def locator_field_names(expr: str) -> list[str]:
    """Extract field selectors from an XPath/direct-field inheritance locator."""
    return re.findall(r"field\s*\[\s*@name\s*=\s*['\"]([^'\"]+)['\"]\s*\]", expr)


def insertion_scope(index: ModelIndex, model: str, expr: str, position: str) -> str:
    """Resolve the model containing nodes inserted by an inheritance locator."""
    fields = locator_field_names(expr)
    current = model
    if not fields:
        return current
    for name in fields[:-1]:
        comodel = index.resolve(current).get(name)
        if comodel:
            current = comodel
    target = fields[-1]
    comodel = index.resolve(current).get(target)
    if position == "inside" and comodel:
        return comodel
    return current


def check_arch_fields(index: ModelIndex, model: str, element: ET.Element,
                      rel: pathlib.Path, depth: int = 0) -> None:
    """Walk an arch, validating field names against the model in scope.

    Descending into a relational field switches scope to its comodel: the fields
    inside <field name="package_ids"><list> belong to dally.shipment.package, not
    to dally.shipment.
    """
    if depth > 12:
        return

    known = dict(index.resolve(model)) if model else {}
    if model:
        for native_field in index.native_mixin_fields(model):
            known.setdefault(native_field, None)
    fully_known = index.is_fully_known(model) if model else False

    for child in element:
        if child.tag == "xpath":
            scope = insertion_scope(
                index, model, child.get("expr", ""), child.get("position", "after")
            )
            check_arch_fields(index, scope, child, rel, depth + 1)
            continue
        if child.tag == "field":
            name = child.get("name")
            if name:
                if name not in known and name not in MAGIC_FIELDS:
                    if fully_known:
                        error(
                            f"{rel}: view of {model} uses field '{name}' which the "
                            f"model does not define"
                        )
                    elif name.startswith("dally_"):
                        error(
                            f"{rel}: view of {model} uses custom field '{name}' "
                            f"which no model defines"
                        )
                    else:
                        info(f"{rel}: {model}.{name} is native — not verifiable")

                position = child.get("position")
                comodel = known.get(name)
                if len(child):
                    # Nested arch: validate against the comodel when we know it.
                    nested_model = (
                        comodel
                        if comodel and (position is None or position == "inside")
                        else model
                    )
                    check_arch_fields(index, nested_model, child, rel, depth + 1)
                continue

        check_arch_fields(index, model, child, rel, depth + 1)


def check_view_fields(addons: pathlib.Path, index: ModelIndex) -> None:
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
            arch = record.find("./field[@name='arch']")
            if model_field is None or not model_field.text or arch is None:
                continue
            check_arch_fields(index, model_field.text.strip(), arch, rel)


def check_acls(addons: pathlib.Path, index: ModelIndex, known_ids: set[str]) -> None:
    our_modules = {p.name for p in addons.iterdir() if p.is_dir()}

    for csv_file in sorted(addons.rglob("security/ir.model.access.csv")):
        rel = csv_file.relative_to(addons)
        module = rel.parts[0]
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
                qualified = model_ref if "." in model_ref else f"{module}.{model_ref}"
                if qualified not in known_ids and qualified.split(".")[0] in our_modules:
                    error(
                        f"{rel}:{number}: model_id '{model_ref}' matches no "
                        f"model defined by our modules"
                    )

                group_ref = cells[group_index]
                if group_ref and group_ref not in known_ids and \
                        group_ref.split(".")[0] in our_modules:
                    error(f"{rel}:{number}: unknown group '{group_ref}'")


def check_refs(addons: pathlib.Path, known_ids: set[str]) -> None:
    our_modules = {p.name for p in addons.iterdir() if p.is_dir()}

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
            if qualified.split(".")[0] in our_modules:
                error(f"{rel}: ref '{ref}' is not defined by any of our modules")
            else:
                info(f"{rel}: ref '{ref}' is native — verify at install time")


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

        for pattern in ("views/*.xml", "data/*.xml", "security/*.xml", "security/*.csv"):
            for found in sorted(module_dir.glob(pattern)):
                relative = str(found.relative_to(module_dir))
                if relative not in declared:
                    error(
                        f"{module}: '{relative}' exists but is not listed in the "
                        f"manifest — it will never be loaded"
                    )

        # Load order only matters when a file actually declares res.groups that
        # the ACL then references. A security file containing only record rules
        # can safely load after the ACL, so checking the filename is not enough —
        # it has to be the content.
        indices = {name: i for i, name in enumerate(declared)}
        acl = next((n for n in declared if n.endswith("ir.model.access.csv")), None)
        if not acl:
            continue

        for name in declared:
            if not name.endswith(".xml") or indices[name] < indices[acl]:
                continue
            candidate = module_dir / name
            if not candidate.exists():
                continue
            try:
                root = ET.parse(candidate).getroot()
            except ET.ParseError:
                continue
            declares_groups = any(
                record.get("model") == "res.groups" for record in root.iter("record")
            )
            if declares_groups:
                error(
                    f"{module}: '{name}' declares res.groups and must be listed "
                    f"before '{acl}', which references them"
                )


def check_init_imports(addons: pathlib.Path) -> None:
    for init_path in sorted(addons.rglob("*/__init__.py")):
        module_dir = init_path.parent
        if module_dir.name not in ("models", "controllers"):
            continue
        rel = init_path.relative_to(addons)
        imported: set[str] = set()
        for group in re.findall(
            r"^from\s+\.\s+import\s+(.+)$",
            init_path.read_text(encoding="utf-8"), re.MULTILINE,
        ):
            imported.update(part.strip() for part in group.split(","))

        for py_file in sorted(module_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            if py_file.stem not in imported:
                error(f"{rel}: does not import '{py_file.stem}' — the file is dead code")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    verbose = "--verbose" in sys.argv
    addons = pathlib.Path(args[0] if args else ".").resolve()
    if not addons.is_dir():
        print(f"Not a directory: {addons}", file=sys.stderr)
        return 2

    print(f"Validating Odoo modules in {addons}\n")

    index = parse_models(addons)
    known_ids = collect_external_ids(addons, index)

    print(f"  modules             : {len([p for p in addons.iterdir() if p.is_dir()])}")
    print(f"  models defined      : {len(index.owned)}")
    print(f"  models extended     : {len(index.fields) - len(index.owned)}")
    print(f"  external ids known  : {len(known_ids)}\n")

    check_manifests(addons)
    check_init_imports(addons)
    check_view_fields(addons, index)
    check_acls(addons, index, known_ids)
    check_refs(addons, known_ids)

    for message in WARNINGS:
        print(f"  WARN  {message}")
    for message in ERRORS:
        print(f"  ERROR {message}")
    if verbose:
        for message in INFO:
            print(f"  info  {message}")

    print()
    print(f"  {len(ERRORS)} error(s), {len(WARNINGS)} warning(s), "
          f"{len(INFO)} native reference(s) not verifiable here")

    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())
