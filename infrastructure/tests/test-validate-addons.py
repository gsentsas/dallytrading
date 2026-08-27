#!/usr/bin/env python3
"""Regression tests for the static addon validator (standard library only)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "infrastructure/scripts/validate-addons.py"


def run_fixture(files: dict[str, str]) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for name, content in files.items():
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        proc = subprocess.run(
            ["python3", str(VALIDATOR), str(base / "x_module")],
            text=True,
            capture_output=True,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr


MANIFEST = """{
    'name': 'X', 'version': '1.0', 'depends': [],
    'data': ['security/ir.model.access.csv', 'views/test.xml']
}"""
INIT = "from . import models\nfrom . import wizard\n"
MODELS_INIT = "from . import models\n"
WIZARD_INIT = "from . import example\n"
MODELS = """from odoo import fields, models

class Parent(models.Model):
    _name = 'x.parent'
    partner_id = fields.Many2one('res.partner')
    line_ids = fields.One2many('x.line', 'parent_id')
    root_extra = fields.Char()

class Line(models.Model):
    _name = 'x.line'
    parent_id = fields.Many2one('x.parent')
    description = fields.Char()
    billing_method = fields.Char()
"""
WIZARD = """from odoo import models

class ExampleWizard(models.TransientModel):
    _name = 'x.example.wizard'
"""
ACL = """id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_x_wizard,x,model_x_example_wizard,base.group_user,1,1,1,1
"""


def fixture(view: str, acl: str = ACL) -> dict[str, str]:
    return {
        "x_module/__init__.py": INIT,
        "x_module/__manifest__.py": MANIFEST,
        "x_module/models/__init__.py": MODELS_INIT,
        "x_module/models/models.py": MODELS,
        "x_module/wizard/__init__.py": WIZARD_INIT,
        "x_module/wizard/example.py": WIZARD,
        "x_module/security/ir.model.access.csv": acl,
        "x_module/views/test.xml": view,
    }


def expect_success(view: str) -> None:
    rc, output = run_fixture(fixture(view))
    assert rc == 0, output


def expect_failure(view: str, needle: str, acl: str = ACL) -> None:
    rc, output = run_fixture(fixture(view, acl))
    assert rc != 0 and needle in output, output


ROOT_VIEW = """<odoo><record id="v" model="ir.ui.view"><field name="model">x.parent</field>
<field name="arch" type="xml">{arch}</field></record></odoo>"""


def main() -> None:
    # Wizard declarations outside models/ produce usable model_* ACL ids.
    expect_success(ROOT_VIEW.format(arch="<field name='partner_id' position='after'><field name='root_extra'/></field>"))
    expect_failure(
        ROOT_VIEW.format(arch="<field name='partner_id' position='after'><field name='root_extra'/></field>"),
        "model_x_missing_wizard",
        ACL.replace("model_x_example_wizard", "model_x_missing_wizard"),
    )

    nested = "<xpath expr=\"//field[@name='line_ids']/list/field[@name='description']\" position='after'><field name='billing_method'/></xpath>"
    expect_success(ROOT_VIEW.format(arch=nested))
    expect_failure(
        ROOT_VIEW.format(arch=nested.replace("billing_method", "billing_methdo")),
        "x.line",
    )

    inside = "<xpath expr=\"//field[@name='line_ids']\" position='inside'><list><field name='billing_method'/></list></xpath>"
    expect_success(ROOT_VIEW.format(arch=inside))
    print("VALIDATE_ADDONS_TESTS=PASS")


if __name__ == "__main__":
    main()
