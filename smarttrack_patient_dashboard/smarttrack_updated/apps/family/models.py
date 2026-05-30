from django.db import models
from apps.accounts.models import CustomUser


class FamilyMember(models.Model):
    """Emergency / linked family contact record for a patient (not a login account)."""
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='family_members')
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='family_link')
    name = models.CharField(max_length=100)
    relation = models.CharField(max_length=50)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    is_emergency_contact = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'family_member_contact'

    def __str__(self):
        return f'{self.name} ({self.relation}) - Family of {self.patient.get_full_name()}'


class FamilyMemberProfile(models.Model):
    """Login profile for family role users — separate from auth_user."""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='family_member_profile')
    family_id = models.CharField(max_length=20, unique=True, blank=True)
    full_name = models.CharField(max_length=200, blank=True)
    relation = models.CharField(max_length=50, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    linked_patient = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='linked_family_profiles', limit_choices_to={'role': 'patient'},
    )
    permissions = models.JSONField(default=dict, blank=True)
    profile_photo = models.ImageField(upload_to='profiles/family/', null=True, blank=True)
    onboarding_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'family_member_profile'

    def save(self, *args, **kwargs):
        if not self.family_id:
            from apps.profiles.profile_bridge import generate_public_id
            fid = generate_public_id('family')
            while FamilyMemberProfile.objects.filter(family_id=fid).exists():
                fid = generate_public_id('family')
            self.family_id = fid
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Family: {self.full_name or self.user.username}'
