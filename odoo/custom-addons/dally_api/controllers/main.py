# -*- coding: utf-8 -*-
"""Shared plumbing for the DallyTrading REST API.

Design choices worth stating, because they are deliberate:

* **``type='http'`` with explicit JSON**, not Odoo's ``type='json'`` RPC
  envelope. The RPC envelope is an Odoo-internal protocol that has changed shape
  across versions and wraps errors in a way HTTP clients do not expect. Plain
  HTTP + JSON gives real status codes and survives Odoo upgrades.

* **No generic model access.** Every endpoint maps to one business operation.
  There is deliberately no way to name a model or a method from outside (§40).

* **Acting user, not superuser.** Requests run as a dedicated integration user
  whose groups bound what the API can do, so record rules and ACLs still apply.
  ``sudo()`` is used only for authentication and logging, where no user context
  exists yet.
"""

import json
import logging
import uuid

from odoo import _, http, SUPERUSER_ID
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

#: Largest request body accepted, in bytes. nginx caps uploads too; this is the
#: application-level backstop.
MAX_BODY_BYTES = 512 * 1024

#: Default calls per minute per key when not configured.
DEFAULT_RATE_LIMIT = 60


class DallyApiError(Exception):
    """An error with an HTTP status and a stable machine-readable code."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class DallyApiController(http.Controller):
    """Base controller. Endpoints subclass this and reuse the helpers."""

    # ─── Responses ───────────────────────────────────────────────────

    @staticmethod
    def _json_response(body, status=200, request_id=None, cache_control=None):
        """Serialise a response.

        ``cache_control`` defaults to ``no-store``: almost every endpoint here
        returns per-customer data, and a cached tracking result served to the wrong
        visitor would be a data breach. Only genuinely public, identical-for-everyone
        responses — the service catalogue — override it, and they must do so
        explicitly.
        """
        payload = dict(body)
        if request_id:
            payload["request_id"] = request_id
        return Response(
            json.dumps(payload, default=str),
            status=status,
            headers=[
                ("Content-Type", "application/json; charset=utf-8"),
                ("Cache-Control", cache_control or "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )

    @classmethod
    def _success(cls, data, status=200, request_id=None):
        return cls._json_response({"success": True, "data": data}, status, request_id)

    @classmethod
    def _error(cls, status, code, message, request_id=None):
        return cls._json_response(
            {"success": False, "error": {"code": code, "message": message}},
            status,
            request_id,
        )

    # ─── Request parsing ─────────────────────────────────────────────

    @staticmethod
    def _client_ip():
        """Source IP as seen through nginx.

        Trustworthy only because nginx sets X-Forwarded-For itself; Odoo runs
        with proxy_mode = True and reads the proxied address.
        """
        return request.httprequest.remote_addr

    @classmethod
    def _read_json_body(cls):
        raw = request.httprequest.get_data()
        if len(raw) > MAX_BODY_BYTES:
            raise DallyApiError(413, "payload_too_large",
                                _("Request body exceeds the allowed size."))
        if not raw:
            raise DallyApiError(400, "empty_body", _("A JSON body is required."))
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise DallyApiError(400, "invalid_json",
                                _("The request body is not valid JSON."))
        if not isinstance(parsed, dict):
            raise DallyApiError(400, "invalid_json",
                                _("The request body must be a JSON object."))
        return parsed

    # ─── Authentication ──────────────────────────────────────────────

    @classmethod
    def _authenticate(cls, required_scope):
        """Authenticate the caller and check its scope.

        Returns ``(api_key, env)`` where ``env`` acts as the key's integration
        user — not as superuser.
        """
        raw_key = request.httprequest.headers.get("X-API-Key")
        if not raw_key:
            raise DallyApiError(401, "missing_api_key",
                                _("The X-API-Key header is required."))

        try:
            api_key = request.env["dally.api.key"].sudo()._authenticate(
                raw_key, source_ip=cls._client_ip()
            )
        except AccessDenied:
            # Uniform message: never reveal whether the key exists, is expired or
            # is used from a disallowed address.
            raise DallyApiError(401, "invalid_api_key",
                                _("Invalid API key."))

        if not api_key.has_scope(required_scope):
            raise DallyApiError(
                403, "insufficient_scope",
                _("This key does not carry the '%s' scope.", required_scope),
            )

        if not api_key.user_id or not api_key.user_id.active:
            raise DallyApiError(500, "misconfigured_key",
                                _("This key has no active integration user."))

        cls._check_rate_limit(api_key)

        env = request.env(user=api_key.user_id.id)
        # La clé a été résolue dans l'environnement NON authentifié (auth="none",
        # donc uid None). La rebasculer sur l'utilisateur agissant est nécessaire :
        # `_register_use()` écrit dessus, et une écriture dans un environnement sans
        # utilisateur casse le flush de fin de requête — le contrôle d'accès y
        # appelle ensure_one() sur un res.users vide. Constaté en production : la
        # création d'une opportunité aboutissait (201 journalisé) puis la requête
        # se terminait en 500.
        return api_key.with_env(env), env

    @classmethod
    def _check_rate_limit(cls, api_key):
        """Coarse per-key limit on logged calls.

        This is a backstop, not the primary defence. It only counts calls that
        reached the log, so it does not throttle failed authentication attempts.
        Real rate limiting belongs at the reverse proxy (§40) — see
        infrastructure/nginx/ for the limit_req configuration.
        """
        limit = int(
            request.env["ir.config_parameter"].sudo().get_param(
                "dally_api.rate_limit_per_minute", DEFAULT_RATE_LIMIT
            )
        )
        if limit <= 0:
            return

        request.env.cr.execute(
            """
            SELECT count(*) FROM dally_api_request
             WHERE api_key_id = %s
               AND create_date > (now() at time zone 'UTC') - interval '1 minute'
            """,
            (api_key.id,),
        )
        used = request.env.cr.fetchone()[0]
        if used >= limit:
            raise DallyApiError(
                429, "rate_limit_exceeded",
                _("Rate limit reached (%(limit)s requests per minute).", limit=limit),
            )

    # ─── Validation helpers ──────────────────────────────────────────

    @staticmethod
    def _require(payload, *field_names):
        """Reject a payload missing any required field.

        A string of spaces counts as missing: a form that submits "   " has not
        supplied a name.
        """
        missing = []
        for name in field_names:
            value = payload.get(name)
            if value is None:
                missing.append(name)
            elif isinstance(value, str) and not value.strip():
                missing.append(name)
        if missing:
            raise DallyApiError(
                422, "missing_fields",
                _("Missing required field(s): %s", ", ".join(missing)),
            )

    @staticmethod
    def _require_email_or_phone(payload):
        """At least one way to reply must be provided.

        A request with neither is unusable: nobody can be called back.
        """
        if not (payload.get("email") or "").strip() and not (payload.get("phone") or "").strip():
            raise DallyApiError(
                422, "no_contact_channel",
                _("Provide at least an email address or a phone number."),
            )

    @staticmethod
    def _validate_uuid(value):
        """Idempotency keys must be real UUIDs.

        Accepting arbitrary strings would let a client send a constant value and
        permanently block every later submission.
        """
        if not value:
            raise DallyApiError(422, "missing_request_uuid",
                                _("request_uuid is required."))
        try:
            uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            raise DallyApiError(422, "invalid_request_uuid",
                                _("request_uuid must be a valid UUID."))
        return str(value)

    # ─── Dispatch ────────────────────────────────────────────────────

    @classmethod
    def _handle(cls, endpoint, required_scope, handler):
        """Run an endpoint with uniform auth, idempotency, logging and errors.

        Every endpoint funnels through here so that behaviour cannot drift
        between them — the usual way one endpoint ends up leaking a traceback.
        """
        correlation_id = str(uuid.uuid4())
        api_key = None
        payload = None
        source_ip = cls._client_ip()

        try:
            payload = cls._read_json_body()
            api_key, env = cls._authenticate(required_scope)
            request_uuid = cls._validate_uuid(payload.get("request_uuid"))

            # Replay a previous successful identical call (§41).
            replay = env["dally.api.request"].find_replay(request_uuid, endpoint)
            if replay and replay.response:
                try:
                    stored = json.loads(replay.response)
                except ValueError:
                    stored = None
                if stored is not None:
                    _logger.info(
                        "[%s] %s replayed for request_uuid=%s",
                        correlation_id, endpoint, request_uuid,
                    )
                    return cls._json_response(stored, 200, correlation_id)

            data, status = handler(env, payload, api_key)

            # Handlers pass the created recordset back under "_record" so it can
            # be logged. It is removed before anything is serialised: it must
            # appear neither in the response nor in the stored replay body.
            created_record = None
            if isinstance(data, dict):
                created_record = data.pop("_record", None)

            body = {"success": True, "data": data}
            env["dally.api.request"].log(
                request_uuid=request_uuid,
                endpoint=endpoint,
                status_code=status,
                api_key=api_key,
                source_ip=source_ip,
                payload=cls._loggable_payload(payload),
                response=json.dumps(body, default=str),
                record=created_record,
            )
            api_key._register_use()

            _logger.info("[%s] %s -> %s", correlation_id, endpoint, status)
            return cls._json_response(body, status, correlation_id)

        except DallyApiError as error:
            _logger.warning(
                "[%s] %s rejected: %s (%s)",
                correlation_id, endpoint, error.code, error.status,
            )
            cls._log_failure(endpoint, error.status, api_key, source_ip, payload,
                             error.message)
            return cls._error(error.status, error.code, error.message, correlation_id)

        except (ValidationError, UserError) as error:
            # Business rule rejected the request: the caller can fix it.
            message = getattr(error, "args", [None])[0] or str(error)
            _logger.info("[%s] %s business error: %s", correlation_id, endpoint, message)
            cls._log_failure(endpoint, 422, api_key, source_ip, payload, message)
            return cls._error(422, "validation_error", str(message), correlation_id)

        except AccessError:
            _logger.warning("[%s] %s access denied", correlation_id, endpoint)
            cls._log_failure(endpoint, 403, api_key, source_ip, payload, "access denied")
            return cls._error(403, "forbidden",
                              _("This key is not allowed to perform this operation."),
                              correlation_id)

        except Exception:  # noqa: BLE001
            # Log the traceback server-side; return nothing revealing. A stack
            # trace in an HTTP response is an information leak.
            _logger.exception("[%s] %s unexpected failure", correlation_id, endpoint)
            cls._log_failure(endpoint, 500, api_key, source_ip, payload,
                             "internal error")
            return cls._error(
                500, "internal_error",
                _("An internal error occurred. Quote reference %s to support.",
                  correlation_id),
                correlation_id,
            )

    @staticmethod
    def _loggable_payload(payload):
        """Strip anything that must never be written to the log."""
        if not isinstance(payload, dict):
            return None
        redacted = dict(payload)
        for key in ("api_key", "password", "token", "secret"):
            if key in redacted:
                redacted[key] = "[redacted]"
        return json.dumps(redacted, default=str)

    @classmethod
    def _log_failure(cls, endpoint, status, api_key, source_ip, payload, message):
        """Log a failed call, tolerating a broken transaction.

        After an exception the cursor may be unusable; a savepoint keeps the
        logging attempt from masking the original error.
        """
        try:
            request_uuid = ""
            if isinstance(payload, dict):
                request_uuid = str(payload.get("request_uuid") or "")
            # Journaliser au nom d'un utilisateur réel. `request.env` est ici
            # l'environnement non authentifié (uid None) : y écrire produit un
            # create_uid NULL et fait échouer le flush de fin de requête.
            log_env = request.env
            if api_key and api_key.user_id:
                log_env = request.env(user=api_key.user_id.id)
            else:
                log_env = request.env(user=SUPERUSER_ID)
            with request.env.cr.savepoint():
                log_env["dally.api.request"].sudo().log(
                    request_uuid=request_uuid,
                    endpoint=endpoint,
                    status_code=status,
                    api_key=api_key,
                    source_ip=source_ip,
                    payload=cls._loggable_payload(payload),
                    error_message=str(message),
                )
        except Exception:  # noqa: BLE001
            _logger.debug("Could not log API failure for %s", endpoint, exc_info=True)
