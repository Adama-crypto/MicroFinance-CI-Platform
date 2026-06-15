from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from rest_framework.test import APIClient
from rest_framework import status
from core.models import LoanRequest, RepaymentInstallment, Payment, InsuranceProduct, InsuranceSubscription, ChatConversation

User = get_user_model()


class PlatformTestCase(TestCase):
    def setUp(self):
        self.client_api = APIClient()

        self.client_user = User.objects.create_user(
            username='test_client', password='password123',
            role='CLIENT', region='Abidjan'
        )
        self.client_user2 = User.objects.create_user(
            username='test_client2', password='password123',
            role='CLIENT', region='Bouake'
        )
        self.agent_user = User.objects.create_user(
            username='test_agent', password='password123',
            role='AGENT', region='Bouake'
        )
        self.admin_user = User.objects.create_superuser(
            username='test_admin', password='password123',
            role='ADMIN'
        )

    def _get_token(self, username, password):
        """Helper: get JWT access token for a user."""
        resp = self.client_api.post('/api/auth/login/', {
            'username': username, 'password': password
        }, format='json')
        return resp.data['access']

    def _auth_as(self, user_type):
        credentials = {
            'client': ('test_client', 'password123'),
            'client2': ('test_client2', 'password123'),
            'agent': ('test_agent', 'password123'),
            'admin': ('test_admin', 'password123'),
        }
        username, password = credentials[user_type]
        token = self._get_token(username, password)
        self.client_api.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    # =========================================================================
    # TEST 1: Roles and User Creation
    # =========================================================================
    def test_user_roles(self):
        self.assertEqual(self.client_user.role, 'CLIENT')
        self.assertEqual(self.agent_user.role, 'AGENT')
        self.assertEqual(self.admin_user.role, 'ADMIN')

    # =========================================================================
    # TEST 2: Eligibility Score & Repayment Schedule Generation
    # =========================================================================
    def test_eligibility_score_and_repayment_schedule(self):
        loan = LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('90000.00'),
            reason='Test reason',
            status='SOUMISE'
        )
        # Score de base 50 + 15 pour montant < 100,000 = 65
        self.assertEqual(loan.eligibility_score, 65)

        loan.status = 'APPROUVEE'
        loan.generate_schedule()
        loan.save()

        installments = loan.installments.all()
        self.assertEqual(installments.count(), 4)

        # Total = 90,000 + 10% = 99,000 FCFA reparti en 4 echeances
        total_due = sum(i.amount_due for i in installments)
        self.assertEqual(total_due, Decimal('99000.00'))

    # =========================================================================
    # TEST 3: Payments auto-distribution across installments
    # =========================================================================
    def test_payments_distribution(self):
        loan = LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('200000.00'),
            reason='Test reason',
            status='DECAISSEE'
        )
        loan.generate_schedule()
        self.assertEqual(loan.installments.count(), 4)

        # Chaque echeance = 220,000 / 4 = 55,000 FCFA
        # Un paiement de 80,000 couvre la 1ere completement et 25,000 sur la 2eme
        Payment.objects.create(
            loan_request=loan,
            amount=Decimal('80000.00'),
            recorded_by=self.agent_user
        )

        inst1, inst2, inst3 = (loan.installments.all()[i] for i in range(3))
        self.assertTrue(inst1.is_paid)
        self.assertEqual(inst1.amount_paid, Decimal('55000.00'))
        self.assertFalse(inst2.is_paid)
        self.assertEqual(inst2.amount_paid, Decimal('25000.00'))
        self.assertEqual(inst3.amount_paid, Decimal('0.00'))

    # =========================================================================
    # TEST 4: SECURITE — Un client ne peut PAS changer le statut d'un credit
    # Doit recevoir 403 Forbidden
    # =========================================================================
    def test_client_cannot_change_credit_status(self):
        # Creer un credit
        loan = LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('150000.00'),
            reason='Test acces refuse',
            status='SOUMISE'
        )
        # Se connecter comme CLIENT
        self._auth_as('client')
        resp = self.client_api.patch(
            f'/api/credits/{loan.id}/status/',
            {'status': 'EN_ANALYSE'},
            format='json'
        )
        # Le client doit recevoir 403 Forbidden
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    # =========================================================================
    # TEST 5: SECURITE — Un client ne voit QUE ses propres credits
    # =========================================================================
    def test_client_sees_only_own_credits(self):
        # Credit pour client1
        LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('100000.00'),
            reason='Credit client1',
            status='SOUMISE'
        )
        # Credit pour client2
        LoanRequest.objects.create(
            client=self.client_user2,
            amount=Decimal('200000.00'),
            reason='Credit client2',
            status='SOUMISE'
        )
        # Se connecter comme client1
        self._auth_as('client')
        resp = self.client_api.get('/api/credits/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Avec la pagination, les resultats sont dans resp.data['results']
        results = resp.data.get('results', resp.data)
        # client1 ne doit voir que son propre credit (1 seul)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['client'], self.client_user.id)

    # =========================================================================
    # TEST 6: SECURITE — Un agent ne peut PAS acceder au dashboard admin
    # Doit recevoir 403 Forbidden
    # =========================================================================
    def test_agent_cannot_access_admin_dashboard(self):
        self._auth_as('agent')
        resp = self.client_api.get('/api/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    # =========================================================================
    # TEST 7: SECURITE — Un admin PEUT acceder au dashboard
    # =========================================================================
    def test_admin_can_access_dashboard(self):
        self._auth_as('admin')
        resp = self.client_api.get('/api/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('loans_by_status', resp.data)
        self.assertIn('recovery_stats', resp.data)

    # =========================================================================
    # TEST 8: SECURITE — Un agent PEUT changer le statut d'un credit
    # =========================================================================
    def test_agent_can_change_credit_status(self):
        loan = LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('150000.00'),
            reason='Test changement statut agent',
            status='SOUMISE'
        )
        self._auth_as('agent')
        resp = self.client_api.patch(
            f'/api/credits/{loan.id}/status/',
            {'status': 'EN_ANALYSE'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        loan.refresh_from_db()
        self.assertEqual(loan.status, 'EN_ANALYSE')

    # =========================================================================
    # TEST 9: WORKFLOW — Un agent ne peut PAS rétrograder un statut
    # =========================================================================
    def test_agent_cannot_downgrade_credit_status(self):
        """Le workflow est strictement unidirectionnel : EN_ANALYSE → SOUMISE interdit."""
        loan = LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('150000.00'),
            reason='Test workflow',
            status='EN_ANALYSE'
        )
        self._auth_as('agent')
        resp = self.client_api.patch(
            f'/api/credits/{loan.id}/status/',
            {'status': 'SOUMISE'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Rétrogradation interdite', resp.data.get('error', ''))

    # =========================================================================
    # TEST 10: RÈGLE MÉTIER — Un client ne peut avoir qu'1 crédit actif
    # =========================================================================
    def test_client_cannot_submit_two_active_loans(self):
        """Un client avec un crédit SOUMISE/EN_ANALYSE ne peut pas en soumettre un nouveau."""
        # Premier crédit actif
        LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('100000.00'),
            reason='Premier crédit actif',
            status='SOUMISE'
        )
        self._auth_as('client')
        resp = self.client_api.post('/api/credits/', {
            'amount': '50000.00',
            'reason': 'Deuxième crédit',
        }, format='json')
        # Doit être refusé (400 ou 422)
        self.assertIn(resp.status_code, [status.HTTP_400_BAD_REQUEST, 422])

    # =========================================================================
    # TEST 11: SÉCURITÉ — Changement de mot de passe correct
    # =========================================================================
    def test_change_password_success(self):
        """Un utilisateur peut changer son mot de passe avec l'ancien correct."""
        self._auth_as('client')
        resp = self.client_api.post('/api/auth/change-password/', {
            'old_password': 'password123',
            'new_password': 'NewPass456',
            'new_password_confirm': 'NewPass456',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertIn('message', resp.data)

    # =========================================================================
    # TEST 12: SÉCURITÉ — Changement de mot de passe avec mauvais ancien mdp
    # =========================================================================
    def test_change_password_wrong_old_password(self):
        """Un utilisateur ne peut pas changer son mdp avec un mauvais ancien mdp."""
        self._auth_as('client')
        resp = self.client_api.post('/api/auth/change-password/', {
            'old_password': 'mauvaismdp',
            'new_password': 'NewPass456',
            'new_password_confirm': 'NewPass456',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('old_password', resp.data)

    # =========================================================================
    # TEST 13: ADMIN — Lister les utilisateurs
    # =========================================================================
    def test_admin_can_list_users(self):
        """Un admin peut lister tous les utilisateurs via /api/admin/users/."""
        self._auth_as('admin')
        resp = self.client_api.get('/api/admin/users/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get('results', resp.data)
        # Il doit y avoir au moins 4 utilisateurs (setUp)
        self.assertGreaterEqual(len(results), 4)

    # =========================================================================
    # TEST 14: ADMIN — Toggle active d'un compte
    # =========================================================================
    def test_admin_can_toggle_user_active(self):
        """Un admin peut désactiver puis réactiver un compte client."""
        self._auth_as('admin')
        # Désactiver
        resp = self.client_api.patch(f'/api/admin/users/{self.client_user.id}/toggle_active/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['is_active'])
        # Réactiver
        resp2 = self.client_api.patch(f'/api/admin/users/{self.client_user.id}/toggle_active/')
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertTrue(resp2.data['is_active'])

    # =========================================================================
    # TEST 15: ADMIN — Un admin ne peut pas désactiver son propre compte
    # =========================================================================
    def test_admin_cannot_deactivate_self(self):
        """La protection contre l'auto-désactivation doit fonctionner."""
        self._auth_as('admin')
        resp = self.client_api.patch(f'/api/admin/users/{self.admin_user.id}/toggle_active/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # =========================================================================
    # TEST 16: ADMIN — Dashboard contient les nouvelles métriques
    # =========================================================================
    def test_admin_dashboard_contains_new_metrics(self):
        """Le dashboard doit retourner users_summary et today_activity."""
        self._auth_as('admin')
        resp = self.client_api.get('/api/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('users_summary', resp.data)
        self.assertIn('today_activity', resp.data)
        self.assertIn('total_clients', resp.data['users_summary'])
        self.assertIn('credits_submitted_today', resp.data['today_activity'])

    # =========================================================================
    # TEST 17: AGENT — Le journal d'audit est accessible à l'agent
    # =========================================================================
    def test_agent_can_access_audit_log(self):
        """Un agent peut consulter son journal d'activité."""
        self._auth_as('agent')
        resp = self.client_api.get('/api/agent/activity/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # =========================================================================
    # TEST 18: AGENT — Chaque changement de statut crée une entrée AuditLog
    # =========================================================================
    def test_status_change_creates_audit_log(self):
        """Un changement de statut par un agent crée une entrée dans AuditLog."""
        from core.models import AuditLog
        loan = LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('100000.00'),
            reason='Test audit',
            status='SOUMISE'
        )
        count_before = AuditLog.objects.count()
        self._auth_as('agent')
        self.client_api.patch(
            f'/api/credits/{loan.id}/status/',
            {'status': 'EN_ANALYSE'},
            format='json'
        )
        self.assertEqual(AuditLog.objects.count(), count_before + 1)
        log = AuditLog.objects.latest('timestamp')
        self.assertEqual(log.action, 'CREDIT_STATUS_CHANGE')

    # =========================================================================
    # TEST 19: SCORE — Le champ eligibility_score_detail est renseigné
    # =========================================================================
    def test_eligibility_score_detail_is_populated(self):
        """Après création, eligibility_score_detail doit contenir une explication."""
        loan = LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('80000.00'),
            reason='Test score detail',
            status='SOUMISE'
        )
        self.assertNotEqual(loan.eligibility_score_detail, '')
        self.assertIn('Score de base', loan.eligibility_score_detail)
        self.assertIn('Total', loan.eligibility_score_detail)

    # =========================================================================
    # TEST 20: PÉNALITÉS — Application automatique sur échéances en retard
    # =========================================================================
    def test_late_penalties_applied_to_installment(self):
        from core.services import apply_late_penalties
        loan = LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('100000.00'),
            reason='Test pénalités',
            status='DECAISSEE'
        )
        loan.generate_schedule()
        inst = loan.installments.first()
        inst.due_date = timezone.localdate() - timezone.timedelta(days=5)
        inst.save()

        updated = apply_late_penalties()
        inst.refresh_from_db()
        self.assertGreater(inst.penalty_amount, Decimal('0.00'))
        self.assertGreater(inst.total_due, inst.amount_due)
        self.assertGreaterEqual(updated, 1)

    # =========================================================================
    # TEST 21: CHAT — Assignation automatique à un agent disponible
    # =========================================================================
    def test_chat_auto_assigns_agent_on_create(self):
        self._auth_as('client')
        resp = self.client_api.post('/api/chat/conversations/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        conv = ChatConversation.objects.get(id=resp.data['id'])
        self.assertIsNotNone(conv.agent_id)
        self.assertEqual(conv.agent.role, 'AGENT')

    # =========================================================================
    # TEST 22: AGENT — Consultation du profil client agrégé
    # =========================================================================
    def test_agent_can_view_client_profile(self):
        LoanRequest.objects.create(
            client=self.client_user,
            amount=Decimal('120000.00'),
            reason='Profil test',
            status='SOUMISE'
        )
        self._auth_as('agent')
        resp = self.client_api.get(f'/api/agent/clients/{self.client_user.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('summary', resp.data)
        self.assertIn('loans', resp.data)
        self.assertEqual(resp.data['summary']['total_loans'], 1)

    # =========================================================================
    # TEST 23: ADMIN — Déclenchement manuel des alertes
    # =========================================================================
    def test_admin_can_run_alerts(self):
        self._auth_as('admin')
        resp = self.client_api.post('/api/admin/run-alerts/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('message', resp.data)
