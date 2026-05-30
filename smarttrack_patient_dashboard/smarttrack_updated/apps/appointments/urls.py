from django.urls import path
from . import views

urlpatterns = [
    path('', views.appointment_list, name='appointment_list'),
    path('book/', views.book_appointment, name='book_appointment'),
    path('update/<int:apt_id>/', views.update_appointment, name='update_appointment'),
    path('detail/<int:apt_id>/', views.appointment_detail, name='appointment_detail'),
    path('video-call/<str:session_id>/', views.video_call, name='video_call'),
    path('video-call/end/<int:apt_id>/', views.end_video_call, name='end_video_call'),
    path('webrtc-signal/<int:apt_id>/', views.webrtc_signal, name='webrtc_signal'),
    path('emergency-history/', views.emergency_history_full, name='emergency_history_full'),
    path('history/', views.appointment_history, name='appointment_history'),
    path('dismiss-missed-alert/<int:apt_id>/', views.dismiss_missed_emergency_alert, name='dismiss_missed_emergency_alert'),
    path('doctor-emergency-sync/', views.doctor_emergency_sync, name='doctor_emergency_sync'),
    path('timeout-check/<int:apt_id>/', views.check_emergency_timeout, name='check_emergency_timeout'),
    path('patient-active-emergency/', views.patient_active_emergency, name='patient_active_emergency'),
    path('emergency-log/<int:apt_id>/', views.log_emergency_event_api, name='log_emergency_event_api'),
    path('nearby-clinics/', views.nearby_clinics, name='nearby_clinics'),
    path('find-nearby-clinics/', views.find_nearby_clinics_api, name='find_nearby_clinics_api'),
    path('emergency-video/', views.request_emergency_video, name='request_emergency_video'),
    path('doctor-schedule/<int:doctor_id>/', views.doctor_schedule, name='doctor_schedule'),
]
