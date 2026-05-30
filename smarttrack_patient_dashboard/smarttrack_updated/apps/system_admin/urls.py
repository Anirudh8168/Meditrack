from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.admin_login, name='system_admin_login'),
    path('logout/', views.admin_logout_view, name='system_admin_logout'),
    path('', views.dashboard, name='system_admin_dashboard'),

    path('patients/', views.patients_list, name='system_admin_patients'),
    path('patients/<int:user_id>/', views.patient_detail, name='system_admin_patient_detail'),
    path('patients/<int:user_id>/edit/', views.patient_edit, name='system_admin_patient_edit'),
    path('patients/<int:user_id>/suspend/', views.patient_suspend, name='system_admin_patient_suspend'),
    path('patients/<int:user_id>/delete/', views.patient_delete, name='system_admin_patient_delete'),

    path('doctors/', views.doctors_list, name='system_admin_doctors'),
    path('doctors/add/', views.doctor_form, name='system_admin_doctor_add'),
    path('doctors/<int:user_id>/', views.doctor_detail, name='system_admin_doctor_detail'),
    path('doctors/<int:user_id>/edit/', views.doctor_form, name='system_admin_doctor_edit'),
    path('doctors/<int:user_id>/verify/', views.doctor_verify, name='system_admin_doctor_verify'),
    path('doctors/<int:user_id>/remove/', views.doctor_remove, name='system_admin_doctor_remove'),

    path('caregivers/', views.caregivers_list, name='system_admin_caregivers'),
    path('caregivers/add/', views.caregiver_form, name='system_admin_caregiver_add'),
    path('caregivers/<int:user_id>/', views.caregiver_detail, name='system_admin_caregiver_detail'),
    path('caregivers/<int:user_id>/edit/', views.caregiver_form, name='system_admin_caregiver_edit'),
    path('caregivers/<int:user_id>/remove/', views.caregiver_remove, name='system_admin_caregiver_remove'),

    path('family/', views.family_list, name='system_admin_family'),
    path('family/<int:member_id>/', views.family_detail, name='system_admin_family_detail'),
    path('family/<int:member_id>/edit/', views.family_edit, name='system_admin_family_edit'),
    path('family/<int:member_id>/delete/', views.family_delete, name='system_admin_family_delete'),
    path('appointments/', views.appointments_list, name='system_admin_appointments'),
    path('emergency/', views.emergency_list, name='system_admin_emergency'),
    path('video/', views.video_list, name='system_admin_video'),
    path('medicines/', views.medicines_list, name='system_admin_medicines'),
    path('activities/', views.activities_list, name='system_admin_activities'),
    path('analytics/', views.health_analytics, name='system_admin_analytics'),
    path('risk/', views.risk_monitoring, name='system_admin_risk'),
    path('reports/', views.reports_list, name='system_admin_reports'),
    path('reports/export/', views.reports_export, name='system_admin_reports_export'),
    path('payments/', views.payments_page, name='system_admin_payments'),
    path('database/', views.database_monitor, name='system_admin_database'),
    path('logs/', views.system_logs, name='system_admin_logs'),
    path('settings/', views.settings_page, name='system_admin_settings'),
    path('profile/', views.profile_page, name='system_admin_profile'),
]
