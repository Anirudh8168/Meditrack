from django.urls import path
from . import views

urlpatterns = [
    path('', views.family_dashboard, name='family_dashboard'),
    path('manage/', views.manage_family, name='manage_family'),
    path('member/remove/<int:member_id>/', views.remove_family_member, name='remove_family_member'),
    path('alert/read/<int:notif_id>/', views.mark_alert_read, name='mark_alert_read'),
]
