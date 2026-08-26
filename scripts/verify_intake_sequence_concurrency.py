"""DEV-only ORM concurrency probe for intake Axxx allocation."""
from threading import Barrier, Thread
from time import time_ns
from odoo import api
from odoo.exceptions import ConcurrencyError
from odoo.modules.registry import Registry

PREFIX = "AIR-DSS-CDG-2099-CONC-" + str(time_ns())
odoo_env = globals().get("env")
if odoo_env is None:
    raise RuntimeError("Ce probe doit être exécuté dans un shell Odoo.")
Con = odoo_env["dally.freight.consolidation"]
Partner = odoo_env["res.partner"]
company = odoo_env.company
odoo_env["dally.shipment"].search([("sync_source_key", "like", PREFIX + "%")]).unlink()
Con.search([("name", "like", PREFIX + "%")]).unlink()
partner = Partner.create({"name": "Probe partner A %s" % PREFIX})
partner_b = Partner.create({"name": "Probe partner B %s" % PREFIX})
con2 = Con.create({"name": PREFIX + "-002", "company_id": company.id, "transport_mode": "air", "direction": "export", "origin_city": "Dakar", "destination_city": "Paris", "state": "collecting"})
con3 = Con.create({"name": PREFIX + "-003", "company_id": company.id, "transport_mode": "air", "direction": "export", "origin_city": "Dakar", "destination_city": "Paris", "state": "collecting"})
odoo_env.cr.commit()
registry = Registry(odoo_env.cr.dbname)
barrier = Barrier(2)
results = []
errors = []

def worker(payload):
    for attempt in range(3):
        try:
            with registry.cursor() as cr:
                worker_env = api.Environment(cr, odoo_env.uid, {})
                if attempt == 0:
                    barrier.wait(timeout=15)
                result, shipment = worker_env["dally.freight.sync.service"].upsert(payload)
                cr.commit()
                results.append((result["collection_local_ref"], result["external_reference"], shipment.id))
                return
        except ConcurrencyError:
            if attempt == 2:
                errors.append("ConcurrencyError after 3 attempts")
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            return

base = {"planned_consolidation_ref": con2.name, "transport_mode": "air", "direction": "export", "client": {"name": partner.name}, "partner_id": partner.id}
base_b = dict(base, client={"name": partner_b.name}, partner_id=partner_b.id)
threads = [Thread(target=worker, args=(dict(base, sync_source_key=PREFIX + "-a"),)), Thread(target=worker, args=(dict(base_b, sync_source_key=PREFIX + "-b"),))]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(20)
assert not errors, errors
assert sorted(item[0] for item in results) == ["A001", "A002"], results

# Different consolidations independently restart at A001.
for ref, con in (("-c", con2), ("-d", con3)):
    result, _shipment = odoo_env["dally.freight.sync.service"].upsert(dict(sync_source_key=PREFIX + ref, planned_consolidation_ref=con.name, transport_mode="air", direction="export", client={"name": partner.name}))
    assert result["collection_local_ref"] == ("A003" if con == con2 else "A001"), result

# Same source key concurrently resolves to one identity.
barrier = Barrier(2)
results[:] = []
errors[:] = []
threads = [Thread(target=worker, args=(dict(base, sync_source_key=PREFIX + "-same"),)), Thread(target=worker, args=(dict(base, sync_source_key=PREFIX + "-same"),))]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(20)
assert not errors, errors
assert len({item[2] for item in results}) == 1 and len(results) == 2, results
assert len({item[0] for item in results}) == 1, results
print("INTAKE_CONCURRENCY=PASS", results)
# Cleanup all committed probe records.
odoo_env["dally.shipment"].search([("sync_source_key", "like", PREFIX + "%")]).unlink()
Con.search([("name", "like", PREFIX + "%")]).unlink()

odoo_env.cr.commit()
remaining = Con.search_count([("name", "like", PREFIX + "%")])
assert remaining == 0, remaining
print("CLEANUP=PASS")
