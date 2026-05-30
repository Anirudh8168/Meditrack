from django.urls import path
from . import views

urlpatterns = [
    path('search/', views.search_users, name='search_users'),
    path('send-request/', views.send_request, name='send_connection_request'),
    path('respond/<int:conn_id>/', views.respond_request, name='respond_connection'),
    path('list/', views.connection_list, name='connection_list'),
]
