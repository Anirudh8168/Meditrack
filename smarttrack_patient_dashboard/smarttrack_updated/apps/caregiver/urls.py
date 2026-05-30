from django.urls import path
from . import views

urlpatterns = [
    path('', views.caregiver_dashboard, name='caregiver_dashboard'),
    path('profile/<int:caregiver_id>/', views.caregiver_profile_detail, name='caregiver_profile_detail'),
    path('patients/', views.caregiver_my_patient, name='caregiver_my_patient'),
    path('my-patient/', views.caregiver_my_patient, name='caregiver_my_patient_alt'),
    path('connect/', views.connect_to_patient, name='caregiver_connect'),
    path('search-patients/', views.search_patients, name='caregiver_search_patients'),
    path('send-request/', views.send_connection_request, name='caregiver_send_request'),
    path('enter-mode/<int:patient_id>/', views.caregiver_enter_patient_mode, name='caregiver_enter_mode'),
    path('exit-mode/', views.caregiver_exit_patient_mode, name='caregiver_exit_mode'),
    path('patient/<int:patient_id>/', views.caregiver_patient_detail, name='caregiver_patient_detail'),
    path('patient/<int:patient_id>/log-activity/', views.caregiver_log_activity, name='caregiver_log_activity'),
    path('mark-medicine/<int:med_id>/', views.caregiver_mark_medicine, name='caregiver_mark_medicine'),
    path('book-appointment/', views.caregiver_book_appointment, name='caregiver_book_appointment'),
    path('disconnect/<int:assignment_id>/', views.disconnect_caregiver, name='disconnect_caregiver'),
    path('accept-caregiver/<int:assignment_id>/', views.patient_accept_caregiver, name='patient_accept_caregiver'),
    path('doctor-assign/', views.doctor_assign_caregiver, name='doctor_assign_caregiver'),
    path('doctor-assign/new/', views.doctor_hospital_caregiver_form, name='doctor_hospital_caregiver_new'),
    path('doctor-assign/<int:assignment_id>/', views.doctor_hospital_caregiver_detail, name='doctor_hospital_caregiver_detail'),
    path('doctor-assign/<int:assignment_id>/edit/', views.doctor_hospital_caregiver_form, name='doctor_hospital_caregiver_edit'),
]
