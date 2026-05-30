from django.db import models
from apps.accounts.models import CustomUser
from django.utils import timezone


class DoctorSchedule(models.Model):
    DAY_CHOICES = [
        ('monday', 'Monday'), ('tuesday', 'Tuesday'), ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'), ('friday', 'Friday'),
        ('saturday', 'Saturday'), ('sunday', 'Sunday'),
    ]
    doctor = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='schedules')
    day_of_week = models.CharField(max_length=10, choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_duration_minutes = models.IntegerField(default=30)
    max_appointments = models.IntegerField(default=10)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['day_of_week', 'start_time']

    def __str__(self):
        return f"Dr.{self.doctor.get_full_name()} - {self.day_of_week} {self.start_time}-{self.end_time}"


class Appointment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('pending_doctor_confirmation', 'Pending Doctor Confirmation'),
        ('pending_confirmation', 'Pending Confirmation'),
        ('doctor_confirmed', 'Doctor Confirmed'),
        ('patient_confirmed', 'Patient Confirmed'),
        ('confirmed', 'Confirmed'),
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
        ('ended', 'Ended'),
        ('cancelled', 'Cancelled'),
        ('cancelled_by_patient', 'Cancelled by Patient'),
        ('cancelled_by_doctor', 'Cancelled by Doctor'),
        ('rejected', 'Rejected'),
        ('doctor_unavailable', 'Doctor Unavailable'),
        ('timeout', 'Timeout'),
    ]
    TYPE_CHOICES = [
        ('in_person', 'In Person'),
        ('video', 'Video Call'),
        ('emergency_video', 'Emergency Video'),
    ]
    CANCELLED_BY_CHOICES = [
        ('patient', 'Patient'),
        ('doctor', 'Doctor'),
        ('system', 'System'),
    ]

    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='patient_appointments')
    doctor = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='doctor_appointments')
    appointment_date = models.DateField()
    appointment_time = models.TimeField()
    appointment_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='in_person')
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    video_link = models.URLField(blank=True)
    video_session_id = models.CharField(max_length=100, blank=True)

    # Cancellation / rejection / confirmation audit
    cancelled_by = models.CharField(max_length=10, choices=CANCELLED_BY_CHOICES, blank=True)
    cancellation_reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='appointments_confirmed',
    )

    # Emergency flag
    is_emergency = models.BooleanField(default=False)
    emergency_notes = models.TextField(blank=True)

    # Video call timing
    call_started_at = models.DateTimeField(null=True, blank=True)
    call_ended_at = models.DateTimeField(null=True, blank=True)
    call_ended_by = models.CharField(max_length=10, blank=True, help_text='patient or doctor')
    call_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    video_call_status = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text='not_started | active | ended',
    )
    timeout_at = models.DateTimeField(null=True, blank=True)
    doctor_joined_at = models.DateTimeField(null=True, blank=True)
    patient_joined_at = models.DateTimeField(null=True, blank=True)

    # Lightweight signaling store for WebRTC offer/answer/ICE exchange
    webrtc_offer = models.JSONField(default=dict, blank=True)
    webrtc_answer = models.JSONField(default=dict, blank=True)
    webrtc_ice_doctor = models.JSONField(default=list, blank=True)
    webrtc_ice_patient = models.JSONField(default=list, blank=True)

    emergency_events = models.JSONField(default=list, blank=True)

    EMERGENCY_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('timed_out', 'Timed Out'),
    ]
    emergency_status = models.CharField(
        max_length=20, choices=EMERGENCY_STATUS_CHOICES, blank=True, default=''
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    doctor_response = models.CharField(max_length=20, blank=True)
    missed_reason = models.TextField(blank=True)
    doctor_missed_alert_seen = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-appointment_date', '-appointment_time']

    def __str__(self):
        return f"Apt: {self.patient} with Dr.{self.doctor} on {self.appointment_date}"

    def cancel_appointment(self, cancelled_by, reason):
        if cancelled_by == 'patient':
            self.status = 'cancelled_by_patient'
        elif cancelled_by == 'doctor':
            self.status = 'cancelled_by_doctor'
        else:
            self.status = 'cancelled'
        self.cancelled_by = cancelled_by
        self.cancellation_reason = reason
        self.cancelled_at = timezone.now()
        self.save(
            update_fields=[
                'status', 'cancelled_by', 'cancellation_reason',
                'cancelled_at', 'updated_at',
            ]
        )

    def is_cancelled(self):
        return self.status in ('cancelled_by_doctor', 'cancelled_by_patient', 'cancelled')

    def get_cancellation_label(self, user=None):
        """Human-readable cancellation label for doctor/patient views."""
        if self.status == 'cancelled_by_doctor':
            if user and getattr(user, 'role', None) == 'doctor':
                return 'Cancelled by You'
            return 'Cancelled by Doctor'
        if self.status == 'cancelled_by_patient':
            if user and user == self.patient:
                return 'Cancelled by You'
            return 'Cancelled by Patient'
        if self.status == 'cancelled':
            return 'Cancelled'
        return self.get_status_display()

    PENDING_STATUSES = (
        'pending',
        'pending_confirmation',
        'pending_doctor_confirmation',
    )

    def is_pending_approval(self):
        return self.status in self.PENDING_STATUSES

    def can_join_video_call(self):
        return (
            self.appointment_type in ('video', 'emergency_video')
            and self.status in ('confirmed', 'ongoing')
            and bool(self.video_link)
        )

    def confirm_by_doctor(self, doctor_user):
        """Doctor approves appointment → status Confirmed."""
        if self.doctor_id != doctor_user.id:
            return False, 'Unauthorized'
        if self.is_emergency and self.status == 'timeout':
            return False, 'This emergency request has expired. The patient is no longer waiting.'
        if (
            self.is_emergency
            and self.status == 'pending_doctor_confirmation'
            and self.timeout_at
            and timezone.now() >= self.timeout_at
        ):
            return False, 'This emergency request has expired. The patient is no longer waiting.'
        if not self.is_pending_approval():
            return False, f'Cannot confirm: appointment is {self.get_status_display()}.'

        self.status = 'confirmed'
        self.confirmed_at = timezone.now()
        self.confirmed_by = doctor_user
        if self.is_emergency:
            self.emergency_status = 'accepted'
            self.doctor_response = 'accepted'
            self.responded_at = timezone.now()
        if self.appointment_type in ('video', 'emergency_video'):
            self.generate_video_link()
        else:
            fields = ['status', 'confirmed_at', 'confirmed_by', 'updated_at']
            if self.is_emergency:
                fields.extend(['emergency_status', 'doctor_response', 'responded_at'])
            self.save(update_fields=fields)
        return True, ''

    def reject_by_doctor(self, doctor_user, reason):
        """Doctor rejects with mandatory reason."""
        reason = (reason or '').strip()
        if not reason:
            return False, 'Rejection reason is required.'
        if self.doctor_id != doctor_user.id:
            return False, 'Unauthorized'
        if self.is_emergency and self.status == 'timeout':
            return False, 'This emergency request has expired.'
        if (
            self.is_emergency
            and self.status == 'pending_doctor_confirmation'
            and self.timeout_at
            and timezone.now() >= self.timeout_at
        ):
            return False, 'This emergency request has expired.'
        if not self.is_pending_approval():
            return False, f'Cannot reject: appointment is {self.get_status_display()}.'

        self.status = 'rejected'
        self.rejection_reason = reason
        self.rejected_at = timezone.now()
        if self.is_emergency:
            self.emergency_status = 'rejected'
            self.doctor_response = 'rejected'
            self.responded_at = timezone.now()
        self.save(
            update_fields=[
                'status', 'rejection_reason', 'rejected_at',
                'emergency_status', 'doctor_response', 'responded_at', 'updated_at',
            ]
        )
        if self.is_emergency:
            self.log_emergency_event('doctor_rejected_emergency', {'reason': reason})
        return True, ''

    def transition_to(self, new_status, **kwargs):
        """
        Handles valid state transitions for appointments.
        Returns (True, "") if successful, (False, "error message") otherwise.
        """
        valid_transitions = {
            'pending': ['confirmed', 'rejected', 'doctor_confirmed', 'cancelled_by_patient', 'cancelled_by_doctor'],
            'pending_confirmation': ['confirmed', 'rejected', 'doctor_confirmed', 'cancelled_by_patient', 'cancelled_by_doctor'],
            'pending_doctor_confirmation': ['confirmed', 'rejected', 'timeout', 'cancelled_by_patient', 'cancelled_by_doctor'],
            'doctor_confirmed': ['patient_confirmed', 'confirmed', 'cancelled_by_patient', 'cancelled_by_doctor'],
            'patient_confirmed': ['confirmed', 'cancelled_by_patient', 'cancelled_by_doctor'],
            'confirmed': ['ongoing', 'cancelled_by_patient', 'cancelled_by_doctor'],
            'ongoing': ['completed', 'ended'],
        }

        # Allow transition to any cancelled state from almost anywhere
        if new_status in ['cancelled_by_patient', 'cancelled_by_doctor', 'cancelled']:
            if self.status in ['completed', 'ended', 'rejected', 'timeout']:
                return False, "Cannot cancel a finished or rejected appointment."
            self.status = new_status
            self.save()
            return True, ""

        current_valid = valid_transitions.get(self.status, [])
        if new_status not in current_valid:
            return False, f"Invalid transition from {self.status} to {new_status}."

        # Specific logic for certain transitions
        if new_status == 'confirmed' and self.appointment_type == 'emergency_video':
            # For emergency video, confirmed means doctor accepted and we can start
            pass

        if new_status == 'ongoing':
            self.call_started_at = timezone.now()

        if new_status in ['completed', 'ended']:
            self.call_ended_at = timezone.now()

        self.status = new_status
        self.save()
        return True, ""

    def get_video_room_id(self):
        """Unique room id shared by doctor and patient for this appointment."""
        return f"appointment_{self.id}_patient_{self.patient_id}_doctor_{self.doctor_id}"

    def clear_webrtc_signaling(self):
        """Reset stored SDP/ICE so a new join starts a clean negotiation."""
        self.webrtc_offer = {}
        self.webrtc_answer = {}
        self.webrtc_ice_doctor = []
        self.webrtc_ice_patient = []

    def end_video_consultation(self, ended_by_user):
        """
        End an active video/emergency video consultation.
        Returns (success: bool, error: str, history: VideoConsultationHistory|None)
        """
        if ended_by_user not in (self.patient, self.doctor):
            return False, 'Unauthorized', None
        if self.appointment_type not in ('video', 'emergency_video'):
            return False, 'Not a video consultation', None
        if self.status not in ('confirmed', 'ongoing'):
            return False, f'Call is not active (status: {self.get_status_display()})', None

        now = timezone.now()
        if self.status == 'confirmed':
            self.status = 'ongoing'

        ended_role = 'doctor' if ended_by_user == self.doctor else 'patient'
        if not self.call_started_at:
            self.call_started_at = now

        self.status = 'completed'
        self.call_ended_at = now
        self.call_ended_by = ended_role
        self.video_call_status = 'ended'
        duration = max(0, int((now - self.call_started_at).total_seconds()))
        self.call_duration_seconds = duration
        self.clear_webrtc_signaling()
        self.doctor_joined_at = None
        self.patient_joined_at = None
        self.save()

        history = VideoConsultationHistory.objects.create(
            appointment=self,
            patient=self.patient,
            doctor=self.doctor,
            call_type=self.appointment_type,
            started_at=self.call_started_at,
            ended_at=self.call_ended_at,
            duration_seconds=duration,
            ended_by=ended_role,
            completion_status='completed',
        )
        return True, '', history

    def generate_video_link(self):
        """
        Generates a secure video call link.
        In a real production environment, this would call an API (like Agora or Daily.co)
        to create a room and return the meeting URL.
        """
        import uuid
        if not self.video_session_id:
            self.video_session_id = str(uuid.uuid4())

        # This link points to our internal video call view
        self.video_link = f"/appointments/video-call/{self.video_session_id}/"
        self.save()
        return self.video_link

    def get_duration(self):
        """
        Returns the duration of the call in a human-readable format.
        """
        if self.call_duration_seconds is not None:
            seconds = self.call_duration_seconds
        elif self.call_started_at and self.call_ended_at:
            diff = self.call_ended_at - self.call_started_at
            seconds = int(diff.total_seconds())
        else:
            return "N/A"
        mins, secs = divmod(seconds, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours}h {mins}m {secs}s"
        elif mins > 0:
            return f"{mins}m {secs}s"
        else:
            return f"{secs}s"

    def get_role_based_status(self, user):
        """
        Returns a user-friendly status label based on whether the viewer is the doctor or patient.
        """
        role_labels = {
            'doctor': {
                'pending': 'Pending Your Approval',
                'pending_doctor_confirmation': 'Patient Waiting for Response',
                'pending_confirmation': 'Awaiting Your Approval',
                'doctor_confirmed': 'Confirmed by You',
                'patient_confirmed': 'Confirmed by Patient',
                'confirmed': 'Confirmed',
                'ongoing': 'Ongoing',
                'completed': 'Completed',
                'ended': 'Ended',
                'cancelled': 'Cancelled',
                'cancelled_by_patient': 'Cancelled by Patient',
                'cancelled_by_doctor': 'Cancelled by You',
                'rejected': 'Rejected by You',
                'doctor_unavailable': 'Unavailable',
                'timeout': 'Missed Emergency Request',
            },
            'patient': {
                'pending': 'Waiting for Doctor Confirmation',
                'pending_doctor_confirmation': 'Waiting for Doctor Response',
                'pending_confirmation': 'Waiting for Doctor Confirmation',
                'doctor_confirmed': 'Doctor Confirmed',
                'patient_confirmed': 'Confirmed by You',
                'confirmed': 'Confirmed',
                'ongoing': 'Ongoing',
                'completed': 'Completed',
                'ended': 'Ended',
                'cancelled': 'Cancelled',
                'cancelled_by_patient': 'Cancelled by You',
                'cancelled_by_doctor': 'Cancelled by Doctor',
                'rejected': 'Doctor Unavailable',
                'doctor_unavailable': 'Doctor Unavailable',
                'timeout': 'Doctor Timed Out',
            }
        }

        role = user.role if user.role in role_labels else 'patient'
        return role_labels[role].get(self.status, self.get_status_display())

    def get_emergency_event_datetime(self):
        """Best timestamp for when the emergency was resolved."""
        return self.timeout_at or self.rejected_at or self.confirmed_at or self.updated_at

    def get_emergency_history_reason(self):
        if self.status == 'timeout' and self.missed_reason:
            return self.missed_reason
        if self.status == 'rejected' and self.rejection_reason:
            return self.rejection_reason
        if self.reason:
            return self.reason
        return ''

    def get_emergency_badge_for_doctor(self):
        """UI badge: label + tailwind color classes for dashboard cards."""
        if self.status == 'timeout':
            return {
                'label': 'Missed Emergency Request',
                'icon': '🟡',
                'bg': 'bg-amber-100',
                'text': 'text-amber-800',
            }
        if self.status == 'rejected':
            return {
                'label': 'Emergency Rejected',
                'icon': '🔴',
                'bg': 'bg-red-100',
                'text': 'text-red-700',
            }
        if self.status in ('confirmed', 'ongoing', 'completed', 'ended'):
            return {
                'label': 'Emergency Accepted',
                'icon': '🟢',
                'bg': 'bg-emerald-100',
                'text': 'text-emerald-800',
            }
        return {
            'label': self.get_role_based_status_display_safe(),
            'icon': '⚪',
            'bg': 'bg-slate-100',
            'text': 'text-slate-700',
        }

    def get_role_based_status_display_safe(self):
        try:
            return self.get_status_display()
        except Exception:
            return self.status or ''

    def log_emergency_event(self, event_type, extra=None):
        events = list(self.emergency_events or [])
        entry = {'type': event_type, 'at': timezone.now().isoformat()}
        if extra:
            entry.update(extra)
        events.append(entry)
        self.emergency_events = events[-40:]
        self.save(update_fields=['emergency_events', 'updated_at'])

    def mark_as_timeout(self):
        """Doctor did not respond within emergency window. Returns True if newly timed out."""
        if self.status == 'timeout':
            return False
        from apps.appointments.emergency_utils import MISSED_EMERGENCY_REASON

        now = timezone.now()
        self.status = 'timeout'
        self.emergency_status = 'timed_out'
        self.doctor_response = 'missed'
        self.missed_reason = MISSED_EMERGENCY_REASON
        if not self.timeout_at:
            self.timeout_at = now
        events = list(self.emergency_events or [])
        events.append({
            'type': 'doctor_response_timeout',
            'at': now.isoformat(),
            'reason': MISSED_EMERGENCY_REASON,
        })
        self.emergency_events = events[-40:]
        self.save(
            update_fields=[
                'status', 'timeout_at', 'emergency_events', 'emergency_status',
                'doctor_response', 'missed_reason', 'updated_at',
            ]
        )
        return True


class VideoConsultationHistory(models.Model):
    """Persistent log of completed video consultations."""
    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name='consultation_history',
    )
    patient = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='video_consultation_history',
    )
    doctor = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='doctor_video_consultation_history',
    )
    call_type = models.CharField(max_length=20)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    ended_by = models.CharField(max_length=10, blank=True)
    completion_status = models.CharField(max_length=30, default='completed')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'video_consultation_history'
        ordering = ['-ended_at', '-created_at']

    def __str__(self):
        return f'Consultation #{self.appointment_id} — {self.duration_seconds}s'
