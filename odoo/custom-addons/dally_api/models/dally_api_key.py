# -*- coding: utf-8 -*-
"""API credentials for server-to-server calls.

Only the Next.js backend uses these keys. They never reach a browser: the
public site talks to its own ``/api`` routes, which hold the key server-side
(§2, §54).
"""

import hashlib
import hmac
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, UserError, ValidationError

#: Bytes of entropy per key. 32 bytes = 256 bits.
KEY_BYTES = 32

#: Characters of the key kept in clear, to let humans tell keys apart.
PREFIX_LENGTH = 8

#: Scopes an endpoint can require. Deliberately coarse: one per business area,
#: split by read vs write. Fine-grained scopes tend to be granted wholesale.
AVAILABLE_SCOPES = [
    "services:read",
    "leads:write",
    "quotes:write",
    "sourcing:write",
    "trading:write",
    "shipments:read",
    "tracking:read",
    "customers:read",
    # Shop scopes are split read/write for a reason that is not symmetry: the
    # catalogue is public information, while placing an order writes a
    # ``sale.order``. A key that only renders the storefront has no business
    # holding the second one, and the storefront is exactly the surface most
    # exposed to the internet.
    "shop:read",
    "shop:checkout",
]


class DallyApiKey(models.Model):
    _name = "dally.api.key"
    _description = "DallyTrading API Key"
    _order = "create_date desc"
    # No chatter: a record whose whole purpose is a secret should not accumulate
    # message history that could quote it.

    name = fields.Char(
        string="Name",
        required=True,
        help="What uses this key, e.g. 'Next.js production'. One key per consumer, "
             "so a leak can be revoked without taking everything else down.",
    )
    key_prefix = fields.Char(
        string="Prefix",
        readonly=True,
        copy=False,
        index=True,
        help="First characters of the key, kept in clear to identify it in logs.",
    )
    key_hash = fields.Char(
        string="Key Hash",
        readonly=True,
        copy=False,
        groups="base.group_system",
        help="SHA-256 of the key. The key itself is never stored.",
    )
    scopes = fields.Char(
        string="Scopes",
        required=True,
        default="leads:write",
        help="Comma-separated permissions, e.g. 'leads:write,tracking:read'. "
             "Grant only what the consumer actually calls.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="Uncheck to revoke immediately. Revoking is preferred over deleting: "
             "the request log keeps referring to the key.",
    )
    expires_on = fields.Date(
        string="Expires On",
        help="Optional. After this date the key is refused. Rotating keys on a "
             "schedule limits the value of a leaked one.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Acting User",
        required=True,
        default=lambda self: self.env.ref(
            "dally_api.user_dally_api_integration", raise_if_not_found=False
        ),
        domain=[("share", "=", False)],
        help="Odoo user the API acts as. Its groups bound what the API can do, "
             "so ACLs and record rules still apply — the API never runs as "
             "superuser. Use a dedicated integration user, never a real person's "
             "account.",
    )
    allowed_ips = fields.Char(
        string="Allowed IPs",
        help="Comma-separated list of source IPs. Empty allows any source.\n\n"
             "ATTENTION — l'adresse observée n'est PAS 127.0.0.1 lorsque Odoo tourne "
             "en conteneur, quoi qu'en dise l'intuition. Mesuré sur l'instance :\n"
             "  • appel direct sur la loopback → passerelle Docker (172.22.0.1)\n"
             "  • appel via le reverse proxy   → IP publique du serveur, transmise "
             "par X-Forwarded-For\n\n"
             "Le défaut était 127.0.0.1, valeur correcte sur un hôte nu et jamais "
             "atteinte ici : toutes les clés étaient rejetées en « invalid_api_key ». "
             "Il n'y a plus de défaut — une valeur à renseigner sciemment vaut mieux "
             "qu'un défaut plausible et faux.\n\n"
             "Relever la valeur réelle : journal Odoo lors d'un appel authentifié.",
    )

    last_used_at = fields.Datetime(string="Last Used", readonly=True)
    request_count = fields.Integer(string="Requests", readonly=True, default=0)

    # Shown once, right after creation, then discarded.
    key_to_display = fields.Char(
        string="Generated Key",
        readonly=True,
        store=False,
        help="Visible only immediately after generation. Copy it now: it cannot "
             "be recovered afterwards, only regenerated.",
    )

    _dally_api_key_prefix_uniq = models.Constraint(
        'UNIQUE(key_prefix)',
        'A key with this prefix already exists.',
    )

    @api.constrains("scopes")
    def _check_scopes(self):
        """Reject unknown scopes at write time.

        A typo like 'lead:write' would otherwise create a key that silently
        fails every request, and the cause would be hard to see.
        """
        for record in self:
            for scope in record._scope_list():
                if scope not in AVAILABLE_SCOPES:
                    raise ValidationError(
                        _(
                            "Unknown scope '%(scope)s'. Available scopes: %(available)s",
                            scope=scope,
                            available=", ".join(AVAILABLE_SCOPES),
                        )
                    )

    def _scope_list(self):
        self.ensure_one()
        return [s.strip() for s in (self.scopes or "").split(",") if s.strip()]

    def has_scope(self, scope):
        self.ensure_one()
        return scope in self._scope_list()

    # ─── Hashing ─────────────────────────────────────────────────────

    @api.model
    def _hash_key(self, key):
        """Hash a key with plain SHA-256.

        Deliberately not PBKDF2/bcrypt. Those exist to slow down brute force on
        low-entropy, human-chosen passwords. These keys are 256 bits of CSPRNG
        output: guessing one is infeasible regardless of hash speed, and a fast
        hash keeps per-request authentication cheap.
        """
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    # ─── Generation ──────────────────────────────────────────────────

    def action_generate_key(self):
        """Generate (or rotate) the secret and return it once."""
        self.ensure_one()
        raw_key = secrets.token_urlsafe(KEY_BYTES)
        self.write({
            "key_prefix": raw_key[:PREFIX_LENGTH],
            "key_hash": self._hash_key(raw_key),
        })
        # Non-stored field: survives for this response only.
        self.key_to_display = raw_key

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context, dally_key_just_generated=True),
        }

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        """Ne pas décrire ce modèle à qui n'a pas le droit de le lire.

        Odoo n'applique aucun contrôle d'accès à ``fields_get``. Sans cette
        surcharge, un utilisateur portail authentifié obtient par
        ``/web/dataset/call_kw`` la description complète de ce modèle — nom des
        champs, libellés, textes d'aide — alors qu'il n'a aucune ACL dessus.

        Aucune clé ne fuite : ``fields_get`` ne renvoie pas de données. Mais la
        description d'un modèle de clés d'API indique où chercher, ce qui est
        déjà trop pour un modèle dont l'existence ne regarde personne d'autre que
        l'administration.

        Constaté sur l'instance, par le test de contournement RPC générique.
        """
        self.check_access("read")
        return super().fields_get(allfields=allfields, attributes=attributes)


    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if not record.key_hash:
                record.action_generate_key()
        return records

    def unlink(self):
        """Refuse deletion while request history references the key.

        An audit trail that points at a missing key is not an audit trail.
        """
        for record in self:
            if self.env["dally.api.request"].search_count([("api_key_id", "=", record.id)]):
                raise UserError(
                    _(
                        "Key '%(name)s' has request history and cannot be deleted. "
                        "Deactivate it instead — that revokes it immediately.",
                        name=record.name,
                    )
                )
        return super().unlink()

    # ─── Authentication ──────────────────────────────────────────────

    @api.model
    def _authenticate(self, raw_key, source_ip=None):
        """Resolve a raw key to an active, non-expired, IP-allowed key record.

        Raises ``AccessDenied`` for every failure mode, with no detail about
        which one: distinguishing "unknown key" from "expired key" would tell an
        attacker whether a key exists.
        """
        if not raw_key or not isinstance(raw_key, str):
            raise AccessDenied()

        candidate_hash = self._hash_key(raw_key)

        # sudo: authentication happens before any user context exists. The lookup
        # is by hash only, so this cannot be steered into reading other records.
        keys = self.sudo().search([("key_prefix", "=", raw_key[:PREFIX_LENGTH])])

        matched = None
        for key in keys:
            # Constant-time comparison: a short-circuiting == leaks how many
            # leading characters were correct through response timing.
            if hmac.compare_digest(key.key_hash or "", candidate_hash):
                matched = key
                break

        if not matched:
            raise AccessDenied()

        if matched.expires_on and matched.expires_on < fields.Date.context_today(matched):
            raise AccessDenied()

        if not matched._ip_allowed(source_ip):
            raise AccessDenied()

        return matched

    def _ip_allowed(self, source_ip):
        """Check the source IP against the allowlist.

        Note: the address comes from X-Forwarded-For, set by our own nginx. It is
        trustworthy only because nginx overwrites the client-supplied value. If
        Odoo were ever exposed without that proxy, this check would be bypassable
        and must not be relied on alone.
        """
        self.ensure_one()
        allowed = [ip.strip() for ip in (self.allowed_ips or "").split(",") if ip.strip()]
        if not allowed:
            return True
        return source_ip in allowed

    def _register_use(self):
        """Record usage. Best-effort: never fail a request over telemetry."""
        self.ensure_one()
        try:
            self.sudo().write({
                "last_used_at": fields.Datetime.now(),
                "request_count": self.request_count + 1,
            })
        except Exception:  # noqa: BLE001 - telemetry must not break the API
            pass
