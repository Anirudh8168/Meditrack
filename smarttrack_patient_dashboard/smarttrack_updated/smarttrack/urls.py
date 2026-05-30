from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', RedirectView.as_view(url='/system-admin/', permanent=False)),
    path('system-admin/', include('apps.system_admin.urls')),
    path('caregiver/doctor-assign/', RedirectView.as_view(url='/dashboard/caregiver/doctor-assign/', permanent=False)),
    path('', include('apps.accounts.urls')),
    path('auth/', include('apps.accounts.urls')),
    path('profile/', include('apps.profiles.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('medicines/', include('apps.medicines.urls')),
    path('appointments/', include('apps.appointments.urls')),
    path('connections/', include('apps.connections.urls')),
    path('messages/', include('apps.messaging.urls')),
    path('family/', include('apps.family.urls')),
    path('reports/', include('apps.reports.urls')),
    path('notifications/', include('apps.notifications.urls')),
    path('payments/', include('apps.payments.urls')),
    path('dashboard/caregiver/', include('apps.caregiver.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) \
  + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
