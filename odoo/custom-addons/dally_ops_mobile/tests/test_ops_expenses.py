# -*- coding: utf-8 -*-
"""Les dépenses de terrain, et la photo qui les justifie.

## Ce que ces tests protègent avant tout

Deux propriétés, et elles ne sont pas symétriques.

La première : une dépense enregistrée ne disparaît jamais. Ni un justificatif
refusé, ni une photo trop lourde, ni un second envoi ne doivent défaire ce qui
est déjà sorti de la caisse. Plusieurs tests ci-dessous ne vérifient rien
d'autre que cela : après l'échec, la dépense est toujours là, inchangée.

La seconde : Dally Ops impute toujours à un départ, alors que le modèle
partagé, lui, ne l'exige pas. Les dépenses venues du tableur n'ont pas de
consolidation ; un test le prouve explicitement, parce que rendre ce champ
obligatoire aurait cassé un flux vivant sans qu'aucun test ne l'annonce.
"""

import ast
import inspect
import json
import uuid

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.dally_freight_consolidation.models.consolidation import (
    _CONSOLIDATION_BYPASS_TOKEN,
)

from odoo.addons.dally_ops_mobile.models.ops_errors import (
    DallyOpsConflict,
    DallyOpsError,
    DallyOpsNotFound,
)
from odoo.addons.dally_ops_mobile.tests.common import (
    MODELES_METIER_FERMES,
    MODELES_TECHNIQUES_LISIBLES,
    modeles_lisibles,
)

#: Des fichiers réduits à ce qui compte : leurs premiers octets.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x2a" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x2a" * 64
WEBP = b"RIFF" + b"\x64\x00\x00\x00" + b"WEBP" + b"\x2a" * 64
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x2a" * 64
HTML = b"<html><script>alert(1)</script></html>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'
ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"\x2a" * 64


def code_seul(module):
    """Le code d'un module, ses textes d'explication retirés.

    Un contrôle négatif qui chercherait « sudo » dans le fichier entier serait
    satisfait par le mot écrit dans un commentaire. On compare le code.
    """
    arbre = ast.parse(inspect.getsource(module))
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.Module, ast.ClassDef,
                                  ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        premier = noeud.body[0] if noeud.body else None
        if (isinstance(premier, ast.Expr)
                and isinstance(premier.value, ast.Constant)
                and isinstance(premier.value.value, str)):
            noeud.body = noeud.body[1:] or [ast.Pass()]
    return ast.unparse(arbre)


@tagged("post_install", "-at_install", "dally")
class TestOpsExpenses(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Une société dédiée : la base de banc porte des départs et des
        # dépenses venus des étapes précédentes, et un comptage global les
        # aurait ramassés.
        cls.societe = cls.env["res.company"].create({"name": "Ops Dépenses SA"})
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Dépenses Autre"})

        cls.eur = cls.env.ref("base.EUR")
        cls.xof = cls.env.ref("base.XOF")
        (cls.eur | cls.xof).write({"active": True})

        cls.logisticien = cls._compte(
            "dep.logi", "Gilles Dépenses",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Gilles")
        cls.responsable = cls._compte(
            "dep.resp", "Dalanda Dépenses",
            "dally_ops_mobile.group_dally_ops_supervisor", acteur="Dalanda")
        cls.sans_acteur = cls._compte(
            "dep.sansacteur", "Sans acteur",
            "dally_ops_mobile.group_dally_ops_logistician", acteur=False)
        cls.non_ops = cls._compte("dep.autre", "Sans rôle", "base.group_user")

        cls.logisticien_autre = cls.env["res.users"].create({
            "name": "Logisticien Autre", "login": "dep.autresociete",
            "group_ids": [(6, 0, [cls.env.ref(
                "dally_ops_mobile.group_dally_ops_logistician").id])],
            "company_id": cls.autre_societe.id,
            "company_ids": [(6, 0, [cls.autre_societe.id])],
            "dally_ops_cash_actor": "Autre",
        })

        cls.consolidation = cls._consolidation("AIR-DSS-CDG-DEP-001", "collecting")

    # ─── Fabriques ───────────────────────────────────────────────────

    @classmethod
    def _compte(cls, login, nom, groupe, acteur=None):
        valeurs = {
            "name": nom, "login": login,
            "group_ids": [(6, 0, [cls.env.ref(groupe).id])],
            "company_id": cls.societe.id,
            "company_ids": [(6, 0, [cls.societe.id])],
        }
        if acteur:
            valeurs["dally_ops_cash_actor"] = acteur
        return cls.env["res.users"].create(valeurs)

    @classmethod
    def _consolidation(cls, reference, etat, mode="air", societe=None, actif=True):
        """Un départ dans l'état voulu, sans rejouer tout le cycle métier.

        Le modèle refuse une création ailleurs qu'en brouillon ou en collecte,
        et n'accepte ensuite que ses propres actions — dont `action_mark_ready`,
        qui exige des lignes chargées. Ces tests portent sur les dépenses, pas
        sur la machine à états : ils empruntent le contournement déjà utilisé
        par `test_ops_consolidations`.
        """
        consolidation = cls.env["dally.freight.consolidation"].create({
            "name": reference, "state": "collecting", "active": actif,
            "company_id": (societe or cls.societe).id, "transport_mode": mode,
            "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })
        if etat != "collecting":
            cls._etat(consolidation, etat)
        return consolidation

    @staticmethod
    def _etat(consolidation, etat):
        consolidation.with_context(
            _dally_consolidation_bypass=_CONSOLIDATION_BYPASS_TOKEN
        ).write({"state": etat})

    def _service(self, utilisateur=None):
        return (self.env["dally.ops.expense.service"]
                .with_user(utilisateur or self.logisticien)
                .with_company(self.societe))

    def _charge(self, **changements):
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "consolidation_reference": self.consolidation.name,
            "expense_date": "2026-08-20",
            "category": "Manutention",
            "description": "Portage entrepôt",
            "beneficiary": "Équipe entrepôt",
            "amount": 15000.0,
            "currency_code": "XOF",
            "payment_method": "cash",
            "comment": "",
        }
        charge.update(changements)
        return charge

    def _depense(self, reference):
        return self.env["dally.cash.expense"].sudo().search([
            ("external_expense_key", "=", "ops:%s" % reference),
            ("company_id", "=", self.societe.id),
        ], limit=1)

    # ─── Le rôle ─────────────────────────────────────────────────────

    def test_un_compte_sans_role_ops_ne_peut_rien_faire(self):
        for appel in (
            lambda: self._service(self.non_ops).list_expense_consolidations(),
            lambda: self._service(self.non_ops).record_expense(self._charge()),
            lambda: self._service(self.non_ops).list_expenses(self.consolidation.name),
            lambda: self._service(self.non_ops).attach_receipt(
                str(uuid.uuid4()), str(uuid.uuid4()), "t.jpg", JPEG),
        ):
            with self.assertRaises(AccessError):
                appel()

    def test_le_responsable_enregistre_aussi_une_depense(self):
        resultat = self._service(self.responsable).record_expense(self._charge())
        self.assertEqual(resultat["status"], "created")
        self.assertEqual(resultat["expense"]["paid_by"], "Dalanda")

    # ─── Les départs éligibles ───────────────────────────────────────

    def test_les_departs_eligibles_couvrent_toute_la_vie_du_depart(self):
        attendus = set()
        for index, etat in enumerate(
                ("collecting", "collection_closed", "ready", "departed", "arrived")):
            attendus.add(self._consolidation("AIR-DEP-OK-%s" % index, etat).name)
        attendus.add(self.consolidation.name)

        for index, etat in enumerate(("draft", "cancelled", "closed")):
            self._consolidation("AIR-DEP-NON-%s" % index, etat)
        self._consolidation("ROAD-DEP-NON", "collecting", mode="road")
        self._consolidation("AIR-DEP-AUTRE", "collecting", societe=self.autre_societe)
        self._consolidation("AIR-DEP-INACTIF", "collecting", actif=False)

        references = {
            depart["reference"]
            for depart in self._service().list_expense_consolidations()
        }
        self.assertEqual(references, attendus)

    def test_le_depart_expose_sa_reference_et_pas_son_identifiant(self):
        depart = self._service().list_expense_consolidations()[0]
        self.assertEqual(
            sorted(depart), ["destination", "origin", "reference", "state", "transport_mode"])

    def test_un_depart_ferme_refuse_une_depense(self):
        for etat in ("draft", "cancelled", "closed"):
            depart = self._consolidation("AIR-DEP-REFUS-%s" % etat, etat)
            with self.assertRaises(DallyOpsNotFound):
                self._service().record_expense(
                    self._charge(consolidation_reference=depart.name))

    def test_un_depart_d_une_autre_societe_est_introuvable(self):
        depart = self._consolidation(
            "AIR-DEP-CLOISON", "collecting", societe=self.autre_societe)
        with self.assertRaises(DallyOpsNotFound):
            self._service().record_expense(
                self._charge(consolidation_reference=depart.name))

    # ─── L'enregistrement ────────────────────────────────────────────

    def test_une_depense_est_ecrite_telle_que_le_serveur_la_decide(self):
        charge = self._charge()
        resultat = self._service().record_expense(charge)
        self.assertEqual(resultat["status"], "created")

        depense = self._depense(charge["request_uuid"])
        self.assertTrue(depense)
        self.assertEqual(depense.state, "review")
        self.assertEqual(depense.source, "backoffice")
        self.assertEqual(depense.consolidation_id, self.consolidation)
        self.assertEqual(depense.company_id, self.societe)
        self.assertEqual(depense.currency_id, self.xof)
        self.assertEqual(depense.payment_method, "cash")
        self.assertEqual(depense.category, "Manutention")
        self.assertEqual(depense.total_amount, 15000.0)
        self.assertFalse(depense.has_receipt)

    def test_une_seule_allocation_au_nom_de_l_acteur_configure(self):
        charge = self._charge()
        self._service().record_expense(charge)
        allocations = self._depense(charge["request_uuid"]).allocation_ids
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations.actor_name, "Gilles")
        self.assertEqual(allocations.amount, 15000.0)

    def test_le_nom_odoo_ne_devient_jamais_l_acteur_de_caisse(self):
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service(self.sans_acteur).record_expense(self._charge())
        self.assertEqual(erreur.exception.code, "cash_actor_not_configured")
        self.assertEqual(
            self.env["dally.cash.expense"].sudo().search_count(
                [("company_id", "=", self.societe.id)]), 0)

    def test_les_instantanes_de_conversion_restent_vides(self):
        charge = self._charge()
        self._service().record_expense(charge)
        depense = self._depense(charge["request_uuid"])
        # Les renseigner exigerait un taux que personne n'a calculé ici.
        self.assertEqual(depense.total_eur_snapshot, 0.0)
        self.assertEqual(depense.total_xof_snapshot, 0.0)

    def test_la_cle_externe_annonce_son_origine(self):
        charge = self._charge()
        self._service().record_expense(charge)
        self.assertEqual(
            self._depense(charge["request_uuid"]).external_expense_key,
            "ops:%s" % charge["request_uuid"])

    # ─── La validation ───────────────────────────────────────────────

    def test_un_montant_nul_ou_negatif_est_refuse(self):
        for montant in (0, -1, 0.0, -12.5, True, "15000", None):
            with self.assertRaises(DallyOpsError):
                self._service().record_expense(self._charge(amount=montant))

    def test_seuls_quatre_modes_de_paiement_sont_acceptes(self):
        for mode in ("cash", "wave", "bank", "other"):
            resultat = self._service().record_expense(
                self._charge(payment_method=mode))
            self.assertEqual(resultat["expense"]["payment_method"], mode)
        for mode in ("wvae", "orange_money", "", None, "CASH", 12):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_expense(self._charge(payment_method=mode))
            self.assertEqual(erreur.exception.code, "payment_method_not_allowed")

    def test_une_date_illisible_ou_future_est_refusee(self):
        for valeur in ("", "20/08/2026", "2026-13-01", "hier", None, 20260820,
                       "2099-01-01"):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_expense(self._charge(expense_date=valeur))
            self.assertEqual(erreur.exception.code, "invalid_expense_date")

    def test_une_devise_inconnue_est_refusee(self):
        with self.assertRaises(DallyOpsError) as erreur:
            self._service().record_expense(self._charge(currency_code="ZZZ"))
        self.assertEqual(erreur.exception.code, "currency_not_available")

    def test_un_champ_decide_par_le_serveur_est_refuse(self):
        for champ, valeur in (
            ("state", "validated"),
            ("source", "google_sheets"),
            ("external_expense_key", "sheet:1"),
            ("company_id", 1),
            ("consolidation_id", 1),
            ("actor_name", "Quelqu'un d'autre"),
            ("total_xof_snapshot", 999),
            ("receipt_attachment_id", 1),
        ):
            with self.assertRaises(DallyOpsError):
                self._service().record_expense(self._charge(**{champ: valeur}))

    def test_un_champ_obligatoire_manquant_est_refuse(self):
        for champ in ("consolidation_reference", "expense_date", "category",
                      "description", "amount", "currency_code", "payment_method"):
            charge = self._charge()
            charge.pop(champ)
            with self.assertRaises(DallyOpsError):
                self._service().record_expense(charge)

    # ─── L'idempotence ───────────────────────────────────────────────

    def test_une_demande_rejouee_ne_cree_qu_une_depense(self):
        charge = self._charge()
        premier = self._service().record_expense(charge)
        second = self._service().record_expense(dict(charge))
        self.assertEqual(premier["status"], "created")
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(premier["expense"]["reference"], second["expense"]["reference"])
        self.assertEqual(
            self.env["dally.cash.expense"].sudo().search_count([
                ("external_expense_key", "=", "ops:%s" % charge["request_uuid"]),
            ]), 1)

    def test_le_meme_identifiant_avec_un_autre_montant_est_un_conflit(self):
        charge = self._charge()
        self._service().record_expense(charge)
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service().record_expense(dict(charge, amount=99000.0))
        self.assertEqual(erreur.exception.code, "idempotency_conflict")

    def test_un_identifiant_de_demande_invalide_est_refuse(self):
        for valeur in ("", "pas-un-uuid", None, 42):
            with self.assertRaises(DallyOpsError):
                self._service().record_expense(self._charge(request_uuid=valeur))

    def test_le_rejeu_dit_la_verite_sur_le_justificatif_joint_depuis(self):
        charge = self._charge()
        premier = self._service().record_expense(charge)
        self.assertFalse(premier["expense"]["has_receipt"])
        self._service().attach_receipt(
            premier["expense"]["reference"], str(uuid.uuid4()), "ticket.jpg", JPEG)
        rejeu = self._service().record_expense(dict(charge))
        self.assertTrue(rejeu["expense"]["has_receipt"])

    # ─── La lecture ──────────────────────────────────────────────────

    def test_la_liste_totalise_par_devise_sans_convertir(self):
        self._service().record_expense(
            self._charge(amount=15000.0, currency_code="XOF"))
        self._service().record_expense(
            self._charge(amount=5000.0, currency_code="XOF"))
        self._service().record_expense(
            self._charge(amount=42.5, currency_code="EUR"))

        resultat = self._service().list_expenses(self.consolidation.name)
        self.assertEqual(resultat["consolidation_reference"], self.consolidation.name)
        self.assertEqual(len(resultat["expenses"]), 3)
        self.assertEqual(resultat["summary"], [
            {"currency_code": "EUR", "amount": 42.5},
            {"currency_code": "XOF", "amount": 20000.0},
        ])

    def test_la_liste_ignore_les_depenses_d_un_autre_depart(self):
        autre = self._consolidation("AIR-DEP-LISTE-2", "collecting")
        self._service().record_expense(self._charge())
        self._service().record_expense(
            self._charge(consolidation_reference=autre.name))
        self.assertEqual(
            len(self._service().list_expenses(self.consolidation.name)["expenses"]), 1)

    def test_la_liste_reste_lisible_sur_un_depart_clos(self):
        # On ne peut plus dépenser sur un départ fermé, mais on doit encore
        # pouvoir relire ce qui y a été dépensé.
        self._service().record_expense(self._charge())
        self._etat(self.consolidation.sudo(), "closed")
        self.assertEqual(
            len(self._service().list_expenses(self.consolidation.name)["expenses"]), 1)

    def test_le_dto_ne_porte_aucun_identifiant_odoo(self):
        charge = self._charge()
        self._service().record_expense(charge)
        rendu = json.dumps(self._service().list_expenses(self.consolidation.name))
        for interdit in ("expense_id", "consolidation_id", "company_id",
                         "currency_id", "attachment_id", "partner_id",
                         "external_expense_key", "allocation_ids"):
            self.assertNotIn(interdit, rendu)

    # ─── Le justificatif ─────────────────────────────────────────────

    def _reference_creee(self):
        charge = self._charge()
        return self._service().record_expense(charge)["expense"]["reference"]

    def test_une_photo_est_rangee_dans_ir_attachment_et_rien_d_autre(self):
        reference = self._reference_creee()
        resultat = self._service().attach_receipt(
            reference, str(uuid.uuid4()), "ticket.jpg", JPEG)
        self.assertEqual(resultat["status"], "attached")
        self.assertTrue(resultat["expense"]["has_receipt"])

        depense = self._depense(reference)
        piece = depense.receipt_attachment_id
        self.assertTrue(piece)
        self.assertEqual(piece.raw, JPEG)
        self.assertEqual(piece.mimetype, "image/jpeg")
        self.assertEqual(piece.res_model, "dally.cash.expense")
        self.assertEqual(piece.res_id, depense.id)
        self.assertFalse(piece.public)

    def test_le_type_est_lu_dans_les_octets_pas_dans_le_nom(self):
        for contenu, attendu in ((JPEG, "image/jpeg"), (PNG, "image/png"),
                                 (WEBP, "image/webp"), (HEIC, "image/heic")):
            reference = self._reference_creee()
            self._service().attach_receipt(
                reference, str(uuid.uuid4()), "n_importe_quoi.txt", contenu)
            self.assertEqual(
                self._depense(reference).receipt_attachment_id.mimetype, attendu)

    def test_un_fichier_dangereux_deguise_en_photo_est_refuse(self):
        for contenu in (HTML, SVG, ELF, PDF, b"texte simple"):
            reference = self._reference_creee()
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().attach_receipt(
                    reference, str(uuid.uuid4()), "photo.jpg", contenu)
            self.assertEqual(erreur.exception.code, "receipt_type_not_allowed")
            # Le refus n'a rien emporté : la dépense est intacte.
            self.assertTrue(self._depense(reference))
            self.assertFalse(self._depense(reference).has_receipt)

    def test_une_photo_trop_lourde_est_refusee_et_la_depense_demeure(self):
        reference = self._reference_creee()
        trop = JPEG + b"\x00" * (10 * 1024 * 1024)
        with self.assertRaises(DallyOpsError) as erreur:
            self._service().attach_receipt(
                reference, str(uuid.uuid4()), "grande.jpg", trop)
        self.assertEqual(erreur.exception.code, "receipt_too_large")
        self.assertTrue(self._depense(reference))
        self.assertFalse(self._depense(reference).has_receipt)

    def test_une_photo_vide_est_refusee(self):
        reference = self._reference_creee()
        for contenu in (b"", None, "pas des octets"):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().attach_receipt(
                    reference, str(uuid.uuid4()), "vide.jpg", contenu)
            self.assertEqual(erreur.exception.code, "receipt_empty")

    def test_une_seconde_photo_ne_remplace_pas_la_premiere_en_silence(self):
        reference = self._reference_creee()
        self._service().attach_receipt(reference, str(uuid.uuid4()), "un.jpg", JPEG)
        piece = self._depense(reference).receipt_attachment_id
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service().attach_receipt(reference, str(uuid.uuid4()), "deux.png", PNG)
        self.assertEqual(erreur.exception.code, "receipt_already_attached")
        self.assertEqual(self._depense(reference).receipt_attachment_id, piece)
        self.assertEqual(piece.raw, JPEG)

    def test_un_envoi_de_photo_rejoue_ne_produit_qu_une_piece(self):
        reference = self._reference_creee()
        demande = str(uuid.uuid4())
        premier = self._service().attach_receipt(reference, demande, "t.jpg", JPEG)
        second = self._service().attach_receipt(reference, demande, "t.jpg", JPEG)
        self.assertEqual(premier["status"], "attached")
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(
            self.env["ir.attachment"].sudo().search_count([
                ("res_model", "=", "dally.cash.expense"),
                ("res_id", "=", self._depense(reference).id),
            ]), 1)

    def test_le_meme_envoi_avec_un_autre_fichier_est_un_conflit(self):
        reference = self._reference_creee()
        demande = str(uuid.uuid4())
        self._service().attach_receipt(reference, demande, "t.jpg", JPEG)
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service().attach_receipt(reference, demande, "t.png", PNG)
        self.assertEqual(erreur.exception.code, "idempotency_conflict")

    def test_le_nom_de_fichier_recu_ne_traverse_pas_tel_quel(self):
        cas = (
            ("../../etc/passwd", "passwd.jpg"),
            (r"C:\\Users\\op\\photo.jpg", "photo.jpg"),
            ("re çu; rm -rf.jpg", "reurm-rf.jpg"),
            ("photos/2026/../ticket.jpg", "ticket.jpg"),
            ("/.jpg", "jpg.jpg"),
            ("", "justificatif.jpg"),
            (None, "justificatif.jpg"),
            ("." * 10, "justificatif.jpg"),
        )
        for recu, attendu in cas:
            reference = self._reference_creee()
            self._service().attach_receipt(reference, str(uuid.uuid4()), recu, JPEG)
            self.assertEqual(
                self._depense(reference).receipt_attachment_id.name, attendu)

    def test_une_photo_pour_une_depense_inconnue_est_introuvable(self):
        with self.assertRaises(DallyOpsNotFound) as erreur:
            self._service().attach_receipt(
                str(uuid.uuid4()), str(uuid.uuid4()), "t.jpg", JPEG)
        self.assertEqual(erreur.exception.code, "expense_not_found")

    def test_une_depense_d_une_autre_societe_est_introuvable(self):
        reference = self._reference_creee()
        autre = (self.env["dally.ops.expense.service"]
                 .with_user(self.logisticien_autre)
                 .with_company(self.autre_societe))
        with self.assertRaises(DallyOpsNotFound):
            autre.attach_receipt(reference, str(uuid.uuid4()), "t.jpg", JPEG)

    # ─── Le journal ──────────────────────────────────────────────────

    def _audit(self, action):
        return self.env["dally.ops.audit.event"].sudo().search([
            ("company_id", "=", self.societe.id), ("action", "=", action),
        ])

    def test_chaque_geste_laisse_une_trace_nominative(self):
        charge = self._charge()
        reference = self._service().record_expense(charge)["expense"]["reference"]
        self._service().record_expense(dict(charge))
        demande = str(uuid.uuid4())
        self._service().attach_receipt(reference, demande, "t.jpg", JPEG)
        self._service().attach_receipt(reference, demande, "t.jpg", JPEG)

        for action in ("expense_recorded", "expense_request_replayed",
                       "expense_receipt_attached", "expense_receipt_request_replayed"):
            evenements = self._audit(action)
            self.assertEqual(len(evenements), 1, action)
            self.assertEqual(evenements.operator_user_id, self.logisticien)
            self.assertEqual(evenements.entity_model, "dally.cash.expense")
            self.assertTrue(evenements.entity_res_id)

    def test_le_journal_ne_recopie_ni_montant_ni_beneficiaire(self):
        charge = self._charge(beneficiary="Moussa Diop", amount=77777.0)
        self._service().record_expense(charge)
        evenement = self._audit("expense_recorded")
        rendu = json.dumps({
            champ: evenement.read([champ])[0][champ]
            for champ in ("action", "entity_model", "entity_res_id", "request_uuid")
        })
        self.assertNotIn("Moussa", rendu)
        self.assertNotIn("77777", rendu)

    # ─── Le flux historique ──────────────────────────────────────────

    def test_une_depense_de_tableur_sans_depart_continue_de_fonctionner(self):
        """Le champ `consolidation_id` reste facultatif au niveau du modèle.

        Dally Ops l'exige, mais le connecteur tableur ne peut pas le fournir :
        ses lignes n'ont pas de départ et n'en auront jamais. Rendre le champ
        obligatoire aurait cassé ce flux sans qu'aucun test ne le dise.
        """
        depense, cree = (self.env["dally.cash.expense"].sudo()
                         .with_company(self.societe)
                         .upsert_from_sync(
                             {"external_expense_key": "sheet:2026-08-20:001",
                              "expense_date": "2026-08-20",
                              "category": "Carburant", "description": "Gasoil",
                              "currency_id": self.xof.id, "source": "google_sheets"},
                             [{"actor_name": "Papa", "amount": 30000.0}]))
        self.assertTrue(cree)
        self.assertFalse(depense.consolidation_id)
        self.assertFalse(depense.has_receipt)
        self.assertEqual(depense.total_amount, 30000.0)

        # Et elle n'apparaît dans aucune liste de départ.
        self._service().record_expense(self._charge())
        self.assertEqual(
            len(self._service().list_expenses(self.consolidation.name)["expenses"]), 1)

    def test_une_depense_de_tableur_rattachee_ne_se_complete_pas_depuis_le_terrain(self):
        """Le back-office peut rattacher une ligne du tableur à un départ.

        Elle compte alors dans le total et doit s'afficher — mais son
        justificatif ne se joint pas d'ici : elle n'a pas de demande d'origine,
        donc rien à quoi rattacher l'envoi. Sans le drapeau, l'écran
        proposerait un bouton qui échouerait.
        """
        depense, _cree = (self.env["dally.cash.expense"].sudo()
                          .with_company(self.societe)
                          .upsert_from_sync(
                              {"external_expense_key": "sheet:2026-08-21:007",
                               "expense_date": "2026-08-21",
                               "category": "Douane", "description": "Frais",
                               "currency_id": self.xof.id,
                               "source": "google_sheets",
                               "consolidation_id": self.consolidation.id},
                              [{"actor_name": "Papa", "amount": 12000.0}]))

        lignes = self._service().list_expenses(self.consolidation.name)["expenses"]
        self.assertEqual(len(lignes), 1)
        self.assertFalse(lignes[0]["can_attach_receipt"])
        # Elle compte malgré tout dans le total du départ.
        self.assertEqual(
            self._service().list_expenses(self.consolidation.name)["summary"],
            [{"currency_code": "XOF", "amount": 12000.0}])

        # Et le serveur refuse bien l'envoi, drapeau ou pas.
        with self.assertRaises(DallyOpsNotFound):
            self._service().attach_receipt(
                depense.external_expense_key, str(uuid.uuid4()), "t.jpg", JPEG)

    def test_une_depense_du_terrain_annonce_qu_elle_attend_sa_photo(self):
        reference = self._reference_creee()
        lignes = self._service().list_expenses(self.consolidation.name)["expenses"]
        self.assertTrue(lignes[0]["can_attach_receipt"])

        self._service().attach_receipt(reference, str(uuid.uuid4()), "t.jpg", JPEG)
        apres = self._service().list_expenses(self.consolidation.name)["expenses"]
        # Une fois la photo jointe, il n'y a plus rien à compléter.
        self.assertFalse(apres[0]["can_attach_receipt"])
        self.assertTrue(apres[0]["has_receipt"])

    def test_une_depense_ne_peut_pas_pointer_le_depart_d_une_autre_societe(self):
        from odoo.exceptions import ValidationError
        depart = self._consolidation(
            "AIR-DEP-CONTRAINTE", "collecting", societe=self.autre_societe)
        with self.assertRaises(ValidationError):
            self.env["dally.cash.expense"].sudo().create({
                "company_id": self.societe.id,
                "external_expense_key": "test:contrainte",
                "expense_date": "2026-08-20", "category": "X", "description": "Y",
                "currency_id": self.xof.id, "consolidation_id": depart.id,
            })

    # ─── L'invariant et les contrôles négatifs ───────────────────────

    def test_l_invariant_de_securite_n_a_pas_bouge(self):
        lisibles = modeles_lisibles(self.env, self.logisticien)
        self.assertEqual(lisibles, set(MODELES_TECHNIQUES_LISIBLES))
        for modele in MODELES_METIER_FERMES:
            self.assertNotIn(modele, lisibles)

    def test_l_operateur_ne_peut_pas_ecrire_dans_ir_attachment(self):
        depense = self.env["dally.cash.expense"]
        self.assertFalse(
            self.env["ir.attachment"].with_user(self.logisticien).has_access("create"))
        self.assertFalse(depense.with_user(self.logisticien).has_access("read"))

    def test_les_registres_de_demande_ne_sont_lisibles_par_personne(self):
        for modele in ("dally.ops.expense.request", "dally.ops.expense.receipt.request"):
            self.assertFalse(
                self.env[modele].with_user(self.logisticien).has_access("read"))

    def test_le_controleur_ne_contient_ni_sudo_ni_cle_d_api(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_expenses
        code = code_seul(ops_expenses)
        for interdit in ("sudo", "SUPERUSER_ID", "API_KEY", "api_key",
                         "with_user", "search(", "browse("):
            self.assertNotIn(interdit, code)
        self.assertIn("auth='user'", code)

    def test_le_service_n_eleve_pas_les_privileges_au_dela_du_sudo(self):
        """Aucun environnement superutilisateur explicite ici.

        Les encaissements en ont eu besoin — mesuré, documenté. Les dépenses
        non : `.sudo()` suffit, et les tests HTTP ci-dessous le prouvent en
        conditions réelles. Ce test empêche l'exception de se généraliser par
        recopie.
        """
        from odoo.addons.dally_ops_mobile.models import ops_expense_service
        code = code_seul(ops_expense_service)
        self.assertNotIn("SUPERUSER_ID", code)
        self.assertNotIn("user=1", code)

    def test_le_service_ne_reutilise_pas_les_canaux_de_paiement_client(self):
        from odoo.addons.dally_ops_mobile.models import ops_expense_service
        code = code_seul(ops_expense_service)
        self.assertNotIn("dally.freight.payment.channel", code)
        self.assertNotIn("account.payment", code)


@tagged("post_install", "-at_install", "dally")
class TestOpsExpensesHttp(HttpCase):
    """Les routes elles-mêmes, éprouvées par HTTP réel.

    L'étape 7 a appris pourquoi : un défaut n'existant que dans le chemin HTTP
    — la sortie d'un point de sauvegarde qui vide *tous* les environnements de
    la transaction — était invisible aux tests de service. Le privilège
    minimal retenu ici ne peut être déclaré suffisant que mesuré ainsi.
    """

    MOT_DE_PASSE = "OpsProbe!2026#dep"

    def setUp(self):
        super().setUp()
        self.societe = self.env["res.company"].create({"name": "Ops Dépenses HTTP SA"})
        self.xof = self.env.ref("base.XOF")
        self.xof.write({"active": True})
        self.logisticien = self._compte(
            "http.dep.logi", "Gilles HTTP Dépenses",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Gilles")
        self.etranger = self._compte("http.dep.autre", "Sans rôle", "base.group_user")
        self.consolidation = self.env["dally.freight.consolidation"].create({
            "name": "AIR-HTTP-DEP-001", "company_id": self.societe.id,
            "transport_mode": "air", "direction": "export", "state": "collecting",
            "origin_country_id": self.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": self.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })

    def _compte(self, login, nom, groupe, acteur=None):
        valeurs = {
            "name": nom, "login": login, "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(groupe).id])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
        }
        if acteur:
            valeurs["dally_ops_cash_actor"] = acteur
        return self.env["res.users"].create(valeurs)

    def _charge(self, **changements):
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "consolidation_reference": self.consolidation.name,
            "expense_date": "2026-08-20",
            "category": "Manutention",
            "description": "Portage entrepôt",
            "beneficiary": "Équipe entrepôt",
            "amount": 15000.0,
            "currency_code": "XOF",
            "payment_method": "cash",
            "comment": "",
        }
        charge.update(changements)
        return charge

    def _poster(self, charge, login="http.dep.logi"):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(
            "/api/v1/ops/expenses", data=json.dumps(charge),
            headers={"Content-Type": "application/json"}, allow_redirects=False)

    def test_le_logisticien_enregistre_une_depense_par_http(self):
        """Le test qui décide du niveau de privilège.

        C'est ici, et pas dans un appel de service, que se mesure ce qu'Odoo
        exige réellement d'écrire une dépense sous une identité sans droits.
        """
        reponse = self._poster(self._charge())
        self.assertEqual(reponse.status_code, 200, reponse.content[:800])
        donnees = json.loads(reponse.content)["data"]
        self.assertEqual(donnees["status"], "created")
        self.assertEqual(donnees["expense"]["state"], "review")
        self.assertEqual(donnees["expense"]["paid_by"], "Gilles")
        self.assertFalse(donnees["expense"]["has_receipt"])

    def test_la_photo_passe_par_un_envoi_multipart(self):
        reference = json.loads(
            self._poster(self._charge()).content)["data"]["expense"]["reference"]
        reponse = self.url_open(
            "/api/v1/ops/expenses/%s/receipt" % reference,
            files={"receipt": ("ticket.jpg", JPEG, "image/jpeg")},
            data={"request_uuid": str(uuid.uuid4())},
            allow_redirects=False)
        self.assertEqual(reponse.status_code, 200, reponse.content[:800])
        donnees = json.loads(reponse.content)["data"]
        self.assertEqual(donnees["status"], "attached")
        self.assertTrue(donnees["expense"]["has_receipt"])

    def test_un_fichier_dangereux_est_refuse_par_http_et_la_depense_demeure(self):
        reference = json.loads(
            self._poster(self._charge()).content)["data"]["expense"]["reference"]
        reponse = self.url_open(
            "/api/v1/ops/expenses/%s/receipt" % reference,
            files={"receipt": ("ticket.jpg", HTML, "image/jpeg")},
            data={"request_uuid": str(uuid.uuid4())},
            allow_redirects=False)
        self.assertEqual(reponse.status_code, 422)
        self.assertEqual(
            json.loads(reponse.content)["error"]["code"], "receipt_type_not_allowed")

        liste = self.url_open(
            "/api/v1/ops/consolidations/%s/expenses" % self.consolidation.name,
            allow_redirects=False)
        expenses = json.loads(liste.content)["data"]["expenses"]
        self.assertEqual(len(expenses), 1)
        self.assertFalse(expenses[0]["has_receipt"])

    def test_les_departs_eligibles_sont_servis_par_http(self):
        self.authenticate("http.dep.logi", self.MOT_DE_PASSE)
        reponse = self.url_open(
            "/api/v1/ops/expense-consolidations", allow_redirects=False)
        self.assertEqual(reponse.status_code, 200)
        references = [
            depart["reference"]
            for depart in json.loads(reponse.content)["data"]["consolidations"]
        ]
        self.assertIn(self.consolidation.name, references)

    def test_un_authentifie_sans_role_ops_est_refuse(self):
        self.assertEqual(self._poster(self._charge(), "http.dep.autre").status_code, 403)

    def test_un_anonyme_est_renvoye_vers_la_connexion(self):
        self.assertIn(self._poster(self._charge(), None).status_code, (302, 303))

    def test_le_conflit_d_idempotence_remonte_en_409(self):
        charge = self._charge()
        self.assertEqual(self._poster(charge).status_code, 200)
        reponse = self._poster(dict(charge, amount=1.0))
        self.assertEqual(reponse.status_code, 409)
        self.assertEqual(
            json.loads(reponse.content)["error"]["code"], "idempotency_conflict")

    def test_le_corps_illisible_ne_produit_pas_une_erreur_serveur(self):
        self.authenticate("http.dep.logi", self.MOT_DE_PASSE)
        reponse = self.url_open(
            "/api/v1/ops/expenses", data=b"{ceci n'est pas du json",
            headers={"Content-Type": "application/json"}, allow_redirects=False)
        self.assertEqual(reponse.status_code, 400)

    def test_le_dto_http_ne_contient_aucun_identifiant_odoo(self):
        contenu = self._poster(self._charge()).content.decode()
        for interdit in ("expense_id", "consolidation_id", "company_id",
                         "currency_id", "attachment_id", "external_expense_key"):
            self.assertNotIn(interdit, contenu)
