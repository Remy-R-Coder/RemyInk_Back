from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import permissions, status, viewsets, serializers
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from drf_spectacular.utils import extend_schema
from django.contrib.auth import get_user_model
from django.db.models import Q, Sum, Avg, Count, Exists, OuterRef, F
from django.middleware.csrf import get_token
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone
from datetime import timedelta
from user_module.services import create_guest_user

from chat.models import ChatThread, ChatMessage, MessageReadStatus
from chat.services import GuestNameService, ChatThreadService
from chat.serializers import ChatThreadListSerializer
from .models import Role, Rating, UserProfile
from orders.models import Job
from notifications.models import Notification, NotificationPreference
import logging
from .serializers import (
    UserSerializer,
    FreelancerOnboardingSerializer,
    ClientAccountFinalizeSerializer,
    ClientTokenObtainPairSerializer,
    FreelancerListSerializer,
    EmailTokenObtainPairSerializer,
    RatingSerializer,
    JobSerializer,
    UserProfileSerializer,
    FeaturedClientSerializer,
    PortfolioSerializer,
    WorkExperienceSerializer,
    EducationSerializer,
    CertificationSerializer,
    SkillSerializer,
    NotificationPreferenceSerializer,
    CompleteProfileSerializer,
    PasswordChangeSerializer,
    AccountSettingsSerializer,
    SetupPasswordConfirmSerializer,
    SetupPasswordRequestSerializer,
    is_guest_linked_client,
)

from .utils import GuestIDCounter

logger = logging.getLogger()
User = get_user_model()


class EmptySerializer(serializers.Serializer):
    pass

@extend_schema(responses={200: dict})
@api_view(['GET'])
@permission_classes([AllowAny])
def get_csrf_and_session(request):
    session = request.session
    if not session.session_key:
        session.create()

    session_key = session.session_key

    user_agent = request.META.get('HTTP_USER_AGENT', '')
    ip_address = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or \
                 request.META.get('REMOTE_ADDR', '')
    referrer = request.META.get('HTTP_REFERER', '')

    try:
        guest_session, created = GuestNameService.get_or_create_guest_session(
            session_key=session_key,
            user_agent=user_agent[:500] if user_agent else None,
            ip_address=ip_address or None,
            referrer=referrer[:500] if referrer else None
        )
        guest_label = guest_session.display_name

        if created:
            logger.info(f"Created new guest session: {guest_label} ({session_key[:8]}...)")
        else:
            logger.debug(f"Retrieved existing guest session: {guest_label}")

    except Exception as e:
        logger.error(f"Error creating guest session: {e}")
        if "guest_label" not in session:
            guest_label = GuestIDCounter.get_next_guest_id()
            session["guest_label"] = guest_label
            session.save()
        else:
            guest_label = session["guest_label"]

    return Response({
        "csrfToken": get_token(request),
        "sessionId": session_key,
        "guestLabel": guest_label
    })


class FreelancerTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer


class ClientTokenObtainPairView(TokenObtainPairView):
    serializer_class = ClientTokenObtainPairSerializer


class SetupPasswordConfirmView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(summary="Set password using secure setup token", request=SetupPasswordConfirmSerializer, responses={200: dict})
    def post(self, request):
        serializer = SetupPasswordConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password set successfully.'}, status=status.HTTP_200_OK)


class SetupPasswordRequestView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(summary="Request secure password setup link", request=SetupPasswordRequestSerializer, responses={200: dict})
    def post(self, request):
        serializer = SetupPasswordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        user = User.objects.filter(email__iexact=email).first()
        if user and is_guest_linked_client(user):
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            frontend_base = str(getattr(settings, 'FRONTEND_URL', '') or '').strip().rstrip('/')
            if frontend_base:
                setup_link = f"{frontend_base}/set-password?uid={uid}&token={token}"
            else:
                backend_base = str(getattr(settings, 'BACKEND_BASE_URL', 'http://127.0.0.1:8000')).strip().rstrip('/')
                setup_link = f"{backend_base}/api/users/password/setup/confirm/?uid={uid}&token={token}"

            try:
                send_mail(
                    subject='Set your RemyInk password',
                    message=(
                        f'Hello {user.username},\n\n'
                        'Use this secure link to set your password:\n'
                        f'{setup_link}\n\n'
                        'This link is time-limited and can only be used once.\n\n'
                        'RemyInk Team'
                    ),
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception as exc:
                logger.warning(f"Failed to send password setup request email to {user.email}: {exc}")

        return Response(
            {'message': 'If an account exists for this email, a setup link has been sent.'},
            status=status.HTTP_200_OK
        )


class UserProfileViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    @extend_schema(summary="Retrieve the current user's profile")
    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


class OnboardingViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.AllowAny]

    @extend_schema(summary="Onboard a new Freelancer", request=FreelancerOnboardingSerializer, responses={201: UserSerializer})
    @action(detail=False, methods=['post'], serializer_class=FreelancerOnboardingSerializer)
    def onboard_freelancer(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = serializer.save()
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(summary="Finalize a Shadow Client Account", request=ClientAccountFinalizeSerializer, responses={200: UserSerializer})
    @action(detail=False, methods=['post'], url_path='finalize-client', serializer_class=ClientAccountFinalizeSerializer, permission_classes=[IsAuthenticated])
    def finalize_client_account(self, request):
        if request.user.role != Role.CLIENT or request.user.is_active:
            return Response({"detail": "User is not a shadow client or is already active."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        try:
            user = serializer.save()
            
            try:
                subject = 'Welcome to RemyInk! Your Client Account is now active'
                message = (
                    f"Hello {user.username},\n\n"
                    f"Your client account registration has been successfully finalized.\n"
                    f"Email: {user.email}\n"
                    f"You can now log in using your new password.\n\n"
                    "Thank you,\n"
                    "The RemyInk Team"
                )
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                logger.info(f"Account finalization email sent to {user.email}")
            except Exception as e:
                logger.error(f"Failed to send account finalization email to {user.email}: {e}")

            return Response(UserSerializer(user).data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error finalizing client account: {e}")
            return Response({"detail": "An error occurred finalizing your account"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FreelancerListViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FreelancerListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        User = get_user_model()
        queryset = User.objects.filter(role=Role.FREELANCER, is_active=True).prefetch_related(
            'freelancerprofile__categories',
            'freelancerprofile__subjects'
        ).distinct()

        category_id = self.request.query_params.get('category_id')
        subject_id = self.request.query_params.get('subject_id')

        query_filters = Q()
        if category_id:
            query_filters &= Q(freelancerprofile__categories=category_id)
        if subject_id:
            query_filters &= Q(freelancerprofile__subjects=subject_id)

        filtered_queryset = queryset.filter(query_filters)
        

        if not filtered_queryset.exists():
            admin_queryset = User.objects.filter(role=Role.ADMIN, is_active=True).prefetch_related(
                'freelancerprofile__categories',
                'freelancerprofile__subjects'
            ).distinct()
            return admin_queryset.order_by('id')

        return filtered_queryset.order_by('id')

    @extend_schema(summary="List all active Freelancers with optional filters")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request):
        try:
            user = request.user

            if user.role == Role.FREELANCER or user.is_superuser:
                job_stats = Job.objects.filter(freelancer=user).aggregate(
                    active_orders=Count('id', filter=Q(status__in=['Active', 'In Progress', 'Awaiting Review'])),
                    completed=Count('id', filter=Q(status='Completed')),
                    total_earnings=Sum('price', filter=Q(status='Completed')),
                    total_clients=Count('client', distinct=True)
                )

                rating_avg = Rating.objects.filter(rated_user=user).aggregate(avg=Avg('score'))['avg']
                rating_value = round(float(rating_avg), 1) if rating_avg is not None else 0.0

                unread_messages_count = ChatMessage.objects.filter(
                    thread__freelancer=user
                ).exclude(
                    sender=user
                ).exclude(
                    read_by__user=user
                ).count()

                total_threads = ChatThread.objects.filter(freelancer=user).count()

                thirty_days_ago = timezone.now() - timedelta(days=30)
                recent_threads = ChatThread.objects.filter(
                    freelancer=user,
                    created_at__gte=thirty_days_ago
                )

                response_times = []
                for thread in recent_threads[:20]:
                    first_client_msg = thread.messages.exclude(sender=user).order_by('timestamp').first()
                    if first_client_msg:
                        first_freelancer_reply = thread.messages.filter(
                            sender=user,
                            timestamp__gt=first_client_msg.timestamp
                        ).order_by('timestamp').first()
                        if first_freelancer_reply:
                            time_diff = first_freelancer_reply.timestamp - first_client_msg.timestamp
                            response_times.append(time_diff.total_seconds() / 60)

                avg_response_time = f"{int(sum(response_times) / len(response_times))} min" if response_times else "N/A"

                stats = {
                    'activeOrders': job_stats['active_orders'] or 0,
                    'completed': job_stats['completed'] or 0,
                    'earnings': float(job_stats['total_earnings'] or 0),
                    'rating': rating_value,
                    'totalClients': job_stats['total_clients'] or 0,
                    'avgResponseTime': avg_response_time,
                    'totalThreads': total_threads,
                    'unreadMessages': unread_messages_count,
                }

            elif user.role == Role.CLIENT:
                job_stats = Job.objects.filter(client=user).aggregate(
                    active_orders=Count('id', filter=Q(status__in=['Active', 'In Progress', 'Awaiting Review'])),
                    completed=Count('id', filter=Q(status='Completed')),
                    total_spent=Sum('price', filter=Q(status='Completed')),
                    total_freelancers=Count('freelancer', distinct=True)
                )

                unread_messages_count = ChatMessage.objects.filter(
                    thread__client=user
                ).exclude(
                    sender=user
                ).exclude(
                    read_by__user=user
                ).count()

                total_threads = ChatThread.objects.filter(
                    client=user
                ).count()

                pending_offers = ChatMessage.objects.filter(
                    thread__client=user,
                    is_offer=True,
                    offer_status='pending'
                ).count()

                accepted_offers = ChatMessage.objects.filter(
                    thread__client=user,
                    is_offer=True,
                    offer_status='accepted'
                ).count()

                rejected_offers = ChatMessage.objects.filter(
                    thread__client=user,
                    is_offer=True,
                    offer_status='rejected'
                ).count()

                stats = {
                    'activeOrders': job_stats['active_orders'] or 0,
                    'completed': job_stats['completed'] or 0,
                    'totalSpent': float(job_stats['total_spent'] or 0),
                    'totalFreelancers': job_stats['total_freelancers'] or 0,
                    'totalThreads': total_threads,
                    'unreadMessages': unread_messages_count,
                    'pendingOffers': pending_offers,
                    'acceptedOffers': accepted_offers,
                    'rejectedOffers': rejected_offers,
                }
            else:
                return Response({'error': 'Invalid user role'}, status=status.HTTP_403_FORBIDDEN)

            return Response(stats)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
class GuestTokenView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            session_key = request.session.session_key
            if not session_key:
                request.session.create()
                session_key = request.session.session_key

            # FIX: Use get_or_create logic instead of just "get"
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            ip_address = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', '')
            
            # Use the service that actually creates the user if missing
            guest_session, created = GuestNameService.get_or_create_guest_session(
                session_key=session_key,
                user_agent=user_agent[:500],
                ip_address=ip_address
            )

            guest_user = guest_session.user
            refresh = RefreshToken.for_user(guest_user)

            return Response({
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "username": guest_user.username,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Guest token creation failed")
            return Response(
                {"error": f"Guest token failed: {str(e)}"}, # Added str(e) to see the real error
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
class DashboardJobsView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request):
        user = request.user

        if user.role == Role.FREELANCER or user.is_superuser:
            jobs = Job.objects.filter(freelancer=user).select_related(
                'client',
                'subject_area',
                'subject_area__task_category'
            ).order_by('-created_at')
        elif user.role == Role.CLIENT:
            jobs = Job.objects.filter(client=user).select_related(
                'freelancer',
                'subject_area',
                'subject_area__task_category'
            ).order_by('-created_at')
        else:
            return Response({'error': 'Invalid user role'}, status=status.HTTP_403_FORBIDDEN)

        serializer = JobSerializer(jobs, many=True)
        return Response(serializer.data)


class DashboardNotificationsView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    @staticmethod
    def _normalize_notification_link(notification):
        link = (getattr(notification, 'link', None) or '').strip()
        metadata = getattr(notification, 'metadata', {}) or {}
        job_id = metadata.get('job_id')

        if link.startswith('/jobs/'):
            return link.replace('/jobs/', '/job/', 1)

        if link == '/orders' and job_id:
            return f'/job/{job_id}'

        return link or None

    def get(self, request):
        user = request.user

        notifications = Notification.objects.filter(
            recipient=user
        ).order_by('-created_at')[:20]

        notifications_data = [
            {
                'id': f'notif-{n.id}',
                'text': n.message,
                'created_at': n.created_at.isoformat(),
                'type': 'notification',
                'link': self._normalize_notification_link(n),
                'is_read': n.is_read,
                'metadata': n.metadata if isinstance(n.metadata, dict) else {},
            }
            for n in notifications
        ]

        if user.role == Role.FREELANCER or user.is_superuser:
            thread_ids = ChatThread.objects.filter(
                freelancer=user
            ).values_list('id', flat=True)
        elif user.role == Role.CLIENT:
            thread_ids = ChatThread.objects.filter(
                client=user
            ).values_list('id', flat=True)
        else:
            thread_ids = []

        messages_data = []

        for thread_id in thread_ids:
            if len(messages_data) >= 10:  
                break

            latest_msg = ChatMessage.objects.filter(
                thread_id=thread_id
            ).exclude(
                sender=user
            ).select_related('thread', 'sender').order_by('-timestamp').first()

            if latest_msg:
                is_read = MessageReadStatus.objects.filter(
                    message=latest_msg,
                    user=user
                ).exists()

                unread_count = ChatMessage.objects.filter(
                    thread_id=thread_id
                ).exclude(
                    sender=user
                ).exclude(
                    read_by__user=user
                ).count()

                sender_name = latest_msg.sender.username if latest_msg.sender else "Unknown User"

                messages_data.append({
                    'id': f'msg-{latest_msg.id}',
                    'text': f'New message from {sender_name}',
                    'created_at': latest_msg.timestamp.isoformat(),
                    'type': 'message',
                    'thread_id': latest_msg.thread.id,
                    'link': f'/messages/{latest_msg.thread.id}',
                    'unread_count': unread_count,
                    'is_read': is_read,
                })

        combined = notifications_data + messages_data
        combined_sorted = sorted(
            combined,
            key=lambda x: x['created_at'],
            reverse=True
        )

        return Response(combined_sorted[:20])


class DashboardNotificationReadView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    def post(self, request, notification_id):
        return self._mark_read(request, notification_id)

    def put(self, request, notification_id):
        return self._mark_read(request, notification_id)

    def _mark_read(self, request, notification_id):
        user = request.user
        identifier = str(notification_id or '').strip()

        if identifier.startswith('notif-'):
            raw_id = identifier.replace('notif-', '', 1)
            notification = Notification.objects.filter(id=raw_id, recipient=user).first()
            if not notification:
                return Response({'detail': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)
            if not notification.is_read:
                notification.is_read = True
                notification.read_at = timezone.now()
                notification.save(update_fields=['is_read', 'read_at', 'updated_at'])
            return Response({'status': 'ok', 'id': identifier, 'is_read': True}, status=status.HTTP_200_OK)

        if identifier.startswith('msg-'):
            raw_id = identifier.replace('msg-', '', 1)
            try:
                message_id = int(raw_id)
            except (TypeError, ValueError):
                return Response({'detail': 'Invalid message id.'}, status=status.HTTP_400_BAD_REQUEST)

            message = ChatMessage.objects.select_related('thread').filter(id=message_id).first()
            if not message:
                return Response({'detail': 'Message not found.'}, status=status.HTTP_404_NOT_FOUND)

            if message.thread.freelancer_id != user.id and message.thread.client_id != user.id:
                return Response({'detail': 'Not allowed.'}, status=status.HTTP_403_FORBIDDEN)

            MessageReadStatus.objects.get_or_create(message=message, user=user)
            return Response({'status': 'ok', 'id': identifier, 'is_read': True}, status=status.HTTP_200_OK)

        return Response({'detail': 'Invalid notification id format.'}, status=status.HTTP_400_BAD_REQUEST)


class DashboardNotificationUnreadView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    def post(self, request, notification_id):
        return self._mark_unread(request, notification_id)

    def put(self, request, notification_id):
        return self._mark_unread(request, notification_id)

    def _mark_unread(self, request, notification_id):
        user = request.user
        identifier = str(notification_id or '').strip()

        if identifier.startswith('notif-'):
            raw_id = identifier.replace('notif-', '', 1)
            notification = Notification.objects.filter(id=raw_id, recipient=user).first()
            if not notification:
                return Response({'detail': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)
            if notification.is_read:
                notification.is_read = False
                notification.read_at = None
                notification.save(update_fields=['is_read', 'read_at', 'updated_at'])
            return Response({'status': 'ok', 'id': identifier, 'is_read': False}, status=status.HTTP_200_OK)

        if identifier.startswith('msg-'):
            raw_id = identifier.replace('msg-', '', 1)
            try:
                message_id = int(raw_id)
            except (TypeError, ValueError):
                return Response({'detail': 'Invalid message id.'}, status=status.HTTP_400_BAD_REQUEST)

            message = ChatMessage.objects.select_related('thread').filter(id=message_id).first()
            if not message:
                return Response({'detail': 'Message not found.'}, status=status.HTTP_404_NOT_FOUND)

            if message.thread.freelancer_id != user.id and message.thread.client_id != user.id:
                return Response({'detail': 'Not allowed.'}, status=status.HTTP_403_FORBIDDEN)

            MessageReadStatus.objects.filter(message=message, user=user).delete()
            return Response({'status': 'ok', 'id': identifier, 'is_read': False}, status=status.HTTP_200_OK)

        return Response({'detail': 'Invalid notification id format.'}, status=status.HTTP_400_BAD_REQUEST)


class GuestThreadsView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request):
        user = request.user
        
        if user.role == Role.FREELANCER or user.is_superuser:
            threads = ChatThreadService.get_user_threads(user)
        elif user.role == Role.CLIENT:
            threads = ChatThread.objects.filter(
                client=user
            ).select_related(
                'freelancer',
                'client'
            ).prefetch_related(
                'messages__sender'
            ).order_by('-updated_at')
        else:
            threads = ChatThread.objects.none()

        serializer = ChatThreadListSerializer(
            threads,
            many=True,
            context={'request': request}
        )
        
        return Response(serializer.data)


class RatingViewSet(viewsets.ModelViewSet):
    queryset = Rating.objects.all()
    serializer_class = RatingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Rating.objects.select_related(
            'rater',
            'rated_user'
        ).all()

    def perform_create(self, serializer):
        serializer.save(rater=self.request.user)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if not refresh_token:
                return Response({"detail": "Refresh token required."}, status=status.HTTP_400_BAD_REQUEST)
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"detail": "Successfully logged out."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Get complete dashboard summary for both clients and freelancers", responses={200: dict})
    def get(self, request):
        user = request.user

        stats_view = DashboardStatsView()
        stats_response = stats_view.get(request)

        jobs_view = DashboardJobsView()
        jobs_response = jobs_view.get(request)

        notifications_view = DashboardNotificationsView()
        notifications_response = notifications_view.get(request)

        return Response({
            'stats': stats_response.data,
            'recentJobs': jobs_response.data[:5],
            'notifications': notifications_response.data[:10],
            'timestamp': timezone.now().isoformat(),
            'userRole': user.role,      
        })


class UnreadMessagesCountView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get unread messages count",
        responses={200: {'type': 'object', 'properties': {'unread_count': {'type': 'integer'}}}}
    )
    def get(self, request):
        user = request.user
        
        if user.role == Role.FREELANCER or user.is_superuser:
            q_filter = Q(thread__freelancer=user)
        elif user.role == Role.CLIENT:
            q_filter = Q(thread__client=user)
        else:
            return Response({'unread_count': 0})
        
        unread_count = ChatMessage.objects.filter(
            q_filter
        ).exclude(
            sender=user
        ).exclude(
            read_by__user=user
        ).count()

        return Response({'unread_count': unread_count})


class ThreadUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get unread counts for all threads",
        responses={200: dict}
    )
    def get(self, request):
        user = request.user
        
        if user.role == Role.FREELANCER or user.is_superuser:
            q_filter = Q(thread__freelancer=user)
        elif user.role == Role.CLIENT:
            q_filter = Q(thread__client=user)
        else:
            return Response({})

        thread_unreads = ChatMessage.objects.filter(
            q_filter
        ).exclude(
            sender=user
        ).exclude(
            read_by__user=user
        ).values('thread_id').annotate(
            unread_count=Count('id')
        )

        unread_map = {
            str(item['thread_id']): item['unread_count']
            for item in thread_unreads
        }

        return Response(unread_map)


class CompleteProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Get complete user profile with all sections", responses={200: CompleteProfileSerializer})
    def get(self, request):
        serializer = CompleteProfileSerializer(request.user)
        return Response(serializer.data)


class UserProfileViewSetNew(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_queryset(self):
        return UserProfile.objects.filter(user=self.request.user)

    def get_object(self):
        profile, created = UserProfile.objects.get_or_create(user=self.request.user)
        return profile

    @extend_schema(summary="Get user profile")
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @extend_schema(summary="Update user profile")
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ProfileAliasView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        alias = (profile.display_name or '').strip() or request.user.username
        return Response({'alias': alias, 'display_name': alias}, status=status.HTTP_200_OK)

    def post(self, request):
        return self._save_alias(request)

    def patch(self, request):
        return self._save_alias(request)

    def _save_alias(self, request):
        raw_alias = request.data.get('alias', request.data.get('display_name', ''))
        alias = str(raw_alias or '').strip()
        if not alias:
            return Response({'alias': 'This field is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(alias) > 100:
            return Response({'alias': 'Ensure this field has no more than 100 characters.'}, status=status.HTTP_400_BAD_REQUEST)

        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.display_name = alias
        profile.save(update_fields=['display_name', 'updated_at'])
        return Response({'alias': profile.display_name, 'display_name': profile.display_name}, status=status.HTTP_200_OK)


class ProfilePictureView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        avatar_url = profile.avatar.url if profile.avatar else None
        if avatar_url:
            avatar_url = request.build_absolute_uri(avatar_url)
        return Response(
            {
                'picture': avatar_url,
                'avatar': avatar_url,
                'country': profile.location or '',
                'location': profile.location or '',
            },
            status=status.HTTP_200_OK
        )

    def post(self, request):
        return self._save(request)

    def patch(self, request):
        return self._save(request)

    def put(self, request):
        return self._save(request)

    def _save(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)

        country = request.data.get('country')
        location = request.data.get('location')
        picture_file = (
            request.FILES.get('picture')
            or request.FILES.get('avatar')
            or request.FILES.get('profile_picture')
        )

        updated_fields = ['updated_at']
        if country is not None:
            profile.location = str(country).strip()
            updated_fields.append('location')
        elif location is not None:
            profile.location = str(location).strip()
            updated_fields.append('location')

        if picture_file is not None:
            profile.avatar = picture_file
            updated_fields.append('avatar')

        if len(updated_fields) == 1:
            return Response(
                {'detail': 'Provide at least one of picture/avatar/profile_picture or country/location.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        profile.save(update_fields=updated_fields)

        avatar_url = profile.avatar.url if profile.avatar else None
        if avatar_url:
            avatar_url = request.build_absolute_uri(avatar_url)
        return Response(
            {
                'picture': avatar_url,
                'avatar': avatar_url,
                'country': profile.location or '',
                'location': profile.location or '',
            },
            status=status.HTTP_200_OK
        )


class FeaturedClientViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = FeaturedClientSerializer

    def get_queryset(self):
        User = get_user_model()
        user_instance = self.request.user if self.request.user.is_authenticated else User.objects.none()
        return user_instance.featured_clients.all() if user_instance else User.objects.none()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PortfolioViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PortfolioSerializer

    def get_queryset(self):
        User = get_user_model()
        user_instance = self.request.user if self.request.user.is_authenticated else User.objects.none()
        return user_instance.portfolio_items.all() if user_instance else User.objects.none()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class WorkExperienceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkExperienceSerializer

    def get_queryset(self):
        User = get_user_model()
        user_instance = self.request.user if self.request.user.is_authenticated else User.objects.none()
        return user_instance.work_experience.all() if user_instance else User.objects.none()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class EducationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = EducationSerializer

    def get_queryset(self):
        User = get_user_model()
        user_instance = self.request.user if self.request.user.is_authenticated else User.objects.none()
        return user_instance.education.all() if user_instance else User.objects.none()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class CertificationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = CertificationSerializer

    def get_queryset(self):
        User = get_user_model()
        user_instance = self.request.user if self.request.user.is_authenticated else User.objects.none()
        return user_instance.certifications.all() if user_instance else User.objects.none()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SkillViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = SkillSerializer

    def get_queryset(self):
        User = get_user_model()
        user_instance = self.request.user if self.request.user.is_authenticated else User.objects.none()
        return user_instance.skills.all() if user_instance else User.objects.none()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AccountSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Get account settings", responses={200: AccountSettingsSerializer})
    def get(self, request):
        serializer = AccountSettingsSerializer(request.user)
        return Response(serializer.data)

    @extend_schema(summary="Update account settings", request=AccountSettingsSerializer, responses={200: AccountSettingsSerializer})
    def patch(self, request):
        serializer = AccountSettingsSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Change password", request=PasswordChangeSerializer, responses={200: dict})
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password changed successfully'})


class NotificationPreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Get notification preferences", responses={200: NotificationPreferenceSerializer})
    def get(self, request):
        preferences, created = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceSerializer(preferences)
        return Response(serializer.data)

    @extend_schema(summary="Update notification preferences", request=NotificationPreferenceSerializer, responses={200: NotificationPreferenceSerializer})
    def patch(self, request):
        preferences, created = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceSerializer(preferences, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
