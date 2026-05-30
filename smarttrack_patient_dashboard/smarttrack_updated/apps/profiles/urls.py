from django.urls import path
from . import views

urlpatterns = [
    path('complete/', views.complete_profile, name='complete_profile'),
    path('patient/', views.patient_profile, name='patient_profile'),
    path('doctor/', views.doctor_profile, name='doctor_profile'),
    path('caregiver/', views.caregiver_profile, name='caregiver_profile'),
    path('caregiver/settings/', views.caregiver_settings, name='caregiver_settings'),
]
