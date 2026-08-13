#!/bin/bash
# Crée le rôle applicatif d'Odoo SANS privilège d'administration, et la base
# `dallytrading` dont il est propriétaire.
#
# ── Pourquoi ce script existe ────────────────────────────────────────
#
# ADR-005 décide que `odoo_dally` n'a ni SUPERUSER ni CREATEDB. Cette décision
# n'était pas appliquée : le compose passait `POSTGRES_USER=odoo_dally`, or dans
# l'image officielle PostgreSQL cette variable désigne le rôle d'AMORÇAGE, celui
# que `initdb` crée — et initdb le crée toujours superutilisateur. Le rôle censé
# être bridé était donc le plus privilégié de l'instance.
#
# Constaté au premier démarrage réel :
#   odoo_dally superuser=true createdb=true
#
# Une revue statique ne pouvait pas le voir : le compose et la documentation
# étaient cohérents entre eux, et faux tous les deux.
#
# Le rôle d'amorçage est désormais `postgres` (superutilisateur, sans mot de passe
# exposé au réseau puisque la base n'est joignable que depuis le réseau Docker
# interne), et ce script crée `odoo_dally` en rôle ordinaire.
#
# ── Ce que le rôle peut, et ne peut pas ──────────────────────────────
#
# Il possède la base `dallytrading` : il y crée ses tables, ses index et ses
# séquences sans restriction — c'est tout ce dont Odoo a besoin, `list_db = False`
# lui interdisant de toute façon de gérer des bases.
#
# Il ne peut ni créer une autre base, ni lire les fichiers du serveur, ni charger
# une extension arbitraire, ni toucher aux catalogues système. Une injection SQL
# aboutissant à `COPY … FROM PROGRAM` échoue faute de privilège.
#
# Exécuté une seule fois, à l'initialisation du volume.

set -euo pipefail

APP_USER="${DALLY_DB_USER:?DALLY_DB_USER requis}"
APP_PASSWORD="${DALLY_DB_PASSWORD:?DALLY_DB_PASSWORD requis}"
APP_DB="${DALLY_DB_NAME:?DALLY_DB_NAME requis}"

echo "[init] création du rôle applicatif ${APP_USER} (sans privilège d'administration)"

# Le mot de passe passe par une variable psql, jamais par interpolation shell :
# une apostrophe dans le secret casserait la requête, et un secret dans une
# commande serait visible dans les journaux du conteneur.
PGPASSWORD="" psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v app_user="$APP_USER" -v app_password="$APP_PASSWORD" -v app_db="$APP_DB" <<-'SQL'
	SELECT format(
	  'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
	  :'app_user', :'app_password'
	)
	\gexec

	SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8''', :'app_db', :'app_user')
	\gexec
SQL

# Odoo crée ses tables dans le schéma `public`. Depuis PostgreSQL 15 ce schéma
# n'est plus ouvert en écriture à tous : sans ce GRANT, la première migration
# échoue sur « permission denied for schema public ».
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$APP_DB" \
  -v app_user="$APP_USER" <<-'SQL'
	SELECT format('GRANT ALL ON SCHEMA public TO %I', :'app_user')
	\gexec
	SELECT format('ALTER SCHEMA public OWNER TO %I', :'app_user')
	\gexec
SQL

echo "[init] rôle ${APP_USER} et base ${APP_DB} créés"
