#!/usr/bin/env python3
"""Proof of the package advisory lock with real concurrent Odoo ORM calls.

Run this file through ``odoo shell`` on an isolated database.  It deliberately
does not use TransactionCase: each worker owns an independent PostgreSQL
connection, cursor and Odoo Environment.
"""

import threading
import time
import traceback
import uuid

from odoo import SUPERUSER_ID, api, sql_db
from odoo.modules.registry import Registry


TIMEOUT = 15


def _env_cursor(dbname, uid):
    db = sql_db.db_connect(dbname)
    cr = db.cursor()
    cr.execute("SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED")
    cr.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
    cr.execute("SET statement_timeout = '30000ms'")
    cr.execute("SELECT pg_backend_pid()")
    pid = cr.fetchone()[0]
    return cr, api.Environment(cr, uid, {}), pid


def _locks(dbname, pids):
    db = sql_db.db_connect(dbname)
    with db.cursor() as cr:
        cr.execute(
            """SELECT pid, database, classid, objid, objsubid, granted
               FROM pg_locks
              WHERE locktype = 'advisory' AND pid = ANY(%s)
              ORDER BY pid""",
            [list(pids)],
        )
        rows = cr.fetchall()
    return rows


def _wait_for_same_lock(dbname, pid_a, pid_b):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        rows = _locks(dbname, [pid_a, pid_b])
        by_identity = {}
        for pid, database, classid, objid, objsubid, granted in rows:
            identity = (database, classid, objid, objsubid)
            by_identity.setdefault(identity, {})[pid] = granted
        for identity, states in by_identity.items():
            if states.get(pid_a) is True and states.get(pid_b) is False:
                return identity, rows
        time.sleep(0.05)
    raise AssertionError("B n'est pas observé en attente du même verrou advisory")


def _setup(env, prefix, quantity):
    partner = env.ref("base.partner_admin")
    shipment = env["dally.shipment"].create({
        "partner_id": partner.id, "external_reference": prefix + "-SHP",
        "transport_mode": "air", "direction": "export",
        "origin_city": "Dakar", "origin_location": "DSS",
        "destination_city": "Paris", "destination_location": "CDG",
        "goods_description": "Concurrency probe",
    })
    package_vals = {
        "shipment_id": shipment.id, "external_line_key": prefix + "|A|1",
        "package_type": "parcel", "description": "Concurrency probe",
        "quantity": quantity, "unit_weight_kg": 1.0, "unit_volume_cbm": 0.01,
    }
    if "billing_method" in env["dally.shipment.package"]._fields:
        package_vals.update({"billing_method": "real", "applied_unit_price_eur": 1.0})
    package = env["dally.shipment.package"].create(package_vals)
    common = {
        "transport_mode": "air", "direction": "export",
        "origin_city": "Dakar", "origin_location": "DSS",
        "destination_city": "Paris", "destination_location": "CDG",
        "state": "collecting",
    }
    cons_a = env["dally.freight.consolidation"].create(dict(common, name=prefix + "-A"))
    cons_b = env["dally.freight.consolidation"].create(dict(common, name=prefix + "-B"))
    env.cr.commit()
    return shipment.id, package.id, cons_a.id, cons_b.id


def _scenario(dbname, uid, ids, mode):
    _shipment_id, package_id, cons_a_id, cons_b_id = ids
    a_holds = threading.Event()
    release_a = threading.Event()
    b_started = threading.Event()
    results = {}
    pids = {}

    def worker_a():
        cr = env = None
        try:
            cr, env, pids["a"] = _env_cursor(dbname, uid)
            Line = env["dally.freight.consolidation.line"]
            if mode == "line_line":
                Line.create({"consolidation_id": cons_a_id, "package_id": package_id,
                             "quantity_loaded": 2})
            else:
                Line.create({"consolidation_id": cons_a_id, "package_id": package_id,
                             "quantity_loaded": 3})
            results["a"] = "success"
            a_holds.set()
            if not release_a.wait(TIMEOUT):
                raise AssertionError("A n'a pas reçu le signal de libération")
            cr.commit()
        except Exception as exc:  # pragma: no cover - exercised by standalone probe
            results["a_error"] = "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc())
            if a_holds.is_set():
                release_a.set()
            if cr:
                cr.rollback()
        finally:
            if cr:
                cr.close()

    def worker_b():
        cr = env = None
        try:
            if not a_holds.wait(TIMEOUT):
                raise AssertionError("B n'a pas observé le verrou A")
            cr, env, pids["b"] = _env_cursor(dbname, uid)
            b_started.set()
            if mode == "line_line":
                env["dally.freight.consolidation.line"].create({
                    "consolidation_id": cons_b_id, "package_id": package_id,
                    "quantity_loaded": 2,
                })
            else:
                env["dally.shipment.package"].browse(package_id).write({"quantity": 1})
            cr.commit()
            results["b"] = "unexpected_success"
        except Exception as exc:  # expected after A commits
            results["b_error"] = "%s: %s" % (type(exc).__name__, exc)
            if cr:
                cr.rollback()
        finally:
            if cr:
                cr.close()

    thread_a = threading.Thread(target=worker_a, name="concurrency-probe-A")
    thread_b = threading.Thread(target=worker_b, name="concurrency-probe-B")
    thread_a.start()
    if not a_holds.wait(TIMEOUT):
        raise AssertionError("A n'a pas terminé son appel ORM dans le délai")
    thread_b.start()
    if not b_started.wait(TIMEOUT):
        raise AssertionError("B n'a pas commencé son appel ORM dans le délai")
    identity, lock_rows = _wait_for_same_lock(dbname, pids["a"], pids["b"])
    premature = not thread_b.is_alive()
    if premature:
        release_a.set()
        thread_a.join(TIMEOUT)
        thread_b.join(TIMEOUT)
        raise AssertionError("B a terminé avant la libération de A")
    release_a.set()
    thread_a.join(TIMEOUT)
    thread_b.join(TIMEOUT)
    if thread_a.is_alive() or thread_b.is_alive():
        raise AssertionError("un thread est resté bloqué après libération")
    if results.get("a") != "success" or "b_error" not in results or results.get("b") == "unexpected_success":
        raise AssertionError("résultats inattendus: %r" % results)
    with sql_db.db_connect(dbname).cursor() as cr:
        env = api.Environment(cr, uid, {})
        package = env["dally.shipment.package"].browse(package_id)
        loaded = sum(env["dally.freight.consolidation.line"].search([
            ("package_id", "=", package_id), ("consolidation_id.state", "!=", "cancelled")
        ]).mapped("quantity_loaded"))
        quantity = package.quantity
    print({"scenario": mode, "pid_a": pids["a"], "pid_b": pids["b"],
           "lock_identity": identity, "lock_rows": lock_rows,
           "premature_b": premature, "results": results,
           "loaded_final": loaded, "quantity_final": quantity})
    if loaded > quantity:
        raise AssertionError("invariant quantity chargée dépassé")
    return identity, results, loaded, quantity


def _cleanup(dbname, uid, prefix):
    registry = Registry(dbname)
    with registry.cursor() as cr:
        env = api.Environment(cr, uid, {})
        lines = env["dally.freight.consolidation.line"].search([
            ("consolidation_id.name", "ilike", prefix)
        ])
        lines.unlink()
        cons = env["dally.freight.consolidation"].search([("name", "ilike", prefix)])
        cons.unlink()
        shipments = env["dally.shipment"].search([("external_reference", "ilike", prefix)])
        packages = env["dally.shipment.package"].search([("external_line_key", "ilike", prefix)])
        packages.unlink()
        shipments.unlink()
        cr.commit()
    with registry.cursor() as cr:
        env = api.Environment(cr, uid, {})
        remaining = {
            "consolidations": env["dally.freight.consolidation"].search_count([("name", "ilike", prefix)]),
            "shipments": env["dally.shipment"].search_count([("external_reference", "ilike", prefix)]),
            "packages": env["dally.shipment.package"].search_count([("external_line_key", "ilike", prefix)]),
        }
    print({"cleanup_remaining": remaining})
    if any(remaining.values()):
        raise AssertionError("nettoyage incomplet: %r" % remaining)


def run(env):  # noqa: F821
    dbname = env.cr.dbname
    uid = SUPERUSER_ID
    prefix = "CONCURRENCY-PROBE-%s" % uuid.uuid4().hex[:10]
    registry = Registry(dbname)
    try:
        with registry.cursor() as cr:
            setup_env = api.Environment(cr, uid, {})
            ids_a = _setup(setup_env, prefix + "-A", 3)
            cr.commit()
        _scenario(dbname, uid, ids_a, "line_line")
        with registry.cursor() as cr:
            setup_env = api.Environment(cr, uid, {})
            ids_b = _setup(setup_env, prefix + "-B", 3)
            cr.commit()
        _scenario(dbname, uid, ids_b, "line_package")
        print("CONCURRENCY_PROBE PASS")
    finally:
        _cleanup(dbname, uid, prefix)


run(env)
