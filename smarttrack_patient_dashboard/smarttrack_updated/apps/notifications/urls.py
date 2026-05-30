from django.urls import path
from . import views

urlpatterns = [
    path('', views.notification_list, name='notification_list'),
    path('feed/', views.notification_feed, name='notification_feed'),
    path('mark-read/<int:notif_id>/', views.mark_read, name='mark_notification_read'),
    path('mark-all-read/', views.mark_all_read, name='mark_all_notifications_read'),
    path('unread-count/', views.unread_count, name='unread_count'),
    path('poll/', views.poll_notifications, name='poll_notifications'),
]
