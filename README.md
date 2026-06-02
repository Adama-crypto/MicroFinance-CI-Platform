# MicroFinance CI Platform

Plateforme de Microfinance complète et moderne développée en Python/Django, conçue spécialement pour le marché ivoirien (devises en FCFA, fuseau horaire d'Abidjan). Cette solution intègre la gestion de microcrédits avec scoring automatique, le suivi des remboursements, des produits d'assurance mobile, des alertes de échéances automatisées et un chat de support en temps réel via WebSockets (Django Channels).

---

## Technologies Utilises

- **Backend** : Python 3.11+, Django 5.x, Django REST Framework (DRF)
- **Authentification** : JWT (djangorestframework-simplejwt)
- **WebSockets** : Django Channels & Daphne (ASGI)
- **Base de donnees** : SQLite en developpement, configure pour PostgreSQL en production.
- **Documentation API** : drf-spectacular (Swagger UI disponible sur `/api/docs/`)
- **Frontend** : Interface Single Page (SPA) en HTML/CSS/JS (Vanilla CSS avec design premium de type Glassmorphism, animations et thematique sombre).

---

## Jeu de donnees de Demo & Comptes de Test

Utilisez la commande de peuplement (voir ci-dessous) pour pre-charger les profils suivants :

| Role | Nom d'utilisateur | Mot de passe | Description | Region |
| :--- | :--- | :--- | :--- | :--- |
| **ADMIN** | `admin1` | `password123` | Administrateur systeme (acces dashboard) | Abidjan |
| **AGENT** | `agent1` | `password123` | Agent de credit (gestion des dossiers, chats) | Bouake |
| **CLIENT** | `client1` | `password123` | Client standard avec pret decaisse en cours | Abidjan |
| **CLIENT** | `client2` | `password123` | Client standard avec pret approuve | Bouake |

---

## Instructions d'Installation & Lancement

### 1. Configurer l'environnement virtuel
Ouvrez votre terminal dans le repertoire racine du projet :

```bash
# Creer l'environnement virtuel
python -m venv venv

# Activer l'environnement virtuel
# Sur Windows :
venv\Scripts\activate
# Sur macOS/Linux :
source venv/bin/activate

# Installer les dependances indispensables
pip install -r requirements.txt
```

### 2. Appliquer les migrations de base de donnees
```bash
python manage.py makemigrations
python manage.py migrate
```

### 3. Peupler la base de donnees avec le jeu de demo
Cette commande cree automatiquement les comptes de test ci-dessus, des polices d'assurance mobile, des credits fictifs avec leurs echeances et des historiques de chat.
```bash
python manage.py seed_db
```

### 4. Simuler/Executer le script journalier d'alertes (Cron)
Pour envoyer des notifications automatiques a J-3 (prochaine echeance), J+1 (echeance en retard) et J-15 (expiration de l'assurance) :
```bash
python manage.py run_alerts
```

### 5. Lancer le serveur de developpement
Puisque Daphne est inclus dans les applications installees, la commande standard lance automatiquement le serveur ASGI compatible WebSockets :
```bash
python manage.py runserver
```
Le serveur sera disponible sur : **`http://127.0.0.1:8000/`**

---

## Liste des Endpoints Exposés

### Authentification & Profils
- `POST /api/auth/register/` : Inscription publique d'un utilisateur.
- `POST /api/auth/login/` : Connexion (SimpleJWT, retourne tokens d'accès et de rafraîchissement).
- `POST /api/auth/refresh/` : Rafraîchissement du token JWT.
- `GET/PATCH /api/profile/` : Consultation et modification du profil de l'utilisateur connecté.

### Gestion des Microcrédits
- `GET /api/credits/` : Liste des demandes (filtrée pour le client connecté, globale pour l'Agent/Admin).
- `POST /api/credits/` : Dépôt d'une demande de crédit (avec upload de fichier justificatif).
- `GET /api/credits/{id}/echeancier/` : Consultation de l'échéancier d'une demande (Client ou Agent/Admin).
- `PATCH /api/credits/{id}/status/` : Permet à l'Agent/Admin de changer le statut (Soumise -> En analyse -> Approuvee -> Decaissee). *Remarque : La transition vers "Approuvee" génère automatiquement l'échéancier.*

### Suivi des Remboursements
- `POST /api/repayments/` : Enregistrement d'un paiement (réservé aux Agents/Admins). *Répartit automatiquement le versement sur les échéances du crédit.*
- `GET /api/repayments/` : Historique des remboursements (filtré pour le client connecté, global pour l'Agent/Admin).

### Produits d'Assurance Mobile
- `GET /api/insurance/products/` : Catalogue public des formules d'assurance mobile.
- `POST /api/insurance/subscribe/` : Souscription d'un client à une formule d'assurance.
- `GET /api/insurance/my-policies/` : Polices d'assurances actives (filtré pour le client connecté, global pour l'Agent/Admin).

### Support et Chat en Temps Réel
- `GET /api/chat/conversations/` : Liste des conversations de chat (filtré pour le client connecté, global pour l'Agent/Admin).
- `POST /api/chat/conversations/` : Ouverture d'une nouvelle conversation par un client.
- `GET /api/chat/conversations/{id}/messages/` : Récupération de l'historique des messages d'une conversation.
- `PATCH /api/chat/conversations/{id}/assign/` : Permet à un Agent/Admin de se voir attribuer la conversation.
- `WebSocket /ws/chat/conversations/{id}/` : Canal WebSocket pour l'échange instantané de messages, d'états d'écriture et de présence en ligne.

### Tableau de Bord Administrateur
- `GET /api/dashboard/` : Métriques avancées (taux de recouvrement, volume par statut, chats ouverts). *Filtres disponibles : `start_date`, `end_date`, `region`, `agent`.*


### Notifications Internes
- `GET /api/notifications/` : Recuperation des alertes de l'utilisateur.
- `PATCH /api/notifications/{id}/mark_as_read/` : Marquer une notification comme lue.
- `PATCH /api/notifications/mark_all_as_read/` : Tout marquer comme lu.

---

## Demonstration du Chat en Temps Reel (WebSockets)
Pour tester le module de chat interactif sans rechargement de page :
1. Ouvrez un premier onglet ou une fenetre privee sur `http://127.0.0.1:8000/`. Connectez-vous en tant que client (`client1` / `password123`).
2. Ouvrez le chat de support dans le coin inferieur droit, puis cliquez sur **"Ouvrir un chat"**.
3. Ouvrez un deuxieme onglet sur `http://127.0.0.1:8000/` et connectez-vous en tant qu'agent (`agent1` / `password123`).
4. Allez dans le menu **"Centre de Support"** de la barre laterale. Vous devriez y voir la conversation en attente de `client1`.
5. Cliquez dessus pour rejoindre. Vous pouvez maintenant echanger des messages instantanement.
6. **Fonctionnalites bonus incluses** :
   - Indicateur « en train d'ecrire... » (s'affiche en direct lorsque l'autre utilisateur tape).
   - Indicateur de presence en ligne (la pastille de statut change de couleur en temps reel).
   - Historique des messages sauvegarde en base de donnees.
