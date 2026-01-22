import os
from urllib.parse import parse_qs, urlparse
from django.db import models

class Institution(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    student_limit = models.IntegerField()
    validity = models.DateField()

    def __str__(self):
        return self.name


class Student(models.Model):
    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name='students'
    )
    name = models.CharField(max_length=255)
    email = models.EmailField()
    student_id = models.CharField(max_length=100)
    password = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['institution', 'email'],
                name='unique_email_per_institution'
            ),
            models.UniqueConstraint(
                fields=['institution', 'student_id'],
                name='unique_studentid_per_institution'
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.student_id})"



class CourseTopic(models.Model):
    title = models.CharField(max_length=255)
    topic_type = models.CharField(max_length=20, choices=[("Reading", "Reading"), ("Video", "Video"), ("Task", "Task")])
    order = models.PositiveIntegerField()

    def __str__(self):
        return self.title





class CourseContent(models.Model):
    topic = models.ForeignKey('CourseTopic', on_delete=models.CASCADE)
    heading = models.CharField(max_length=255)
    pdf_file = models.FileField(upload_to='course_pdfs/', blank=True, null=True)
    video_url = models.URLField(blank=True, null=True)
    task_info = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.topic.title} - Content"

    def pdf_filename(self):
        return os.path.basename(self.pdf_file.name)

    def get_embed_url(self):
        """
        Converts standard YouTube URLs to embed format.
        """
        if self.video_url:
            parsed_url = urlparse(self.video_url)
            if 'youtube' in parsed_url.netloc:
                query = parse_qs(parsed_url.query)
                video_id = query.get('v')
                if video_id:
                    return f"https://www.youtube.com/embed/{video_id[0]}"
            elif 'youtu.be' in parsed_url.netloc:
                video_id = parsed_url.path.lstrip('/')
                return f"https://www.youtube.com/embed/{video_id}"
        return self.video_url



class CourseTopic1(models.Model):
    title = models.CharField(max_length=255)
    topic_type = models.CharField(
        max_length=20,
        choices=[("Reading", "Reading"), ("Video", "Video"), ("Task", "Task")]
    )
    order = models.PositiveIntegerField()

    def __str__(self):
        return self.title


class CourseContent1(models.Model):
    topic = models.ForeignKey('CourseTopic1', on_delete=models.CASCADE)
    heading = models.CharField(max_length=255)
    pdf_file = models.FileField(upload_to='course_pdfs/', blank=True, null=True)
    video_url = models.URLField(blank=True, null=True)
    task_info = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.topic.title} - Content"

    def pdf_filename(self):
        return os.path.basename(self.pdf_file.name)

    def get_embed_url(self):
        """
        Converts a YouTube URL into its embeddable form.
        Handles:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - Returns original URL if not a YouTube video.
        """
        if not self.video_url:
            return ""

        parsed_url = urlparse(self.video_url)

        if 'youtube.com' in parsed_url.netloc:
            query = parse_qs(parsed_url.query)
            video_id = query.get('v')
            if video_id:
                return f"https://www.youtube.com/embed/{video_id[0]}"

        elif 'youtu.be' in parsed_url.netloc:
            video_id = parsed_url.path.lstrip('/')
            return f"https://www.youtube.com/embed/{video_id}"

        return self.video_url  # fallback for non-YouTube URLs

from django.db import models

class Registration(models.Model):
    # Key
    trn = models.CharField(max_length=32, unique=True)

    # KPI bar
    due_date = models.DateField(null=True, blank=True)
    last_modified = models.DateField(null=True, blank=True)
    profile_percent = models.PositiveIntegerField(default=0)

    # Step 1: Business details
    legal_name = models.CharField(max_length=150, blank=True)
    pan = models.CharField(max_length=16, blank=True)
    trade_name = models.CharField(max_length=150, blank=True)
    constitution = models.CharField(max_length=60, blank=True)
    state = models.CharField(max_length=60, blank=True)
    district = models.CharField(max_length=60, blank=True)
    is_casual = models.BooleanField(default=False)
    is_composition = models.BooleanField(default=False)
    reason_to_register = models.CharField(max_length=120, blank=True)
    commencement_date = models.DateField(null=True, blank=True)
    liability_date = models.DateField(null=True, blank=True)

    # Existing Registration (single row demo)
    existing_type = models.CharField(max_length=60, blank=True)
    existing_reg_no = models.CharField(max_length=60, blank=True)
    existing_reg_date = models.DateField(null=True, blank=True)

    # Step 2: Promoter/Partner (Proprietor)
    first_name = models.CharField(max_length=40, blank=True)
    middle_name = models.CharField(max_length=40, blank=True)
    last_name = models.CharField(max_length=40, blank=True)
    father_first = models.CharField(max_length=40, blank=True)
    father_middle = models.CharField(max_length=40, blank=True)
    father_last = models.CharField(max_length=40, blank=True)
    dob = models.DateField(null=True, blank=True)
    mobile = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    designation = models.CharField(max_length=60, blank=True)
    din = models.CharField(max_length=40, blank=True)
    pan_promoter = models.CharField(max_length=16, blank=True)
    passport_no = models.CharField(max_length=20, blank=True)
    aadhaar_no = models.CharField(max_length=20, blank=True)
    citizen = models.BooleanField(default=True)
    gender = models.CharField(max_length=10, blank=True)  # Male/Female/Others
    tel_std = models.CharField(max_length=8, blank=True)
    tel_no = models.CharField(max_length=20, blank=True)

    # Promoter Residential Address
    res_building = models.CharField(max_length=120, blank=True)
    res_floor = models.CharField(max_length=40, blank=True)
    res_premises = models.CharField(max_length=120, blank=True)
    res_road = models.CharField(max_length=120, blank=True)
    res_locality = models.CharField(max_length=120, blank=True)
    res_country = models.CharField(max_length=60, blank=True)
    res_state_name = models.CharField(max_length=60, blank=True)
    res_district_name = models.CharField(max_length=60, blank=True)
    res_pincode = models.CharField(max_length=10, blank=True)

    # Photo (store filename only for demo)
    photo_name = models.CharField(max_length=120, blank=True)

    also_authorized_signatory = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.trn} / {self.legal_name or 'Draft'}"
    

class CourseContent2(models.Model):
    topic = models.ForeignKey('CourseTopic2', on_delete=models.CASCADE)
    heading = models.CharField(max_length=255)
    pdf_file = models.FileField(upload_to='course_pdfs/', blank=True, null=True)
    video_url = models.URLField(blank=True, null=True)
    task_info = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.topic.title} - Content"

    def pdf_filename(self):
        return os.path.basename(self.pdf_file.name)

    def get_embed_url(self):
        """
        Converts a YouTube URL into its embeddable form.
        Handles:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - Returns original URL if not a YouTube video.
        """
        if not self.video_url:
            return ""

        parsed_url = urlparse(self.video_url)

        if 'youtube.com' in parsed_url.netloc:
            query = parse_qs(parsed_url.query)
            video_id = query.get('v')
            if video_id:
                return f"https://www.youtube.com/embed/{video_id[0]}"

        elif 'youtu.be' in parsed_url.netloc:
            video_id = parsed_url.path.lstrip('/')
            return f"https://www.youtube.com/embed/{video_id}"

        return self.video_url  # fallback for non-YouTube URLs


class CourseTopic2(models.Model):
    title = models.CharField(max_length=255)
    topic_type = models.CharField(
        max_length=20,
        choices=[("Reading", "Reading"), ("Video", "Video"), ("Task", "Task")]
    )
    order = models.PositiveIntegerField()

    def __str__(self):
        return self.title
    
