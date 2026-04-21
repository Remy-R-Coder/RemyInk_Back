from django.contrib import admin
from django.urls import path, re_path, include
from django.shortcuts import redirect
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from django.conf.urls.static import static
from django.conf import settings
from django.views.static import serve  # Required to serve files in production
from user_module.views import (
    DashboardStatsView,
    DashboardJobsView,
    DashboardNotificationsView,
    DashboardNotificationReadView,
    DashboardNotificationUnreadView,
    DashboardSummaryView,
    ProfileAliasView,
    ProfilePictureView,
)

admin.site.site_header = "RemyInk!"
admin.site.site_title = "Job Matching"
admin.site.index_title = "Welcome to the Freelancer Marketplace"

urlpatterns = [
    # path('', lambda request: redirect('http://localhost:5173')),
    
    path('admin/', admin.site.urls),
    
    path('api/orders/', include('orders.urls')),
    path('api/chat/', include('chat.urls')),
    path('api/users/', include('user_module.urls')),
    # Backward-compatible dashboard aliases
    path('api/dashboard/stats/', DashboardStatsView.as_view(), name='dashboard-stats-alias'),
    path('api/dashboard/jobs/', DashboardJobsView.as_view(), name='dashboard-jobs-alias'),
    path('api/dashboard/notifications/', DashboardNotificationsView.as_view(), name='dashboard-notifications-alias'),
    path('api/dashboard/notifications/<str:notification_id>/read/', DashboardNotificationReadView.as_view(), name='dashboard-notification-read-alias'),
    path('api/dashboard/notifications/<str:notification_id>/unread/', DashboardNotificationUnreadView.as_view(), name='dashboard-notification-unread-alias'),
    path('api/dashboard/summary/', DashboardSummaryView.as_view(), name='dashboard-summary-alias'),
    path('api/profile/alias/', ProfileAliasView.as_view(), name='profile-alias-api-alias'),
    path('profile/alias/', ProfileAliasView.as_view(), name='profile-alias-root-alias'),
    path('api/profile/picture/', ProfilePictureView.as_view(), name='profile-picture-api-alias'),
    path('profile/picture/', ProfilePictureView.as_view(), name='profile-picture-root-alias'),
    path('api/jobs/', include('jobs.urls')),
    path('api/payment/', include('pay_freelancer.urls')),
    path('api/payments/', include('payment_gateway.urls')),
    path('api/payments-mpesa/', include('payments.urls')),
    
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT) + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
]  