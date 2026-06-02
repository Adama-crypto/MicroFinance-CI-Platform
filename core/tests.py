from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from rest_framework.test import APIClient
from rest_framework import status
from core.models import LoanRequest, RepaymentInstallment, Payment, InsuranceProduct, InsuranceSubscription

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
        # client1 ne doit voir que son propre credit (1 seul)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['client'], self.client_user.id)

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
