#   COFINANCE CI — Plateforme de Microfinance & Assurance Mobile

> **Plateforme digitale complète de gestion de microcrédits, d'assurance mobile et de support client en temps réel.**
> Développée avec Django / DRF · JWT Auth · WebSockets · Design Premium
>  Contexte ivoirien : devises **FCFA**, fuseau horaire **Africa/Abidjan**

---

##   Stack Technique

| Couche | Technologies |
|---|---|
| **Backend** | Python 3.11+, Django 5.x, Django REST Framework |
| **Authentification** | JWT via `djangorestframework-simplejwt` |
| **WebSockets** | Django Channels + Daphne (ASGI) |
| **Base de données** | SQLite (dev) · PostgreSQL (prod) |
| **Documentation API** | drf-spectacular → Swagger `/api/docs/` · Redoc `/api/redoc/` |
| **Images** | Pillow (upload & validation photos de profil) |
| **Frontend** | HTML/CSS/JS vanilla — Glassmorphism, dark mode, animations |

---

##   Comptes de Démonstration

```bash
python manage.py seed_db
```

| Rôle | Identifiant | Mot de passe | Description |
|:---|:---|:---|:---|
| **ADMIN** | `admin1` | `password123` | Accès dashboard + gestion utilisateurs |
| **AGENT** | `agent1` | `password123` | Gestion dossiers crédits + chat support |
| **CLIENT** | `client1` | `password123` | Crédit décaissé en cours de remboursement |
| **CLIENT** | `client2` | `password123` | Crédit approuvé + souscription assurance |

---

##   Installation & Lancement

```bash
# 1. Créer et activer l'environnement virtuel
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Appliquer les migrations (4 migrations)
python manage.py makemigrations
python manage.py migrate

# 4. Peupler la base de données (comptes de démo + données fictives)
python manage.py seed_db

# 5. Lancer les alertes automatiques (échéances, expirations assurance)
python manage.py run_alerts

# 6. Démarrer le serveur (ASGI + WebSockets)
python manage.py runserver
```

  Application disponible sur : **`http://127.0.0.1:8000/`**
  Documentation API : **`http://127.0.0.1:8000/api/docs/`**
  Admin Django : **`http://127.0.0.1:8000/admin/`**

---

##   Référence Complète des Endpoints API

###   Authentification & Profil

| Méthode | URL | Accès | Description |
|:---|:---|:---|:---|
| `POST` | `/api/auth/register/` | Public | Inscription avec validation stricte (téléphone, username, mdp) |
| `POST` | `/api/auth/login/` | Public | Connexion JWT (retourne access + refresh tokens) |
| `POST` | `/api/auth/refresh/` | Public | Rafraîchissement du token JWT |
| `POST` | `/api/auth/change-password/` | Connecté | Changement de mot de passe (ancien + nouveau + confirmation) |
| `GET/PATCH` | `/api/profile/` | Connecté | Consulter / modifier son profil |
| `POST` | `/api/profile/avatar/` | Connecté | Upload photo de profil (JPEG/PNG, max 5 Mo) |
| `DELETE` | `/api/profile/avatar/` | Connecté | Supprimer la photo de profil |

###  Gestion des Microcrédits

| Méthode | URL | Accès | Description |
|:---|:---|:---|:---|
| `GET` | `/api/credits/` | Connecté | Liste paginée (client: les siens / agent-admin: tous) |
| `POST` | `/api/credits/` | CLIENT | Soumettre une demande (**1 seul crédit actif** à la fois) |
| `PATCH` | `/api/credits/{id}/status/` | AGENT/ADMIN | Avancer le statut (**workflow unidirectionnel** SOUMISE→EN_ANALYSE→APPROUVEE→DECAISSEE) |
| `GET` | `/api/credits/{id}/echeancier/` | Connecté | Échéancier détaillé d'un crédit |
| `PUT/PATCH` | `/api/credits/{id}/` | CLIENT | Modifier une demande (**SOUMISE uniquement**, bloqué sinon) |
| `DELETE` | `/api/credits/{id}/` | CLIENT | Supprimer une demande (**SOUMISE uniquement**, bloqué sinon) |

>   Le champ `eligibility_score_detail` explique en clair comment le score a été calculé.

###   Suivi des Remboursements

| Méthode | URL | Accès | Description |
|:---|:---|:---|:---|
| `POST` | `/api/repayments/` | AGENT/ADMIN | Enregistrer un paiement (+ AuditLog automatique) |
| `GET` | `/api/repayments/` | Connecté | Historique paginé des remboursements |

###   Assurances Mobiles

| Méthode | URL | Accès | Description |
|:---|:---|:---|:---|
| `GET` | `/api/insurance/products/` | Public | Catalogue des formules d'assurance |
| `POST` | `/api/insurance/subscribe/` | CLIENT | Souscrire (**doublon actif refusé**) |
| `GET` | `/api/insurance/my-policies/` | CLIENT | Mes polices d'assurance |

###   Chat de Support en Temps Réel

| Méthode | URL | Accès | Description |
|:---|:---|:---|:---|
| `GET/POST` | `/api/chat/conversations/` | Connecté | Lister / ouvrir une conversation |
| `GET/POST` | `/api/chat/conversations/{id}/messages/` | Connecté | Historique + envoi de messages |
| `POST` | `/api/chat/conversations/{id}/join/` | AGENT | Rejoindre une conversation (+ AuditLog) |
| `PATCH` | `/api/chat/conversations/{id}/assign/` | ADMIN | Assigner un agent à une conversation (+ AuditLog) |
| `POST` | `/api/chat/conversations/{id}/close/` | Connecté | Fermer une conversation |
| `WS` | `/ws/chat/conversations/{id}/` | Connecté | Canal WebSocket temps réel |

###  Notifications Internes

| Méthode | URL | Accès | Description |
|:---|:---|:---|:---|
| `GET` | `/api/notifications/` | Connecté | Mes notifications (paginées) |
| `PATCH` | `/api/notifications/{id}/mark_as_read/` | Connecté | Marquer comme lue |
| `PATCH` | `/api/notifications/mark_all_as_read/` | Connecté | Tout marquer comme lu |

###   Tableau de Bord Administrateur

| Méthode | URL | Accès | Description |
|:---|:---|:---|:---|
| `GET` | `/api/dashboard/` | ADMIN | Métriques complètes (crédits, recouvrement, utilisateurs, activité du jour) |

> Filtres disponibles : `?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&region=Abidjan&agent=<id>`

###   Gestion des Utilisateurs (Admin)

| Méthode | URL | Accès | Description |
|:---|:---|:---|:---|
| `GET` | `/api/admin/users/` | ADMIN | Lister tous les utilisateurs (filtrable par rôle, région, is_active) |
| `POST` | `/api/admin/users/` | ADMIN | Créer un agent ou un admin |
| `GET/PATCH` | `/api/admin/users/{id}/` | ADMIN | Détail / modifier un utilisateur |
| `PATCH` | `/api/admin/users/{id}/toggle_active/` | ADMIN | Activer ou désactiver un compte |

###   Journal d'Audit (Agent / Admin)

| Méthode | URL | Accès | Description |
|:---|:---|:---|:---|
| `GET` | `/api/agent/activity/` | AGENT/ADMIN | Journal d'activité filtrable (`?action=CREDIT_STATUS_CHANGE`) |

> Chaque action agent/admin (changement statut, paiement, chat) génère automatiquement une entrée `AuditLog` horodatée.

---

##   Sécurité & Règles Métier

### Validation stricte des entrées
| Champ | Règle |
|:---|:---|
| `phone` | Chiffres uniquement (`+`, espaces, tirets autorisés) — lettres **refusées** |
| `username` | Alphanumérique + `.`, `-`, `_` — minimum 3 caractères |
| `password` | Minimum 8 caractères + au moins 1 lettre + 1 chiffre |
| `email` | Unicité vérifiée — format RFC5321 |
| `region` | Lettres + espaces + tirets uniquement — chiffres refusés |
| `avatar` | JPEG/PNG uniquement — taille max 5 Mo |

### Règles métier critiques
-    **1 crédit actif max** par client à la fois
-    **Workflow unidirectionnel** des statuts — rétrogradation impossible
-    **Doublons assurance** bloqués (même produit actif)
-    **Auto-désactivation admin** impossible
-    **Throttling** : 100 req/jour (anonyme), 2000/jour (connecté), 5 tentatives/min (login)

---

##   Suite de Tests

```bash
python manage.py test core --verbosity=2
```

**19 tests** couvrant :
- ✅ Rôles et création d'utilisateurs
- ✅ Score d'éligibilité + explication textuelle
- ✅ Génération automatique de l'échéancier
- ✅ Distribution automatique des paiements
- ✅ Workflow unidirectionnel (rétrogradation bloquée)
- ✅ Limite 1 crédit actif par client
- ✅ Changement de mot de passe (succès + échec)
- ✅ Sécurité des rôles (403 CLIENT, 403 AGENT)
- ✅ Gestion des utilisateurs par l'admin
- ✅ Toggle actif/inactif + protection auto-désactivation
- ✅ Dashboard enrichi (nouvelles métriques)
- ✅ Journal d'audit (AuditLog créé à chaque action)
- ✅ Ségrégation des données par client

---

##  Alertes Automatiques (Cron)

La commande `python manage.py run_alerts` envoie des notifications pour :
-  **J-3** : Prochaine échéance dans 3 jours
-  **J+1** : Échéance en retard
-  **J-15** : Expiration d'assurance dans 15 jours

---

##  Test du Chat Temps Réel (WebSockets)

1. **Onglet 1** → `http://127.0.0.1:8000/` → Connexion `client1` → Ouvrir un chat
2. **Onglet 2** → `http://127.0.0.1:8000/` → Connexion `agent1` → Centre de Support → Rejoindre
3.  Messages instantanés, indicateur *"en train d'écrire..."*, indicateur de présence en ligne

---

##  Structure du Projet

```
MicroFinance CI Platform/
├── core/
│   ├── migrations/         # 4 migrations de base de données
│   ├── management/commands/
│   │   ├── seed_db.py      # Données de démonstration
│   │   └── run_alerts.py   # Alertes automatiques
│   ├── models.py           # User, LoanRequest, Payment, Insurance, Chat, AuditLog
│   ├── serializers.py      # Validation stricte + serializers spécialisés
│   ├── views.py            # ViewSets + APIViews par module
│   ├── permissions.py      # IsClient, IsAgent, IsAdmin, IsClientOrAgent
│   ├── consumers.py        # WebSocket consumer (Django Channels)
│   ├── admin.py            # Administration Django enrichie avec badges et aperçus
│   ├── urls.py             # 20+ endpoints enregistrés
│   └── tests.py            # 19 tests automatisés
├── microfinance_ci/
│   ├── settings.py         # Config complète (JWT, Throttling, Channels, Media)
│   ├── urls.py             # Routing principal + Swagger + Media
│   ├── asgi.py             # Config ASGI pour WebSockets
│   └── wsgi.py
├── media/                  # Fichiers uploadés (avatars, documents justificatifs)
├── requirements.txt
└── README.md
```
