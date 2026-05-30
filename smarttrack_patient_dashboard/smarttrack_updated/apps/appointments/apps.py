from django.apps import AppConfig


def _configure_sqlite(connection, **kwargs):
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA busy_timeout=30000;')
        cursor.execute('PRAGMA synchronous=NORMAL;')


class AppointmentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.appointments'

    def ready(self):
        from django.db.backends.signals import connection_created
        connection_created.connect(_configure_sqlite)
