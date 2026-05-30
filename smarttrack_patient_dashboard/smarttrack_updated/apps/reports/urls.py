from django.urls import path
from . import views

urlpatterns = [
    path('', views.report_list, name='report_list'),
    path('generate/<int:patient_id>/', views.generate_report, name='generate_report'),
    path('<int:report_id>/', views.report_detail, name='report_detail'),
    path('<int:report_id>/pdf/', views.download_report_pdf, name='download_report_pdf'),
]
