from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='medicines.RiskScore')
def sync_risk_to_patient_profile(sender, instance, **kwargs):
    from apps.profiles.profile_bridge import sync_patient_risk_cache
    sync_patient_risk_cache(instance.patient)
