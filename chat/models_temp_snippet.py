class ReelReport(models.Model):
    """Model for reported reels"""
    REPORT_REASONS = [
        ('spam', 'Spam'),
        ('inappropriate', 'Inappropriate Content'),
        ('harassment', 'Harassment or Bullying'),
        ('violence', 'Violence or Threats'),
        ('hate_speech', 'Hate Speech'),
        ('false_info', 'False Information'),
        ('copyright', 'Copyright Infringement'),
        ('other', 'Other'),
    ]
    
    reporter = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='reel_reports_made')
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name='reports')
    reason = models.CharField(max_length=20, choices=REPORT_REASONS)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed = models.BooleanField(default=False)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('reporter', 'reel')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.reporter.username} reported reel {self.reel.id} for {self.reason}"
