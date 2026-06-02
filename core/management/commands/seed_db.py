from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from core.models import (
    LoanRequest, RepaymentInstallment, Payment,
    InsuranceProduct, InsuranceSubscription, Notification,
    ChatConversation, ChatMessage
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds the database with initial demo data for MicroFinance CI Platform.'

    def handle(self, *args, **options):
        self.stdout.write('Seeding database...')

        # 1. Clean existing data
        ChatMessage.objects.all().delete()
        ChatConversation.objects.all().delete()
        Notification.objects.all().delete()
        InsuranceSubscription.objects.all().delete()
        InsuranceProduct.objects.all().delete()
        Payment.objects.all().delete()
        RepaymentInstallment.objects.all().delete()
        LoanRequest.objects.all().delete()
        User.objects.all().delete()

        # 2. Create Users
        self.stdout.write('Creating users...')
        admin = User.objects.create_superuser(
            username='admin1',
            email='admin@microfinance.ci',
            password='password123',
            role='ADMIN',
            region='Abidjan',
            phone='+225 0707070707'
        )
        
        agent1 = User.objects.create_user(
            username='agent1',
            email='agent1@microfinance.ci',
            password='password123',
            role='AGENT',
            region='Bouaké',
            phone='+225 0505050505'
        )
        
        agent2 = User.objects.create_user(
            username='agent2',
            email='agent2@microfinance.ci',
            password='password123',
            role='AGENT',
            region='Yamoussoukro',
            phone='+225 0101010101'
        )

        client1 = User.objects.create_user(
            username='client1',
            email='client1@gmail.com',
            password='password123',
            role='CLIENT',
            region='Abidjan',
            phone='+225 0909090909'
        )

        client2 = User.objects.create_user(
            username='client2',
            email='client2@gmail.com',
            password='password123',
            role='CLIENT',
            region='Bouaké',
            phone='+225 0808080808'
        )

        # 3. Create Insurance Products
        self.stdout.write('Creating insurance products...')
        ins1 = InsuranceProduct.objects.create(
            name='Sécurité Mobile Standard',
            description='Couverture de base pour smartphone contre le vol et la casse accidentelle.',
            premium_amount=Decimal('1000.00'),
            coverage_amount=Decimal('50000.00'),
            duration_days=30
        )
        
        ins2 = InsuranceProduct.objects.create(
            name='Garantie Premium CI',
            description='Protection complète tous risques pour vos terminaux mobiles.',
            premium_amount=Decimal('2500.00'),
            coverage_amount=Decimal('150000.00'),
            duration_days=60
        )

        ins3 = InsuranceProduct.objects.create(
            name='Protection Micro-Business',
            description='Assurance spéciale pour commerçants couvrant les pertes de matériel mobile professionnel.',
            premium_amount=Decimal('5000.00'),
            coverage_amount=Decimal('500000.00'),
            duration_days=90
        )

        # 4. Create Insurance Subscriptions
        self.stdout.write('Creating insurance subscriptions...')
        sub1 = InsuranceSubscription.objects.create(
            client=client1,
            product=ins1,
            start_date=timezone.localdate() - timezone.timedelta(days=10),
            is_active=True
        )
        
        # Expired or near expiration subscription for testing (J-15 check)
        sub2 = InsuranceSubscription.objects.create(
            client=client2,
            product=ins2,
            start_date=timezone.localdate() - timezone.timedelta(days=45), # Ends in 15 days
            is_active=True
        )

        # 5. Create Loans
        self.stdout.write('Creating loan requests...')
        
        # Loan 1: client1, Disbursed, partly paid
        loan1 = LoanRequest.objects.create(
            client=client1,
            amount=Decimal('300000.00'),
            reason='Besoin de fonds de roulement pour commerce de détail.',
            status='DECAISSEE',
            interest_rate=Decimal('10.00'),
            duration_weeks=8
        )
        loan1.generate_schedule()
        
        # Make one installment paid and one partially paid
        # Inst 1 (Due date in past for testing J+1 overdue warnings)
        inst1 = loan1.installments.all()[0]
        inst1.due_date = timezone.localdate() - timezone.timedelta(days=5)
        inst1.save()
        
        # Inst 2 (Due date in 3 days for testing J-3 warnings)
        inst2 = loan1.installments.all()[1]
        inst2.due_date = timezone.localdate() + timezone.timedelta(days=3)
        inst2.save()
        
        # Let's record a payment of 82500 FCFA (covers first installment completely)
        payment1 = Payment.objects.create(
            loan_request=loan1,
            amount=Decimal('82500.00'),
            paid_at=timezone.now() - timezone.timedelta(days=4),
            recorded_by=agent1
        )
        
        # Loan 2: client2, Approved (not yet disbursed)
        loan2 = LoanRequest.objects.create(
            client=client2,
            amount=Decimal('150000.00'),
            reason="Achat de matériel agricole pour coopérative.",
            status='APPROUVEE',
            interest_rate=Decimal('10.00')
        )
        loan2.generate_schedule()

        # Loan 3: client1, Submitted (pending)
        loan3 = LoanRequest.objects.create(
            client=client1,
            amount=Decimal('600000.00'),
            reason="Frais de scolarité et matériel informatique.",
            status='SOUMISE',
            interest_rate=Decimal('10.00')
        )

        # 6. Create Chat Conversations
        self.stdout.write('Creating chat conversations...')
        chat1 = ChatConversation.objects.create(
            client=client1,
            agent=agent1,
            status='OPEN'
        )
        
        ChatMessage.objects.create(
            conversation=chat1,
            sender=client1,
            message="Bonjour, je souhaiterais savoir s'il est possible de prolonger mon échéance ?"
        )
        ChatMessage.objects.create(
            conversation=chat1,
            sender=agent1,
            message="Bonjour client1, oui c'est possible sous certaines conditions. Laissez-moi analyser votre dossier."
        )

        chat2 = ChatConversation.objects.create(
            client=client2,
            status='OPEN'
        )
        ChatMessage.objects.create(
            conversation=chat2,
            sender=client2,
            message="Allô ? J'aimerais souscrire à une assurance mobile premium."
        )

        # 7. Notifications
        self.stdout.write('Creating notifications...')
        Notification.objects.create(
            user=client1,
            message="Bienvenue sur la plateforme MicroFinance CI ! Votre profil a été configuré.",
            notification_type='SUPPORT',
            is_read=True
        )
        Notification.objects.create(
            user=client1,
            message="Votre crédit #1 a été décaissé.",
            notification_type='CREDIT_STATUS',
            is_read=False
        )

        self.stdout.write(self.style.SUCCESS('Database successfully seeded!'))
