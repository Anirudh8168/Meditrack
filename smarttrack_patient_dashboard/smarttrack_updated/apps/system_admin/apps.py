from django.apps import AppConfig


class SystemAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.system_admin'
    verbose_name = 'System Admin'
