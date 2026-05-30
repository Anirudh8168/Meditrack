"""Resolve exactly one active sidebar menu key for the current request."""


# url_name → sidebar menu key (most specific names first in lookup order)
_URL_NAME_MENU = {
    # Activities (before generic medicines)
    'activity_list': 'activities',
    'edit_activity': 'activities',
    'activity_detail': 'activities',
    'log_activity': 'activities',
    'activity_reminder_status': 'activities',
    'start_activity_session': 'activities',
    'activity_session': 'activities',
    'complete_activity_session': 'activities',
    'snooze_activity_reminder': 'activities',
    'caregiver_log_activity': 'activities',

    # Appointments — book before list
    'book_appointment': 'book_appointment',
    'caregiver_book_appointment': 'book_appointment',

    # Appointments (list & related)
    'appointment_list': 'appointments',
    'appointment_detail': 'appointments',
    'update_appointment': 'appointments',
    'video_call': 'appointments',
    'webrtc_signal': 'appointments',
    'emergency_history_full': 'appointments',
    'appointment_history': 'appointments',
    'dismiss_missed_emergency_alert': 'appointments',
    'doctor_emergency_sync': 'appointments',
    'check_emergency_timeout': 'appointments',
    'patient_active_emergency': 'appointments',
    'log_emergency_event_api': 'appointments',
    'nearby_clinics': 'appointments',
    'find_nearby_clinics_api': 'appointments',
    'request_emergency_video': 'appointments',
    'doctor_schedule': 'appointments',

    # Health analytics & family
    'health_analytics': 'health_analytics',
    'family_contacts': 'family_contacts',

    # Medicines (patient list & actions — not prescribe)
    'medicine_list': 'medicines',
    'mark_medicine': 'medicines',
    'medicine_detail': 'medicines',
    'delete_medicine': 'medicines',
    'medicine_reminder_status': 'medicines',
    'find_pharmacies': 'medicines',
    'deactivate_medicine': 'medicines',
    'daily_health_check': 'medicines',
    'caregiver_mark_medicine': 'medicines',

    # Doctor prescribe
    'add_medicine': 'prescribe',
    'edit_medicine': 'prescribe',

    # Reports
    'report_list': 'reports',
    'report_detail': 'reports',
    'download_report_pdf': 'reports',
    'generate_report': 'reports',

    # Connections
    'connection_list': 'connections',
    'search_users': 'connections',
    'send_connection_request': 'connections',
    'respond_connection': 'connections',

    # Messages & notifications
    'inbox': 'messages',
    'send_message': 'messages',
    'get_messages': 'messages',
    'get_user_status': 'messages',
    'unread_message_count': 'messages',
    'notification_list': 'notifications',
    'notification_feed': 'notifications',
    'mark_notification_read': 'notifications',
    'mark_all_notifications_read': 'notifications',
    'unread_count': 'notifications',
    'poll_notifications': 'notifications',

    # Payments
    'payment_history': 'payments',
    'pay_consultation': 'payments',
    'payment_success': 'payments',
    'download_receipt': 'payments',
    'doctor_earnings': 'earnings',

    # Dashboards
    'patient_dashboard': 'patient_dashboard',
    'doctor_dashboard': 'dashboard',
    'caregiver_dashboard': 'dashboard',

    # Doctor patient detail → still "My Patients" context when viewing patient
    'patient_detail': 'patients',

    # Caregiver
    'caregiver_my_patient': 'my_patient',
    'caregiver_my_patient_alt': 'my_patient',
    'caregiver_patient_detail': 'my_patient',
    'caregiver_profile_detail': 'my_patient',
    'caregiver_connect': 'my_patient',
    'caregiver_search_patients': 'my_patient',
    'caregiver_send_request': 'my_patient',
    'caregiver_enter_mode': 'my_patient',
    'caregiver_exit_mode': 'my_patient',
    'disconnect_caregiver': 'my_patient',
    'patient_accept_caregiver': 'my_patient',

    # Doctor assign caregiver
    'doctor_assign_caregiver': 'assign_caregiver',
    'doctor_hospital_caregiver_new': 'assign_caregiver',
    'doctor_hospital_caregiver_detail': 'assign_caregiver',
    'doctor_hospital_caregiver_edit': 'assign_caregiver',

    # Family role
    'family_dashboard': 'dashboard',
    'manage_family': 'dashboard',
    'remove_family_member': 'dashboard',
    'mark_alert_read': 'dashboard',
}

# Exact path fallback when url_name is missing
_EXACT_PATH_MENU = {
    '/dashboard/patient/': 'patient_dashboard',
    '/dashboard/doctor/': 'dashboard',
    '/dashboard/caregiver/': 'dashboard',
    '/medicines/': 'medicines',
    '/medicines/analytics/': 'health_analytics',
    '/medicines/family-contacts/': 'family_contacts',
    '/appointments/': 'appointments',
    '/appointments/book/': 'book_appointment',
    '/connections/list/': 'connections',
    '/reports/': 'reports',
    '/messages/': 'messages',
    '/notifications/': 'notifications',
    '/payments/': 'payments',
    '/payments/doctor/earnings/': 'earnings',
    '/medicines/add/': 'prescribe',
    '/family/': 'dashboard',
}


def get_sidebar_active(request):
    """Return a single sidebar menu key for the current request, or empty string."""
    match = getattr(request, 'resolver_match', None)
    url_name = match.url_name if match else None

    if url_name and url_name in _URL_NAME_MENU:
        key = _URL_NAME_MENU[url_name]
        user = getattr(request, 'user', None)
        # Patient home dashboard vs caregiver "Patient Dashboard" (same URL)
        if key == 'patient_dashboard' and user and user.is_authenticated and user.role == 'patient':
            return 'dashboard'
        # Doctor connections list = "My Patients"
        if key == 'connections' and user and user.is_authenticated and user.role == 'doctor':
            return 'patients'
        return key

    path = request.path
    if not path.endswith('/'):
        path = path + '/'

    if path in _EXACT_PATH_MENU:
        key = _EXACT_PATH_MENU[path]
        user = getattr(request, 'user', None)
        if key == 'patient_dashboard' and user and user.is_authenticated and user.role == 'patient':
            return 'dashboard'
        if key == 'connections' and user and user.is_authenticated and user.role == 'doctor':
            return 'patients'
        return key

    # Activity sub-pages (log, session) — grouped under activities only
    if path.startswith('/medicines/activities/'):
        return 'activities'

    return ''


def sidebar_active_context(request):
    return {'sidebar_active': get_sidebar_active(request)}
