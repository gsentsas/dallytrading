/**
 * Configuration de banc pour les tests.
 *
 * Chargée avant les modules testés : `opsEnv()` trouve donc une configuration
 * valide sans qu'aucun test n'ait à la fabriquer. Le secret est une valeur de
 * banc, sans rapport avec quoi que ce soit de réel.
 */

process.env.OPS_PUBLIC_URL = 'https://ops.example.test';
process.env.OPS_SESSION_SECRET = 'secret-de-banc-pour-les-tests-0123456789';
process.env.ODOO_URL = 'https://odoo.example.test';
process.env.ODOO_DATABASE = 'banc';
process.env.ODOO_TIMEOUT_MS = '5000';
