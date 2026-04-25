import uuid
import secrets
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any, List
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.db.models import Sum, Q, F, Avg, Count, Case, When, Value
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class Currency(models.TextChoices):
    NGN = 'NGN', 'Nigerian Naira'
    KES = 'KES', 'Kenyan Shilling'
    GHS = 'GHS', 'Ghanaian Cedi'
    ZAR = 'ZAR', 'South African Rand'
    USD = 'USD', 'US Dollar'


class TransactionType(models.TextChoices):
    DEPOSIT = 'deposit', 'Deposit'
    WITHDRAWAL = 'withdrawal', 'Withdrawal'
    ESCROW_FUND = 'escrow_fund', 'Escrow Fund'
    ESCROW_RELEASE = 'escrow_release', 'Escrow Release'
    ESCROW_REFUND = 'escrow_refund', 'Escrow Refund'
    PLATFORM_FEE = 'platform_fee', 'Platform Fee'
    TRANSFER_IN = 'transfer_in', 'Transfer In'
    TRANSFER_OUT = 'transfer_out', 'Transfer Out'
    PAYOUT = 'payout', 'Payout'
    REVERSAL = 'reversal', 'Reversal'
    ADJUSTMENT = 'adjustment', 'Adjustment'
    BONUS = 'bonus', 'Bonus'
    PENALTY = 'penalty', 'Penalty'


class TransactionStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    SUCCESS = 'success', 'Success'
    FAILED = 'failed', 'Failed'
    REVERSED = 'reversed', 'Reversed'
    CANCELLED = 'cancelled', 'Cancelled'
    ON_HOLD = 'on_hold', 'On Hold'


class PaymentStatus(models.TextChoices):
    INITIALIZED = 'initialized', 'Initialized'
    PENDING = 'pending', 'Pending'
    SUCCESS = 'success', 'Success'
    FAILED = 'failed', 'Failed'
    ABANDONED = 'abandoned', 'Abandoned'
    REVERSED = 'reversed', 'Reversed'
    EXPIRED = 'expired', 'Expired'


class OrderStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    PENDING_PAYMENT = 'pending_payment', 'Pending Payment'
    PAID = 'paid', 'Paid'
    IN_PROGRESS = 'in_progress', 'In Progress'
    DELIVERED = 'delivered', 'Delivered'
    REVISION_REQUESTED = 'revision_requested', 'Revision Requested'
    COMPLETED = 'completed', 'Completed'
    CANCELLED = 'cancelled', 'Cancelled'
    DISPUTED = 'disputed', 'Disputed'
    REFUNDED = 'refunded', 'Refunded'
    ON_HOLD = 'on_hold', 'On Hold'


class EscrowStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    FUNDED = 'funded', 'Funded'
    PARTIALLY_RELEASED = 'partially_released', 'Partially Released'
    RELEASED = 'released', 'Released'
    REFUNDED = 'refunded', 'Refunded'
    PARTIALLY_REFUNDED = 'partially_refunded', 'Partially Refunded'
    DISPUTED = 'disputed', 'Disputed'
    CANCELLED = 'cancelled', 'Cancelled'
    EXPIRED = 'expired', 'Expired'


class PayoutStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    APPROVED = 'approved', 'Approved'
    PROCESSING = 'processing', 'Processing'
    SUCCESS = 'success', 'Success'
    FAILED = 'failed', 'Failed'
    REVERSED = 'reversed', 'Reversed'
    CANCELLED = 'cancelled', 'Cancelled'
    ON_HOLD = 'on_hold', 'On Hold'


class DisputeStatus(models.TextChoices):
    OPEN = 'open', 'Open'
    UNDER_REVIEW = 'under_review', 'Under Review'
    AWAITING_RESPONSE = 'awaiting_response', 'Awaiting Response'
    ESCALATED = 'escalated', 'Escalated'
    RESOLVED_CLIENT = 'resolved_client', 'Resolved - Client Favor'
    RESOLVED_FREELANCER = 'resolved_freelancer', 'Resolved - Freelancer Favor'
    RESOLVED_SPLIT = 'resolved_split', 'Resolved - Split'
    CLOSED = 'closed', 'Closed'
    WITHDRAWN = 'withdrawn', 'Withdrawn'


class DisputeReason(models.TextChoices):
    QUALITY = 'quality', 'Work Quality Issues'
    INCOMPLETE = 'incomplete', 'Incomplete Delivery'
    LATE_DELIVERY = 'late_delivery', 'Late Delivery'
    NOT_AS_DESCRIBED = 'not_as_described', 'Not As Described'
    COMMUNICATION = 'communication', 'Communication Issues'
    NON_DELIVERY = 'non_delivery', 'Non-Delivery'
    SCOPE_CREEP = 'scope_creep', 'Scope Creep'
    UNRESPONSIVE = 'unresponsive', 'Unresponsive Party'
    OTHER = 'other', 'Other'


CURRENCY_CONFIG = {
    'NGN': {'symbol': '₦', 'decimals': 2, 'min_amount': Decimal('100'), 'country': 'nigeria'},
    'KES': {'symbol': 'KSh', 'decimals': 2, 'min_amount': Decimal('100'), 'country': 'kenya'},
    'GHS': {'symbol': 'GH₵', 'decimals': 2, 'min_amount': Decimal('10'), 'country': 'ghana'},
    'ZAR': {'symbol': 'R', 'decimals': 2, 'min_amount': Decimal('50'), 'country': 'south_africa'},
    'USD': {'symbol': '$', 'decimals': 2, 'min_amount': Decimal('5'), 'country': 'international'},
}


def generate_reference(prefix: str = 'REF') -> str:
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
    random_part = secrets.token_hex(4).upper()
    return f"{prefix}-{timestamp}-{random_part}"


def generate_transaction_id() -> str:
    return f"TXN-{uuid.uuid4().hex[:16].upper()}"


def generate_order_number() -> str:
    timestamp = timezone.now().strftime('%Y%m%d')
    random_part = secrets.token_hex(3).upper()
    return f"ORD-{timestamp}-{random_part}"


class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditMixin(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_created'
    )
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_modified'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        abstract = True


class WalletQuerySet(models.QuerySet):
    def with_balance_stats(self):
        return self.annotate(
            total_credits=Coalesce(
                Sum('transactions__amount', filter=Q(
                    transactions__transaction_type__in=[
                        TransactionType.DEPOSIT, TransactionType.ESCROW_RELEASE,
                        TransactionType.TRANSFER_IN, TransactionType.REVERSAL,
                        TransactionType.BONUS, TransactionType.ESCROW_REFUND
                    ],
                    transactions__status=TransactionStatus.SUCCESS
                )),
                Decimal('0')
            ),
            total_debits=Coalesce(
                Sum('transactions__amount', filter=Q(
                    transactions__transaction_type__in=[
                        TransactionType.WITHDRAWAL, TransactionType.ESCROW_FUND,
                        TransactionType.TRANSFER_OUT, TransactionType.PAYOUT,
                        TransactionType.PLATFORM_FEE, TransactionType.PENALTY
                    ],
                    transactions__status=TransactionStatus.SUCCESS
                )),
                Decimal('0')
            ),
            transaction_count=Count('transactions', filter=Q(transactions__status=TransactionStatus.SUCCESS))
        )

    def active(self):
        return self.filter(is_active=True, is_frozen=False)

    def frozen(self):
        return self.filter(is_frozen=True)

    def with_positive_balance(self):
        return self.filter(balance__gt=0)

    def with_available_balance(self, min_amount: Decimal = Decimal('0')):
        return self.annotate(
            available=F('balance') - F('locked_balance')
        ).filter(available__gt=min_amount)

    def for_user(self, user):
        return self.filter(user=user)

    def by_currency(self, currency: str):
        return self.filter(currency=currency)


class WalletManager(models.Manager):
    def get_queryset(self):
        return WalletQuerySet(self.model, using=self._db)

    def get_or_create_for_user(self, user, currency: str = None):
        currency = currency or getattr(settings, 'DEFAULT_CURRENCY', Currency.KES)
        wallet, created = self.get_or_create(
            user=user,
            currency=currency,
            defaults={
                'balance': Decimal('0'),
                'locked_balance': Decimal('0'),
                'lifetime_deposits': Decimal('0'),
                'lifetime_withdrawals': Decimal('0'),
            }
        )
        return wallet, created

    def active(self):
        return self.get_queryset().active()

    def get_total_balance_for_user(self, user) -> Dict[str, Decimal]:
        wallets = self.filter(user=user, is_active=True)
        return {w.currency: w.available_balance for w in wallets}


class Wallet(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='wallets'
    )
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KES)
    balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))]
    )
    locked_balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))]
    )
    lifetime_deposits = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    lifetime_withdrawals = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    lifetime_earnings = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    is_active = models.BooleanField(default=True)
    is_frozen = models.BooleanField(default=False)
    frozen_at = models.DateTimeField(null=True, blank=True)
    frozen_reason = models.TextField(blank=True)
    last_transaction_at = models.DateTimeField(null=True, blank=True)
    daily_limit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    monthly_limit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = WalletManager()

    class Meta:
        unique_together = ['user', 'currency']
        indexes = [
            models.Index(fields=['user', 'currency']),
            models.Index(fields=['is_active', 'is_frozen']),
            models.Index(fields=['currency', 'balance']),
        ]

    def __str__(self):
        return f"{self.user}'s {self.currency} Wallet ({self.available_balance})"

    def clean(self):
        if self.locked_balance > self.balance:
            raise ValidationError({'locked_balance': 'Locked balance cannot exceed total balance'})

    @property
    def available_balance(self) -> Decimal:
        return (self.balance - self.locked_balance).quantize(Decimal('0.01'))

    @property
    def currency_symbol(self) -> str:
        return CURRENCY_CONFIG.get(self.currency, {}).get('symbol', '')

    @property
    def formatted_balance(self) -> str:
        return f"{self.currency_symbol}{self.balance:,.2f}"

    @property
    def formatted_available(self) -> str:
        return f"{self.currency_symbol}{self.available_balance:,.2f}"

    def can_debit(self, amount: Decimal) -> bool:
        return (
            self.is_active and
            not self.is_frozen and
            self.available_balance >= amount and
            amount > 0
        )

    def check_limits(self, amount: Decimal) -> Dict[str, Any]:
        issues = []
        today = timezone.now().date()
        month_start = today.replace(day=1)

        if self.daily_limit:
            daily_spent = Transaction.objects.filter(
                wallet=self,
                transaction_type__in=[TransactionType.WITHDRAWAL, TransactionType.PAYOUT, TransactionType.TRANSFER_OUT],
                status=TransactionStatus.SUCCESS,
                created_at__date=today
            ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

            if daily_spent + amount > self.daily_limit:
                issues.append({
                    'type': 'daily_limit',
                    'limit': self.daily_limit,
                    'used': daily_spent,
                    'remaining': self.daily_limit - daily_spent
                })

        if self.monthly_limit:
            monthly_spent = Transaction.objects.filter(
                wallet=self,
                transaction_type__in=[TransactionType.WITHDRAWAL, TransactionType.PAYOUT, TransactionType.TRANSFER_OUT],
                status=TransactionStatus.SUCCESS,
                created_at__date__gte=month_start
            ).aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

            if monthly_spent + amount > self.monthly_limit:
                issues.append({
                    'type': 'monthly_limit',
                    'limit': self.monthly_limit,
                    'used': monthly_spent,
                    'remaining': self.monthly_limit - monthly_spent
                })

        return {'within_limits': len(issues) == 0, 'issues': issues}

    @transaction.atomic
    def credit(self, amount: Decimal, update_lifetime: bool = False, is_earning: bool = False):
        if amount <= 0:
            raise ValidationError("Credit amount must be positive")
        if self.is_frozen:
            raise ValidationError("Wallet is frozen")

        self.balance = F('balance') + amount
        self.last_transaction_at = timezone.now()
        update_fields = ['balance', 'last_transaction_at', 'updated_at']

        if update_lifetime:
            self.lifetime_deposits = F('lifetime_deposits') + amount
            update_fields.append('lifetime_deposits')

        if is_earning:
            self.lifetime_earnings = F('lifetime_earnings') + amount
            update_fields.append('lifetime_earnings')

        self.save(update_fields=update_fields)
        self.refresh_from_db()

    @transaction.atomic
    def debit(self, amount: Decimal, update_lifetime: bool = False):
        if amount <= 0:
            raise ValidationError("Debit amount must be positive")
        if not self.can_debit(amount):
            raise ValidationError(f"Insufficient available balance. Available: {self.available_balance}")

        self.balance = F('balance') - amount
        self.last_transaction_at = timezone.now()
        update_fields = ['balance', 'last_transaction_at', 'updated_at']

        if update_lifetime:
            self.lifetime_withdrawals = F('lifetime_withdrawals') + amount
            update_fields.append('lifetime_withdrawals')

        self.save(update_fields=update_fields)
        self.refresh_from_db()

    @transaction.atomic
    def lock_funds(self, amount: Decimal):
        if amount <= 0:
            raise ValidationError("Lock amount must be positive")
        if self.available_balance < amount:
            raise ValidationError(f"Insufficient available balance to lock. Available: {self.available_balance}")

        self.locked_balance = F('locked_balance') + amount
        self.save(update_fields=['locked_balance', 'updated_at'])
        self.refresh_from_db()

    @transaction.atomic
    def unlock_funds(self, amount: Decimal):
        if amount <= 0:
            raise ValidationError("Unlock amount must be positive")
        if self.locked_balance < amount:
            raise ValidationError(f"Cannot unlock more than locked balance. Locked: {self.locked_balance}")

        self.locked_balance = F('locked_balance') - amount
        self.save(update_fields=['locked_balance', 'updated_at'])
        self.refresh_from_db()

    @transaction.atomic
    def freeze(self, reason: str = ''):
        self.is_frozen = True
        self.frozen_at = timezone.now()
        self.frozen_reason = reason
        self.save(update_fields=['is_frozen', 'frozen_at', 'frozen_reason', 'updated_at'])

    @transaction.atomic
    def unfreeze(self):
        self.is_frozen = False
        self.frozen_at = None
        self.frozen_reason = ''
        self.save(update_fields=['is_frozen', 'frozen_at', 'frozen_reason', 'updated_at'])


class TransactionQuerySet(models.QuerySet):
    def successful(self):
        return self.filter(status=TransactionStatus.SUCCESS)

    def pending(self):
        return self.filter(status=TransactionStatus.PENDING)

    def failed(self):
        return self.filter(status=TransactionStatus.FAILED)

    def for_wallet(self, wallet):
        return self.filter(wallet=wallet)

    def for_user(self, user):
        return self.filter(wallet__user=user)

    def credits(self):
        return self.filter(transaction_type__in=[
            TransactionType.DEPOSIT, TransactionType.ESCROW_RELEASE,
            TransactionType.TRANSFER_IN, TransactionType.REVERSAL,
            TransactionType.BONUS, TransactionType.ESCROW_REFUND
        ])

    def debits(self):
        return self.filter(transaction_type__in=[
            TransactionType.WITHDRAWAL, TransactionType.ESCROW_FUND,
            TransactionType.TRANSFER_OUT, TransactionType.PAYOUT,
            TransactionType.PLATFORM_FEE, TransactionType.PENALTY
        ])

    def in_date_range(self, start_date, end_date):
        return self.filter(created_at__range=[start_date, end_date])

    def today(self):
        return self.filter(created_at__date=timezone.now().date())

    def this_month(self):
        month_start = timezone.now().date().replace(day=1)
        return self.filter(created_at__date__gte=month_start)

    def by_type(self, transaction_type: str):
        return self.filter(transaction_type=transaction_type)

    def total_amount(self) -> Decimal:
        return self.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

    def with_related(self):
        return self.select_related('wallet', 'wallet__user', 'related_transaction')

    def summary_by_type(self):
        return self.values('transaction_type').annotate(
            count=Count('id'),
            total=Sum('amount'),
            avg=Avg('amount')
        ).order_by('-total')

    def daily_summary(self, days: int = 30):
        start_date = timezone.now() - timedelta(days=days)
        return self.filter(
            created_at__gte=start_date,
            status=TransactionStatus.SUCCESS
        ).annotate(date=TruncDate('created_at')).values('date').annotate(
            credits=Sum('amount', filter=Q(transaction_type__in=[
                TransactionType.DEPOSIT, TransactionType.ESCROW_RELEASE, TransactionType.TRANSFER_IN
            ])),
            debits=Sum('amount', filter=Q(transaction_type__in=[
                TransactionType.WITHDRAWAL, TransactionType.PAYOUT, TransactionType.TRANSFER_OUT
            ])),
            count=Count('id')
        ).order_by('date')


class TransactionManager(models.Manager):
    def get_queryset(self):
        return TransactionQuerySet(self.model, using=self._db)

    def successful(self):
        return self.get_queryset().successful()

    def for_user(self, user):
        return self.get_queryset().for_user(user)

    def create_transaction(
        self,
        wallet: 'Wallet',
        transaction_type: str,
        amount: Decimal,
        description: str = '',
        reference: str = None,
        provider_reference: str = None,
        metadata: dict = None,
        related_transaction: 'Transaction' = None,
        status: str = TransactionStatus.PENDING
    ) -> 'Transaction':
        return self.create(
            wallet=wallet,
            transaction_type=transaction_type,
            amount=amount,
            currency=wallet.currency,
            status=status,
            balance_before=wallet.balance,
            balance_after=wallet.balance,
            reference=reference or generate_reference('TXN'),
            provider_reference=provider_reference,
            description=description,
            metadata=metadata or {},
            related_transaction=related_transaction
        )


class Transaction(BaseModel):
    transaction_id = models.CharField(
        max_length=50,
        unique=True,
        default=generate_transaction_id,
        db_index=True
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices, db_index=True)
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    currency = models.CharField(max_length=3, choices=Currency.choices)
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING,
        db_index=True
    )
    balance_before = models.DecimalField(max_digits=18, decimal_places=2)
    balance_after = models.DecimalField(max_digits=18, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True, default=generate_reference, db_index=True)
    provider_reference = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    related_transaction = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='related_transactions'
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    objects = TransactionManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'transaction_type']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['reference']),
            models.Index(fields=['provider_reference']),
            models.Index(fields=['wallet', 'created_at']),
            models.Index(fields=['transaction_type', 'status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.transaction_id} - {self.transaction_type} - {self.amount} {self.currency}"

    @property
    def is_credit(self) -> bool:
        return self.transaction_type in [
            TransactionType.DEPOSIT, TransactionType.ESCROW_RELEASE,
            TransactionType.TRANSFER_IN, TransactionType.REVERSAL,
            TransactionType.BONUS, TransactionType.ESCROW_REFUND
        ]

    @property
    def is_debit(self) -> bool:
        return not self.is_credit

    @property
    def is_successful(self) -> bool:
        return self.status == TransactionStatus.SUCCESS

    @property
    def is_pending(self) -> bool:
        return self.status == TransactionStatus.PENDING

    @property
    def can_retry(self) -> bool:
        return self.status == TransactionStatus.FAILED and self.retry_count < 3

    @property
    def formatted_amount(self) -> str:
        symbol = CURRENCY_CONFIG.get(self.currency, {}).get('symbol', '')
        prefix = '+' if self.is_credit else '-'
        return f"{prefix}{symbol}{self.amount:,.2f}"

    def mark_success(self, balance_after: Decimal = None):
        self.status = TransactionStatus.SUCCESS
        self.processed_at = timezone.now()
        if balance_after is not None:
            self.balance_after = balance_after
        self.save(update_fields=['status', 'processed_at', 'balance_after', 'updated_at'])

    def mark_failed(self, reason: str = ''):
        self.status = TransactionStatus.FAILED
        self.failure_reason = reason
        self.processed_at = timezone.now()
        self.save(update_fields=['status', 'failure_reason', 'processed_at', 'updated_at'])

    def mark_reversed(self, reason: str = ''):
        self.status = TransactionStatus.REVERSED
        self.failure_reason = reason
        self.processed_at = timezone.now()
        self.save(update_fields=['status', 'failure_reason', 'processed_at', 'updated_at'])

    def increment_retry(self):
        self.retry_count = F('retry_count') + 1
        self.save(update_fields=['retry_count', 'updated_at'])
        self.refresh_from_db()


class PaystackPaymentQuerySet(models.QuerySet):
    def successful(self):
        return self.filter(status=PaymentStatus.SUCCESS)

    def pending(self):
        return self.filter(status__in=[PaymentStatus.INITIALIZED, PaymentStatus.PENDING])

    def failed(self):
        return self.filter(status=PaymentStatus.FAILED)

    def for_user(self, user):
        return self.filter(user=user)

    def deposits(self):
        return self.filter(payment_type='deposit')

    def order_payments(self):
        return self.filter(payment_type='order')

    def verified(self):
        return self.filter(verified=True)

    def unverified(self):
        return self.filter(verified=False)

    def expired(self):
        expiry_threshold = timezone.now() - timedelta(hours=24)
        return self.filter(status=PaymentStatus.INITIALIZED, created_at__lt=expiry_threshold)

    def with_related(self):
        return self.select_related('user', 'transaction')


class PaystackPaymentManager(models.Manager):
    def get_queryset(self):
        return PaystackPaymentQuerySet(self.model, using=self._db)

    def create_payment(self, user, amount: Decimal, currency: str, payment_type: str, metadata: dict = None):
        return self.create(
            user=user,
            amount=amount,
            currency=currency,
            email=user.email,
            payment_type=payment_type,
            metadata=metadata or {}
        )

    def get_by_reference(self, reference: str):
        return self.filter(Q(reference=reference) | Q(paystack_reference=reference)).first()


class PaystackPayment(BaseModel, AuditMixin):
    PAYMENT_TYPE_CHOICES = [
        ('deposit', 'Wallet Deposit'),
        ('order', 'Order Payment'),
        ('subscription', 'Subscription'),
        ('tip', 'Tip'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='paystack_payments')
    reference = models.CharField(max_length=100, unique=True, default=generate_reference, db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('1'))])
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KES)
    email = models.EmailField()
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.INITIALIZED)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='deposit')
    paystack_reference = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    authorization_url = models.URLField(max_length=500, blank=True, null=True)
    access_code = models.CharField(max_length=100, blank=True, null=True)
    channel = models.CharField(max_length=50, blank=True, null=True)
    card_type = models.CharField(max_length=50, blank=True, null=True)
    last_four = models.CharField(max_length=4, blank=True, null=True)
    bank = models.CharField(max_length=100, blank=True, null=True)
    authorization_code = models.CharField(max_length=100, blank=True, null=True)
    reusable = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    failure_reason = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_attempts = models.PositiveSmallIntegerField(default=0)
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment'
    )
    fees = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    gateway_response = models.TextField(blank=True)

    objects = PaystackPaymentManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['reference']),
            models.Index(fields=['paystack_reference']),
            models.Index(fields=['payment_type', 'status']),
            models.Index(fields=['verified', 'created_at']),
        ]

    def __str__(self):
        return f"Payment {self.reference} - {self.amount} {self.currency} ({self.status})"

    @property
    def is_expired(self) -> bool:
        if self.status != PaymentStatus.INITIALIZED:
            return False
        return timezone.now() > self.created_at + timedelta(hours=24)

    @property
    def formatted_amount(self) -> str:
        symbol = CURRENCY_CONFIG.get(self.currency, {}).get('symbol', '')
        return f"{symbol}{self.amount:,.2f}"

    @property
    def net_amount(self) -> Decimal:
        return self.amount - self.fees

    def mark_verified(self, paystack_data: dict):
        self.verified = True
        self.verified_at = timezone.now()
        self.status = PaymentStatus.SUCCESS
        self.paystack_reference = paystack_data.get('reference')
        self.channel = paystack_data.get('channel')
        self.paid_at = timezone.now()
        self.gateway_response = paystack_data.get('gateway_response', '')
        self.fees = Decimal(str(paystack_data.get('fees', 0))) / 100

        authorization = paystack_data.get('authorization', {})
        if authorization:
            self.authorization_code = authorization.get('authorization_code')
            self.card_type = authorization.get('card_type')
            self.last_four = authorization.get('last4')
            self.bank = authorization.get('bank')
            self.reusable = authorization.get('reusable', False)

        self.save()

    def mark_failed(self, reason: str = ''):
        self.status = PaymentStatus.FAILED
        self.failure_reason = reason
        self.save(update_fields=['status', 'failure_reason', 'updated_at'])

    def mark_expired(self):
        self.status = PaymentStatus.EXPIRED
        self.save(update_fields=['status', 'updated_at'])

    def increment_verification_attempts(self):
        self.verification_attempts = F('verification_attempts') + 1
        self.save(update_fields=['verification_attempts', 'updated_at'])
        self.refresh_from_db()


class EscrowQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status__in=[EscrowStatus.PENDING, EscrowStatus.FUNDED, EscrowStatus.PARTIALLY_RELEASED])

    def funded(self):
        return self.filter(status=EscrowStatus.FUNDED)

    def pending(self):
        return self.filter(status=EscrowStatus.PENDING)

    def disputed(self):
        return self.filter(status=EscrowStatus.DISPUTED)

    def for_order(self, order):
        return self.filter(order=order)

    def for_client(self, user):
        return self.filter(client=user)

    def for_freelancer(self, user):
        return self.filter(freelancer=user)

    def for_user(self, user):
        return self.filter(Q(client=user) | Q(freelancer=user))

    def due_for_release(self):
        return self.filter(status=EscrowStatus.FUNDED, auto_release_at__lte=timezone.now())

    def expiring_soon(self, days: int = 3):
        threshold = timezone.now() + timedelta(days=days)
        return self.filter(
            status=EscrowStatus.FUNDED,
            auto_release_at__lte=threshold,
            auto_release_at__gt=timezone.now()
        )

    def with_related(self):
        return self.select_related('order', 'client', 'freelancer')

    def total_held(self) -> Decimal:
        return self.filter(
            status__in=[EscrowStatus.FUNDED, EscrowStatus.PARTIALLY_RELEASED]
        ).aggregate(
            total=Coalesce(Sum(F('amount') - F('released_amount') - F('refunded_amount')), Decimal('0'))
        )['total']


class EscrowManager(models.Manager):
    def get_queryset(self):
        return EscrowQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def due_for_release(self):
        return self.get_queryset().due_for_release()

    def for_user(self, user):
        return self.get_queryset().for_user(user)


class Escrow(BaseModel):
    order = models.OneToOneField('Order', on_delete=models.PROTECT, related_name='escrow')
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='client_escrows')
    freelancer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='freelancer_escrows')
    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KES)
    platform_fee_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('10.00'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))]
    )
    platform_fee_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    released_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    refunded_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    status = models.CharField(max_length=20, choices=EscrowStatus.choices, default=EscrowStatus.PENDING, db_index=True)
    funded_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    auto_release_at = models.DateTimeField(null=True, blank=True, db_index=True)
    release_conditions = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    funding_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='funded_escrows'
    )
    payment_reference = models.CharField(max_length=100, blank=True, null=True)

    objects = EscrowManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['client', 'status']),
            models.Index(fields=['freelancer', 'status']),
            models.Index(fields=['auto_release_at']),
            models.Index(fields=['funded_at']),
        ]

    def __str__(self):
        return f"Escrow for Order {self.order_id} - {self.amount} {self.currency} ({self.status})"

    @property
    def remaining_amount(self) -> Decimal:
        return (self.amount - self.released_amount - self.refunded_amount).quantize(Decimal('0.01'))

    @property
    def freelancer_amount(self) -> Decimal:
        return (self.amount - self.platform_fee_amount).quantize(Decimal('0.01'))

    @property
    def release_percentage(self) -> Decimal:
        if self.amount == 0:
            return Decimal('0')
        return ((self.released_amount / self.amount) * 100).quantize(Decimal('0.01'))

    @property
    def is_fully_released(self) -> bool:
        return self.remaining_amount <= 0 and self.released_amount > 0

    @property
    def is_fully_refunded(self) -> bool:
        return self.remaining_amount <= 0 and self.refunded_amount > 0

    @property
    def days_until_auto_release(self) -> Optional[int]:
        if not self.auto_release_at:
            return None
        delta = self.auto_release_at - timezone.now()
        return max(0, delta.days)

    @property
    def formatted_amount(self) -> str:
        symbol = CURRENCY_CONFIG.get(self.currency, {}).get('symbol', '')
        return f"{symbol}{self.amount:,.2f}"

    def calculate_platform_fee(self) -> Decimal:
        fee = (self.amount * self.platform_fee_percentage / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.platform_fee_amount = fee
        return fee

    def mark_funded(self, payment_reference: str = None, transaction: Transaction = None):
        self.status = EscrowStatus.FUNDED
        self.funded_at = timezone.now()
        self.calculate_platform_fee()
        if payment_reference:
            self.payment_reference = payment_reference
        if transaction:
            self.funding_transaction = transaction
        self.save()

    def release(self, amount: Decimal):
        if amount > self.remaining_amount:
            raise ValidationError(f"Cannot release {amount}. Remaining: {self.remaining_amount}")
        if amount <= 0:
            raise ValidationError("Release amount must be positive")

        self.released_amount = F('released_amount') + amount
        self.save(update_fields=['released_amount', 'updated_at'])
        self.refresh_from_db()

        if self.remaining_amount <= 0:
            self.status = EscrowStatus.RELEASED
            self.released_at = timezone.now()
        elif self.released_amount > 0:
            self.status = EscrowStatus.PARTIALLY_RELEASED
        self.save(update_fields=['status', 'released_at', 'updated_at'])

    def refund(self, amount: Decimal):
        if amount > self.remaining_amount:
            raise ValidationError(f"Cannot refund {amount}. Remaining: {self.remaining_amount}")
        if amount <= 0:
            raise ValidationError("Refund amount must be positive")

        self.refunded_amount = F('refunded_amount') + amount
        self.save(update_fields=['refunded_amount', 'updated_at'])
        self.refresh_from_db()

        if self.remaining_amount <= 0:
            self.status = EscrowStatus.REFUNDED
            self.refunded_at = timezone.now()
        elif self.refunded_amount > 0 and self.released_amount == 0:
            self.status = EscrowStatus.PARTIALLY_REFUNDED
        self.save(update_fields=['status', 'refunded_at', 'updated_at'])


class OrderQuerySet(models.QuerySet):
    def for_client(self, user):
        return self.filter(client=user)

    def for_freelancer(self, user):
        return self.filter(freelancer=user)

    def for_user(self, user):
        return self.filter(Q(client=user) | Q(freelancer=user))

    def active(self):
        return self.exclude(status__in=[OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REFUNDED])

    def completed(self):
        return self.filter(status=OrderStatus.COMPLETED)

    def cancelled(self):
        return self.filter(status=OrderStatus.CANCELLED)

    def disputed(self):
        return self.filter(status=OrderStatus.DISPUTED)

    def in_progress(self):
        return self.filter(status__in=[
            OrderStatus.PAID, OrderStatus.IN_PROGRESS,
            OrderStatus.DELIVERED, OrderStatus.REVISION_REQUESTED
        ])

    def pending_payment(self):
        return self.filter(status=OrderStatus.PENDING_PAYMENT)

    def overdue(self):
        return self.filter(
            status__in=[OrderStatus.IN_PROGRESS, OrderStatus.REVISION_REQUESTED],
            due_date__lt=timezone.now()
        )

    def delivered_awaiting_acceptance(self, days: int = 7):
        threshold = timezone.now() - timedelta(days=days)
        return self.filter(status=OrderStatus.DELIVERED, delivered_at__lt=threshold)

    def with_related(self):
        return self.select_related('client', 'freelancer', 'escrow', 'chat_thread')

    def statistics(self) -> Dict[str, Any]:
        return self.aggregate(
            total_count=Count('id'),
            total_value=Coalesce(Sum('amount'), Decimal('0')),
            avg_value=Coalesce(Avg('amount'), Decimal('0')),
            completed_count=Count('id', filter=Q(status=OrderStatus.COMPLETED)),
            cancelled_count=Count('id', filter=Q(status=OrderStatus.CANCELLED)),
            disputed_count=Count('id', filter=Q(status=OrderStatus.DISPUTED)),
        )


class OrderManager(models.Manager):
    def get_queryset(self):
        return OrderQuerySet(self.model, using=self._db)

    def for_user(self, user):
        return self.get_queryset().for_user(user)

    def active(self):
        return self.get_queryset().active()

    def overdue(self):
        return self.get_queryset().overdue()


class Order(BaseModel, AuditMixin):
    order_number = models.CharField(max_length=20, unique=True, default=generate_order_number, db_index=True)
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='client_orders')
    freelancer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='freelancer_orders')
    title = models.CharField(max_length=255)
    description = models.TextField()
    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KES)
    platform_fee_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10.00'))
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.DRAFT, db_index=True)
    delivery_days = models.PositiveIntegerField(default=7, validators=[MinValueValidator(1), MaxValueValidator(365)])
    max_revisions = models.PositiveIntegerField(default=2, validators=[MaxValueValidator(10)])
    revisions_used = models.PositiveIntegerField(default=0)
    requirements = models.TextField(blank=True)
    deliverables = models.TextField(blank=True)
    due_date = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_orders'
    )
    chat_thread = models.ForeignKey(
        'chat.ChatThread',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders'
    )
    chat_offer = models.ForeignKey(
        'chat.ChatMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders'
    )
    priority = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(10)])
    is_featured = models.BooleanField(default=False)
    client_rating = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    freelancer_rating = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    client_review = models.TextField(blank=True)
    freelancer_review = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = OrderManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', 'status']),
            models.Index(fields=['freelancer', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['order_number']),
            models.Index(fields=['due_date']),
            models.Index(fields=['status', 'due_date']),
        ]

    def __str__(self):
        return f"Order {self.order_number} - {self.title} ({self.status})"

    def clean(self):
        if self.client_id == self.freelancer_id:
            raise ValidationError("Client and freelancer cannot be the same user")

    @property
    def is_overdue(self) -> bool:
        if not self.due_date:
            return False
        if self.status not in [OrderStatus.IN_PROGRESS, OrderStatus.REVISION_REQUESTED]:
            return False
        return timezone.now() > self.due_date

    @property
    def days_overdue(self) -> int:
        if not self.is_overdue:
            return 0
        delta = timezone.now() - self.due_date
        return delta.days

    @property
    def days_until_due(self) -> Optional[int]:
        if not self.due_date:
            return None
        if self.status not in [OrderStatus.IN_PROGRESS, OrderStatus.REVISION_REQUESTED]:
            return None
        delta = self.due_date - timezone.now()
        return max(0, delta.days)

    @property
    def can_request_revision(self) -> bool:
        return self.status == OrderStatus.DELIVERED and self.revisions_used < self.max_revisions

    @property
    def revisions_remaining(self) -> int:
        return max(0, self.max_revisions - self.revisions_used)

    @property
    def platform_fee_amount(self) -> Decimal:
        return (self.amount * self.platform_fee_percentage / 100).quantize(Decimal('0.01'))

    @property
    def freelancer_earnings(self) -> Decimal:
        return (self.amount - self.platform_fee_amount).quantize(Decimal('0.01'))

    @property
    def formatted_amount(self) -> str:
        symbol = CURRENCY_CONFIG.get(self.currency, {}).get('symbol', '')
        return f"{symbol}{self.amount:,.2f}"

    @property
    def completion_time_days(self) -> Optional[int]:
        if not self.started_at or not self.completed_at:
            return None
        delta = self.completed_at - self.started_at
        return delta.days

    def get_status_history(self) -> List[Dict]:
        return self.metadata.get('status_history', [])

    def add_status_history(self, from_status: str, to_status: str, changed_by=None, note: str = ''):
        history = self.metadata.setdefault('status_history', [])
        history.append({
            'from': from_status,
            'to': to_status,
            'changed_by': str(changed_by.id) if changed_by else None,
            'changed_at': timezone.now().isoformat(),
            'note': note
        })
        self.save(update_fields=['metadata', 'updated_at'])


class BankAccountQuerySet(models.QuerySet):
    def verified(self):
        return self.filter(is_verified=True)

    def unverified(self):
        return self.filter(is_verified=False)

    def active(self):
        return self.filter(is_active=True)

    def primary(self):
        return self.filter(is_primary=True)

    def for_user(self, user):
        return self.filter(user=user)

    def by_currency(self, currency: str):
        return self.filter(currency=currency)


class BankAccountManager(models.Manager):
    def get_queryset(self):
        return BankAccountQuerySet(self.model, using=self._db)

    def verified(self):
        return self.get_queryset().verified()

    def get_primary_for_user(self, user):
        return self.filter(user=user, is_primary=True, is_active=True, is_verified=True).first()

    def for_user(self, user):
        return self.get_queryset().for_user(user).active()


class BankAccount(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bank_accounts')
    bank_code = models.CharField(max_length=20)
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=20, validators=[RegexValidator(r'^\d{10,20}$', 'Enter a valid account number')])
    account_name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=50, blank=True)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KES)
    recipient_code = models.CharField(max_length=100, blank=True, null=True, db_index=True, unique=True)
    is_verified = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_attempts = models.PositiveSmallIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = BankAccountManager()

    class Meta:
        ordering = ['-is_primary', '-created_at']
        indexes = [
            models.Index(fields=['user', 'is_primary']),
            models.Index(fields=['recipient_code']),
            models.Index(fields=['user', 'is_active', 'is_verified']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'account_number', 'bank_code'],
                name='unique_user_bank_account'
            )
        ]

    def __str__(self):
        return f"{self.bank_name} - ****{self.account_number[-4:]}"

    @property
    def masked_account_number(self) -> str:
        if len(self.account_number) > 4:
            return '*' * (len(self.account_number) - 4) + self.account_number[-4:]
        return self.account_number

    @property
    def display_name(self) -> str:
        return f"{self.bank_name} ({self.masked_account_number})"

    @transaction.atomic
    def set_as_primary(self):
        BankAccount.objects.filter(user=self.user, is_primary=True).update(is_primary=False)
        self.is_primary = True
        self.save(update_fields=['is_primary', 'updated_at'])

    def mark_verified(self, recipient_code: str = None):
        self.is_verified = True
        self.verified_at = timezone.now()
        if recipient_code:
            self.recipient_code = recipient_code
        self.save(update_fields=['is_verified', 'verified_at', 'recipient_code', 'updated_at'])

    def mark_used(self):
        self.last_used_at = timezone.now()
        self.save(update_fields=['last_used_at', 'updated_at'])


class PayoutQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(status=PayoutStatus.PENDING)

    def approved(self):
        return self.filter(status=PayoutStatus.APPROVED)

    def processing(self):
        return self.filter(status=PayoutStatus.PROCESSING)

    def successful(self):
        return self.filter(status=PayoutStatus.SUCCESS)

    def failed(self):
        return self.filter(status=PayoutStatus.FAILED)

    def for_user(self, user):
        return self.filter(user=user)

    def by_date_range(self, start_date, end_date):
        return self.filter(created_at__range=[start_date, end_date])

    def with_related(self):
        return self.select_related('user', 'bank_account', 'transaction')

    def total_amount(self) -> Decimal:
        return self.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']

    def requires_approval(self):
        threshold = Decimal(getattr(settings, 'PAYOUT_APPROVAL_THRESHOLD', '10000'))
        return self.filter(status=PayoutStatus.PENDING, amount__gte=threshold)


class PayoutManager(models.Manager):
    def get_queryset(self):
        return PayoutQuerySet(self.model, using=self._db)

    def pending(self):
        return self.get_queryset().pending()

    def for_user(self, user):
        return self.get_queryset().for_user(user)


class Payout(BaseModel, AuditMixin):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payouts')
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name='payouts')
    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('1'))])
    fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    net_amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KES)
    reference = models.CharField(max_length=100, unique=True, default=generate_reference, db_index=True)
    transfer_code = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    transfer_reference = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=PayoutStatus.choices, default=PayoutStatus.PENDING, db_index=True)
    reason = models.CharField(max_length=255, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_payouts'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payout'
    )
    metadata = models.JSONField(default=dict, blank=True)

    objects = PayoutManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['reference']),
            models.Index(fields=['transfer_code']),
        ]

    def __str__(self):
        return f"Payout {self.reference} - {self.amount} {self.currency} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.net_amount:
            self.net_amount = self.amount - self.fee
        super().save(*args, **kwargs)

    @property
    def formatted_amount(self) -> str:
        symbol = CURRENCY_CONFIG.get(self.currency, {}).get('symbol', '')
        return f"{symbol}{self.amount:,.2f}"

    @property
    def requires_approval(self) -> bool:
        threshold = Decimal(getattr(settings, 'PAYOUT_APPROVAL_THRESHOLD', '10000'))
        return self.amount >= threshold

    @property
    def can_retry(self) -> bool:
        return self.status == PayoutStatus.FAILED and self.retry_count < 3

    def mark_approved(self, approved_by):
        self.status = PayoutStatus.APPROVED
        self.approved_by = approved_by
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    def mark_processing(self, transfer_code: str, transfer_reference: str = None):
        self.status = PayoutStatus.PROCESSING
        self.transfer_code = transfer_code
        self.transfer_reference = transfer_reference
        self.save(update_fields=['status', 'transfer_code', 'transfer_reference', 'updated_at'])

    def mark_success(self):
        self.status = PayoutStatus.SUCCESS
        self.processed_at = timezone.now()
        self.save(update_fields=['status', 'processed_at', 'updated_at'])

    def mark_failed(self, reason: str = ''):
        self.status = PayoutStatus.FAILED
        self.failure_reason = reason
        self.processed_at = timezone.now()
        self.retry_count = F('retry_count') + 1
        self.save(update_fields=['status', 'failure_reason', 'processed_at', 'retry_count', 'updated_at'])
        self.refresh_from_db()

    def mark_reversed(self, reason: str = ''):
        self.status = PayoutStatus.REVERSED
        self.failure_reason = reason
        self.save(update_fields=['status', 'failure_reason', 'updated_at'])


class DisputeQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=[
            DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW,
            DisputeStatus.AWAITING_RESPONSE, DisputeStatus.ESCALATED
        ])

    def resolved(self):
        return self.filter(status__in=[
            DisputeStatus.RESOLVED_CLIENT, DisputeStatus.RESOLVED_FREELANCER,
            DisputeStatus.RESOLVED_SPLIT, DisputeStatus.CLOSED
        ])

    def for_user(self, user):
        return self.filter(
            Q(raised_by=user) |
            Q(order__client=user) |
            Q(order__freelancer=user)
        )

    def for_order(self, order):
        return self.filter(order=order)

    def by_reason(self, reason: str):
        return self.filter(reason=reason)

    def escalated(self):
        return self.filter(status=DisputeStatus.ESCALATED)

    def stale(self, days: int = 7):
        threshold = timezone.now() - timedelta(days=days)
        return self.filter(
            status__in=[DisputeStatus.OPEN, DisputeStatus.AWAITING_RESPONSE],
            updated_at__lt=threshold
        )

    def with_related(self):
        return self.select_related('order', 'raised_by', 'resolved_by', 'order__client', 'order__freelancer')


class DisputeManager(models.Manager):
    def get_queryset(self):
        return DisputeQuerySet(self.model, using=self._db)

    def open(self):
        return self.get_queryset().open()

    def for_user(self, user):
        return self.get_queryset().for_user(user)


class Dispute(BaseModel, AuditMixin):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='disputes')
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='raised_disputes')
    reason = models.CharField(max_length=30, choices=DisputeReason.choices)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=DisputeStatus.choices, default=DisputeStatus.OPEN, db_index=True)
    priority = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(5)])
    resolution_notes = models.TextField(blank=True)
    client_refund_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    freelancer_payment_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_disputes'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='escalated_disputes'
    )
    evidence = models.JSONField(default=list, blank=True)
    response_deadline = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = DisputeManager()

    class Meta:
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['order', 'status']),
            models.Index(fields=['raised_by', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['priority', 'status']),
        ]

    def __str__(self):
        return f"Dispute #{self.id} for Order {self.order.order_number} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status in [
            DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW,
            DisputeStatus.AWAITING_RESPONSE, DisputeStatus.ESCALATED
        ]

    @property
    def is_resolved(self) -> bool:
        return self.status in [
            DisputeStatus.RESOLVED_CLIENT, DisputeStatus.RESOLVED_FREELANCER,
            DisputeStatus.RESOLVED_SPLIT, DisputeStatus.CLOSED
        ]

    @property
    def age_days(self) -> int:
        delta = timezone.now() - self.created_at
        return delta.days

    @property
    def time_to_resolution(self) -> Optional[int]:
        if not self.resolved_at:
            return None
        delta = self.resolved_at - self.created_at
        return delta.days

    def escalate(self, escalated_by, reason: str = ''):
        self.status = DisputeStatus.ESCALATED
        self.escalated_at = timezone.now()
        self.escalated_by = escalated_by
        self.priority = min(self.priority + 1, 5)
        self.metadata.setdefault('escalation_history', []).append({
            'escalated_by': str(escalated_by.id),
            'escalated_at': timezone.now().isoformat(),
            'reason': reason
        })
        self.save()

    def add_evidence(self, evidence_item: Dict):
        self.evidence.append({**evidence_item, 'added_at': timezone.now().isoformat()})
        self.save(update_fields=['evidence', 'updated_at'])


class WebhookEventQuerySet(models.QuerySet):
    def processed(self):
        return self.filter(processed=True)

    def unprocessed(self):
        return self.filter(processed=False)

    def failed(self):
        return self.filter(processed=False, retry_count__gt=0)

    def by_event_type(self, event_type: str):
        return self.filter(event_type=event_type)

    def by_provider(self, provider: str):
        return self.filter(provider=provider)

    def retriable(self, max_retries: int = 3):
        return self.filter(processed=False, retry_count__lt=max_retries)

    def stale(self, hours: int = 24):
        threshold = timezone.now() - timedelta(hours=hours)
        return self.filter(processed=False, created_at__lt=threshold)


class WebhookEventManager(models.Manager):
    def get_queryset(self):
        return WebhookEventQuerySet(self.model, using=self._db)

    def unprocessed(self):
        return self.get_queryset().unprocessed()

    def retriable(self, max_retries: int = 3):
        return self.get_queryset().retriable(max_retries)


class WebhookEvent(BaseModel):
    event_type = models.CharField(max_length=100, db_index=True)
    event_id = models.CharField(max_length=100, unique=True, db_index=True)
    payload = models.JSONField()
    headers = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=50, default='paystack', db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    objects = WebhookEventManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', 'processed']),
            models.Index(fields=['event_id']),
            models.Index(fields=['processed', 'created_at']),
            models.Index(fields=['provider', 'event_type']),
            models.Index(fields=['next_retry_at']),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.event_id} ({'Processed' if self.processed else 'Pending'})"

    @property
    def can_retry(self) -> bool:
        return not self.processed and self.retry_count < 5

    def mark_processed(self, result: dict = None):
        self.processed = True
        self.processed_at = timezone.now()
        if result:
            self.processing_result = result
        self.save(update_fields=['processed', 'processed_at', 'processing_result', 'updated_at'])

    def mark_failed(self, error: str):
        self.error_message = error
        self.retry_count = F('retry_count') + 1
        retry_delay = min(2 ** self.retry_count * 60, 3600)
        self.next_retry_at = timezone.now() + timedelta(seconds=retry_delay)
        self.save(update_fields=['error_message', 'retry_count', 'next_retry_at', 'updated_at'])
        self.refresh_from_db()


class PlatformRevenue(BaseModel):
    transaction = models.OneToOneField(Transaction, on_delete=models.PROTECT, related_name='platform_revenue')
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='platform_revenues', null=True, blank=True)
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name='platform_revenues', null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KES)
    fee_type = models.CharField(max_length=50, default='escrow_fee', db_index=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['fee_type', 'created_at']),
            models.Index(fields=['currency', 'created_at']),
        ]

    def __str__(self):
        return f"Platform Revenue: {self.amount} {self.currency} ({self.fee_type})"

    @classmethod
    def total_by_currency(cls, start_date=None, end_date=None) -> Dict[str, Decimal]:
        qs = cls.objects.all()
        if start_date:
            qs = qs.filter(created_at__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__lte=end_date)

        return dict(qs.values('currency').annotate(total=Sum('amount')).values_list('currency', 'total'))


class SavedCard(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_cards')
    authorization_code = models.CharField(max_length=100)
    card_type = models.CharField(max_length=50)
    last_four = models.CharField(max_length=4)
    exp_month = models.CharField(max_length=2)
    exp_year = models.CharField(max_length=4)
    bin = models.CharField(max_length=6, blank=True)
    bank = models.CharField(max_length=100)
    channel = models.CharField(max_length=50, default='card')
    signature = models.CharField(max_length=100, blank=True)
    country_code = models.CharField(max_length=5, blank=True)
    account_name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    last_used_at = models.DateTimeField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-is_default', '-last_used_at', '-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['authorization_code']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'signature'],
                condition=Q(signature__gt=''),
                name='unique_user_card_signature'
            )
        ]

    def __str__(self):
        return f"{self.card_type} ****{self.last_four}"

    @property
    def display_name(self) -> str:
        return f"{self.card_type} ending in {self.last_four}"

    @property
    def is_expired(self) -> bool:
        try:
            from datetime import datetime
            exp_date = datetime(int(self.exp_year), int(self.exp_month), 1, tzinfo=timezone.utc)
            return timezone.now() > exp_date
        except (ValueError, TypeError):
            return True

    @property
    def expiry_display(self) -> str:
        return f"{self.exp_month}/{self.exp_year[-2:]}"

    @transaction.atomic
    def set_as_default(self):
        SavedCard.objects.filter(user=self.user, is_default=True).update(is_default=False)
        self.is_default = True
        self.save(update_fields=['is_default', 'updated_at'])

    def mark_used(self):
        self.last_used_at = timezone.now()
        self.use_count = F('use_count') + 1
        self.save(update_fields=['last_used_at', 'use_count', 'updated_at'])
        self.refresh_from_db()

    def deactivate(self):
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])


class AuditLog(BaseModel):
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('view', 'View'),
        ('export', 'Export'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('payment', 'Payment'),
        ('payout', 'Payout'),
        ('refund', 'Refund'),
        ('dispute', 'Dispute'),
        ('approval', 'Approval'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'action']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['action', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user} - {self.action} - {self.object_repr}"

    @classmethod
    def log(cls, action: str, user=None, obj=None, changes: dict = None, ip_address: str = None, user_agent: str = '', extra_data: dict = None):
        content_type = None
        object_id = ''
        object_repr = ''

        if obj:
            content_type = ContentType.objects.get_for_model(obj)
            object_id = str(obj.pk)
            object_repr = str(obj)[:255]

        return cls.objects.create(
            user=user,
            action=action,
            content_type=content_type,
            object_id=object_id,
            object_repr=object_repr,
            changes=changes or {},
            ip_address=ip_address,
            user_agent=user_agent,
            extra_data=extra_data or {}
        )