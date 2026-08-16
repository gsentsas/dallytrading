"""Ancrages d'installation et de mise à jour du pont."""

from .models.lockdown_guard import verifier_confinement


def post_init_hook(env):
    """Refuse d'installer ou de mettre à jour sur un confinement défait.

    Voir `models/lockdown_guard` : l'échec est volontairement dur ici, et
    seulement journalisé au chargement ordinaire du registre.
    """
    verifier_confinement(env)
