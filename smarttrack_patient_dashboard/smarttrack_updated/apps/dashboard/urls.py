from django.urls import path
from django.views.generic import RedirectView
from . import views
from apps.caregiver.views import patient_accept_caregiver

urlpatterns = [
    path('', views.dashboard_redirect, name='dashboard'),
    path('patient/', views.patient_dashboard, name='patient_dashboard'),
    path('doctor/', views.doctor_dashboard, name='doctor_dashboard'),
    path('admin/', RedirectView.as_view(url='/system-admin/', permanent=False), name='admin_dashboard'),
    path('doctor/patient/<int:patient_id>/', views.patient_detail, name='patient_detail'),
    path('patient/accept-caregiver/<int:assignment_id>/', patient_accept_caregiver, name='patient_accept_caregiver'),
]
