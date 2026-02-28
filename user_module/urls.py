from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    UserProfileViewSet,
    OnboardingViewSet,
    FreelancerListViewSet,
    FreelancerTokenObtainPairView,
    ClientTokenObtainPairView,
    SetupPasswordConfirmView,
    SetupPasswordRequestView,
    GuestThreadsView,
    RatingViewSet,
    LogoutView,
    get_csrf_and_session,
    DashboardStatsView,
    DashboardJobsView,
    DashboardNotificationsView,
    DashboardNotificationReadView,
    DashboardNotificationUnreadView,
    DashboardSummaryView,
    UnreadMessagesCountView,
    ThreadUnreadCountView,
    CompleteProfileView,
    UserProfileViewSetNew,
    ProfileAliasView,
    ProfilePictureView,
    FeaturedClientViewSet,
    PortfolioViewSet,
    WorkExperienceViewSet,
    EducationViewSet,
    CertificationViewSet,
    SkillViewSet,
    AccountSettingsView,
    PasswordChangeView,
    NotificationPreferencesView,
)

router = DefaultRouter()
router.register(r'onboarding', OnboardingViewSet, basename='onboarding')
router.register(r'freelancers', FreelancerListViewSet, basename='freelancer')
router.register(r'ratings', RatingViewSet, basename='rating')

router.register(r'profile/featured-clients', FeaturedClientViewSet, basename='featured-client')
router.register(r'profile/portfolio', PortfolioViewSet, basename='portfolio')
router.register(r'profile/work-experience', WorkExperienceViewSet, basename='work-experience')
router.register(r'profile/education', EducationViewSet, basename='education')
router.register(r'profile/certifications', CertificationViewSet, basename='certification')
router.register(r'profile/skills', SkillViewSet, basename='skill')

urlpatterns = [
    path('token/freelancer/', FreelancerTokenObtainPairView.as_view(), name='token_obtain_pair_freelancer'),
    path('token/client/', ClientTokenObtainPairView.as_view(), name='token_obtain_pair_client'),
    path('password/setup/request/', SetupPasswordRequestView.as_view(), name='password-setup-request'),
    path('password/setup/confirm/', SetupPasswordConfirmView.as_view(), name='password-setup-confirm'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    
    path('me/', UserProfileViewSet.as_view({'get': 'retrieve'}), name='user-profile-me'),
    
    path('dashboard/stats/', DashboardStatsView.as_view(), name='dashboard-stats'),
    path('dashboard/jobs/', DashboardJobsView.as_view(), name='dashboard-jobs'),
    path('dashboard/notifications/', DashboardNotificationsView.as_view(), name='dashboard-notifications'),
    path('dashboard/notifications/<str:notification_id>/read/', DashboardNotificationReadView.as_view(), name='dashboard-notification-read'),
    path('dashboard/notifications/<str:notification_id>/unread/', DashboardNotificationUnreadView.as_view(), name='dashboard-notification-unread'),
    
    path('dashboard/summary/', DashboardSummaryView.as_view(), name='dashboard-summary'),
    path('dashboard/unread-count/', UnreadMessagesCountView.as_view(), name='dashboard-unread-count'),
    path('dashboard/thread-unreads/', ThreadUnreadCountView.as_view(), name='dashboard-thread-unreads'),
    
    path('chat/threads/', GuestThreadsView.as_view(), name='user-chat-threads'),

    path('profile/complete/', CompleteProfileView.as_view(), name='complete-profile'),
    path('profile/', UserProfileViewSetNew.as_view({'get': 'retrieve', 'patch': 'update'}), name='user-profile'),
    path('profile/alias/', ProfileAliasView.as_view(), name='profile-alias'),
    path('profile/picture/', ProfilePictureView.as_view(), name='profile-picture'),

    path('settings/account/', AccountSettingsView.as_view(), name='account-settings'),
    path('settings/password/', PasswordChangeView.as_view(), name='password-change'),
    path('settings/notifications/', NotificationPreferencesView.as_view(), name='notification-preferences'),

    path('csrf-and-session/', get_csrf_and_session, name='csrf-and-session'),

    path('', include(router.urls)),
]
