# Gabarit Caddy du POC Documenso sur Oracle Cloud.
#
# oracle/deploy.sh substitue les marqueurs et écrit le résultat dans
# /opt/documenso-poc/Caddyfile, monté en lecture seule dans le conteneur.
# Un marqueur s'écrit : deux arobases, un nom en majuscules, deux arobases.
# Ce commentaire n'en contient volontairement aucun, sans quoi il ferait
# échouer le contrôle de substitution de oracle/render-caddyfile.py.
#
# POINT DE SÉCURITÉ, cf. RESULTATS_TEST_2026-09-12.md constat 3 :
# les formulaires /signin, /signup et /forgot-password de Documenso sont servis
# sans attribut `method` et peuvent, avant hydratation du JavaScript, partir en
# GET avec l'email et le mot de passe dans la query string. Documenso ne les
# journalise pas, mais un reverse proxy le ferait par défaut.
#
# Parade retenue ici : AUCUN access log HTTP. La directive `log { output
# discard }` est posée explicitement sur chaque site, plutôt que de se reposer
# sur le fait que Caddy ne journalise pas les accès par défaut : l'intention est
# alors lisible, et une reprise du fichier ne la perdra pas par accident.

{
	# L'API d'administration (127.0.0.1:2019 dans le conteneur) n'a aucun usage
	# ici et devient une surface d'attaque de plus. Coupée.
	admin off
}

(poc_no_access_log) {
	log {
		output discard
	}
}

# ---------------------------------------------------------------------------
# Application Documenso
# ---------------------------------------------------------------------------
@@APP_HOST@@ {
	import poc_no_access_log

	encode zstd gzip

@@APP_GUARD@@
	reverse_proxy documenso:3000
}

# ---------------------------------------------------------------------------
# Boîte aux lettres Mailpit : jamais ouverte sans authentification.
# ---------------------------------------------------------------------------
@@MAIL_HOST@@ {
	import poc_no_access_log

	basic_auth {
		@@AUTH_USER@@ @@MAIL_AUTH_HASH@@
	}

	reverse_proxy mailpit:8025
}

# ---------------------------------------------------------------------------
# Support de démonstration : page statique, aucun secret, aucun appel d'API
# authentifié côté navigateur. Protégée par le même Basic Auth que Mailpit.
# ---------------------------------------------------------------------------
@@DEMO_HOST@@ {
	import poc_no_access_log

	basic_auth {
		@@AUTH_USER@@ @@DEMO_AUTH_HASH@@
	}

	handle_path /webhooks* {
		reverse_proxy webhook-sink:9000
	}

	handle {
		root * /srv/demo
		file_server
	}
}
