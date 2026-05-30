from django.db import models
from apps.accounts.models import CustomUser


class Report(models.Model):
    STATUS_CHOICES = [('draft','Draft'),('sent','Sent'),('viewed','Viewed')]
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='patient_reports')
    doctor = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='doctor_reports')
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    ai_analysis = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    risk_level = models.CharField(max_length=10, default='low')
    risk_score = models.IntegerField(default=0)
    adherence_pct = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    report_data = models.JSONField(default=dict)
    pdf_file = models.FileField(upload_to='reports/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Report: {self.patient} by Dr.{self.doctor}"

    def get_health_analysis_display(self):
        """Return analysis text with legacy branding normalized for display."""
        text = self.ai_analysis or ''
        replacements = (
            ('AI Health Intelligence Report', 'Health Report'),
            ('AI Health Analysis', 'Clinical Health Review'),
            ('AI Clinical Recommendations', 'Clinical Recommendations'),
            ('AI Clinical Recommendation', 'Clinical Recommendation'),
            ('AI Summary', 'Health Summary'),
            ('AI Insights', 'Health Insights'),
            ('AI Monitoring', 'Health Monitoring'),
            ('AI Prediction', 'Health Assessment'),
            ('AI Recommendation', 'Clinical Recommendation'),
            ('AI Recommendations', 'Clinical Recommendations'),
            ('AI Risk Score', 'Health Risk Level'),
            ('AI risk score', 'health risk level'),
            ('AI Risk', 'Health Risk'),
            ('AI Alert', 'Health Alert'),
            ('AI Dashboard', 'Healthcare Dashboard'),
            ('AI Analytics', 'Health Analytics'),
            ('AI Assistant', 'Health Assistant'),
            ('Artificial Intelligence', ''),
            ('AI-generated', 'generated'),
            ('AI powered', ''),
            ('AI-powered', ''),
            ('AI-driven', ''),
            ('AI ', ''),
        )
        for old, new in replacements:
            text = text.replace(old, new)
        return ' '.join(text.split())
