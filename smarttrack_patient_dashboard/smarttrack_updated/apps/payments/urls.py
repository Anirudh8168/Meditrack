from django.urls import path
from . import views

urlpatterns = [
    path('', views.payment_history, name='payment_history'),
    path('pay/<str:payment_id>/', views.pay_consultation, name='pay_consultation'),
    path('initiate/<str:payment_id>/', views.initiate_payment_view, name='initiate_payment'),
    path('verify/<str:payment_id>/', views.payment_verify, name='payment_verify'),
    path('confirm/<str:payment_id>/', views.verify_payment, name='verify_payment'),
    path('cancel/<str:payment_id>/', views.cancel_payment_view, name='cancel_payment'),
    path('success/<str:payment_id>/', views.payment_success, name='payment_success'),
    path('receipt/<str:payment_id>/', views.download_receipt, name='download_receipt'),
    path('doctor/earnings/', views.doctor_earnings, name='doctor_earnings'),
]
