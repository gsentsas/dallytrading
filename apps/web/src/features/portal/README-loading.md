Pas de `loading.tsx` dans `app/espace-client/` — c'est délibéré.

Un `loading.tsx` installe une frontière Suspense : Next envoie alors la coque de
la page immédiatement, ce qui **fige le statut HTTP à 200**. Un `notFound()`
appelé ensuite affiche bien la page « Dossier introuvable », mais dans une
réponse 200.

Mesuré sur l'instance E2E : avec le squelette, une référence forgée renvoyait
200 ; sans lui, 404.

Le squelette n'apportait presque rien — chaque page fait un seul appel à Odoo —
et coûtait le bon statut sur toutes les pages de détail. Si un squelette redevient
souhaitable, le placer sur les segments de LISTE uniquement, jamais sur un segment
qui peut appeler `notFound()`.
