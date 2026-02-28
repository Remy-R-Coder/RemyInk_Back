from rest_framework import serializers
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
from .models import (
    User, FreelancerProfile, Role, Freelancer, Client, Rating,
    UserProfile, FeaturedClient, Portfolio, WorkExperience,
    Education, Certification, Skill
)
from notifications.models import NotificationPreference
from notifications.models import NotificationType
from orders.models import Job
from jobs.models import TaskCategory, TaskSubjectArea
from pay_freelancer.models import Payout, PayoutLog, PayoutStatus
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from notifications.models import Notification
from chat.models import ChatMessage, ChatThread
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from user_module.models import GuestSession


def is_guest_linked_client(user):
    if not user or user.role != Role.CLIENT:
        return False

    if GuestSession.objects.filter(shadow_client=user).exists():
        return True

    try:
        from chat.models import GuestSession as ChatGuestSession
        if ChatGuestSession.objects.filter(converted_to_user=user).exists():
            return True
    except Exception:
        pass

    return False


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskCategory
        fields = ['id', 'name']


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = 'email'

    def validate(self, attrs):
        email = attrs.get('email')
        if email:
            candidate = User.objects.filter(email__iexact=email).first()
            if candidate and not candidate.has_usable_password():
                raise serializers.ValidationError(
                    {"detail": "Password setup required. Check your email for the secure setup link."}
                )

        data = super().validate(attrs)
        user = self.user

        # Freelancer login endpoint should not issue tokens for unrelated roles.
        if user.role not in (Role.FREELANCER, Role.ADMIN):
            raise serializers.ValidationError(
                {"detail": "This account is not allowed to sign in as freelancer."}
            )

        data["user"] = {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
        }
        return data


class SubjectAreaSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = TaskSubjectArea
        fields = ['id', 'name', 'category']


class FreelancerProfileSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    avg_price = serializers.SerializerMethodField()
    avg_delivery_time = serializers.SerializerMethodField()
    avg_rating = serializers.SerializerMethodField()
    total_chats = serializers.SerializerMethodField()
    avg_response_time = serializers.SerializerMethodField()
    completed_jobs = serializers.IntegerField(read_only=True)
    hourly_rate = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    experience_years = serializers.IntegerField(read_only=True)
    bio = serializers.CharField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)
    has_payout_method = serializers.BooleanField(read_only=True)
    payout_method_details = serializers.SerializerMethodField()

    class Meta:
        model = FreelancerProfile
        fields = [
            'user',
            'mpesa_number',
            'categories',
            'subjects',
            'avg_price',
            'avg_delivery_time',
            'avg_rating',
            'total_chats',  
            'avg_response_time',
            'completed_jobs',
            'hourly_rate',
            'experience_years',
            'bio',
            'is_available',
            'has_payout_method',
            'payout_method_details',
            'payout_preference',
        ]
        extra_kwargs = {
            'categories': {'read_only': True},
            'subjects': {'read_only': True},
            'payout_preference': {'read_only': True},
        }

    def get_user(self, obj):
        return {
            'id': obj.user.id,
            'username': obj.user.username,
            'is_admin': obj.user.role == Role.ADMIN,
        }

    def get_avg_price(self, obj):
        subject_id = self.context.get('subject_id')
        avg_price = Job.objects.filter(
            freelancer__id=obj.user.id,
            subject_area__id=subject_id
        ).aggregate(Avg('price'))['price__avg']
        return round(avg_price, 2) if avg_price is not None else 50.00

    def get_avg_delivery_time(self, obj):
        subject_id = self.context.get('subject_id')
        avg_time = Job.objects.filter(
            freelancer__id=obj.user.id,
            subject_area__id=subject_id
        ).aggregate(Avg('delivery_time_days'))['delivery_time_days__avg']
        return round(avg_time) if avg_time is not None else 3

    def get_avg_rating(self, obj):
        avg = Rating.objects.filter(rated_user=obj.user).aggregate(Avg("score"))["score__avg"]
        return round(avg, 1) if avg is not None else None

    def get_total_chats(self, obj):
        return ChatThread.objects.filter(freelancer=obj.user).count()

    def get_avg_response_time(self, obj):
        return "< 1 hour"

    def get_payout_method_details(self, obj):
        return obj.payout_method_details


class UserSerializer(serializers.ModelSerializer):
    freelancerprofile = FreelancerProfileSerializer(read_only=True)
    unread_messages = serializers.SerializerMethodField()
    balance_info = serializers.SerializerMethodField()
    is_freelancer = serializers.BooleanField(read_only=True)
    is_shadow_account = serializers.SerializerMethodField() 

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'phone',
            'role',
            'is_active',
            'warnings',
            'suspended_until',
            'freelancerprofile',
            'unread_messages',
            'balance_info',
            'is_freelancer',
            'current_balance',
            'pending_balance',
            'total_earnings',
            'is_shadow_account',
        ]
        read_only_fields = [
            'username', 'role', 'is_active', 'warnings', 'suspended_until',
            'current_balance', 'pending_balance', 'total_earnings', 'is_shadow_account'
        ]

    def get_unread_messages(self, obj):
        if obj.role in [Role.FREELANCER, Role.ADMIN]:
            return ChatMessage.objects.filter(
                Q(thread__freelancer=obj)
            ).exclude(
                sender=obj
            ).exclude(
                read_by__user=obj
            ).count()
        elif obj.role == Role.CLIENT:
            return ChatMessage.objects.filter(
                Q(thread__client=obj)
            ).exclude(
                sender=obj
            ).exclude(
                read_by__user=obj
            ).count()
        return 0

    def get_balance_info(self, obj):
        return {
            'current_balance': str(obj.current_balance),
            'pending_balance': str(obj.pending_balance),
            'total_earnings': str(obj.total_earnings),
            'available_for_payout': obj.available_for_payout,
            'total_payouts': str(obj.total_payouts),
        }
        
    def get_is_shadow_account(self, obj):
        return obj.role == Role.CLIENT and not obj.is_active


class FreelancerOnboardingSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    categories = serializers.PrimaryKeyRelatedField(
        queryset=TaskCategory.objects.all(), 
        many=True, 
        write_only=True, 
        required=False,
        allow_empty=True
    )
    subjects = serializers.PrimaryKeyRelatedField(
        queryset=TaskSubjectArea.objects.all(), 
        many=True, 
        write_only=True, 
        required=False,
        allow_empty=True
    )
    mpesa_number = serializers.CharField(write_only=True, required=False, allow_blank=True)
    hourly_rate = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    experience_years = serializers.IntegerField(required=False, default=0)
    bio = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            'email', 'password', 'phone', 'categories', 'subjects', 
            'mpesa_number', 'hourly_rate', 'experience_years', 'bio'
        ]
    
    def validate(self, data):
        categories_data = data.get('categories', [])
        subjects_data = data.get('subjects', [])

        if subjects_data and not categories_data:
            raise serializers.ValidationError({"categories": "Categories are required if subjects are provided."})
            
        if subjects_data and categories_data:
            subject_category_ids = {subject.category.id for subject in subjects_data}
            selected_category_ids = {category.id for category in categories_data}
            
            if not subject_category_ids.issubset(selected_category_ids):
                raise serializers.ValidationError({"subjects": "All selected subjects must belong to one of the selected categories."})
            
            if len(subjects_data) > 3:
                raise serializers.ValidationError({"subjects": "You can only select up to 3 subject areas."})
            
        return data

    @transaction.atomic
    def create(self, validated_data):
        categories_data = validated_data.pop("categories", [])
        subjects_data = validated_data.pop("subjects", [])
        mpesa_number = validated_data.pop("mpesa_number", "")
        hourly_rate = validated_data.pop("hourly_rate", None)
        experience_years = validated_data.pop("experience_years", 0)
        bio = validated_data.pop("bio", "")
        password = validated_data.pop("password")
        
        user, _ = User.objects.create_freelancer(
            email=validated_data["email"],
            password=password,
            phone=validated_data.get("phone"),
        )
        
        freelancer_user = Freelancer.objects.get(id=user.id)
        
        profile = freelancer_user.freelancerprofile
        profile.mpesa_number = mpesa_number
        profile.hourly_rate = hourly_rate
        profile.experience_years = experience_years
        profile.bio = bio
        profile.save()
        
        profile.categories.set(categories_data)
        profile.subjects.set(subjects_data)
        
        return user


class ClientAccountFinalizeSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    
    def validate_email(self, value):
        request = self.context['request']
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            raise serializers.ValidationError("Authentication context is missing.")

        user = request.user 
        
        if User.objects.filter(email=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    @transaction.atomic
    def save(self):
        user = self.context['request'].user
        user.email = self.validated_data['email']
        user.set_password(self.validated_data['password'])
        user.is_active = True
        user.save()

        # Link any guest threads to this now-active client account
        try:
            from chat.models import GuestSession, ChatThread
            from chat.services import ChatThreadService
            import logging
            logger = logging.getLogger(__name__)

            # Find guest session by looking at threads linked to this shadow client
            # Shadow clients have email format: client###.{hex}.{session[:8]}.shadow
            if user.email and '.shadow' in str(user.email):
                # Extract session key from email
                email_parts = str(user.email).split('.')
                if len(email_parts) >= 4:
                    session_prefix = email_parts[-2]  # Get session[:8] part

                    # Find matching guest session
                    guest_sessions = GuestSession.objects.filter(
                        session_key__startswith=session_prefix,
                        converted_to_user__isnull=True
                    )

                    for guest_session in guest_sessions:
                        # Link threads for this guest session (if not already linked)
                        linked_count = ChatThreadService.link_guest_threads_to_client(
                            client=user,
                            guest_session_key=guest_session.session_key
                        )
                        if linked_count > 0:
                            logger.info(f"Automatically linked {linked_count} guest threads to finalized client {user.username}")

            # Also check threads that already have this client linked
            # (they may have been linked when guest sent first message)
            threads_to_update = ChatThread.objects.filter(
                client=user,
                guest_session_key__isnull=False
            )

            for thread in threads_to_update:
                # Mark the guest session as converted if it exists
                try:
                    guest_session = GuestSession.objects.get(session_key=thread.guest_session_key)
                    if not guest_session.converted_to_user:
                        guest_session.mark_converted(user)
                        logger.info(f"Marked guest session {thread.guest_session_key[:8]}... as converted to {user.username}")
                except GuestSession.DoesNotExist:
                    pass

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not auto-link guest threads during client finalization: {e}")

        return user


class ClientTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = 'email'

    def validate(self, attrs):
        email = attrs.get('email')
        if email:
            candidate = User.objects.filter(email__iexact=email).first()
            if candidate and not candidate.has_usable_password():
                raise serializers.ValidationError(
                    {"detail": "Password setup required. Check your email for the secure setup link."}
                )

        data = super().validate(attrs)
        user = self.user

        # Client login endpoint should not issue tokens for unrelated roles.
        if user.role not in (Role.CLIENT, Role.ADMIN):
            raise serializers.ValidationError(
                {"detail": "This account is not allowed to sign in as client."}
            )

        data["user"] = {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
        }
        return data


class SetupPasswordConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, min_length=8, required=True)
    confirm_password = serializers.CharField(write_only=True, min_length=8, required=True)

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})

        try:
            user_id = urlsafe_base64_decode(attrs['uid']).decode()
            user = User.objects.get(pk=user_id)
        except Exception:
            raise serializers.ValidationError({'uid': 'Invalid setup link.'})

        if not default_token_generator.check_token(user, attrs['token']):
            raise serializers.ValidationError({'token': 'Invalid or expired setup link.'})

        if not is_guest_linked_client(user):
            raise serializers.ValidationError({'detail': 'This setup flow is available for guest-converted client accounts only.'})

        attrs['user'] = user
        return attrs

    def save(self):
        user = self.validated_data['user']
        user.set_password(self.validated_data['password'])
        user.is_active = True
        user.save(update_fields=['password', 'is_active'])
        return user


class SetupPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class FreelancerListSerializer(serializers.ModelSerializer):
    profile = FreelancerProfileSerializer(source='freelancerprofile', read_only=True)
    avg_rating = serializers.SerializerMethodField()
    is_admin = serializers.SerializerMethodField()
    active_chats = serializers.SerializerMethodField()
    response_rate = serializers.SerializerMethodField()
    total_earnings = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    current_balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'phone',
            'profile',
            'avg_rating',
            'is_admin',
            'active_chats',
            'response_rate',
            'total_earnings',
            'current_balance',
        ]

    def get_avg_rating(self, obj):
        avg = Rating.objects.filter(rated_user=obj).aggregate(Avg("score"))["score__avg"]
        return round(avg, 1) if avg is not None else None

    def get_is_admin(self, obj):
        return obj.role == Role.ADMIN

    def get_active_chats(self, obj):
        seven_days_ago = timezone.now() - timedelta(days=7)
        return ChatThread.objects.filter(
            freelancer=obj,
            updated_at__gte=seven_days_ago
        ).count()

    def get_response_rate(self, obj):
        total_threads = ChatThread.objects.filter(freelancer=obj).count()
        if total_threads == 0:
            return 100  
        
        threads_with_response = ChatThread.objects.filter(
            freelancer=obj,
            messages__sender=obj
        ).distinct().count()
        
        return round((threads_with_response / total_threads) * 100)


class RatingSerializer(serializers.ModelSerializer):
    rater_username = serializers.CharField(source="rater.username", read_only=True)
    rated_user_username = serializers.CharField(source="rated_user.username", read_only=True)
    job_id = serializers.UUIDField(source='job.id', read_only=True)
    job_title = serializers.CharField(source='job.title', read_only=True)

    class Meta:
        model = Rating
        fields = [
            'id', 'rater', 'rated_user', 'job', 'job_id', 'job_title',
            'score', 'review', 'created_at', 'rater_username', 'rated_user_username'
        ]
        read_only_fields = ['id', 'created_at', 'rater_username', 'rated_user_username', 'job_id', 'job_title']


class PayoutLogSerializer(serializers.ModelSerializer):
    triggered_by_username = serializers.CharField(source='triggered_by.username', read_only=True)
    
    class Meta:
        model = PayoutLog
        fields = ['id', 'status_update', 'response_data', 'timestamp', 'triggered_by', 'triggered_by_username']
        read_only_fields = ['id', 'timestamp', 'triggered_by_username']


class PayoutSerializer(serializers.ModelSerializer):
    freelancer_username = serializers.CharField(source='freelancer.username', read_only=True)
    freelancer_email = serializers.CharField(source='freelancer.email', read_only=True)
    job_title = serializers.CharField(source='job.title', read_only=True)
    job_id = serializers.UUIDField(source='job.id', read_only=True)
    net_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_completed = serializers.BooleanField(read_only=True)
    is_processing = serializers.BooleanField(read_only=True)
    can_retry = serializers.BooleanField(read_only=True)
    logs = PayoutLogSerializer(many=True, read_only=True)

    class Meta:
        model = Payout
        fields = [
            'id',
            'reference',
            'freelancer',
            'freelancer_username',
            'freelancer_email',
            'job',
            'job_title',
            'job_id',
            'payout_amount',
            'fee_amount',
            'net_amount',
            'recipient_code',
            'transfer_code',
            'status',
            'response_data',
            'error_message',
            'retry_count',
            'last_retry_at',
            'processed_at',
            'created_at',
            'updated_at',
            'is_completed',
            'is_processing',
            'can_retry',
            'logs',
        ]
        read_only_fields = [
            'id', 'reference', 'created_at', 'updated_at', 'transfer_code',
            'response_data', 'error_message', 'retry_count', 'last_retry_at',
            'processed_at', 'net_amount', 'is_completed', 'is_processing',
            'can_retry', 'logs'
        ]

    def validate(self, data):
        user = self.context['request'].user
        
        if data['payout_amount'] <= Decimal('0.00'):
            raise serializers.ValidationError({'payout_amount': 'Payout amount must be positive.'})
        
        if data['payout_amount'] < Payout.MINIMUM_PAYOUT:
            raise serializers.ValidationError({
                'payout_amount': f'Payout amount must be at least {Payout.MINIMUM_PAYOUT}.'
            })
        
        if not user.available_for_payout:
            raise serializers.ValidationError('No balance available for payout.')
        
        if user.current_balance < data['payout_amount']:
            raise serializers.ValidationError(f'Insufficient balance. Available: {user.current_balance}')
        
        profile = user.freelancerprofile
        if not profile.has_payout_method:
            raise serializers.ValidationError('Please set up your payout method first.')
        
        if profile.payout_preference == 'MPESA' and not profile.mpesa_number:
            raise serializers.ValidationError('M-Pesa number is required for payout.')
        
        return data

    def create(self, validated_data):
        user = self.context['request'].user
        profile = user.freelancerprofile
        
        payout = Payout.objects.create(
            freelancer=user,
            payout_amount=validated_data['payout_amount'],
            recipient_code=validated_data.get('recipient_code') or profile.mpesa_number,
            job=validated_data.get('job'),
        )
        
        return payout


class PayoutRequestSerializer(serializers.Serializer):
    payout_amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    job_id = serializers.UUIDField(required=False, allow_null=True)
    recipient_code = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, data):
        user = self.context['request'].user
        
        if data['payout_amount'] < Payout.MINIMUM_PAYOUT:
            raise serializers.ValidationError({
                'payout_amount': f'Payout amount must be at least {Payout.MINIMUM_PAYOUT}.'
            })
        
        if user.current_balance < data['payout_amount']:
            raise serializers.ValidationError(f'Insufficient balance. Available: {user.current_balance}')
        
        return data


class FreelancerProfileUpdateSerializer(serializers.ModelSerializer):
    categories = serializers.PrimaryKeyRelatedField(
        queryset=TaskCategory.objects.all(), 
        many=True, 
        required=False
    )
    subjects = serializers.PrimaryKeyRelatedField(
        queryset=TaskSubjectArea.objects.all(), 
        many=True, 
        required=False
    )
    
    class Meta:
        model = FreelancerProfile
        fields = [
            'bio',
            'hourly_rate',
            'experience_years',
            'is_available',
            'max_jobs_concurrent',
            'categories',
            'subjects',
            'mpesa_number',
            'payout_preference',
        ]
    
    def validate(self, data):
        categories_data = data.get('categories', None)
        subjects_data = data.get('subjects', None)
        
        if subjects_data is not None and categories_data is not None:
            subject_category_ids = {subject.category.id for subject in subjects_data}
            selected_category_ids = {category.id for category in categories_data}
            
            if not subject_category_ids.issubset(selected_category_ids):
                raise serializers.ValidationError({"subjects": "All selected subjects must belong to one of the selected categories."})
            
            if len(subjects_data) > 3:
                raise serializers.ValidationError({"subjects": "You can only select up to 3 subject areas."})
        
        return data


class PayoutMethodUpdateSerializer(serializers.Serializer):
    payout_preference = serializers.ChoiceField(choices=[('MPESA', 'M-Pesa')])
    mpesa_number = serializers.CharField(required=True)
    
    def validate(self, data):
        if data['payout_preference'] == 'MPESA' and not data['mpesa_number']:
            raise serializers.ValidationError({'mpesa_number': 'M-Pesa number is required.'})
        return data


class JobSerializer(serializers.ModelSerializer):
    client = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    chat_thread_id = serializers.SerializerMethodField()
    unread_messages = serializers.SerializerMethodField()
    deadline = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            'id', 'title', 'description', 'price', 'status', 'deadline', 
            'progress', 'client', 'chat_thread_id', 'unread_messages'
        ]

    def get_client(self, obj):
        return {
            'name': obj.client.username,
            'avatar': obj.client.profile.avatar.url if hasattr(obj.client, 'profile') and obj.client.profile.avatar else None
        }

    def get_progress(self, obj):
        return 0

    def get_deadline(self, obj):
        return obj.delivery_time_days

    def get_chat_thread_id(self, obj):
        thread = ChatThread.objects.filter(
            freelancer=obj.freelancer,
            client=obj.client
        ).first()
        return thread.id if thread else None

    def get_unread_messages(self, obj):
        thread = ChatThread.objects.filter(
            freelancer=obj.freelancer,
            client=obj.client
        ).first()
        
        if not thread:
            return 0
        
        return ChatMessage.objects.filter(
            thread=thread
        ).exclude(
            sender=obj.freelancer
        ).exclude(
            read_by__user=obj.freelancer
        ).count()


class NotificationSerializer(serializers.ModelSerializer):
    thread_id = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'title', 'message', 'created_at', 'is_read', 'link', 'thread_id']

    def get_thread_id(self, obj):
        if obj.notification_type == NotificationType.MESSAGE and obj.link and obj.link.startswith("/messages/"):
            try:
                return int(obj.link.replace("/messages/", ""))
            except ValueError:
                return None
        return None


class MessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    thread_id = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ['id', 'text', 'timestamp', 'sender_username', 'thread_id']

    def get_thread_id(self, obj):
        return obj.thread.id if obj.thread else None


class DashboardStatsSerializer(serializers.Serializer):
    activeOrders = serializers.IntegerField()
    completed = serializers.IntegerField()
    earnings = serializers.SerializerMethodField()
    rating = serializers.FloatField()
    totalClients = serializers.IntegerField()
    avgResponseTime = serializers.CharField()
    totalThreads = serializers.IntegerField()
    unreadMessages = serializers.IntegerField()
    current_balance = serializers.SerializerMethodField()
    pending_balance = serializers.SerializerMethodField()
    total_earnings = serializers.SerializerMethodField()
    pending_payouts = serializers.SerializerMethodField()
    successful_payouts = serializers.SerializerMethodField()
    
    def get_earnings(self, obj):
        return str(obj.get('earnings', Decimal('0.00')))
    
    def get_current_balance(self, obj):
        return str(obj.get('current_balance', Decimal('0.00')))
    
    def get_pending_balance(self, obj):
        return str(obj.get('pending_balance', Decimal('0.00')))
    
    def get_total_earnings(self, obj):
        return str(obj.get('total_earnings', Decimal('0.00')))
    
    def get_pending_payouts(self, obj):
        return obj.get('pending_payouts', 0)
    
    def get_successful_payouts(self, obj):
        return str(obj.get('successful_payouts', Decimal('0.00')))


class ChatThreadSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    other_party_username = serializers.SerializerMethodField()
    last_message_preview = serializers.CharField()
    unread_count = serializers.IntegerField()
    updated_at = serializers.DateTimeField()
    
    class Meta:
        fields = [
            'id', 'other_party_username', 'last_message_preview', 
            'unread_count', 'updated_at'
        ]

    def get_other_party_username(self, obj):
        request = self.context.get('request')
        user = request.user
        
        if obj.freelancer == user:
            return obj.client.username
        elif obj.client == user:
            return obj.freelancer.username
        
        return "Unknown"


class BalanceTransactionSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    job_id = serializers.UUIDField(required=False)
    description = serializers.CharField(required=False, max_length=255)
    
    def validate_amount(self, value):
        if value <= Decimal('0.00'):
            raise serializers.ValidationError('Amount must be positive.')
        return value


class PayoutDashboardSerializer(serializers.Serializer):
    total_payouts = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_payouts = serializers.DecimalField(max_digits=12, decimal_places=2)
    successful_payouts = serializers.DecimalField(max_digits=12, decimal_places=2)
    failed_payouts = serializers.DecimalField(max_digits=12, decimal_places=2)
    recent_payouts = PayoutSerializer(many=True)
    payout_statistics = serializers.DictField()


class AdminPayoutStatsSerializer(serializers.Serializer):
    total_payouts_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_payouts_count = serializers.IntegerField()
    pending_payouts_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_payouts_count = serializers.IntegerField()
    successful_payouts_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    successful_payouts_count = serializers.IntegerField()
    failed_payouts_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    failed_payouts_count = serializers.IntegerField()
    top_freelancers = serializers.ListField(child=serializers.DictField())


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            'display_name', 'tagline', 'location', 'languages',
            'about', 'intro_video_url', 'avatar', 'cover_image',
            'is_public', 'account_status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class FeaturedClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeaturedClient
        fields = [
            'id', 'client_name', 'client_logo', 'client_url',
            'description', 'order', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_order(self, value):
        if value < 0 or value > 4:
            raise serializers.ValidationError("Order must be between 0 and 4 (max 5 featured clients)")
        return value


class PortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Portfolio
        fields = [
            'id', 'title', 'description', 'project_url', 'image',
            'thumbnail', 'client_name', 'completion_date', 'tags',
            'is_featured', 'order', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class WorkExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkExperience
        fields = [
            'id', 'job_title', 'company', 'location', 'start_date',
            'end_date', 'is_current', 'description', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, data):
        if not data.get('is_current') and not data.get('end_date'):
            raise serializers.ValidationError({
                'end_date': 'End date is required if not currently working'
            })
        if data.get('end_date') and data.get('start_date') and data['end_date'] < data['start_date']:
            raise serializers.ValidationError({
                'end_date': 'End date must be after start date'
            })
        return data


class EducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Education
        fields = [
            'id', 'institution', 'degree', 'field_of_study',
            'start_year', 'graduation_year', 'is_current', 'grade',
            'description', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, data):
        if not data.get('is_current') and not data.get('graduation_year'):
            raise serializers.ValidationError({
                'graduation_year': 'Graduation year is required if not currently studying'
            })
        if data.get('graduation_year') and data.get('start_year') and data['graduation_year'] < data['start_year']:
            raise serializers.ValidationError({
                'graduation_year': 'Graduation year must be after start year'
            })
        return data


class CertificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Certification
        fields = [
            'id', 'certification_name', 'issuing_organization',
            'issue_year', 'expiry_year', 'credential_id',
            'credential_url', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, data):
        if data.get('expiry_year') and data.get('issue_year') and data['expiry_year'] < data['issue_year']:
            raise serializers.ValidationError({
                'expiry_year': 'Expiry year must be after issue year'
            })
        return data


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = [
            'id', 'skill_name', 'skill_level', 'years_experience',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    email_new_message = serializers.BooleanField(required=False)
    email_new_offer = serializers.BooleanField(required=False)
    email_offer_accepted = serializers.BooleanField(required=False)
    email_job_completed = serializers.BooleanField(required=False)
    email_payment_received = serializers.BooleanField(required=False)
    email_marketing = serializers.BooleanField(required=False)
    app_new_message = serializers.BooleanField(required=False)
    app_new_offer = serializers.BooleanField(required=False)
    app_offer_accepted = serializers.BooleanField(required=False)
    app_job_completed = serializers.BooleanField(required=False)
    app_payment_received = serializers.BooleanField(required=False)

    class Meta:
        model = NotificationPreference
        fields = [
            'email_new_message', 'email_new_offer', 'email_offer_accepted',
            'email_job_completed', 'email_payment_received', 'email_marketing',
            'app_new_message', 'app_new_offer', 'app_offer_accepted',
            'app_job_completed', 'app_payment_received',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    _TYPE_FIELD_MAP = {
        'email_new_message': ('MESSAGE', 'email'),
        'email_new_offer': ('OFFER_RECEIVED', 'email'),
        'email_offer_accepted': ('OFFER_ACCEPTED', 'email'),
        'email_job_completed': ('JOB_COMPLETED', 'email'),
        'email_payment_received': ('PAYMENT_RECEIVED', 'email'),
        'app_new_message': ('MESSAGE', 'in_app'),
        'app_new_offer': ('OFFER_RECEIVED', 'in_app'),
        'app_offer_accepted': ('OFFER_ACCEPTED', 'in_app'),
        'app_job_completed': ('JOB_COMPLETED', 'in_app'),
        'app_payment_received': ('PAYMENT_RECEIVED', 'in_app'),
    }

    def _type_channel_enabled(self, instance, notification_type, channel):
        type_prefs = instance.type_preferences or {}
        scoped = type_prefs.get(notification_type, {})
        if channel in scoped:
            return bool(scoped[channel])
        if channel == 'email':
            return bool(instance.email_enabled)
        if channel == 'in_app':
            return bool(instance.in_app_enabled)
        return False

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for field_name, (notification_type, channel) in self._TYPE_FIELD_MAP.items():
            data[field_name] = self._type_channel_enabled(instance, notification_type, channel)

        category_prefs = instance.category_preferences or {}
        system_prefs = category_prefs.get('SYSTEM', {})
        data['email_marketing'] = bool(system_prefs.get('email', instance.email_enabled))
        return data

    def update(self, instance, validated_data):
        type_prefs = dict(instance.type_preferences or {})
        category_prefs = dict(instance.category_preferences or {})

        for field_name, (notification_type, channel) in self._TYPE_FIELD_MAP.items():
            if field_name not in validated_data:
                continue
            scoped = dict(type_prefs.get(notification_type, {}))
            scoped[channel] = bool(validated_data.pop(field_name))
            type_prefs[notification_type] = scoped

        if 'email_marketing' in validated_data:
            system_scoped = dict(category_prefs.get('SYSTEM', {}))
            system_scoped['email'] = bool(validated_data.pop('email_marketing'))
            category_prefs['SYSTEM'] = system_scoped

        instance.type_preferences = type_prefs
        instance.category_preferences = category_prefs
        instance.save(update_fields=['type_preferences', 'category_preferences', 'updated_at'])
        return instance


class CompleteProfileSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    featured_clients = FeaturedClientSerializer(many=True, read_only=True)
    portfolio_items = PortfolioSerializer(many=True, read_only=True)
    work_experience = WorkExperienceSerializer(many=True, read_only=True)
    education = EducationSerializer(many=True, read_only=True)
    certifications = CertificationSerializer(many=True, read_only=True)
    skills = SkillSerializer(many=True, read_only=True)
    freelancerprofile = FreelancerProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'is_active',
            'profile', 'featured_clients', 'portfolio_items',
            'work_experience', 'education', 'certifications',
            'skills', 'freelancerprofile'
        ]


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({
                'confirm_password': 'New passwords do not match'
            })

        user = self.context['request'].user
        if not user.check_password(data['current_password']):
            raise serializers.ValidationError({
                'current_password': 'Current password is incorrect'
            })

        return data

    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user


class AccountSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email', 'phone']
        read_only_fields = ['email']
