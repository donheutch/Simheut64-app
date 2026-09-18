# SimHeut96 — Appli d'activation de licences

## Contenu
- `license.py` — logique de génération/vérification des codes (HMAC-SHA256)
- `app.py` — backend FastAPI (API + base de données SQLite)
- `static/admin.html` — page pour générer des codes (vous, protégée par mot de passe)
- `static/activate.html` — page pour les associations (activation de leur code)

## Fonctionnalités
- Génération de codes (admin, protégé par mot de passe)
- Activation par les associations
- **Révocation** : l'admin peut désactiver un code à tout moment (bouton "Révoquer"), y compris déjà activé
- **Statistiques** : nombre de codes générés, associations actives, codes expirant sous 30 jours, codes révoqués
- **Envoi par email** : en générant un code, l'admin peut indiquer l'email de l'association pour que le code lui soit envoyé automatiquement (optionnel — nécessite de configurer un serveur SMTP, voir ci-dessous)

## 1. Tester en local

```bash
pip install -r requirements.txt

export SIMHEUT96_SECRET_KEY="une-longue-chaine-aleatoire-a-generer-une-fois"
export SIMHEUT96_ADMIN_PASSWORD="votre-mot-de-passe-admin"

uvicorn app:app --reload
```

Puis ouvrez :
- http://127.0.0.1:8000/ → page d'activation (associations)
- http://127.0.0.1:8000/admin → page admin (génération)

Pour générer une clé secrète aléatoire solide :
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Activer l'envoi d'email (optionnel)

Sans ces variables, la génération de code fonctionne normalement, l'admin récupère juste le code à la main (aucun email n'est envoyé, sans erreur).

```bash
export SIMHEUT96_SMTP_HOST="smtp.gmail.com"      # ou votre fournisseur (Outlook, OVH, SendGrid...)
export SIMHEUT96_SMTP_PORT="587"
export SIMHEUT96_SMTP_USER="votre-adresse@gmail.com"
export SIMHEUT96_SMTP_PASSWORD="un-mot-de-passe-d-application"   # PAS votre mot de passe habituel
export SIMHEUT96_SMTP_FROM="votre-adresse@gmail.com"
```

Avec Gmail, il faut créer un "mot de passe d'application" spécifique (Compte Google → Sécurité → Mots de passe des applications) ; le mot de passe normal du compte ne fonctionnera pas.

## 2. Déployer en ligne (gratuit, sans serveur à gérer)

**Option recommandée : Render.com**

1. Créez un compte sur https://render.com et un dépôt Git (GitHub) contenant ces fichiers.
2. Sur Render : *New → Web Service* → connectez votre dépôt.
3. Configuration :
   - Build command : `pip install -r requirements.txt`
   - Start command : `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Dans *Environment*, ajoutez les variables :
   - `SIMHEUT96_SECRET_KEY` (générée comme ci-dessus)
   - `SIMHEUT96_ADMIN_PASSWORD`
   - (optionnel) les 5 variables `SIMHEUT96_SMTP_*` si vous voulez l'envoi d'email
5. **Important** : ajoutez un disque persistant (*Disks*, ex. 1 Go monté sur `/opt/render/project/src/data`) sinon la base de données SQLite sera effacée à chaque redéploiement.
6. Déployez. Vos URLs seront `https://votre-app.onrender.com/` et `.../admin`.

**Alternative** : Railway.app fonctionne de façon très similaire, avec un volume persistant lui aussi à activer.

## 3. Évolutions à prévoir avant une mise en production sérieuse

- Remplacer SQLite par une vraie base (Postgres, via Supabase par ex.) si vous attendez beaucoup d'associations simultanées.
- Ajouter HTTPS (automatique sur Render/Railway).
- Limiter les tentatives d'activation (anti-brute-force) si le volume grandit.
- Sauvegardes régulières de la base de données.

## Sécurité — à ne jamais oublier
- `SIMHEUT96_SECRET_KEY` ne doit **jamais** apparaître dans le code, un commit Git, ou côté client. Uniquement en variable d'environnement sur le serveur.
- La page `/admin` n'est protégée que par un mot de passe simple : suffisant pour un usage interne, mais à renforcer (ex. authentification à deux facteurs) si plusieurs personnes y accèdent.
