from decimal import Decimal
from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import (
    Wallet,
    Transaction,
    PaystackPayment,
    Escrow,
    Order,
    Payout,
    BankAccount,
    Dispute,
    WebhookEvent,
    TransactionType,
    TransactionStatus,
    OrderStatus,
    EscrowStatus,
    PayoutStatus,
    DisputeStatus,
    Currency,
)

User = get_user_model()


class UserMinimalSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
    email = serializers.EmailField()


class WalletSerializer(serializers.ModelSerializer):
    user = UserMinimalSerializer(read_only=True)
    available_balance = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    
    class Meta:
        model = Wallet
        fields = [
            'id', 'user', 'currency', 'balance', 'locked_balance',
            'available_balance', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'balance', 'locked_balance', 'created_at', 'updated_at']


class WalletBalanceSerializer(serializers.Serializer):
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    locked_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    available_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()


class TransactionSerializer(serializers.ModelSerializer):
    wallet_id = serializers.UUIDField(source='wallet.id', read_only=True)
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'wallet_id', 'reference', 'amount', 'fee',
            'transaction_type', 'status', 'provider', 'provider_reference',
            'description', 'balance_before', 'balance_after',
            'created_at', 'completed_at'
        ]
        read_only_fields = fields


class TransactionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            'id', 'reference', 'amount', 'transaction_type',
            'status', 'description', 'created_at'
        ]
        read_only_fields = fields


class PaystackPaymentSerializer(serializers.ModelSerializer):
    user = UserMinimalSerializer(read_only=True)
    
    class Meta:
        model = PaystackPayment
        fields = [
            'id', 'user', 'reference', 'paystack_reference', 'amount',
            'currency', 'email', 'status', 'channel', 'card_type',
            'last_four', 'bank', 'gateway_response', 'paystack_fees',
            'paid_at', 'created_at'
        ]
        read_only_fields = fields


class InitializeDepositSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        min_value=Decimal('100.00')
    )
    currency = serializers.ChoiceField(
        choices=Currency.CHOICES,
        default=Currency.DEFAULT
    )
    callback_url = serializers.URLField(required=False)


class InitializeOrderPaymentSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    callback_url = serializers.URLField(required=False)


class VerifyPaymentSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=100)


class PaymentResponseSerializer(serializers.Serializer):
    payment_id = serializers.CharField()
    reference = serializers.CharField()
    authorization_url = serializers.URLField()
    access_code = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()


class EscrowSerializer(serializers.ModelSerializer):
    client = UserMinimalSerializer(read_only=True)
    freelancer = UserMinimalSerializer(read_only=True)
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    remaining_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    freelancer_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    
    class Meta:
        model = Escrow
        fields = [
            'id', 'reference', 'order_number', 'client', 'freelancer',
            'amount', 'released_amount', 'refunded_amount', 'remaining_amount',
            'platform_fee', 'freelancer_amount', 'currency', 'status',
            'funded_at', 'release_date', 'released_at', 'refunded_at',
            'created_at'
        ]
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    client = UserMinimalSerializer(read_only=True)
    freelancer = UserMinimalSerializer(read_only=True)
    freelancer_earnings = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    is_overdue = serializers.BooleanField(read_only=True)
    escrow = EscrowSerializer(read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'client', 'freelancer', 'title',
            'description', 'amount', 'platform_fee_percentage', 'platform_fee',
            'freelancer_earnings', 'currency', 'status', 'delivery_days',
            'revision_count', 'max_revisions', 'requirements', 'deliverables',
            'is_overdue', 'due_date', 'started_at', 'delivered_at',
            'completed_at', 'cancelled_at', 'cancellation_reason',
            'created_at', 'updated_at', 'escrow'
        ]
        read_only_fields = [
            'id', 'order_number', 'client', 'platform_fee', 'freelancer_earnings',
            'status', 'revision_count', 'is_overdue', 'due_date', 'started_at',
            'delivered_at', 'completed_at', 'cancelled_at', 'created_at', 'updated_at'
        ]


class OrderListSerializer(serializers.ModelSerializer):
    client_username = serializers.CharField(source='client.username', read_only=True)
    freelancer_username = serializers.CharField(source='freelancer.username', read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'client_username', 'freelancer_username',
            'title', 'amount', 'currency', 'status', 'due_date',
            'is_overdue', 'created_at'
        ]
        read_only_fields = fields


class CreateOrderSerializer(serializers.Serializer):
    freelancer_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        min_value=Decimal('100.00')
    )
    currency = serializers.ChoiceField(
        choices=Currency.CHOICES,
        default=Currency.DEFAULT
    )
    delivery_days = serializers.IntegerField(min_value=1, default=7)
    max_revisions = serializers.IntegerField(min_value=0, default=2)
    requirements = serializers.CharField(required=False, allow_blank=True)


class CreateOrderFromOfferSerializer(serializers.Serializer):
    offer_message_id = serializers.IntegerField()
    requirements = serializers.CharField(required=False, allow_blank=True)


class DeliverOrderSerializer(serializers.Serializer):
    deliverables = serializers.CharField(required=False, allow_blank=True)


class RequestRevisionSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10)


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10)


class ExtendDeadlineSerializer(serializers.Serializer):
    additional_days = serializers.IntegerField(min_value=1, max_value=30)
    reason = serializers.CharField(required=False, allow_blank=True)


class BankAccountSerializer(serializers.ModelSerializer):
    masked_account_number = serializers.SerializerMethodField()
    
    class Meta:
        model = BankAccount
        fields = [
            'id', 'bank_code', 'bank_name', 'masked_account_number',
            'account_name', 'currency', 'is_primary', 'is_verified',
            'is_active', 'created_at'
        ]
        read_only_fields = [
            'id', 'bank_name', 'account_name', 'is_verified', 'created_at'
        ]
    
    def get_masked_account_number(self, obj):
        if obj.account_number:
            return f"****{obj.account_number[-4:]}"
        return None


class AddBankAccountSerializer(serializers.Serializer):
    account_number = serializers.CharField(max_length=20)
    bank_code = serializers.CharField(max_length=20)
    currency = serializers.ChoiceField(
        choices=Currency.CHOICES,
        default=Currency.DEFAULT
    )
    is_primary = serializers.BooleanField(default=False)


class BankListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()
    country = serializers.CharField()
    currency = serializers.CharField()


class PayoutSerializer(serializers.ModelSerializer):
    bank_account = BankAccountSerializer(read_only=True)
    net_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    
    class Meta:
        model = Payout
        fields = [
            'id', 'reference', 'amount', 'fee', 'net_amount', 'currency',
            'status', 'bank_account', 'failure_reason',
            'requested_at', 'processed_at', 'completed_at'
        ]
        read_only_fields = fields


class PayoutListSerializer(serializers.ModelSerializer):
    bank_name = serializers.CharField(source='bank_account.bank_name', read_only=True)
    net_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    
    class Meta:
        model = Payout
        fields = [
            'id', 'reference', 'amount', 'fee', 'net_amount',
            'currency', 'status', 'bank_name', 'requested_at'
        ]
        read_only_fields = fields


class RequestPayoutSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        min_value=Decimal('100.00')
    )
    bank_account_id = serializers.UUIDField(required=False)
    currency = serializers.ChoiceField(
        choices=Currency.CHOICES,
        default=Currency.DEFAULT
    )


class DisputeSerializer(serializers.ModelSerializer):
    initiated_by = UserMinimalSerializer(read_only=True)
    resolved_by = UserMinimalSerializer(read_only=True)
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    
    class Meta:
        model = Dispute
        fields = [
            'id', 'reference', 'order_number', 'initiated_by', 'reason',
            'description', 'status', 'resolution_notes',
            'client_refund_amount', 'freelancer_payment_amount',
            'resolved_by', 'created_at', 'resolved_at'
        ]
        read_only_fields = fields


class CreateDisputeSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    reason = serializers.ChoiceField(choices=Dispute.REASON_CHOICES)
    description = serializers.CharField(min_length=20)


class ResolveDisputeSerializer(serializers.Serializer):
    RESOLUTION_CHOICES = [
        ('client', 'Full Refund to Client'),
        ('freelancer', 'Full Payment to Freelancer'),
        ('split', 'Split Between Both'),
    ]
    
    resolution = serializers.ChoiceField(choices=RESOLUTION_CHOICES)
    client_refund_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2,
        min_value=Decimal('0'), max_value=Decimal('100'),
        required=False
    )
    freelancer_payment_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2,
        min_value=Decimal('0'), max_value=Decimal('100'),
        required=False
    )
    resolution_notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, data):
        if data['resolution'] == 'split':
            client_pct = data.get('client_refund_percentage')
            freelancer_pct = data.get('freelancer_payment_percentage')
            
            if client_pct is None or freelancer_pct is None:
                raise serializers.ValidationError(
                    "Split resolution requires both percentages"
                )
            
            if client_pct + freelancer_pct != Decimal('100'):
                raise serializers.ValidationError(
                    "Percentages must sum to 100"
                )
        
        return data


class TransactionSummarySerializer(serializers.Serializer):
    total_credits = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_debits = serializers.DecimalField(max_digits=12, decimal_places=2)
    net_change = serializers.DecimalField(max_digits=12, decimal_places=2)
    transaction_count = serializers.IntegerField()


class OrderStatisticsSerializer(serializers.Serializer):
    total_orders = serializers.IntegerField()
    completed_orders = serializers.IntegerField()
    active_orders = serializers.IntegerField()
    cancelled_orders = serializers.IntegerField()
    completion_rate = serializers.FloatField()
    total_earnings = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    total_spent = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )


class WebhookEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEvent
        fields = [
            'id', 'event_type', 'provider', 'reference',
            'is_processed', 'is_valid', 'processing_error',
            'created_at', 'processed_at'
        ]
        read_only_fields = fields