"""DEV-only ORM concurrency probe for intake Axxx allocation."""
from threading import Barrier, Thread
from time import time_ns
from odoo import api
from odoo.modules.registry import Registry

PREFIX = "AIR-DSS-CDG-2099-CONC-" + str(time_ns())
Con = env["dally.freight.consolidation"]
Partner = env["res.partner"]
company = env.company
env["dally.shipment"].search([("sync_source_key", "like", PREFIX + "%")]).unlink()
Con.search([("name", "like", PREFIX + "%")]).unlink()
partner = company.partner_id
partner_b = company.partner_id
con2 = Con.create({"name": PREFIX + "-002", "company_id": company.id, "transport_mode": "air", "direction": "export", "origin_city": "Dakar", "destination_city": "Paris", "state": "collecting"})
con3 = Con.create({"name": PREFIX + "-003", "company_id": company.id, "transport_mode": "air", "direction": "export", "origin_city": "Dakar", "destination_city": "Paris", "state": "collecting"})
env.cr.commit()
registry = Registry(env.cr.dbname)
barrier = Barrier(2)
results = []
errors = []

def worker(payload):
    try:
        with registry.cursor() as cr:
            worker_env = api.Environment(cr, env.uid, {})
            cr.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            barrier.wait(timeout=15)
            result, shipment = worker_env["dally.freight.sync.service"].upsert(payload)
            cr.commit()
            results.append((result["collection_local_ref"], result["external_reference"], shipment.id))
    except Exception as exc:  # noqa: BLE001
        errors.append(repr(exc))

base = {"planned_consolidation_ref": con2.name, "transport_mode": "air", "direction": "export", "client": {"name": partner.name}, "partner_id": partner.id}
base_b = dict(base, client={"name": partner_b.name}, partner_id=partner_b.id)
threads = [Thread(target=worker, args=(dict(base, sync_source_key=PREFIX + "-a"),)), Thread(target=worker, args=(dict(base_b, sync_source_key=PREFIX + "-b"),))]
[t.start() for t in threads]
[t.join(20) for t in threads]
assert not errors, errors
assert sorted(item[0] for item in results) == ["A001", "A002"], results

# Different consolidations independently restart at A001.
for ref, con in (("-c", con2), ("-d", con3)):
    result, _shipment = env["dally.freight.sync.service"].upsert(dict(sync_source_key=PREFIX + ref, planned_consolidation_ref=con.name, transport_mode="air", direction="export", client={"name": partner.name}))
    assert result["collection_local_ref"] == ("A003" if con == con2 else "A001"), result

# Same source key concurrently resolves to one identity.
barrier = Barrier(2); results[:] = []; errors[:] = []
threads = [Thread(target=worker, args=(dict(base, sync_source_key=PREFIX + "-same"),)), Thread(target=worker, args=(dict(base, sync_source_key=PREFIX + "-same"),))]
[t.start() for t in threads]
[t.join(20) for t in threads]
assert not errors, errors
assert len({item[2] for item in results}) == 1 and len(results) == 2, results
assert len({item[0] for item in results}) == 1, results
print("INTAKE_CONCURRENCY=PASS", results)
# Cleanup all committed probe records.
env["dally.shipment"].search([("sync_source_key", "like", PREFIX + "%")]).unlink()
Con.search([("name", "like", PREFIX + "%")]).unlink()

env.cr.commit()
remaining = Con.search_count([("name", "like", PREFIX + "%")])
assert remaining == 0, remaining
print("CLEANUP=PASS")
