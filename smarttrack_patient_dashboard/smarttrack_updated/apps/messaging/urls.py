from django.urls import path
from . import views

urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('send/', views.send_message, name='send_message'),
    path('get/<int:user_id>/', views.get_messages, name='get_messages'),
    path('status/<int:user_id>/', views.get_user_status, name='get_user_status'),
    path('unread-count/', views.unread_message_count, name='unread_message_count'),
]
